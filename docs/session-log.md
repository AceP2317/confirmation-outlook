# Session log — newest first

## 2026-07-12 — Wrap: zero to live in one session

**Arc:** built the entire demo from empty directory to a live, verified public deployment — synthetic world, engines, serving, front, adversarial review, publish, and an interim-host pivot mid-flight.

**Shipped (every claim tool-verified this session):**
- Synthetic world + engines + bake (`a3d63de`): direct-hazard Markov generator (seed 20250834), measured-frequency engine; selfcheck first-run green; determinism proven (two from-scratch builds, identical inspect output). Measured story: headline 90.95 mean / autocorr 0.061; 2×2 = 1.9/17.9/53.6/89.3%; hard-search 7.0/6.9/21.7×; horizon 9.5→5.7×; held-out floor .736, leading 11.1× (n=256), recall .97, worklist precision .80.
- Serving layer (`94380dd`): REST + MCP (mount-path/lifespan gotchas carried from the internal build) + capped Ask; cold start 236 ms (bake killed the internal 90 s warm); live Ask numbers cross-checked exact vs API.
- React front (`df291b8`): flight-deck graphite+amber (operator's pick), dataviz-validated palettes (3 validator iterations per theme), verified in-browser both themes, all numbers exact.
- **Adversarial review** (fresh-context subagent, 15 findings) → fixes (`890d5a5`): P0 = FastMCP DNS-rebinding protection would 421 every request on a public host — fixed and proven with a spoofed-Host probe (200); 38→42 assertion-count drift in five places; filtered xlsx export silently capped at 400 rows; XFF spoof (now last hop); check/record race (reserve-at-check + lock); anthropic timeout 30 s; /mcp 307 redirect; CI docker job added. Post-fix: selfcheck 42/42, pytest 17/17 (later 18/18).
- Hosting pivot: HF free tier returned **402 — Docker Spaces now require PRO** (research from earlier in the day was stale). The personal-box fallback was STOPPED on recon: the operator's own business-separation rule (business content lives on its own VPS) plus that box's sealed zero-ingress perimeter. Operator call: **Render free interim** (`f9456cd` blueprint), business VPS later. `86c1531` keepalive (repointed to Render, 10-min cadence during US day).
- **Published + deployed:** repo public (explicit operator go), CI green all 3 jobs incl. docker build (run 29200869584). Operator connected Render + set key. Live verify: health 327 ms, all numbers exact, MCP handshake through Render's proxy OK, keepalive scheduled run success (17:56Z). Render rollover 404s diagnosed (router plaintext "Not Found" during env-var redeploy — normal).
- Live-fire fixes: junk-week tool call read as "no data" → unknown weeks fall back to latest with a note (`9ea2b3f`, 18/18 tests, re-proven live: Supply 5,855 with exact cause split); model transparency chip — API-echoed `claude-haiku-4-5-20251001` on every Ask answer (`0f1a6d6`, captured live).

**Decisions locked this session → DECISIONS.md D1–D9.**

**Watch:**
- xlsx 0.18.5 Dependabot banner may appear on the repo (accepted, D9).
- keepalive: GitHub pauses cron workflows after ~60 days of repo inactivity; any commit re-arms.
- Register renders top 400 with note; exports carry all rows (fixed this session — keep it that way).

**Remains:** VPS migration + the full worklist → PICKUP.md.
