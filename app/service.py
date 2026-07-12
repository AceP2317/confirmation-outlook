"""Serving singleton: one warm, JSON-safe source of truth.

Baked tables load into memory once at startup (fast — everything expensive
was computed at build time). Rollup endpoints (root cause, breakdown) run
live SQL per request against the read-only database.
"""
from __future__ import annotations

import json
import math
import threading

import numpy as np
import pandas as pd

from . import engine
from .db import DB_PATH, connect, read_frame

DEFAULT_REGISTER_LIMIT = 400


def jsafe(obj):
    """Recursively convert pandas/numpy scalars to JSON-native values."""
    if isinstance(obj, dict):
        return {k: jsafe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsafe(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if obj is pd.NaT or (isinstance(obj, float) and pd.isna(obj)):
        return None
    return obj


class Service:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        conn = connect(db_path, ro=True)
        meta = read_frame(conn, "SELECT key, value FROM meta").set_index("key")["value"]
        self.latest_week = meta["latest_week"]
        self.asof = meta["asof"]
        self.target = float(meta["target"])
        self.band = json.loads(meta["band"])
        self.volume_train = json.loads(meta["volume_train"])
        self.n_materials = int(meta["n_materials"])
        self.trajectory = read_frame(conn, "SELECT * FROM trajectory ORDER BY week_idx")
        self.trajectory["by_category"] = self.trajectory["by_category"].map(json.loads)
        self.register_df = read_frame(conn, "SELECT * FROM register")
        self.calib = read_frame(conn, "SELECT * FROM calib_cells")
        self.hard_search = read_frame(conn, "SELECT * FROM hard_search")
        self.horizon = read_frame(conn, "SELECT * FROM horizon_reach")
        self.heldout = json.loads(
            read_frame(conn, "SELECT value FROM heldout_metrics WHERE key='heldout'").iloc[0, 0])
        conn.close()

    # --- payloads -------------------------------------------------------

    def headline(self) -> dict:
        weeks = [{
            "cw": r["week"], "asof": r["asof"], "rate": r["rate"],
            "order": r["order_qty"], "conf": r["conf"], "unconf": r["unconf"],
            "byCategory": r["by_category"],
        } for _, r in self.trajectory.iterrows()]
        cur_exposure = float(self.trajectory.iloc[-1]["unconf"])
        return jsafe({
            "latest": self.latest_week, "asof": self.asof, "target": self.target,
            "weeks": weeks,
            "forecast": {**self.band, "curExposure": cur_exposure},
        })

    def forecast(self) -> dict:
        reg = self.register_df
        failing = reg[reg["failing"] == 1]
        total_unconf = float(failing["unconf"].sum())
        rec_units = float(failing.loc[failing["recoverable"] == 1, "unconf"].sum())
        struct_units = float(failing.loc[failing["structural"] == 1, "unconf"].sum())
        coarse = self.calib[self.calib["level"] == "coarse"]
        fine = self.calib[self.calib["level"] == "fine"]
        held_vol = self.heldout["volume"]
        point = sum(float(r["riskProb"]) * float(r["unconf"]) for _, r in failing.iterrows())
        point *= 1 + self.volume_train["new_share"] / (1 - self.volume_train["new_share"])
        return jsafe({
            "week": self.latest_week, "asof": self.asof,
            "leadingSignal": self.heldout["leadingSignal"],
            "persistFloor": self.heldout["persistFloor"],
            "netRecall": self.heldout["netRecall"],
            "worklistPrecision": self.heldout["worklistPrecision"],
            "worklistN": self.heldout["worklistN"],
            "volume": {
                "point": round(point), "naive": float(self.trajectory.iloc[-1]["unconf"]),
                "mape": self.volume_train["mape"], "newShare": self.volume_train["new_share"],
                "heldout": held_vol,
            },
            "recoverable": {
                "units": rec_units, "structuralUnits": struct_units,
                "pct": round(rec_units / total_unconf, 3) if total_unconf else None,
            },
            "riskModel": coarse[["failing", "short", "p", "n"]].to_dict("records"),
            "riskModelFine": fine[["failing", "short", "stressed", "p", "n"]].to_dict("records"),
            "horizonReach": self.horizon.to_dict("records"),
            "hardSearch": self.hard_search.to_dict("records"),
            "heldout": self.heldout,
        })

    def register(self, category=None, plant=None, supplier=None, recoverable=None,
                 confidence=None, min_prob=None, limit=DEFAULT_REGISTER_LIMIT) -> dict:
        df = self.register_df
        if category:
            df = df[df["category"].str.lower() == str(category).lower()]
        if plant:
            df = df[df["plant"].str.upper() == str(plant).upper()]
        if supplier:
            df = df[df["supplier"].str.lower() == str(supplier).lower()]
        if recoverable is not None:
            df = df[df["recoverable"] == (1 if recoverable else 0)]
        if confidence:
            df = df[df["confidence"].str.lower() == str(confidence).lower()]
        if min_prob is not None:
            df = df[df["riskProb"] >= float(min_prob)]
        returned = df.head(max(int(limit), 0)) if limit is not None else df
        return jsafe({
            "week": self.latest_week, "count": len(df), "returned": len(returned),
            "rows": returned.to_dict("records"),
        })

    def worklist(self, n: int = 60) -> dict:
        df = self.register_df
        top = df[df["recoverable"] == 1].nlargest(max(int(n), 0), "expectedUnits")
        return jsafe({
            "week": self.latest_week, "n": len(top),
            "rows": top.to_dict("records"),
        })

    def root_cause(self, week: str | None = None) -> dict:
        week = week or self.latest_week
        conn = connect(self.db_path, ro=True)
        df = engine.root_cause(conn, week)
        conn.close()
        return jsafe({"week": week, "rows": df.to_dict("records")})

    def breakdown(self, week: str | None = None) -> dict:
        week = week or self.latest_week
        conn = connect(self.db_path, ro=True)
        idx = read_frame(conn, "SELECT week_idx FROM weeks WHERE week = ?", (week,))
        prev = None
        if len(idx) and int(idx.iloc[0, 0]) > 1:
            prev = read_frame(conn, "SELECT week FROM weeks WHERE week_idx = ?",
                              (int(idx.iloc[0, 0]) - 1,)).iloc[0, 0]
        out = engine.breakdown(conn, week, prev)
        conn.close()
        return jsafe({"week": week, "prev": prev, **out})

    def health(self) -> dict:
        return jsafe({
            "status": "ok", "latestWeek": self.latest_week, "asof": self.asof,
            "weeks": len(self.trajectory), "materials": self.n_materials,
            "registerRows": len(self.register_df),
        })


_service: Service | None = None
_lock = threading.Lock()


def get_service() -> Service:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = Service()
    return _service
