"""Synthetic world generator for Northpoint Manufacturing (a fictional company).

Everything downstream is computed from this data by the real engine; nothing
in the app reads generator_truth. The design is a direct-hazard Markov model:
signals CAUSE failure with the hazards planted in CONFIG["hazards"], and the
engine then MEASURES those hazards empirically, with honest sampling noise.
selfcheck.py asserts the measured tables recover the planted gradient.

Deterministic: one seeded numpy Generator drives every draw.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

CONFIG = {
    "seed": 20250834,
    "n_materials": 2400,
    "n_weeks": 12,          # last week is the held-out validation week
    "burn_in": 8,           # unrecorded warm-up weeks so week 1 starts in steady state
    "first_cw": 34,         # calendar weeks CW34..CW45 2025
    "year": 2025,
    # receipt-short Markov chain (the leading signal)
    "p_stay_short": 0.85,
    "p_go_short": 0.026,
    "strained_plant_factor": 1.6,   # strained plants slip into shortage more easily
    # static trouble shares
    "share_forecast_weak": 0.10,    # chronic forecast_accuracy < 0.5
    "share_coverage_thin": 0.08,    # chronic coverage_months < 1
    "share_eos": 0.05,              # on the end-of-sale list
    # failure hazards by (failing, short, stressed) — the planted causal table
    "hazards": {
        (0, 0, 0): 0.005,
        (0, 0, 1): None,    # per-signal: see stress_hazard()
        (0, 1, 0): 0.13,
        (0, 1, 1): 0.22,
        (1, 0, 0): 0.36,
        (1, 0, 1): 0.48,
        (1, 1, 0): 0.68,
        (1, 1, 1): 0.78,
    },
    # quiet + receipt-sufficient stress hazards (drive the "added signal" lifts)
    "hazard_forecast_weak": 0.035,
    "hazard_coverage_thin": 0.04,
    "hazard_eos": 0.12,
    # demand-linked risk: busy materials strain supply more
    "demand_risk_boost": 0.5,       # hazard *= 1 + boost * demand_percentile (quiet cells)
    "persist_size_boost": 0.30,     # failing hazard *= 1 + boost * unconf_percentile
    # volume layer
    "demand_mu": 2.6, "demand_sigma": 1.6,     # lognormal weekly units per material
    "demand_week_noise": 0.20,
    "severity_a": 4.0, "severity_b": 2.0,      # Beta: unconfirmed share of a failing material
    "severity_week_sigma": 0.25,               # iid weekly shock keeps the headline memoryless
    "share_overseas": 0.30,
}

PLANTS = [
    ("D01", "Great Lakes DC", "Midwest"),
    ("D02", "Southeast DC", "Southeast"),
    ("D03", "Gulf Coast DC", "South"),
    ("D04", "Atlantic DC", "Northeast"),
    ("D05", "Central Plains DC", "Midwest"),
    ("D06", "Pacific DC", "West"),
    ("D07", "Mountain West DC", "West"),
    ("D08", "Ohio Valley DC", "Midwest"),
    ("D09", "Tidewater DC", "Southeast"),
    ("D10", "Desert Southwest DC", "West"),
    ("D11", "Northwoods DC", "Midwest"),
    ("D12", "Riverbend DC", "South"),
]
STRAINED_PLANTS = {"D01", "D03"}   # two of the biggest — concentrates trouble

BUSINESS_FIELDS = ["Compressors", "Pumps", "Motors", "Controls", "Fixtures"]
PART_NOUNS = {
    "Compressors": ["Rotary Compressor", "Scroll Compressor", "Compressor Valve Kit", "Head Gasket Set"],
    "Pumps": ["Circulation Pump", "Drain Pump", "Impeller Assembly", "Pump Housing"],
    "Motors": ["Drive Motor", "Fan Motor", "Motor Mount Kit", "Rotor Assembly"],
    "Controls": ["Control Board", "Sensor Module", "Relay Pack", "Interface Panel"],
    "Fixtures": ["Mounting Bracket", "Door Hinge Set", "Trim Kit", "Fastener Pack"],
}

# root-cause taxonomy: 5 categories, 10 detailed causes, assigned from the causal driver
CAUSES = {
    "supply_short": [("Supply", "Component shortage"), ("Supply", "PO receipt delay")],
    "logistics_short": [("Logistics", "Inbound transit delay"), ("Logistics", "Carrier capacity")],
    "forecast": [("Forecasting", "Forecast under-plan"), ("Forecasting", "Demand spike")],
    "coverage": [("Supply", "Stock run-out"), ("Supply", "Safety stock breach")],
    "eos": [("Other", "End of sale"), ("Other", "Phase-out allocation")],
    "customer": [("Customer", "Order change"), ("Customer", "Credit hold")],
}


def week_labels(cfg: dict) -> list[tuple[str, int, str]]:
    """[(week label, index, as-of ISO date)] — Mondays of consecutive calendar weeks."""
    out = []
    monday = date.fromisocalendar(cfg["year"], cfg["first_cw"], 1)
    for i in range(cfg["n_weeks"]):
        cw = cfg["first_cw"] + i
        out.append((f"cw{cw} {cfg['year']}", i + 1, (monday + timedelta(weeks=i)).isoformat()))
    return out


def stress_hazard(cfg: dict, fweak: bool, cthin: bool, eos: bool) -> float:
    """Quiet + receipt-sufficient hazard when at least one stress flag is set."""
    h = 0.0
    if fweak:
        h = max(h, cfg["hazard_forecast_weak"])
    if cthin:
        h = max(h, cfg["hazard_coverage_thin"])
    if eos:
        h = max(h, cfg["hazard_eos"])
    return h


def generate(cfg: dict = CONFIG) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(cfg["seed"])
    n = cfg["n_materials"]
    weeks = week_labels(cfg)

    # --- plants: Zipf-skewed weights => volume concentration falls out naturally
    zipf = 1.0 / np.arange(1, len(PLANTS) + 1) ** 1.15
    plant_w = zipf / zipf.sum()
    plants = pd.DataFrame(PLANTS, columns=["plant", "name", "region"])
    plants["weight"] = plant_w
    plants["strained"] = plants["plant"].isin(STRAINED_PLANTS).astype(int)

    # --- materials
    bf = rng.choice(BUSINESS_FIELDS, size=n)
    home = rng.choice(plants["plant"], size=n, p=plant_w)
    supplier = np.where(rng.random(n) < cfg["share_overseas"], "Overseas", "Local")
    descs = []
    for i in range(n):
        noun = PART_NOUNS[bf[i]][rng.integers(0, 4)]
        descs.append(f"{noun} {rng.integers(10, 96)}-{rng.integers(100, 999)}")
    base_demand = rng.lognormal(cfg["demand_mu"], cfg["demand_sigma"], n).clip(1, 4000)
    demand_pct = pd.Series(base_demand).rank(pct=True).to_numpy()

    fweak = rng.random(n) < cfg["share_forecast_weak"]
    fa_base = np.where(fweak, rng.uniform(0.15, 0.45, n), rng.uniform(0.55, 0.98, n))
    cthin = rng.random(n) < cfg["share_coverage_thin"]
    cov_base = np.where(cthin, rng.uniform(0.1, 0.9, n), rng.uniform(1.2, 6.0, n))

    in_eos = rng.random(n) < cfg["share_eos"]
    first_monday = date.fromisoformat(weeks[0][2])
    # staggered end-sale dates: ~40% already past at week 1, the rest spread +/- around the series
    eos_offset = rng.integers(-20, 16, n)  # weeks relative to first monday
    end_sale = np.array([
        (first_monday + timedelta(weeks=int(o))).isoformat() if e else None
        for e, o in zip(in_eos, eos_offset)
    ], dtype=object)

    materials = pd.DataFrame({
        "product": [f"NP-{10000 + i}" for i in range(n)],
        "description": descs, "business_field": bf, "home_plant": home,
        "supplier": supplier, "end_sale_date": end_sale,
    })

    strained = plants.set_index("plant")["strained"].reindex(home).to_numpy()
    p_go = np.where(strained == 1, cfg["p_go_short"] * cfg["strained_plant_factor"], cfg["p_go_short"])

    # --- Markov simulation (burn-in + recorded weeks)
    short = rng.random(n) < p_go / (p_go + (1 - cfg["p_stay_short"]))  # start at steady state
    failing = np.zeros(n, dtype=bool)
    sev_base = rng.beta(cfg["severity_a"], cfg["severity_b"], n)

    sig_rows, line_rows, truth_rows, week_rows = [], [], [], []
    total_weeks = cfg["burn_in"] + cfg["n_weeks"]
    for step in range(total_weeks):
        rec = step >= cfg["burn_in"]
        wlabel, widx, asof = weeks[step - cfg["burn_in"]] if rec else (None, None, None)
        asof_d = date.fromisoformat(asof) if rec else None

        fa = np.clip(fa_base + rng.normal(0, 0.04, n), 0.05, 1.0)
        cov = np.clip(cov_base * rng.lognormal(0, 0.15, n), 0.05, 12.0)
        if rec:
            eos_past = np.array([
                bool(e) and d is not None and date.fromisoformat(d) <= asof_d
                for e, d in zip(in_eos, end_sale)
            ])
        stressed = (fa < 0.5) | (cov < 1.0) | in_eos

        # volume + recorded rows for this week
        if rec:
            demand = (base_demand * rng.lognormal(0, cfg["demand_week_noise"], n)).clip(1, None).round()
            shock = rng.lognormal(0, cfg["severity_week_sigma"], n)
            severity = np.clip(sev_base * shock, 0.05, 0.98)
            unconf = np.where(failing, (severity * demand).round().clip(1, None), 0.0)
            conf = demand - unconf
            shortfall = np.where(short, (demand * rng.uniform(0.5, 2.0, n)).round(), 0.0)

            week_rows.append({"week": wlabel, "week_idx": widx, "asof": asof})
            sig_rows.append(pd.DataFrame({
                "week": wlabel, "product": materials["product"],
                "receipt_short": short.astype(int), "shortfall": shortfall,
                "forecast_accuracy": fa.round(3), "coverage_months": cov.round(2),
                "in_eos": in_eos.astype(int), "eos_past": eos_past.astype(int),
            }))
            line_rows.append(_order_lines(
                rng, cfg, wlabel, materials, plants, demand, unconf,
                failing, short, eos_past, fa, cov,
            ))

        # transition to next week's state (hazard measured as-of this week)
        hz = np.empty(n)
        for i in range(n):
            key = (int(failing[i]), int(short[i]), int(stressed[i]))
            base = cfg["hazards"][key]
            if base is None:
                base = stress_hazard(cfg, fa[i] < 0.5, cov[i] < 1.0, bool(in_eos[i]))
                base = base if base > 0 else cfg["hazards"][(0, 0, 0)]
            hz[i] = base
        quiet = ~failing
        hz[quiet] *= 1 + cfg["demand_risk_boost"] * demand_pct[quiet]
        if failing.any():
            up = pd.Series(np.where(failing, sev_base * base_demand, 0.0)).rank(pct=True).to_numpy()
            hz[failing] *= 1 + cfg["persist_size_boost"] * up[failing]
        hz = np.clip(hz, 0, 0.97)

        if rec:
            truth_rows.append(pd.DataFrame({
                "week": wlabel, "product": materials["product"],
                "failing": failing.astype(int), "planted_hazard": hz.round(4),
                "cell": [f"{int(f)}{int(s)}{int(x)}" for f, s, x in zip(failing, short, stressed)],
            }))

        failing = rng.random(n) < hz
        short = np.where(short, rng.random(n) < cfg["p_stay_short"], rng.random(n) < p_go)

    return {
        "plants": plants,
        "materials": materials,
        "weeks": pd.DataFrame(week_rows),
        "order_lines": pd.concat(line_rows, ignore_index=True),
        "material_signals": pd.concat(sig_rows, ignore_index=True),
        "generator_truth": pd.concat(truth_rows, ignore_index=True),
    }


def _order_lines(rng, cfg, wlabel, materials, plants, demand, unconf,
                 failing, short, eos_past, fa, cov) -> pd.DataFrame:
    """Split each material's weekly demand into 1-8 order lines; assign cause on failing lines."""
    n = len(materials)
    plant_list = plants["plant"].tolist()
    rows = []
    doc_seq = 0
    for i in range(n):
        d = demand[i]
        k = int(min(1 + rng.poisson(min(d / 40, 4)), 8))
        splits = rng.dirichlet(np.ones(k)) * d
        splits = np.maximum(splits.round(), 1)
        splits[-1] = max(d - splits[:-1].sum(), 1)
        u_left = unconf[i]
        cat, cause = (None, None)
        if failing[i]:
            cat, cause = _pick_cause(rng, short[i], eos_past[i], fa[i] < 0.5, cov[i] < 1.0)
        for j in range(k):
            doc_seq += 1
            q = splits[j]
            u = min(u_left, q)
            u_left -= u
            pl = materials["home_plant"].iloc[i] if rng.random() < 0.85 else plant_list[rng.integers(0, len(plant_list))]
            rows.append((
                wlabel, f"SO-{wlabel[2:4]}{doc_seq:05d}", 10 * (j + 1),
                materials["product"].iloc[i], pl, materials["supplier"].iloc[i],
                materials["business_field"].iloc[i],
                cat if u > 0 else None, cause if u > 0 else None,
                float(q), float(q - u), float(u),
            ))
    return pd.DataFrame(rows, columns=[
        "week", "sales_doc", "item", "product", "plant", "supplier",
        "business_field", "category", "cause", "order_qty", "conf_qty", "unconf_qty",
    ])


def _pick_cause(rng, is_short, is_eos_past, is_fweak, is_cthin) -> tuple[str, str]:
    if is_eos_past:
        key = "eos"
    elif is_short:
        key = "supply_short" if rng.random() < 0.7 else "logistics_short"
    elif is_fweak:
        key = "forecast"
    elif is_cthin:
        key = "coverage"
    else:
        key = "customer" if rng.random() < 0.6 else "forecast"
    pair = CAUSES[key]
    return pair[rng.integers(0, len(pair))]
