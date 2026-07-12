"""Validation gate for the synthetic world + engines.

Asserts that the engine, run honestly on the generated data, recovers the
planted causal structure — the demo's analog of a backtest against real
history. Runs as `python -m app.selfcheck` (nonzero exit on failure) and is
executed inside the Docker build, so a red check fails the image.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from . import predict
from .db import DB_PATH, connect, read_frame

PASSED, FAILED = [], []


def check(cond: bool, msg: str) -> None:
    (PASSED if cond else FAILED).append(msg)
    if not cond:
        print(f"  FAIL: {msg}")


def run(db_path=DB_PATH) -> int:
    PASSED.clear()
    FAILED.clear()
    conn = connect(db_path, ro=True)

    # --- headline: right level, memoryless
    traj = read_frame(conn, "SELECT * FROM trajectory ORDER BY week_idx")
    rates = traj["rate"].to_numpy(dtype=float)
    band = json.loads(read_frame(conn, "SELECT value FROM meta WHERE key='band'").iloc[0, 0])
    check(90.5 <= rates.mean() <= 93.5, f"headline mean in [90.5, 93.5] (got {rates.mean():.2f})")
    check(bool(((rates >= 88) & (rates <= 95.5)).all()), f"every week in [88, 95.5] (got {rates.min():.1f}..{rates.max():.1f})")
    check(abs(band["autocorr"]) < 0.35, f"|lag-1 autocorr| < 0.35 (got {band['autocorr']})")

    # --- risk table: monotone gradient, strong leading lift
    calib = read_frame(conn, "SELECT * FROM calib_cells")
    co = calib[calib["level"] == "coarse"].set_index(["failing", "short"])["p"]
    p00, p01, p10, p11 = co[(0, 0)], co[(0, 1)], co[(1, 0)], co[(1, 1)]
    check(p00 < p01 < p10 < p11, f"2x2 monotone (got {p00} < {p01} < {p10} < {p11})")
    check(p11 > 0.5, f"both-flag cell > 0.5 (got {p11})")
    check(p01 / p00 > 8, f"leading lift p01/p00 > 8 (got {p01 / p00:.1f})")
    check(bool((calib["p"].between(0, 1)).all()), "all cell probabilities in [0, 1]")
    fine = calib[calib["level"] == "fine"]
    check(bool((fine["n"] >= predict.MIN_SUPPORT).sum() >= 6),
          f"at least 6 fine cells above min-support (got {(fine['n'] >= predict.MIN_SUPPORT).sum()})")

    # --- measured vs planted: the engine recovers the generator's hazards
    panel = predict.material_panel(conn)
    trans = predict.transitions(panel)
    truth = read_frame(conn, "SELECT * FROM generator_truth")
    tt = trans.merge(truth, on=["week", "product"], suffixes=("", "_t"))
    for cell, g in tt.groupby("cell"):
        if len(g) < 200:
            continue
        measured, planted = g["fail_next"].mean(), g["planted_hazard"].mean()
        check(abs(measured - planted) / planted < 0.35,
              f"cell {cell}: measured {measured:.3f} within 35% of planted {planted:.3f}")

    # --- persistence floor
    floor = float(trans[trans["failing"] == 1]["fail_next"].mean())
    check(0.55 <= floor <= 0.78, f"persistence floor in [0.55, 0.78] (got {floor:.3f})")

    # --- hard-search: every stress signal adds real lift
    hs = read_frame(conn, "SELECT * FROM hard_search").set_index("signal")
    check(hs.loc["fweak", "lift"] > 3, f"forecast-weak lift > 3 (got {hs.loc['fweak', 'lift']})")
    check(hs.loc["cthin", "lift"] > 3, f"coverage-thin lift > 3 (got {hs.loc['cthin', 'lift']})")
    check(hs.loc["in_eos", "lift"] > 5, f"end-of-sale lift > 5 (got {hs.loc['in_eos', 'lift']})")

    # --- horizon: the leading signal reaches forward
    hz = read_frame(conn, "SELECT * FROM horizon_reach").set_index("h")
    check(hz.loc[1, "lift"] > 8, f"T+1 lift > 8 (got {hz.loc[1, 'lift']})")
    check(hz.loc[4, "lift"] > 0.4 * hz.loc[1, "lift"],
          f"T+4 lift > 0.4 x T+1 (got {hz.loc[4, 'lift']} vs T+1 {hz.loc[1, 'lift']})")

    # --- held-out final week (never seen in calibration)
    held = json.loads(read_frame(conn, "SELECT value FROM heldout_metrics WHERE key='heldout'").iloc[0, 0])
    check(held["leadingSignal"]["lift"] > 3, f"held-out leading lift > 3 (got {held['leadingSignal']['lift']})")
    check(held["netRecall"] > 0.9, f"held-out net recall > 0.9 (got {held['netRecall']})")
    check(held["worklistPrecision"] > 0.6, f"held-out worklist precision > 0.6 (got {held['worklistPrecision']})")

    # --- concentration: watch the few, not the thousands
    latest = read_frame(conn, "SELECT value FROM meta WHERE key='latest_week'").iloc[0, 0]
    by_plant = read_frame(conn, """SELECT plant, SUM(unconf_qty) u FROM order_lines
        WHERE week = ? GROUP BY plant ORDER BY u DESC""", (latest,))
    top5 = by_plant["u"].head(5).sum() / by_plant["u"].sum()
    check(top5 >= 0.70, f"top-5 plants >= 70% of unconfirmed volume (got {top5:.2f})")
    by_prod = read_frame(conn, """SELECT product, SUM(unconf_qty) u FROM order_lines
        WHERE week = ? AND unconf_qty > 0 GROUP BY product ORDER BY u DESC""", (latest,))
    csum = by_prod["u"].cumsum() / by_prod["u"].sum()
    k80 = int((csum < 0.8).sum()) + 1
    check(k80 <= 150, f"top-{k80} products cover 80% of unconfirmed volume (<= 150)")

    # --- register partitions + spot checks
    reg = read_frame(conn, "SELECT * FROM register")
    check(len(reg) == int(read_frame(conn, "SELECT value FROM meta WHERE key='register_rows'").iloc[0, 0]),
          "register row count matches meta")
    n_fail = int((reg["failing"] == 1).sum())
    n_emerging = int((reg["failing"] == 0).sum())
    check(n_fail + n_emerging == len(reg), "failing + emerging partition the register exactly")
    check(int(reg["recoverable"].sum()) + int(reg["structural"].sum()) == len(reg),
          "recoverable + structural partition the register exactly")
    check(bool((reg.loc[reg["failing"] == 0, "unconf"] == 0).all()),
          "emerging rows carry no measured unconf (two exposure scales never blended)")
    check(bool(reg["lever"].notna().all()) and bool(reg["confidence"].notna().all()),
          "every register row has a lever and a confidence tier")
    check(bool(np.isfinite(reg[["unconf", "shortfall", "riskProb", "expectedUnits"]].to_numpy()).all()),
          "register numerics all finite")

    # spot check: a chronically short material must be in the register as short
    wk_last = panel[panel["week_idx"] == panel["week_idx"].max()]
    chronic = panel.groupby("product")["receipt_short"].sum()
    chronic = chronic[chronic >= 10]
    if len(chronic):
        still = wk_last[wk_last["product"].isin(chronic.index) & (wk_last["receipt_short"] == 1)]
        in_reg = still["product"].isin(reg["product"])
        check(bool(in_reg.all()), f"all {len(still)} chronically-short materials present in register")
    # spot check: past end-of-sale failing rows are structural with the phase-out lever
    eosf = reg[(reg["eos_past"] == 1)]
    if len(eosf):
        check(bool((~eosf["recoverable"].astype(bool)).all()), "past-EOS rows are all structural")
    # spot check: a clean quiet material is NOT in the register
    clean = wk_last[(wk_last["failing"] == 0) & (wk_last["receipt_short"] == 0) & (wk_last["stressed"] == 0)]
    check(not clean["product"].isin(reg["product"]).any(),
          "clean quiet materials never appear in the register")

    # --- the app never reads generator_truth (transparency table is display-only)
    app_dir = Path(__file__).parent
    for name in ["engine.py", "predict.py", "service.py", "api.py", "mcp_server.py", "agent.py"]:
        p = app_dir / name
        if p.exists():
            check("generator_truth" not in p.read_text(encoding="utf-8"),
                  f"{name} does not read generator_truth")

    conn.close()
    total = len(PASSED) + len(FAILED)
    if FAILED:
        print(f"SELFCHECK FAILED - {len(PASSED)}/{total} assertions passed")
        return 1
    print(f"SELFCHECK PASSED - {total}/{total} assertions")
    return 0


if __name__ == "__main__":
    sys.exit(run())
