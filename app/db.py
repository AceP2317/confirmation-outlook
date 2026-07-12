"""SQLite layer for the Northpoint demo.

One file database. Raw synthetic tables are written once by build_db;
the running app opens the file read-only.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "northpoint.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS plants (
    plant TEXT PRIMARY KEY, name TEXT, region TEXT, weight REAL, strained INTEGER
);
CREATE TABLE IF NOT EXISTS materials (
    product TEXT PRIMARY KEY, description TEXT, business_field TEXT,
    home_plant TEXT, supplier TEXT, end_sale_date TEXT
);
CREATE TABLE IF NOT EXISTS weeks (
    week TEXT PRIMARY KEY, week_idx INTEGER, asof TEXT
);
CREATE TABLE IF NOT EXISTS order_lines (
    week TEXT, sales_doc TEXT, item INTEGER, product TEXT, plant TEXT,
    supplier TEXT, business_field TEXT, category TEXT, cause TEXT,
    order_qty REAL, conf_qty REAL, unconf_qty REAL
);
CREATE INDEX IF NOT EXISTS idx_lines_week ON order_lines(week);
CREATE INDEX IF NOT EXISTS idx_lines_week_product ON order_lines(week, product);
CREATE TABLE IF NOT EXISTS material_signals (
    week TEXT, product TEXT, receipt_short INTEGER, shortfall REAL,
    forecast_accuracy REAL, coverage_months REAL, in_eos INTEGER, eos_past INTEGER,
    PRIMARY KEY (week, product)
);
CREATE TABLE IF NOT EXISTS generator_truth (
    week TEXT, product TEXT, failing INTEGER, planted_hazard REAL, cell TEXT,
    PRIMARY KEY (week, product)
);
"""


def connect(path: Path | str = DB_PATH, ro: bool = True) -> sqlite3.Connection:
    if ro:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def write_frame(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    df.to_sql(table, conn, if_exists="replace", index=False)


def read_frame(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)
