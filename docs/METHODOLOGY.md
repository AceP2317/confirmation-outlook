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
