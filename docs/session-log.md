# Session log — newest first

## 2026-07-13 — Wrap: public-safety remediation, a money bug, and a hero plan reversed on measurement

**Arc:** set out to make this demo the hero of both public sites. Found a public-safety leak first, then a rate-limiter bug that would have cost real money on the new host, then measured the sites and discovered the hero plan itself was wrong. Shipped the fixes; scrapped both heroes.

**Shipped (every claim tool-verified this session):**
- **Public-safety remediation.** Four committed files named the employer, an internal program, a private repo, and the operator's own infrastructure. A force-push would only have *hidden* them — GitHub keeps unreachable commits readable by SHA indefinitely — so the repo was **deleted and recreated**. Verified: the old tip returns HTTP 404; all five strings clean across the entire remote history; `CLAUDE.md` and `PICKUP.md` are now untracked and gitignored (they are working docs and were never part of the build); `DECISIONS.md` D5 and this log were scrubbed and kept, since the adversarial-review record is the strongest "read the source" signal here.
- **Client-IP trust is topology-scoped** (`d4d345a`, **D10**) + a new `/api/whoami` probe. `client_ip()` took the **last** `X-Forwarded-For` hop unconditionally — correct behind the interim host's proxy, but wrong behind a Cloudflare Tunnel, where the last hop can be the tunnel daemon: every visitor would collapse into **one** rate-limit bucket, making the 5/hr/IP cap on the paid Ask endpoint a global 5/hr for the entire internet. Trusting `CF-Connecting-IP` unconditionally fails the other way — on a directly-reachable host a visitor can simply *send* the header and mint a fresh bucket per request. Now the header wins **only** under `TRUST_CF_CONNECTING_IP=1`, set only where the edge is the sole route in. Driven against the real app under both topologies: forged header loses when untrusted, wins when trusted, two clients → two buckets, missing header falls back without crashing. **pytest 20 passed** (was 18); CI green.
- **Social card** (`e855ec2`). The app had **no OG tags at all** — a shared link rendered a blank grey box. Added og/twitter meta with an **absolute** image URL plus a 1200×630 card in the app's own flight-deck palette (the measured risk table, carrying its own "no fitted model, no manufactured forecast" line). Verified `dist/og.png` ships through Vite into the same uvicorn process — no second asset host.

**Decisions locked (don't relitigate):**
- **D10 — client-IP trust is topology-scoped, never hardcoded.** Deploy the container **keyless** on any new host, run the three `/api/whoami` probes, and only then install the API key. If the spoof probe wins, the limiter is bypassable and the key does not go on.
- **Working docs are local-only.** `CLAUDE.md` and `PICKUP.md` are gitignored. Never commit them to this public repo.
- **The heroes were the wrong shape** — see the two site repos' logs. This demo gets its own dedicated page on the business site, not a hero panel, and it is **not** an eighth entry in that site's tool registry (the registry's proof copy says "open any one in your browser", which is false of a hosted service).

**Watch items:**
- **Interim-host instance-hour cap — dated.** The free tier grants **750 instance-hours per workspace per calendar month**, and a sleeping service consumes none. The keepalive pinger now runs every minute, 24/7, which keeps the app warm but burns **~744h in a full month**. Safe through **2026-07-31** (partial month). **If the business box is not live by 2026-08-01, dial the pinger back to a window or the host hard-suspends the service until the 1st of the following month.**
- Anyone who cloned during the ~24h public window still has the old content. 26 unique clones in that period were almost certainly bots (CI, the host pulling, GitHub mirroring) — unverifiable either way.
- The interim host's Git integration is probably broken by the repo recreate. The container still serves (health 200); auto-deploy likely does not. Irrelevant — that host is being retired.
- `xlsx@0.18.5` Dependabot banner (D9, accepted — write-only use).

**Remains:** the business box. Everything else is done or held on it.

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
