"""Descriptive engine: confirmation-rate math over the order book.

Confirmation rate = confirmed / (confirmed + unconfirmed) units against the
requested delivery date. Target: 95%. All rollups are live SQL over
order_lines — deliberately, so the database layer does real work.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

from .db import read_frame

TARGET = 95.0


def trajectory(conn: sqlite3.Connection) -> pd.DataFrame:
    """Per-week order/conf/unconf totals + confirmation rate + category split."""
    df = read_frame(conn, """
        SELECT l.week, w.week_idx, w.asof,
               SUM(l.order_qty) AS order_qty,
               SUM(l.conf_qty)  AS conf,
               SUM(l.unconf_qty) AS unconf
        FROM order_lines l JOIN weeks w ON w.week = l.week
        GROUP BY l.week ORDER BY w.week_idx""")
    df["rate"] = (100 * df["conf"] / (df["conf"] + df["unconf"])).round(2)
    cats = read_frame(conn, """
        SELECT week, category, SUM(unconf_qty) AS unconf
        FROM order_lines WHERE category IS NOT NULL
        GROUP BY week, category""")
    by_cat = {w: dict(zip(g["category"], g["unconf"])) for w, g in cats.groupby("week")}
    df["by_category"] = df["week"].map(lambda w: by_cat.get(w, {}))
    return df


def root_cause(conn: sqlite3.Connection, week: str) -> pd.DataFrame:
    """Unconfirmed units by detailed cause for one week."""
    return read_frame(conn, """
        SELECT category, cause, SUM(unconf_qty) AS unconf, COUNT(DISTINCT product) AS materials
        FROM order_lines WHERE week = ? AND unconf_qty > 0
        GROUP BY category, cause ORDER BY unconf DESC""", (week,))


def breakdown(conn: sqlite3.Connection, week: str, prev_week: str | None) -> dict:
    """Unconfirmed units by plant / business field / supplier / category, vs prior week."""
    out = {}
    for key, col in [("byPlant", "plant"), ("byBusinessField", "business_field"),
                     ("bySupplier", "supplier"), ("byCategory", "category")]:
        cur = _dim(conn, col, week)
        prev = _dim(conn, col, prev_week) if prev_week else {}
        rows = []
        for name, units in sorted(cur.items(), key=lambda kv: -kv[1]):
            p = prev.get(name, 0.0)
            rows.append({
                "name": name, "unconf": units, "prev": p, "delta": round(units - p, 1),
                "trend": "up" if units > p * 1.05 else ("down" if units < p * 0.95 else "flat"),
            })
        out[key] = rows
    return out


def _dim(conn: sqlite3.Connection, col: str, week: str) -> dict:
    df = read_frame(conn, f"""
        SELECT {col} AS name, SUM(unconf_qty) AS unconf
        FROM order_lines WHERE week = ? AND unconf_qty > 0 AND {col} IS NOT NULL
        GROUP BY {col}""", (week,))
    return dict(zip(df["name"], df["unconf"]))
