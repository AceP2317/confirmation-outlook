"""Predictive engine: which materials miss confirmation next week.

Everything here is a measured frequency over observed week-to-week
transitions — no fitted model, no manufactured forecast. The headline rate
is close to memoryless, so the engine predicts at material grain instead:

- risk table: P(fail next week) by (failing now, receipt short, stressed),
  with a min-support fallback to the coarse (failing, short) table
- hard-search: does each stress signal add lift among receipt-sufficient,
  not-yet-failing materials? (forecast-weak, coverage-thin, end-of-sale)
- horizon: how far ahead the receipt-short signal reaches (T+1..T+4)
- held-out test: calibrate on all weeks but the last, predict the last,
  score honestly (persistence floor vs leading signal, never blended)
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from .db import read_frame

MIN_SUPPORT = 50
WORKLIST_N = 60

LEVERS = {
    "eos": "Structural (past end-of-sale) - reallocate, no recovery lever",
    "short": "Expedite inbound receipt / PO follow-up",
    "fweak": "Correct the demand plan for this material",
    "cthin": "Rebuild safety stock / raise coverage",
    "other": "Review order book with the customer team",
}


def material_panel(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per (week, material): signals as-of that week + observed outcome."""
    df = read_frame(conn, """
        SELECT s.week, w.week_idx, s.product, s.receipt_short, s.shortfall,
               s.forecast_accuracy, s.coverage_months, s.in_eos, s.eos_past,
               COALESCE(l.unconf, 0) AS unconf, COALESCE(l.order_qty, 0) AS demand,
               m.home_plant AS plant, m.supplier, m.business_field, m.description
        FROM material_signals s
        JOIN weeks w ON w.week = s.week
        JOIN materials m ON m.product = s.product
        LEFT JOIN (SELECT week, product, SUM(unconf_qty) AS unconf,
                          SUM(order_qty) AS order_qty
                   FROM order_lines GROUP BY week, product) l
          ON l.week = s.week AND l.product = s.product""")
    df["failing"] = (df["unconf"] > 0).astype(int)
    df["fweak"] = (df["forecast_accuracy"] < 0.5).astype(int)
    df["cthin"] = (df["coverage_months"] < 1.0).astype(int)
    df["stressed"] = ((df["fweak"] == 1) | (df["cthin"] == 1) | (df["in_eos"] == 1)).astype(int)
    return df.sort_values(["week_idx", "product"]).reset_index(drop=True)


def transitions(panel: pd.DataFrame, max_week: int | None = None, gap: int = 1) -> pd.DataFrame:
    """Join week t signals to week t+gap outcome. max_week bounds the OUTCOME week."""
    a = panel.copy()
    b = panel[["week_idx", "product", "failing", "unconf"]].copy()
    b["week_idx"] -= gap
    b = b.rename(columns={"failing": "fail_next", "unconf": "unconf_next"})
    t = a.merge(b, on=["week_idx", "product"], how="inner")
    if max_week is not None:
        t = t[t["week_idx"] + gap <= max_week]
    return t


def calibrate(trans: pd.DataFrame) -> pd.DataFrame:
    """Measured P(fail next) by cell, fine (3-way) and coarse (2x2)."""
    rows = []
    for keys, level in [(["failing", "receipt_short", "stressed"], "fine"),
                        (["failing", "receipt_short"], "coarse")]:
        g = trans.groupby(keys)["fail_next"].agg(["mean", "count"]).reset_index()
        for _, r in g.iterrows():
            rows.append({
                "failing": int(r["failing"]), "short": int(r["receipt_short"]),
                "stressed": int(r["stressed"]) if level == "fine" else None,
                "p": round(float(r["mean"]), 4), "n": int(r["count"]), "level": level,
            })
    return pd.DataFrame(rows)


def risk_prob(calib: pd.DataFrame, failing: int, short: int, stressed: int) -> float:
    fine = calib[(calib["level"] == "fine") & (calib["failing"] == failing)
                 & (calib["short"] == short) & (calib["stressed"] == stressed)]
    if len(fine) and fine.iloc[0]["n"] >= MIN_SUPPORT:
        return float(fine.iloc[0]["p"])
    coarse = calib[(calib["level"] == "coarse") & (calib["failing"] == failing)
                   & (calib["short"] == short)]
    return float(coarse.iloc[0]["p"]) if len(coarse) else 0.0


def hard_search(trans: pd.DataFrame) -> pd.DataFrame:
    """Added signal per stress flag among quiet, receipt-sufficient materials.

    Baseline = quiet + receipt-sufficient + no stress flag at all, so each
    lift answers: does this flag predict NEW failures beyond a clean book?
    """
    base_pool = trans[(trans["failing"] == 0) & (trans["receipt_short"] == 0)]
    clean = base_pool[(base_pool["fweak"] == 0) & (base_pool["cthin"] == 0) & (base_pool["in_eos"] == 0)]
    p_clean = float(clean["fail_next"].mean())
    rows = []
    for flag, label in [("fweak", "Forecast accuracy < 0.5"),
                        ("cthin", "Stock coverage < 1 month"),
                        ("in_eos", "On end-of-sale list")]:
        sub = base_pool[base_pool[flag] == 1]
        p_flag = float(sub["fail_next"].mean()) if len(sub) else 0.0
        rows.append({
            "signal": flag, "label": label,
            "pFlag": round(p_flag, 4), "pClean": round(p_clean, 4),
            "lift": round(p_flag / p_clean, 1) if p_clean > 0 else None,
            "nFlag": int(len(sub)),
        })
    return pd.DataFrame(rows)


def horizon(panel: pd.DataFrame, max_week: int) -> pd.DataFrame:
    """Receipt-short lift at T+1..T+4 among not-yet-failing materials."""
    rows = []
    for h in range(1, 5):
        t = transitions(panel, max_week=max_week, gap=h)
        t = t[t["failing"] == 0]
        p_s = float(t[t["receipt_short"] == 1]["fail_next"].mean())
        p_q = float(t[t["receipt_short"] == 0]["fail_next"].mean())
        rows.append({"h": h, "lift": round(p_s / p_q, 1) if p_q > 0 else None,
                     "pShort": round(p_s, 4), "pQuiet": round(p_q, 4)})
    return pd.DataFrame(rows)


def build_register(panel: pd.DataFrame, calib: pd.DataFrame, week_idx: int,
                   cause_by_product: dict[str, str] | None = None) -> pd.DataFrame:
    """At-risk register for one week: every failing OR flagged material, scored.

    Two exposure kinds on different unit scales, never blended:
    failing rows carry measured unconf (expectedUnits = prob x unconf);
    emerging rows carry only the forward shortfall proxy.
    """
    wk = panel[panel["week_idx"] == week_idx].copy()
    wk = wk[(wk["failing"] == 1) | (wk["receipt_short"] == 1) | (wk["stressed"] == 1)].copy()
    wk["riskProb"] = [
        risk_prob(calib, f, s, x)
        for f, s, x in zip(wk["failing"], wk["receipt_short"], wk["stressed"])
    ]
    wk["expectedUnits"] = (wk["riskProb"] * wk["unconf"]).round(1)
    wk["structural"] = wk["eos_past"].astype(bool)
    wk["recoverable"] = ~wk["structural"]
    wk["lever"] = [
        LEVERS["eos"] if ep else
        LEVERS["short"] if s else
        LEVERS["fweak"] if fw else
        LEVERS["cthin"] if ct else LEVERS["other"]
        for ep, s, fw, ct in zip(wk["eos_past"], wk["receipt_short"], wk["fweak"], wk["cthin"])
    ]
    wk["confidence"] = pd.cut(wk["riskProb"], [-1, 0.15, 0.5, 2], labels=["Watch", "Medium", "High"])
    if cause_by_product:
        wk["category"] = wk["product"].map(cause_by_product)
    else:
        wk["category"] = None
    pred_cat = np.where(wk["eos_past"] == 1, "Other",
               np.where(wk["receipt_short"] == 1, "Supply",
               np.where(wk["fweak"] == 1, "Forecasting",
               np.where(wk["cthin"] == 1, "Supply", "Customer"))))
    wk["category"] = wk["category"].fillna(pd.Series(pred_cat, index=wk.index))
    wk = wk.sort_values(["expectedUnits", "shortfall"], ascending=False).reset_index(drop=True)
    cols = ["product", "description", "plant", "supplier", "business_field", "category",
            "unconf", "shortfall", "riskProb", "expectedUnits", "receipt_short",
            "stressed", "in_eos", "eos_past", "failing", "recoverable", "structural",
            "confidence", "lever"]
    return wk[cols]


def volume_stats(trans_train: pd.DataFrame, calib: pd.DataFrame) -> dict:
    """Point forecast machinery + dispersion, from training pairs only."""
    per_week = []
    for widx, g in trans_train.groupby("week_idx"):
        probs = np.array([risk_prob(calib, f, s, x) for f, s, x in
                          zip(g["failing"], g["receipt_short"], g["stressed"])])
        persist_point = float((probs * g["unconf"]).sum())
        actual = float(g["unconf_next"].sum())
        new_units = float(g.loc[g["failing"] == 0, "unconf_next"].sum())
        per_week.append({"week_idx": widx, "persist_point": persist_point,
                         "actual": actual, "new_units": new_units})
    pw = pd.DataFrame(per_week)
    new_share = float((pw["new_units"] / pw["actual"]).mean())
    pw["point"] = pw["persist_point"] * (1 + new_share / (1 - new_share))
    mape = float((abs(pw["point"] - pw["actual"]) / pw["actual"]).mean())
    return {"new_share": round(new_share, 4), "mape": round(mape, 4)}


def heldout_test(panel: pd.DataFrame) -> dict:
    """Walk-forward validation on the final week (never seen in calibration)."""
    last = int(panel["week_idx"].max())
    train = transitions(panel, max_week=last - 1)
    calib = calibrate(train)
    score = transitions(panel)
    score = score[score["week_idx"] == last - 1]

    failing = score[score["failing"] == 1]
    persist_floor = float(failing["fail_next"].mean())

    quiet = score[score["failing"] == 0]
    p_flag = float(quiet[quiet["receipt_short"] == 1]["fail_next"].mean())
    p_quiet = float(quiet[quiet["receipt_short"] == 0]["fail_next"].mean())

    predicted = score[(score["failing"] == 1) | (score["receipt_short"] == 1) | (score["stressed"] == 1)]
    actual_fail = set(score.loc[score["fail_next"] == 1, "product"])
    recall = len(actual_fail & set(predicted["product"])) / max(len(actual_fail), 1)

    reg = build_register(panel, calib, last - 1)
    reg = reg.merge(score[["product", "fail_next"]], on="product", how="left")
    top = reg[reg["recoverable"]].nlargest(WORKLIST_N, "expectedUnits")
    precision = float(top["fail_next"].fillna(0).mean())

    vol = volume_stats(train, calib)
    probs = np.array([risk_prob(calib, f, s, x) for f, s, x in
                      zip(score["failing"], score["receipt_short"], score["stressed"])])
    persist_point = float((probs * score["unconf"]).sum())
    point = persist_point * (1 + vol["new_share"] / (1 - vol["new_share"]))
    naive = float(score["unconf"].sum())
    actual = float(score["unconf_next"].sum())

    return {
        "heldoutWeek": last, "persistFloor": round(persist_floor, 3),
        "leadingSignal": {
            "pFlag": round(p_flag, 4), "pQuiet": round(p_quiet, 4),
            "lift": round(p_flag / p_quiet, 1) if p_quiet > 0 else None,
            "nFlags": int((quiet["receipt_short"] == 1).sum()),
        },
        "netRecall": round(recall, 3), "worklistPrecision": round(precision, 3),
        "worklistN": WORKLIST_N,
        "volume": {"point": round(point), "naive": round(naive), "actual": round(actual),
                   "mape": vol["mape"], "newShare": vol["new_share"]},
    }


def band_stats(traj: pd.DataFrame) -> dict:
    """Trajectory dispersion: the honest 'the % is memoryless' frame."""
    rates = traj["rate"].to_numpy(dtype=float)
    mean, std = float(rates.mean()), float(rates.std(ddof=1))
    ac = float(np.corrcoef(rates[:-1], rates[1:])[0, 1]) if len(rates) > 2 else 0.0
    return {
        "mean": round(mean, 2), "std": round(std, 2), "autocorr": round(ac, 3),
        "central": round(mean, 1), "lo": round(mean - std, 1), "hi": round(mean + std, 1),
        "memoryless": bool(abs(ac) < 0.35),
    }
