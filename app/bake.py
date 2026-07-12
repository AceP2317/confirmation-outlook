"""Bake warm state into SQLite at build time.

Everything expensive (calibration, hard-search, horizon, held-out test,
register scoring, band stats) is computed once here and written as plain
tables, so the server starts in under two seconds and the numbers are
inspectable with any sqlite3 client.
"""
from __future__ import annotations

import json
import sqlite3

import pandas as pd

from . import engine, predict
from .db import read_frame, write_frame


def bake(conn: sqlite3.Connection) -> dict:
    traj = engine.trajectory(conn)
    panel = predict.material_panel(conn)
    last = int(panel["week_idx"].max())
    latest_week = traj.loc[traj["week_idx"] == last, "week"].iloc[0]

    trans = predict.transitions(panel)          # all observed pairs
    calib = predict.calibrate(trans)
    hs = predict.hard_search(trans)
    hz = predict.horizon(panel, max_week=last)
    held = predict.heldout_test(panel)
    band = predict.band_stats(traj)
    vol = predict.volume_stats(trans, calib)

    cause = read_frame(conn, """
        SELECT product, category, SUM(unconf_qty) AS u FROM order_lines
        WHERE week = ? AND unconf_qty > 0 GROUP BY product, category""", (latest_week,))
    cause_by_product = dict(
        cause.sort_values("u", ascending=False).drop_duplicates("product")[["product", "category"]].values
    )
    register = predict.build_register(panel, calib, last, cause_by_product)
    register["confidence"] = register["confidence"].astype(str)

    traj_out = traj.copy()
    traj_out["by_category"] = traj_out["by_category"].map(json.dumps)

    write_frame(conn, "trajectory", traj_out)
    write_frame(conn, "calib_cells", calib)
    write_frame(conn, "hard_search", hs)
    write_frame(conn, "horizon_reach", hz)
    write_frame(conn, "register", register)
    write_frame(conn, "heldout_metrics", pd.DataFrame(
        [{"key": "heldout", "value": json.dumps(held)}]))
    meta = {
        "latest_week": latest_week, "latest_week_idx": last,
        "asof": traj.loc[traj["week_idx"] == last, "asof"].iloc[0],
        "target": engine.TARGET, "band": json.dumps(band),
        "volume_train": json.dumps(vol),
        "n_materials": int(panel["product"].nunique()),
        "register_rows": len(register),
    }
    write_frame(conn, "meta", pd.DataFrame([{"key": k, "value": str(v)} for k, v in meta.items()]))
    conn.commit()
    return {"weeks": len(traj), "register_rows": len(register), "heldout": held, "band": band}
