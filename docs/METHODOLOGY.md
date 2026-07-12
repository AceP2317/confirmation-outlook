# Methodology — how a synthetic demo stays honest

The point of this demo is a predictive method, not a dataset. Since the real-world data it was
modeled on can't be published, the demo runs on a synthetic world — which raises the obvious
question: *if you generated the data, aren't the results circular?*

They would be, if the engine were shown the answers. It isn't. This document explains the
construction and the guardrails.

## 1. The synthetic world (`app/generate.py`)

A single seeded `numpy` generator builds 12 weeks of material-grain supply data for the fictional
Northpoint Manufacturing: ~2,400 materials across 12 distribution centers, ~53k order lines.

The world is a **direct-hazard Markov model** — signals *cause* failure with planted hazards:

- **Receipt-short** (the leading signal) is a sticky two-state Markov chain per material
  (P(stay short) = 0.85). Stickiness is why signal reach at T+2..T+4 *emerges* rather than
  being scripted per horizon.
- **Stress signals** — chronically weak forecast accuracy (~10% of materials), thin stock
  coverage (~8%), end-of-sale listing (~5%) — are mostly material-static with weekly noise.
- **Failure next week** is drawn from a hazard table keyed by (failing now, receipt-short,
  stressed), ranging from 0.005 (clean quiet) to 0.78 (failing + short + stressed), with a
  demand-linked boost (busy materials strain supply more).
- **Volume** uses heavy-tailed lognormal demand and Zipf-weighted plant assignment — so the
  concentration pattern (a few DCs and materials carry most of the exposure) *falls out* of the
  distributions, it isn't painted on. An i.i.d. weekly severity shock keeps the headline rate
  memoryless even though the failing *set* persists.

The planted hazards are written to a `generator_truth` table in the database — shipped
deliberately, as a transparency asset.

## 2. The engine measures; it never peeks

`app/engine.py` and `app/predict.py` compute everything from the observable tables only
(order lines and as-of signals): the weekly trajectory, the risk table as **measured
frequencies** over observed transitions (fine 3-way cells with a min-support-50 fallback to the
coarse 2×2), conditional lifts for each stress signal among receipt-sufficient materials, horizon
reach, and the ranked at-risk register.

No fitted model. No access to `generator_truth` — the selfcheck greps the serving modules to
enforce that.

## 3. Held-out week, walk-forward

The final week is excluded from calibration **for every validation metric below** (the risk
table shipped to the UI is then recalibrated on all weeks, as is standard once validation is
done — the two tables are baked separately). The register is predicted from the prior week's
signals and scored against what actually happened:

- **Persistence floor** — the share of currently-failing materials that fail again. Reported
  *separately*, because recurrence needs no model, and a dishonest summary would credit it to
  the "predictive" signal.
- **Leading signal** — among *not-yet-failing* materials, receipt-short vs quiet failure rates.
  This is the signal's real value: catching new failures before they exist.
- **Register recall** and **top-N worklist precision** (ranked by expected units =
  measured probability × current exposure).
- **Volume**, stated with its dispersion (±MAPE from training pairs) next to a naive
  carry-forward baseline — the headline is memoryless, so volume is inherently wide, and the
  material register, not the volume point, is the deliverable.

## 4. The validation gate (`app/selfcheck.py`)

42 assertions run at every database build — inside the Docker build itself, so a red check
fails the image:

- headline level and |lag-1 autocorrelation| (memorylessness);
- risk-table monotonicity and magnitude; **measured cells within 35% of the mean planted hazard**
  (the engine recovers the truth with honest sampling noise — that closeness is the point, and
  it is checked, not assumed);
- conditional lifts for every stress signal; horizon reach;
- held-out recall, precision, leading lift;
- volume concentration by plant and by material;
- register partition assertions (failing/emerging exact partition, recoverable/structural sums,
  two exposure scales never blended) and spot-checks on rows whose classification is known by
  construction;
- the no-peeking grep.

Determinism: same seed, same world — two from-scratch builds produce identical numbers.

## 5. What the demo does *not* claim

- The specific numbers (11.1× lift, 90.98% rate, …) describe the synthetic world, not any real
  company. The *method* — measured cell frequencies, held-out scoring, honest decomposition —
  is the transferable part.
- In-session state is read-only by design; write-back/disposition would ride an ERP connector in
  a production deployment.
- The Ask tab answers only from live tool results and is hard-capped because this is a public
  endpoint.
