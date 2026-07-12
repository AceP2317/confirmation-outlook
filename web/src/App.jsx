// Confirmation Outlook — Northpoint Manufacturing (fictional; synthetic data)
// Built by Ian Provencher
import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import * as XLSX from 'xlsx'

const API_BASE = import.meta.env.VITE_API_BASE || ''

// ---------- formatting ----------
const fmtInt = (x) => (x == null || !isFinite(x) ? '—' : Math.round(x).toLocaleString('en-US'))
const fmtPct = (x, d = 1) => (x == null || !isFinite(x) ? '—' : `${(x * 100).toFixed(d)}%`)
const fmtRate = (x) => (x == null || !isFinite(x) ? '—' : `${Number(x).toFixed(2)}%`)
const fmtX = (x) => (x == null || !isFinite(x) ? '—' : `${Number(x).toFixed(1)}×`)
const cwShort = (w) => (w || '').replace(' 2025', '').toUpperCase()

const CAT_COLORS = {
  Supply: 'var(--c-supply)', Forecasting: 'var(--c-forecast)', Logistics: 'var(--c-logistics)',
  Customer: 'var(--c-customer)', Other: 'var(--c-other)',
}
const CAT_ORDER = ['Supply', 'Forecasting', 'Logistics', 'Customer', 'Other']

// ---------- glossary ----------
const GLOSSARY = {
  rate: 'Confirmation rate = confirmed units / (confirmed + unconfirmed) against the requested delivery date. Northpoint’s target is 95%.',
  memoryless: 'Week-over-week, the headline % barely correlates with itself (lag-1 autocorrelation near zero). A good week says almost nothing about next week — so this tool predicts materials, not the %.',
  band: 'Mean ± one standard deviation of the 12 observed weeks. It describes dispersion — it is not a confidence interval.',
  short: 'Receipt-short: the material’s inbound receipts over the forward window do not cover its demand. Measured from supply data as-of each week — a leading state, not a symptom.',
  leading: 'Among materials NOT yet failing, how much more often receipt-short ones fail the next week vs quiet ones. This is the signal’s real value: catching new failures early.',
  floor: 'Share of currently-failing materials that fail again next week — the problem’s persistence, available without any model. Reported separately so the leading signal never takes credit for it.',
  lift: 'A ratio of failure rates: P(fail | flag) / P(fail | no flag). 10× means flagged materials fail ten times as often.',
  expected: 'Expected units = measured risk probability × current unconfirmed units. Zero for emerging rows, which carry a forward shortfall proxy instead — two different unit scales, never blended.',
  shortfall: 'Forward exposure proxy for not-yet-failing materials: how many units the forward window leaves uncovered. Not measured unconfirmed volume.',
  structural: 'Past end-of-sale: the material is no longer sold, so the exposure cannot be recovered by expediting. Excluded from the operator worklist.',
  confidence: 'Tier from the measured cell probability: High ≥ 50%, Medium ≥ 15%, Watch below. Probabilities are measured frequencies, not model scores.',
  heldout: 'The last week was excluded from calibration; the register was predicted from the prior week’s signals and scored against what actually happened.',
  fa: 'Forecast accuracy below 0.5 — the demand plan for this material has been running far off actuals.',
  cov: 'Stock coverage below one month of demand.',
  eos: 'On the end-of-sale list. Materials past their end-sale date are structural; listed-but-still-sold materials are a stress signal.',
  mape: 'Mean absolute percentage error of the volume point forecast over training weeks. The headline is memoryless, so volume is inherently wide — the material register is the trustworthy deliverable.',
}

const TipCtx = createContext(null)

function TipLayer({ children }) {
  const [tip, setTip] = useState(null)
  const show = (content, x, y) => setTip({ content, x, y })
  const hide = () => setTip(null)
  const pos = tip ? {
    left: Math.min(tip.x + 12, window.innerWidth - 300),
    top: Math.min(tip.y + 14, window.innerHeight - 120),
  } : null
  return (
    <TipCtx.Provider value={{ show, hide }}>
      {children}
      {tip && <div className="np-tip-box" style={pos}>{tip.content}</div>}
    </TipCtx.Provider>
  )
}

function Q({ k }) {
  const tips = useContext(TipCtx)
  return (
    <button type="button" className="np-q" aria-label={`What is this? ${GLOSSARY[k]}`}
      onMouseEnter={(e) => tips.show(GLOSSARY[k], e.clientX, e.clientY)}
      onMouseLeave={tips.hide} onFocus={(e) => { const r = e.target.getBoundingClientRect(); tips.show(GLOSSARY[k], r.left, r.bottom) }}
      onBlur={tips.hide}>?</button>
  )
}

// ---------- charts (hand-rolled SVG) ----------
function TrajectoryChart({ weeks, forecast, target }) {
  const tips = useContext(TipCtx)
  const W = 560, H = 218, L = 44, R = 12, T = 14, B = 30
  const lo = 88, hi = 96
  const x = (i) => L + (i * (W - L - R)) / (weeks.length - 1)
  const y = (r) => T + ((hi - r) * (H - T - B)) / (hi - lo)
  const path = weeks.map((w, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(w.rate).toFixed(1)}`).join('')
  const gridVals = [88, 90, 92, 94, 96]
  return (
    <svg className="np-svg np-fade" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Confirmation rate by week, ${weeks.map((w) => `${cwShort(w.cw)} ${w.rate}%`).join(', ')}`}>
      {gridVals.map((g) => (
        <g key={g}>
          <line x1={L} x2={W - R} y1={y(g)} y2={y(g)} stroke="var(--line)" strokeWidth="1" />
          <text x={L - 6} y={y(g) + 3.5} textAnchor="end" fontSize="10" fill="var(--mut)">{g}</text>
        </g>
      ))}
      <rect x={L} width={W - L - R} y={y(forecast.hi)} height={Math.max(y(forecast.lo) - y(forecast.hi), 0)}
        fill="var(--amber)" opacity="0.12" />
      <line x1={L} x2={W - R} y1={y(target)} y2={y(target)} stroke="var(--green)" strokeWidth="1" strokeDasharray="4 4" opacity="0.8" />
      <text x={W - R} y={y(target) - 4} textAnchor="end" fontSize="10" fill="var(--green)">target {target}%</text>
      <path d={path} fill="none" stroke="var(--amber)" strokeWidth="2" strokeLinejoin="round" />
      {weeks.map((w, i) => (
        <g key={w.cw}>
          <circle cx={x(i)} cy={y(w.rate)} r="2.5" fill="var(--amber)" />
          <rect x={x(i) - 12} y={T} width="24" height={H - T - B} fill="transparent"
            onMouseMove={(e) => tips.show(
              <>{cwShort(w.cw)}: <b>{fmtRate(w.rate)}</b><br />{fmtInt(w.conf)} confirmed / {fmtInt(w.unconf)} unconfirmed</>,
              e.clientX, e.clientY)}
            onMouseLeave={tips.hide} />
          {i % 2 === 0 && <text x={x(i)} y={H - 10} textAnchor="middle" fontSize="9.5" fill="var(--mut)">{cwShort(w.cw)}</text>}
        </g>
      ))}
    </svg>
  )
}

function heatInk(t) { return t > 0.45 ? 'var(--amber-ink)' : 'var(--ink)' }

function RiskHeatmap({ coarse, fine }) {
  const tips = useContext(TipCtx)
  const cell = (f, s) => coarse.find((c) => c.failing === f && c.short === s) || {}
  const fineOf = (f, s) => fine.filter((c) => c.failing === f && c.short === s)
  const bg = (p) => `color-mix(in oklab, var(--amber) ${Math.round(p * 100)}%, var(--heat-lo))`
  const rows = [[1, 'failing now'], [0, 'not failing']]
  const cols = [[0, 'receipts sufficient'], [1, 'receipt-short']]
  return (
    <table className="np-heat np-fade" aria-label="Measured probability of failing next week, by current state">
      <thead>
        <tr><th></th>{cols.map(([s, label]) => <th key={s} scope="col">{label}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map(([f, rowLabel]) => (
          <tr key={f}>
            <th scope="row" style={{ textAlign: 'right' }}>{rowLabel}</th>
            {cols.map(([s]) => {
              const c = cell(f, s)
              const fs = fineOf(f, s)
              return (
                <td key={s} className="cell" style={{ background: bg(c.p ?? 0), color: heatInk(c.p ?? 0) }}
                  onMouseMove={(e) => tips.show(
                    <>P(fail next wk) = <b>{fmtPct(c.p)}</b> (n={fmtInt(c.n)})<br />
                      {fs.map((x) => `${x.stressed ? 'stressed' : 'unstressed'}: ${fmtPct(x.p)} (n=${fmtInt(x.n)})`).join(' · ')}</>,
                    e.clientX, e.clientY)}
                  onMouseLeave={tips.hide}>
                  <div className="p">{fmtPct(c.p)}</div>
                  <div className="nn">n={fmtInt(c.n)}</div>
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function HorizonChart({ reach }) {
  const tips = useContext(TipCtx)
  const W = 300, H = 150, L = 34, R = 14, T = 16, B = 26
  const maxLift = Math.max(...reach.map((r) => r.lift || 0), 1) * 1.2
  const x = (i) => L + (i * (W - L - R)) / (reach.length - 1)
  const y = (v) => T + ((maxLift - (v || 0)) * (H - T - B)) / maxLift
  const path = reach.map((r, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(r.lift).toFixed(1)}`).join('')
  return (
    <svg className="np-svg np-fade" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Receipt-short lift by weeks ahead: ${reach.map((r) => `T+${r.h} ${r.lift}x`).join(', ')}`}>
      <line x1={L} x2={W - R} y1={H - B} y2={H - B} stroke="var(--line)" />
      <path d={path} fill="none" stroke="var(--amber)" strokeWidth="2" strokeLinejoin="round" />
      {reach.map((r, i) => (
        <g key={r.h}>
          <circle cx={x(i)} cy={y(r.lift)} r="3" fill="var(--amber)" />
          <text x={x(i)} y={y(r.lift) - 8} textAnchor="middle" fontSize="10.5" fill="var(--ink)">{fmtX(r.lift)}</text>
          <text x={x(i)} y={H - 8} textAnchor="middle" fontSize="10" fill="var(--mut)">T+{r.h}</text>
          <rect x={x(i) - 18} y={T} width="36" height={H - T - B} fill="transparent"
            onMouseMove={(e) => tips.show(
              <>{`T+${r.h}`}: short {fmtPct(r.pShort)} vs quiet {fmtPct(r.pQuiet)} = <b>{fmtX(r.lift)}</b></>,
              e.clientX, e.clientY)} onMouseLeave={tips.hide} />
        </g>
      ))}
    </svg>
  )
}

function BarRow({ name, value, max, color, right, delta, tipContent }) {
  const tips = useContext(TipCtx)
  const w = max > 0 ? Math.max((value / max) * 100, 1) : 0
  return (
    <div className="np-bar-row"
      onMouseMove={tipContent ? (e) => tips.show(tipContent, e.clientX, e.clientY) : undefined}
      onMouseLeave={tipContent ? tips.hide : undefined}>
      <span className="n" title={name}>{name}</span>
      <span className="track"><span className="fill" style={{ width: `${w}%`, background: color }} /></span>
      <span className="val">{right}{delta != null && (
        <span className="delta" style={{ color: delta > 0 ? 'var(--red)' : delta < 0 ? 'var(--green)' : 'var(--mut)' }}>
          {delta > 0 ? '▲' : delta < 0 ? '▼' : '▬'}
        </span>)}
      </span>
    </div>
  )
}

// ---------- Outlook tab ----------
function Outlook({ head, fc, brk }) {
  const f = head.forecast
  const latest = head.weeks[head.weeks.length - 1]
  const ls = fc.leadingSignal
  const vol = fc.volume
  const hv = vol.heldout || {}
  const catMax = Math.max(...(brk.byCategory || []).map((r) => r.unconf), 1)
  const plantRows = (brk.byPlant || []).slice(0, 6)
  const plantMax = Math.max(...plantRows.map((r) => r.unconf), 1)
  return (
    <div className="np-fade">
      <p className="np-intro">
        Northpoint confirmed <b>{fmtRate(latest.rate)}</b> of ordered units against requested delivery
        dates in {cwShort(latest.cw)}, versus a {head.target}% target. The headline is close to
        memoryless <Q k="memoryless" />, so this tool predicts at material level instead: next week&rsquo;s
        at-risk book points to <b>{fmtInt(vol.point)}</b> units, and <b>{fmtPct(fc.recoverable.pct, 0)}</b> of
        this week&rsquo;s exposure is recoverable if the right materials are chased now.
      </p>

      <div className="np-section">
        <div className="np-stats">
          <div className="np-stat">
            <div className="v">{fmtRate(latest.rate)}</div>
            <div className="s">confirmation rate in {cwShort(latest.cw)} <Q k="rate" /> &mdash; {fmtInt(latest.unconf)} units unconfirmed</div>
          </div>
          <div className="np-stat">
            <div className="v">{f.lo}&ndash;{f.hi}<span className="u">%</span></div>
            <div className="s">next-week dispersion band <Q k="band" /> &mdash; autocorr {f.autocorr}, so treat the % as noise</div>
          </div>
          <div className="np-stat">
            <div className="v amber">{fmtX(ls.lift)}</div>
            <div className="s">leading signal <Q k="leading" />: receipt-short materials fail next week {fmtX(ls.lift)} as often ({fmtPct(ls.pFlag)} vs {fmtPct(ls.pQuiet)}, n={fmtInt(ls.nFlags)})</div>
          </div>
          <div className="np-stat">
            <div className="v green">{fmtPct(fc.recoverable.pct, 0)}</div>
            <div className="s">of this week&rsquo;s {fmtInt(fc.recoverable.units + fc.recoverable.structuralUnits)} at-risk units are recoverable; {fmtInt(fc.recoverable.structuralUnits)} structural <Q k="structural" /></div>
          </div>
        </div>
      </div>

      <div className="np-section np-2col">
        <div className="np-panel">
          <div className="np-chart-title">12-week trajectory <Q k="rate" /></div>
          <div className="np-chart-sub">amber band = mean &plusmn; 1&sigma; dispersion, not a forecast of the %</div>
          <TrajectoryChart weeks={head.weeks} forecast={f} target={head.target} />
        </div>
        <div className="np-panel">
          <div className="np-chart-title">Measured risk table <Q k="lift" /></div>
          <div className="np-chart-sub">P(material fails next week), measured over {fmtInt((fc.riskModel || []).reduce((a, c) => a + (c.n || 0), 0))} observed transitions &mdash; hover a cell for the stressed split</div>
          <RiskHeatmap coarse={fc.riskModel} fine={fc.riskModelFine} />
          <p className="np-caveat">Every probability is a measured frequency from the 12 synthetic weeks &mdash; no fitted model, no manufactured forecast.</p>
        </div>
      </div>

      <div className="np-section np-2col">
        <div className="np-panel">
          <div className="np-chart-title">How far ahead the signal reaches</div>
          <div className="np-chart-sub">receipt-short lift on not-yet-failing materials, T+1 through T+4</div>
          <HorizonChart reach={fc.horizonReach} />
        </div>
        <div className="np-panel">
          <div className="np-chart-title">What else adds signal</div>
          <div className="np-chart-sub">conditional lift among receipt-sufficient, not-yet-failing materials</div>
          <div className="np-bars">
            {(fc.hardSearch || []).map((h) => (
              <BarRow key={h.signal} name={h.label} value={h.lift || 0}
                max={Math.max(...fc.hardSearch.map((x) => x.lift || 0))}
                color="var(--amber)" right={fmtX(h.lift)}
                tipContent={<>{h.label}: {fmtPct(h.pFlag)} vs clean {fmtPct(h.pClean)} (n={fmtInt(h.nFlag)})</>} />
            ))}
          </div>
          <p className="np-caveat">Signals kept only if they added lift beyond receipt-short in backtesting <Q k="fa" /> <Q k="cov" /> <Q k="eos" /></p>
        </div>
      </div>

      <div className="np-section np-2col">
        <div className="np-panel">
          <div className="np-chart-title">This week&rsquo;s unconfirmed volume by cause</div>
          <div className="np-chart-sub">{cwShort(brk.week)} vs {cwShort(brk.prev)} &mdash; live from the order book</div>
          <div className="np-bars">
            {CAT_ORDER.filter((c) => (brk.byCategory || []).some((r) => r.name === c)).map((c) => {
              const r = brk.byCategory.find((x) => x.name === c)
              return <BarRow key={c} name={c} value={r.unconf} max={catMax} color={CAT_COLORS[c]}
                right={fmtInt(r.unconf)} delta={r.delta}
                tipContent={<>{c}: {fmtInt(r.unconf)} units ({r.delta > 0 ? '+' : ''}{fmtInt(r.delta)} vs prior week)</>} />
            })}
          </div>
          <div className="np-legend">
            {CAT_ORDER.map((c) => <span key={c}><span className="sw" style={{ background: CAT_COLORS[c] }} />{c}</span>)}
          </div>
        </div>
        <div className="np-panel">
          <div className="np-chart-title">Concentration: the few plants that matter</div>
          <div className="np-chart-sub">unconfirmed units by distribution center, top 6 of 12</div>
          <div className="np-bars">
            {plantRows.map((r) => (
              <BarRow key={r.name} name={r.name} value={r.unconf} max={plantMax} color="var(--amber)"
                right={fmtInt(r.unconf)} delta={r.delta}
                tipContent={<>{r.name}: {fmtInt(r.unconf)} units, prior week {fmtInt(r.prev)}</>} />
            ))}
          </div>
        </div>
      </div>

      <div className="np-section">
        <h2>Held-out validation <Q k="heldout" /></h2>
        <div className="np-stats">
          <div className="np-stat">
            <div className="v">{fmtPct(fc.persistFloor, 1)}</div>
            <div className="s">persistence floor <Q k="floor" /> &mdash; recurrence needs no model; the leading signal is judged on top of this, never credited with it</div>
          </div>
          <div className="np-stat">
            <div className="v amber">{fmtX(fc.heldout.leadingSignal.lift)}</div>
            <div className="s">leading-signal lift on the held-out week &mdash; new failures caught before they happened</div>
          </div>
          <div className="np-stat">
            <div className="v">{fmtPct(fc.netRecall, 1)}</div>
            <div className="s">of the week&rsquo;s actual failures were inside the flagged register</div>
          </div>
          <div className="np-stat">
            <div className="v">{fmtPct(fc.worklistPrecision, 1)}</div>
            <div className="s">of the top-{fc.worklistN} operator worklist (by expected units <Q k="expected" />) did fail &mdash; time spent chasing them was not wasted</div>
          </div>
        </div>
        <p className="np-caveat">
          Volume, stated honestly <Q k="mape" />: point {fmtInt(hv.point)} vs naive {fmtInt(hv.naive)} vs
          actual {fmtInt(hv.actual)} units on the held-out week (&plusmn;{fmtPct(vol.mape, 0)} typical error).
          The register of materials, not the volume number, is the deliverable.
        </p>
      </div>

      <details className="np-details">
        <summary>How this works &mdash; the whole method in six sentences</summary>
        <div className="body">
          <p>A seeded generator builds 12 weeks of synthetic order and supply data for a fictional company; every number on this page is then <b>computed, not scripted</b> &mdash; the engine has no access to the generator&rsquo;s hidden state.</p>
          <p>The headline % is nearly memoryless week to week, so forecasting it is theater. Instead, each material-week is classified by three observable states: failing now, receipt-short, and stressed (weak forecast accuracy, thin coverage, or end-of-sale).</p>
          <p>P(fail next week) is <b>measured</b> for each state cell across all observed transitions &mdash; a frequency table, not a fitted model &mdash; with a minimum-support fallback from the fine table to the coarse one.</p>
          <p>The final week is <b>held out</b>: the register is predicted from the prior week&rsquo;s signals and scored against what actually happened.</p>
          <p>The at-risk register ranks materials by expected units (probability &times; current exposure), splits recoverable from structural, and names the lever an operator would pull.</p>
          <p>A build-time validation gate (42 assertions) checks that the engine honestly recovers the planted structure &mdash; the build fails if any assertion fails. See <a href="https://github.com/AceP2317/confirmation-outlook/blob/main/docs/METHODOLOGY.md">METHODOLOGY.md</a>.</p>
        </div>
      </details>
    </div>
  )
}

// ---------- Register tab ----------
const REG_COLS = [
  ['product', 'Material'], ['description', 'Description'], ['plant', 'DC'], ['supplier', 'Supplier'],
  ['category', 'Cause'], ['unconf', 'Unconf units'], ['shortfall', 'Fwd shortfall'],
  ['riskProb', 'P(fail next wk)'], ['expectedUnits', 'Expected units'], ['confidence', 'Tier'],
  ['lever', 'Lever'],
]

function reasonFor(row) {
  const bits = []
  if (row.failing) bits.push(`currently failing with ${fmtInt(row.unconf)} unconfirmed units`)
  else bits.push('not failing today')
  if (row.receipt_short) bits.push(`receipt-short (forward shortfall proxy ${fmtInt(row.shortfall)} units)`)
  if (row.eos_past) bits.push('past end-of-sale (structural)')
  else if (row.in_eos) bits.push('on the end-of-sale list')
  if (row.stressed && !row.receipt_short && !row.in_eos) bits.push('stressed (weak forecast accuracy or thin coverage)')
  return bits.join('; ')
}

function Register() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [filters, setFilters] = useState({ category: '', plant: '', supplier: '', recoverable: '', confidence: '', min_prob: '' })
  const qs = useMemo(() => {
    const p = new URLSearchParams()
    Object.entries(filters).forEach(([k, v]) => { if (v !== '') p.set(k, v) })
    p.set('limit', '400')
    return p.toString()
  }, [filters])

  useEffect(() => {
    let live = true
    setErr(null)
    fetch(`${API_BASE}/api/register?${qs}`).then((r) => r.json())
      .then((d) => { if (live) setData(d) })
      .catch((e) => { if (live) setErr(String(e)) })
    return () => { live = false }
  }, [qs])

  const exportXlsx = async (scope) => {
    // both exports refetch with limit lifted — the on-screen 400-row cap never truncates a file
    const query = scope === 'filtered'
      ? `${qs.replace(/limit=\d+/, 'limit=100000')}`
      : 'limit=100000'
    const r = await fetch(`${API_BASE}/api/register?${query}`)
    const rows = (await r.json()).rows
    const flat = rows.map((r) => Object.fromEntries(REG_COLS.map(([k, label]) => [label, r[k]])))
    const ws = XLSX.utils.json_to_sheet(flat)
    ws['!cols'] = REG_COLS.map(([k]) => ({ wch: k === 'lever' ? 44 : k === 'description' ? 26 : 14 }))
    ws['!autofilter'] = { ref: ws['!ref'] }
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, 'At-risk register')
    XLSX.writeFile(wb, scope === 'filtered'
      ? `northpoint-register-filtered-${rows.length}.xlsx`
      : `northpoint-register-full-${rows.length}.xlsx`)
  }

  if (err) return <div className="np-note warn">Could not load the register: {err}</div>
  if (!data) return <div className="np-loading">loading register&hellip;</div>

  const maxExpected = Math.max(...data.rows.map((r) => r.expectedUnits || 0), 1)
  const maxShortfall = Math.max(...data.rows.map((r) => (r.failing ? 0 : r.shortfall) || 0), 1)
  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="np-fade">
      <p className="np-intro">
        <b>{fmtInt(data.count)}</b> materials are flagged for {cwShort(data.week)} &mdash; every one is
        failing now, receipt-short, or stressed. Solid amber bars are expected units on measured
        exposure <Q k="expected" />; hatched bars are the forward shortfall proxy on emerging
        rows <Q k="shortfall" /> &mdash; two different unit scales, deliberately never blended.
      </p>
      <div className="np-controls" role="group" aria-label="Register filters">
        <select className="np-select" value={filters.category} onChange={set('category')} aria-label="Cause category">
          <option value="">all causes</option>
          {CAT_ORDER.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="np-select" value={filters.plant} onChange={set('plant')} aria-label="Distribution center">
          <option value="">all DCs</option>
          {Array.from({ length: 12 }, (_, i) => `D${String(i + 1).padStart(2, '0')}`).map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <select className="np-select" value={filters.supplier} onChange={set('supplier')} aria-label="Supplier class">
          <option value="">all suppliers</option><option>Local</option><option>Overseas</option>
        </select>
        <select className="np-select" value={filters.recoverable} onChange={set('recoverable')} aria-label="Recoverable">
          <option value="">recoverable + structural</option>
          <option value="true">recoverable only</option>
          <option value="false">structural only</option>
        </select>
        <select className="np-select" value={filters.confidence} onChange={set('confidence')} aria-label="Confidence tier">
          <option value="">all tiers</option><option>High</option><option>Medium</option><option>Watch</option>
        </select>
        <input className="np-input" style={{ width: 110 }} type="number" step="0.05" min="0" max="1"
          placeholder="min P" value={filters.min_prob} onChange={set('min_prob')} aria-label="Minimum probability" />
        <span className="np-count">
          {data.returned < data.count ? `showing ${data.returned} of ${data.count} — filter to narrow · exports carry all rows` : `${data.count} rows`}
        </span>
        <span style={{ flex: 1 }} />
        <button className="np-btn" onClick={() => exportXlsx('filtered')}>Export view ({fmtInt(data.count)})</button>
        <button className="np-btn" onClick={() => exportXlsx('full')}>Export full register</button>
      </div>
      <div className="np-datawin" tabIndex="0" role="region" aria-label="At-risk register table">
        <table className="np-table">
          <thead>
            <tr>
              <th className="lead">Material</th>
              <th>DC</th><th>Supplier</th><th>Cause</th>
              <th style={{ textAlign: 'right' }}>Unconf</th>
              <th style={{ textAlign: 'right' }}>P(fail) <Q k="confidence" /></th>
              <th style={{ textAlign: 'right' }}>Expected <Q k="expected" /></th>
              <th style={{ minWidth: 150 }}>Impact</th>
              <th>Tier</th><th>Why</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <React.Fragment key={r.product}>
                <tr>
                  <td className="lead" title={r.description}>{r.product}{r.structural ? ' †' : ''}</td>
                  <td>{r.plant}</td>
                  <td>{r.supplier}</td>
                  <td><span className="np-chip" style={{ borderColor: CAT_COLORS[r.category] || 'var(--line)', color: CAT_COLORS[r.category] || 'var(--ink2)' }}>{r.category}</span></td>
                  <td className="num">{r.failing ? fmtInt(r.unconf) : '—'}</td>
                  <td className="num">{fmtPct(r.riskProb, 0)}</td>
                  <td className="num">{r.failing ? fmtInt(r.expectedUnits) : '—'}</td>
                  <td>
                    {r.failing
                      ? <span className="np-impact measured" style={{ width: `${Math.max((r.expectedUnits / maxExpected) * 140, 2)}px` }} title={`expected units ${fmtInt(r.expectedUnits)}`} />
                      : <span className="np-impact proxy" style={{ width: `${Math.max((r.shortfall / maxShortfall) * 140, 2)}px` }} title={`forward shortfall proxy ${fmtInt(r.shortfall)}`} />}
                  </td>
                  <td><span className={`np-chip ${String(r.confidence).toLowerCase()}${r.structural ? ' structural' : ''}`}>{r.structural ? 'structural' : r.confidence}</span></td>
                  <td><button className="np-expand-btn" aria-expanded={expanded === r.product}
                    onClick={() => setExpanded(expanded === r.product ? null : r.product)}>
                    {expanded === r.product ? 'hide' : 'why'}</button></td>
                </tr>
                {expanded === r.product && (
                  <tr><td colSpan={10} style={{ padding: 0 }}>
                    <div className="np-reason">
                      <b>{r.product}</b> ({r.description}) at {r.plant}: {reasonFor(r)}. Measured cell
                      probability <b>{fmtPct(r.riskProb, 0)}</b>{r.failing ? <> on {fmtInt(r.unconf)} exposed units = <b>{fmtInt(r.expectedUnits)}</b> expected at risk</> : null}.
                      Lever: <b>{r.lever}</b>.
                    </div>
                  </td></tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <p className="np-caveat">&dagger; structural = past end-of-sale <Q k="structural" />. Register sorted by expected units, then forward shortfall. Disposition/write-back would ride the ERP connector in a production deployment; this demo is read-only by design.</p>
    </div>
  )
}

// ---------- Ask tab ----------
// minimal markdown: only **bold** — answers are prose + numbers, a full renderer is a dep we don't need
function renderBold(text) {
  return String(text).split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? <b key={i}>{part.slice(2, -2)}</b> : part)
}

const SUGGESTIONS = [
  'Which DC drives the most at-risk volume next week?',
  'How much of the at-risk book is recoverable, and what levers apply?',
  'Why is the leading signal more useful than the persistence floor?',
  'Top 5 materials by expected units - and why each is flagged?',
]

function Ask() {
  const [q, setQ] = useState('')
  const [state, setState] = useState({ kind: 'idle' })

  const submit = async (question) => {
    const text = (question || q).trim()
    if (!text || state.kind === 'loading') return
    setQ(text)
    setState({ kind: 'loading' })
    try {
      const r = await fetch(`${API_BASE}/api/ask`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text }),
      })
      const body = await r.json().catch(() => ({}))
      if (r.status === 503) setState({ kind: 'offline', detail: body.detail })
      else if (r.status === 429) setState({ kind: 'limited', scope: body.scope, retryAfter: body.retryAfter })
      else if (!r.ok) setState({ kind: 'error', detail: body.detail || `HTTP ${r.status}` })
      else setState({ kind: 'answer', answer: body.answer, tools: body.toolsUsed || [] })
    } catch (e) {
      setState({ kind: 'error', detail: String(e) })
    }
  }

  return (
    <div className="np-ask np-fade">
      <p className="np-intro">
        Ask the data a question in plain English. Claude answers by calling the same read-only
        tools the MCP endpoint exposes &mdash; answers come from live tool results, never from
        the model&rsquo;s imagination. This is a public demo, so requests are capped (5/hour per visitor).
      </p>
      <div className="np-ask-row">
        <input className="np-input" value={q} maxLength={300} placeholder="e.g. which DC drives next week's risk?"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && submit()}
          aria-label="Question" />
        <button className="np-btn primary" onClick={() => submit()} disabled={state.kind === 'loading'}>
          {state.kind === 'loading' ? 'asking…' : 'Ask'}
        </button>
      </div>
      <div className="np-suggest">
        {SUGGESTIONS.map((s) => <button key={s} onClick={() => submit(s)}>{s}</button>)}
      </div>
      {state.kind === 'answer' && (
        <div className="np-answer">
          <div className="a">{renderBold(state.answer)}</div>
          {state.tools.length > 0 && (
            <div className="np-tools">{state.tools.map((t, i) => <span key={i} className="np-chip">{t}</span>)}</div>
          )}
        </div>
      )}
      {state.kind === 'offline' && (
        <div className="np-note"><b>Ask is offline on this deployment</b> &mdash; no API key is configured.
          Everything else works without one; the agent code is in the repo (<code>app/agent.py</code>).</div>
      )}
      {state.kind === 'limited' && (
        <div className="np-note warn"><b>Rate limit reached</b> ({state.scope === 'global' ? 'the demo’s shared daily budget' : 'per-visitor cap'}).
          Try again in ~{Math.ceil((state.retryAfter || 60) / 60)} min. The cap keeps a public LLM endpoint affordable &mdash; see <code>app/ratelimit.py</code>.</div>
      )}
      {state.kind === 'error' && (
        <div className="np-note warn"><b>That didn&rsquo;t work</b> &mdash; {state.detail}</div>
      )}
    </div>
  )
}

// ---------- shell ----------
export default function App() {
  const [theme, setTheme] = useState('dark')
  const [tab, setTab] = useState('outlook')
  const [data, setData] = useState(null)
  const [loadErr, setLoadErr] = useState(null)
  const tries = useRef(0)

  useEffect(() => {
    let live = true
    const load = () => {
      Promise.all([
        fetch(`${API_BASE}/api/headline`).then((r) => r.json()),
        fetch(`${API_BASE}/api/forecast`).then((r) => r.json()),
        fetch(`${API_BASE}/api/breakdown`).then((r) => r.json()),
      ]).then(([head, fc, brk]) => { if (live) setData({ head, fc, brk }) })
        .catch(() => {
          if (!live) return
          if (tries.current++ < 5) setTimeout(load, 900)
          else setLoadErr('The API is not responding. If you just started the server, give it a second and reload.')
        })
    }
    load()
    return () => { live = false }
  }, [])

  const tabs = [['outlook', 'Outlook'], ['register', 'At-risk register'], ['ask', 'Ask']]
  return (
    <div className="np-root" data-theme={theme}>
      <TipLayer>
        <div className="np-shell">
          <header className="np-header">
            <span className="np-title">Confirmation Outlook <span className="co">&mdash; Northpoint Manufacturing</span></span>
            <span className="np-demo-tag">synthetic demo</span>
            <span className="spacer" />
            {data && <span className="np-asof">as of {data.head.asof} &middot; {cwShort(data.head.latest)}</span>}
            <button className="np-btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
              {theme === 'dark' ? '☀' : '☾'}
            </button>
          </header>
          <nav className="np-tabs" role="tablist" aria-label="Views">
            {tabs.map(([k, label]) => (
              <button key={k} role="tab" aria-selected={tab === k} className="np-tab" onClick={() => setTab(k)}>{label}</button>
            ))}
          </nav>
          <main>
            {loadErr && <div className="np-note warn" style={{ marginTop: 24 }}>{loadErr}</div>}
            {!data && !loadErr && <div className="np-loading">loading the demo data&hellip;</div>}
            {data && tab === 'outlook' && <Outlook head={data.head} fc={data.fc} brk={data.brk} />}
            {data && tab === 'register' && <Register />}
            {data && tab === 'ask' && <Ask />}
          </main>
          <footer className="np-foot">
            <span>Built by Ian Provencher</span>
            <span>Northpoint Manufacturing is fictional; all data is synthetic (seeded generator, validated engine)</span>
            <a href={`${API_BASE}/docs`}>API</a>
            <a href="https://github.com/AceP2317/confirmation-outlook">Source</a>
          </footer>
        </div>
      </TipLayer>
    </div>
  )
}
