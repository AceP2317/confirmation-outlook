# Methodology — how a synthetic demo stays honest

The point of this demo is a predictive method, not a dataset. Since the real-world data it was
modeled on can't be published, the demo runs on a synthetic world — which raises the obvious
question: *if you generated the data, aren't the results circular?*

They would be, if the engine were shown the answers. It isn't. This document explains the
construction and the guardrails.

<details open>
<summary><b>Plain-English terms used in this document (click to collapse)</b></summary>

No supply-chain or statistics background assumed. Every technical term below is used somewhere
in the sections that follow; this is the fast lookup.

- **Assertion** — an automatic check the code runs on itself before it's allowed to ship; if one fails, the build fails.
- **Calibration** — the step where the risk table's percentages are computed from historical data, so they match what actually happened.
- **Coarse vs. fine cells** — "fine" groups materials by three signals at once (more detailed, fewer materials per group); "coarse" groups by just two signals (less detailed, more materials per group, more reliable when data is thin).
- **DC** — Distribution Center: a warehouse/plant that ships materials.
- **Determinism / seed** — the synthetic data is generated from a fixed starting number (the "seed"), so rebuilding it from scratch always produces the exact same numbers.
- **Disposition / write-back** — actually acting on a flagged material inside the real business system (e.g. SAP). This demo only reads data; it never writes back to anything.
- **Dispersion vs. confidence interval** — dispersion just describes how spread out past observations were (mean ± one standard deviation, here); a confidence interval is a formal statistical guarantee about a future value. This document only ever claims the former.
- **Docker build / image** — the packaged, ready-to-run version of the app. Building it from scratch also regenerates and re-validates all the data.
- **Emerging** (material/row) — a material that hasn't failed yet, but is showing a warning sign (receipt-short or stressed).
- **ERP** — Enterprise Resource Planning software: the company's main system of record (e.g. SAP), where real orders and inventory actually live.
- **Exposure** — how many units are riding on a given material or week: the thing at stake, measured in order units, not dollars.
- **Fitted model** (vs. measured frequency) — a fitted model tunes itself to match the data as closely as possible, which risks fooling itself; a measured frequency is just a plain count ("out of these materials, how many actually failed"), nothing tuned.
- **Grep** — a code search tool. Used here to prove a specific word never appears in the prediction code, mechanically, not just by promise.
- **Hazard table** — the generator's own hidden "rulebook" for how likely a material is to fail, used only to build the practice data and never shown to the prediction engine.
- **Headline rate** — the single weekly confirmation-rate percentage (confirmed units divided by confirmed-plus-unconfirmed units).
- **Heavy-tailed / lognormal / Zipf-weighted** — statistical ways of saying "a small number of materials and plants naturally account for most of the volume," the same pattern real supply chains show, rather than every material carrying an equal share.
- **i.i.d.** ("independent and identically distributed") — each week's random noise is a fresh, unrelated coin flip; one week's luck doesn't carry into the next.
- **Lift** — a ratio: how many times more often flagged materials fail compared to unflagged ones. A lift of 10× means flagged materials fail ten times as often.
- **MAPE** ("Mean Absolute Percentage Error") — the typical size of a forecasting miss, expressed as a percentage.
- **Markov chain** ("sticky") — a state that mostly carries over from one week to the next, the way a rainy day makes tomorrow more likely to be rainy too, rather than each week being random.
- **Min-support fallback** — a rule that only trusts a detailed statistic if there are enough examples behind it (at least 50, here); otherwise it falls back to a broader, less detailed grouping that has more data to work with.
- **Monotonicity** — a sanity rule: adding another warning sign should never lower the measured risk, only raise or hold it.
- **Partition** — splitting a group into pieces that don't overlap and add up to the whole (e.g. every material is either recoverable or structural, never both, never neither).
- **Precision** — of the materials the tool flagged, what share actually did fail.
- **Recall** — of the materials that actually failed, what share the tool had already flagged in advance.
- **Register** — the ranked list of at-risk materials; the tool's actual output.

</details>

## 1. The synthetic world (`app/generate.py`)

A single seeded (see "determinism / seed" above) `numpy` generator builds 12 weeks of
material-grain supply data for the fictional Northpoint Manufacturing: ~2,400 materials across
12 distribution centers ("DCs"), ~53k order lines.

The world is a **direct-hazard Markov model** — plainly: next week's problems are directly caused
by this week's warning signs, and today's state mostly carries over into tomorrow's (see "Markov
chain" above) — signals *cause* failure with planted hazards (see "hazard table" above):

- **Receipt-short** (the leading signal) is a sticky two-state Markov chain per material
  (P(stay short) = 0.85, i.e. an 85% chance a short material is still short next week). Stickiness
  is why signal reach at T+2..T+4 (two, three, and four weeks ahead) *emerges* rather than being
  scripted per horizon.
- **Stress signals** — chronically weak forecast accuracy (~10% of materials), thin stock
  coverage (~8%), end-of-sale listing (~5%) — are mostly material-static with weekly noise.
- **Failure next week** is drawn from a hazard table keyed by (failing now, receipt-short,
  stressed), ranging from 0.005 (clean quiet: a 0.5% chance) to 0.78 (failing + short + stressed:
  a 78% chance), with a demand-linked boost (busy materials strain supply more).
- **Volume** uses heavy-tailed lognormal demand and Zipf-weighted plant assignment (see "heavy-
  tailed / lognormal / Zipf-weighted" above) — so the concentration pattern (a few DCs and
  materials carry most of the exposure) *falls out* of the distributions, it isn't painted on. An
  i.i.d. weekly severity shock (see "i.i.d." above) keeps the headline rate memoryless even though
  the failing *set* persists.

The planted hazards are written to a `generator_truth` table in the database — shipped
deliberately, as a transparency asset.

## 2. The engine measures; it never peeks

`app/engine.py` and `app/predict.py` compute everything from the observable tables only
(order lines and as-of signals): the weekly trajectory, the risk table as **measured
frequencies** (plain counts of what actually happened, not a model that's been tuned to fit — see
"fitted model" above) over observed transitions (fine 3-way cells with a min-support-50 fallback
to the coarse 2×2 — see "coarse vs. fine cells" and "min-support fallback" above), conditional
lifts (see "lift" above) for each stress signal among receipt-sufficient materials, horizon reach,
and the ranked at-risk register (see "register" above).

No fitted model — this is a deliberate choice: a fitted model tunes itself to the data, which
risks fooling itself, while a plain count cannot. No access to `generator_truth` either — the
selfcheck greps (see "grep" above) the serving modules to enforce that mechanically, not just by
promise.

## 3. Held-out week, walk-forward

The final week is excluded from calibration (see "calibration" above) **for every validation
metric below** (the risk table shipped to the UI is then recalibrated on all weeks, as is
standard once validation is done — the two tables are baked separately). The register is
predicted from the prior week's signals and scored against what actually happened:

- **Persistence floor** — the share of currently-failing materials that fail again. Reported
  *separately*, because recurrence needs no model, and a dishonest summary would credit it to
  the "predictive" signal.
- **Leading signal** — among *not-yet-failing* materials, receipt-short vs quiet failure rates.
  This is the signal's real value: catching new failures before they exist.
- **Register recall** (see "recall" above: of the materials that actually failed, what share was
  already flagged) and **top-N worklist precision** (see "precision" above: of the top-flagged
  materials, what share actually did fail) — both ranked by expected units = measured probability
  × current exposure (see "exposure" above).
- **Volume**, stated with its dispersion (see "dispersion vs. confidence interval" above) as
  ±MAPE (see "MAPE" above) from training pairs, next to a naive carry-forward baseline (just
  repeating last week's number as the guess) — the headline is memoryless, so volume is
  inherently wide, and the material register, not the volume point, is the deliverable.

## 4. The validation gate (`app/selfcheck.py`)

42 assertions (see "assertion" above) run at every database build — inside the Docker build
itself (see "Docker build / image" above), so a red check fails the image:

- headline level and |lag-1 autocorrelation| (memorylessness) — autocorrelation is a statistical
  measure of whether this week's number predicts next week's; near zero means it doesn't, which is
  what "memoryless" means;
- risk-table monotonicity (see "monotonicity" above: more warning signs should never lower the
  measured risk) and magnitude; **measured cells within 35% of the mean planted hazard**
  (the engine recovers the truth with honest sampling noise — that closeness is the point, and
  it is checked, not assumed);
- conditional lifts for every stress signal; horizon reach;
- held-out recall, precision, leading lift (see "recall," "precision," and "lift" above);
- volume concentration by plant and by material;
- register partition assertions (see "partition" above: failing/emerging exact partition,
  recoverable/structural sums, two exposure scales never blended) and spot-checks on rows whose
  classification is known by construction;
- the no-peeking grep (see "grep" above).

Determinism (see "determinism / seed" above): same seed, same world — two from-scratch builds
produce identical numbers.

## 5. What the demo does *not* claim

- The specific numbers (11.1× lift, 90.98% rate, …) describe the synthetic world, not any real
  company. The *method* — measured cell frequencies, held-out scoring, honest decomposition —
  is the transferable part.
- In-session state is read-only by design; write-back/disposition (see "disposition / write-back"
  above) would ride an ERP connector (see "ERP" above) in a production deployment.
- The Ask tab answers only from live tool results and is hard-capped (rate-limited: 5 questions
  per hour per visitor, plus a shared daily budget) because this is a public endpoint.

## 6. Full technical reference: every constant, formula, and threshold

Sections 1-5 tell the story. This section is the complete reference underneath it: every named
constant, every formula exactly as coded, and every one of the 42 build-time assertions, so
nothing in the codebase's math is left undocumented anywhere.

<details>
<summary><b>6.1 Generator internals (planted ground truth, never read by the engine)</b></summary>

Everything in this subsection shapes the *practice data*, not the tool's live math. It is
generator-internal by design (see "hazard table" in the glossary above) — the engine only ever
sees the same `order_lines` and signal columns a real system would expose, and `selfcheck.py`
mechanically greps the serving code to prove none of this is read directly (§4, "no-peeking
grep"). It's documented here in full for transparency, not because the tool depends on a reader
knowing it.

**Constants** (`app/generate.py`, the `CONFIG` dict):

| Constant | Value | What it controls |
|---|---|---|
| `seed` | 20250834 | Seeds the entire random generator; same seed always produces the same world |
| `n_materials` | 2,400 | Synthetic materials simulated |
| `n_weeks` | 12 | Recorded weeks (the last is the held-out validation week) |
| `burn_in` | 8 | Unrecorded warm-up weeks so week 1 starts mid-stream, not from a cold start |
| `p_stay_short` | 0.85 | 85% chance a receipt-short material is still short next week |
| `p_go_short` | 0.026 | Baseline 2.6% chance a fine material goes short next week |
| `strained_plant_factor` | 1.6× | Multiplier on `p_go_short` for two deliberately strained plants (see below) |
| `share_forecast_weak` | 10% | Share of materials with a chronically weak forecast |
| `share_coverage_thin` | 8% | Share of materials with chronically thin stock coverage |
| `share_eos` | 5% | Share of materials on the end-of-sale list |
| `hazard_forecast_weak` | 0.035 | Stress-hazard contribution from a weak forecast alone |
| `hazard_coverage_thin` | 0.04 | Stress-hazard contribution from thin coverage alone |
| `hazard_eos` | 0.12 | Stress-hazard contribution from end-of-sale alone |
| `demand_risk_boost` | 0.5 | Boost coefficient applied only to quiet (not-yet-failing) materials, scaled by demand size |
| `persist_size_boost` | 0.30 | Boost coefficient applied only to already-failing materials, scaled by failure size |
| `demand_mu` / `demand_sigma` | 2.6 / 1.6 | Lognormal parameters for each material's base weekly demand |
| `demand_week_noise` | 0.20 | Lognormal sigma for week-to-week demand noise |
| `severity_a` / `severity_b` | 4.0 / 2.0 | Beta-distribution parameters for a failing material's base unconfirmed share |
| `severity_week_sigma` | 0.25 | Lognormal sigma for the independent weekly "shock" that keeps the headline rate memoryless |
| `share_overseas` | 30% | Share of materials assigned an overseas supplier |

**The planted hazard table**, keyed by (failing now, receipt-short, stressed) as 0/1:

| failing | short | stressed | Planted weekly failure chance |
|---|---|---|---|
| 0 | 0 | 0 | 0.5% |
| 0 | 0 | 1 | computed dynamically (see `stress_hazard` below) |
| 0 | 1 | 0 | 13% |
| 0 | 1 | 1 | 22% |
| 1 | 0 | 0 | 36% |
| 1 | 0 | 1 | 48% |
| 1 | 1 | 0 | 68% |
| 1 | 1 | 1 | 78% |

Note this is the *planted* table used to build the practice data, not the *measured* table the
engine recovers empirically (shown in the earlier sections and on the dashboard) — §4's "measured
cells within 35%" assertion is exactly what ties the two together: the engine has to rediscover
something close to this table using only observed outcomes, with no access to it directly.

**Key formulas, exactly as coded:**

- `stress_hazard` (used only for the `(0,0,1)` cell above): the *maximum* of whichever stress
  flags are set (`0.035` if forecast-weak, `0.04` if coverage-thin, `0.12` if end-of-sale), not a
  sum — the worst single flag dominates rather than stacking additively. If none apply, it falls
  back to the `(0,0,0)` baseline of 0.5%.
- Zipf plant weighting: `weight ∝ rank^-1.15`, normalized across the 12 plants, ranked 1 to 12.
  This is what makes plant volume concentrate on its own rather than being scripted.
- Strained-plant multiplier: exactly two of the twelve plants (`D01`, `D03`) get
  `p_go_short × 1.6` instead of the baseline `p_go_short` — 4.16% instead of 2.6% per week.
- Demand-linked boost: `hazard *= 1 + 0.5 × demand_percentile`, applied only to quiet
  (not-yet-failing) materials — busier materials strain supply more.
- Persistence-size boost: `hazard *= 1 + 0.30 × failure_size_percentile`, applied only to
  already-failing materials, ranked by (base severity × base demand) as a proxy for how big the
  failure is. A material never receives both boosts in the same week.
- Hazard ceiling: every weekly failure chance is capped at 97%, regardless of boosts. Once the
  hazard has been decided, whether a material actually fails that week is a coin flip weighted
  by that hazard.
- Base weekly demand: `lognormal(mean=2.6, sigma=1.6)`, clipped to [1, 4,000] units.
- Weekly severity (the unconfirmed share of a failing material): a base draw from
  `Beta(4.0, 2.0)` per material, multiplied by an independent weekly "shock" of
  `lognormal(0, sigma=0.25)`, clipped to [5%, 98%] — the shock is what keeps the headline rate
  memoryless even though the *set* of failing materials persists.
- Order-line split: each material's weekly demand is split into 1-8 order lines via a
  symmetric Dirichlet distribution (equal weight per line), with the number of lines drawn
  from a Poisson process capped at 8. Each line ships from the material's home plant 85% of the
  time, otherwise a uniformly random plant.
- End-of-sale dates are assigned an offset of -20 to +15 weeks from the start of the simulation,
  so a large share are already past their end-sale date from week 1 (structural from the start,
  not something that develops during the demo).
- Root-cause attribution: if a material is past end-of-sale, its cause is always "eos" regardless
  of any other flag; otherwise a receipt-short material's cause splits 70/30 between
  "supply shortage" and "logistics delay," and the residual fallback splits 60/40 between
  "customer" and "forecast."

</details>

### 6.2 The descriptive engine (`app/engine.py`)

- **Confirmation rate**: `rate = 100 × confirmed ÷ (confirmed + unconfirmed)`, rounded to 2
  decimal places, computed fresh per week from the order-line table.
- **Week-over-week trend**: `up` if this week's units exceed last week's by more than 5%, `down`
  if they fall short by more than 5%, otherwise `flat`. If there's no prior week to compare
  against, the trend defaults to `up` (since any positive number exceeds a zero baseline).
- `TARGET = 95.0` — the confirmation-rate target the rest of the app compares against.

### 6.3 The predictive engine (`app/predict.py`)

- **Flags**: `failing` = unconfirmed units > 0; `forecast-weak` = forecast accuracy < 0.5;
  `coverage-thin` = stock coverage < 1.0 months; `stressed` = any one of forecast-weak,
  coverage-thin, or on the end-of-sale list.
- **Calibration**: for every combination of flags, `p = round(mean(fail_next), 4)` and
  `n = count`, computed once at three-signal ("fine") granularity and once at two-signal
  ("coarse") granularity.
- **The min-support fallback**: use the fine-cell percentage only if it has at least 50 examples
  behind it (`MIN_SUPPORT = 50`); otherwise fall back to the coarser, more example-rich cell.
- **Lift** (both the "extra warning signs" and "horizon reach" charts): `lift = P(fail | flag) ÷
  P(fail | no flag)`, rounded to one decimal.
- **Expected units**: `round(risk probability × unconfirmed units, 1)`.
- **Structural vs. recoverable**: structural = past end-of-sale; recoverable = everything else.
- **The lever cascade**, in priority order: past end-of-sale → "reallocate, no recovery lever";
  else receipt-short → "expedite inbound receipt / PO follow-up"; else forecast-weak → "correct
  the demand plan for this material"; else coverage-thin → "rebuild safety stock / raise
  coverage"; else → "review order book with the customer team."
- **Confidence tier**: risk probability binned as Watch (up to 15%), Medium (15% up to 50%), or
  High (50% and above) — literally `pandas.cut(riskProb, [-1, 0.15, 0.5, 2], labels=["Watch",
  "Medium", "High"])`.
- **Category fallback**: when a measured cause isn't available, one is predicted from the driving
  signal: past end-of-sale → Other; else receipt-short → Supply; else forecast-weak →
  Forecasting; else coverage-thin → Supply; else → Customer.
- **Register sort**: by expected units descending, ties broken by shortfall descending.
- **The volume point forecast** — the most involved formula in the codebase, worth spelling out
  in full:
  ```
  persistence estimate = Σ (risk probability × unconfirmed units) over all currently-failing materials
  new_share             = the historical average share of a week's actual unconfirmed volume that
                           comes from materials that were NOT yet failing the week before
                           (i.e. "brand-new" trouble, not a repeat)
  point forecast         = persistence estimate ÷ (1 − new_share)
  ```
  Algebraically, `persistence_estimate × (1 + new_share/(1-new_share))` (the form in the code)
  and `persistence_estimate ÷ (1 - new_share)` are the same thing — the persistence-only number
  is inflated to account for the trouble that historically shows up from nowhere. `MAPE` is then
  `mean(|point forecast − actual| ÷ actual)` across the training weeks.
- **Dispersion band** (`band_stats`): `mean` and `std` (sample standard deviation) of the 12
  weekly rates, `autocorrelation` = the lag-1 correlation coefficient between each week's rate and
  the next, `band = mean ± 1 std`, and `memoryless = |autocorrelation| < 0.35`.

### 6.4 Held-out validation formulas

All four are computed by calibrating on every week except the last, then scoring the prediction
against what the held-out week actually did:

- **Persistence floor**: `mean(fail next week | failing this week)`, on the held-out week.
- **Leading-signal lift**: among materials not yet failing, `P(fail | receipt-short) ÷ P(fail |
  quiet)`, on the held-out week.
- **Net recall**: `(materials that actually failed AND were flagged in advance) ÷ (all materials
  that actually failed)`.
- **Worklist precision**: of the top 60 recoverable materials ranked by expected units, the share
  that actually failed.
- **Held-out volume**: the same point-forecast formula as §6.3, using only the `new_share`
  measured from training weeks, compared against a naive carry-forward baseline (just repeating
  the current week's exposure) and the real actual outcome.

<details>
<summary><b>6.5 The validation gate, complete: all 42 assertions</b></summary>

`app/selfcheck.py` runs at every database build, grouped exactly as follows. If any assertion
fails, the build itself fails and nothing ships. The total count (42) is emergent from the data
(one group has a variable number of checks, one per statistically-qualifying cell and one per
serving file that exists on disk), not a hardcoded loop bound.

**Headline: right level, memoryless**
1. Mean weekly confirmation rate is between 90.5% and 93.5%.
2. Every individual week's rate is between 88% and 95.5%.
3. The absolute lag-1 autocorrelation is below 0.35 (i.e. the headline is genuinely memoryless).

**Risk table: monotone gradient, strong leading lift**
4. The coarse 2×2 cells are strictly increasing: quiet-and-fine < quiet-and-short <
   failing-and-fine < failing-and-short.
5. The both-flags cell (failing and short) exceeds 50%.
6. The leading lift (short-only vs. neither flag) exceeds 8×.
7. Every calibrated probability falls between 0 and 1.
8. At least 6 of the fine (three-signal) cells have 50 or more examples behind them.

**Measured vs. planted: does the engine honestly recover the generator's hidden hazards?**
9. For every state with at least 200 observations, the measured next-week failure rate is within
   35% (relative) of the mean planted hazard for that state — one check per qualifying state, so
   this group's count varies run to run depending on how much data landed in each bucket.

**Persistence floor**
10. The persistence floor falls between 55% and 78%.

**Hard-search: every extra warning sign adds real lift**
11. Forecast-weak lift exceeds 3×.
12. Coverage-thin lift exceeds 3×.
13. End-of-sale lift exceeds 5×.

**Horizon: the leading signal reaches forward**
14. The one-week-ahead (T+1) lift exceeds 8×.
15. The four-week-ahead (T+4) lift is still at least 40% of the T+1 lift (it's allowed to fade,
    but not collapse to nothing).

**Held-out final week (a week the calibration never saw)**
16. Held-out leading-signal lift exceeds 3×.
17. Held-out net recall exceeds 90%.
18. Held-out worklist precision exceeds 60%.

**Concentration: watch the few, not the thousands**
19. The top 5 plants carry at least 70% of the latest week's unconfirmed volume.
20. 150 or fewer materials (ranked by unconfirmed volume) account for 80% of that volume.

**Register partitions and spot-checks**
21. The register's row count matches the build's own recorded count.
22. Every register row is either "failing" or "emerging," and those two groups exactly partition
    the register (no overlap, nothing left out).
23. Every register row is either "recoverable" or "structural," and those two groups exactly
    partition the register the same way.
24. Every "emerging" (not-yet-failing) row carries zero measured unconfirmed units, so it can
    never be confused with a measured number.
25. Every register row has both a lever and a confidence tier assigned.
26. Every numeric column in the register (units, shortfall, risk probability, expected units) is
    a finite number, never blank or broken.
27. Materials that have been receipt-short for 10 or more of the 12 weeks, and are still short in
    the final week, all appear in the register (chronic problems can't slip through).
28. Every register row past its end-of-sale date is marked structural, with no exceptions.
29. Materials that are quiet, supply-sufficient, and unstressed in the final week never appear in
    the register (the tool doesn't flag things it has no reason to flag).

**The tool never reads the hidden answer key**
30. For each of the six live-serving code files, the literal text `generator_truth` does not
    appear anywhere in it — checked mechanically per file, so the exact count depends on which
    files exist in a given build.

**Determinism**: rebuilding the practice world from scratch, twice, with the same seed, produces
exactly the same numbers both times.

</details>
