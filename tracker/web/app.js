'use strict';

const $view = document.getElementById('view');
const state = { pf: 'all', zoom: '10y', showPay: true, sel: null, year: null, month: null, audience: 'owner' };
const cache = {};

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = (n, dp = 2) => n == null ? '—' : (n < 0 ? '−$' : '$') + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
const kmoney = (n) => n == null ? '—' : (n < 0 ? '−$' : '$') + (Math.abs(n) / 1000).toFixed(1) + 'k';
const fmtDate = (s, opts = { day: 'numeric', month: 'short', year: 'numeric' }) => s ? new Date(s + 'T00:00:00').toLocaleDateString('en-GB', opts) : '';
const monthLabel = (s) => fmtDate(s, { month: 'short', year: '2-digit' });

async function api(path) {
  if (cache[path]) return cache[path];
  const r = await fetch(path, { credentials: 'same-origin' });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return (cache[path] = await r.json());
}

const PF_COLORS = {};

/* ------------------------------------------------------------------ status */
async function renderStatus() {
  const data = await api('/api/status');
  data.portfolios.forEach((p) => (PF_COLORS[p.key] = p.color));
  const pfs = data.portfolios.filter((p) => state.pf === 'all' || p.key === state.pf);
  const houses = data.portfolios.flatMap((p) => p.houses);
  const missing = data.portfolios.filter((p) => p.missing.length).map((p) => `${p.short}: ${p.missing.join(', ')}`);
  const vacant = houses.filter((h) => h.status === 'vacant');
  const attention = houses.reduce((n, h) => n + h.flags.length, 0);

  $view.innerHTML = `
    <div class="head">
      <div><h1>Status board</h1><div class="sub">What is happening at each house, from the latest statements and Mid South's emails.</div></div>
      <div class="seg" role="group" aria-label="Portfolio">
        ${[['all', 'All'], ...data.portfolios.map((p) => [p.key, p.short])].map(([k, l]) =>
          `<button class="btn ${state.pf === k ? 'on' : ''}" data-pf="${k}" aria-pressed="${state.pf === k}">${esc(l)}</button>`).join('')}
      </div>
    </div>
    ${missing.length ? `<div class="banner"><strong>Statements missing this year.</strong> ${esc(missing.join(' · '))}. Parts of this page may be out of date.</div>` : ''}
    <section class="grid tight" aria-label="At a glance">
      <div class="card"><div class="sub">Houses</div><div class="money-big">${houses.length}</div><div class="sub">${data.portfolios.map((p) => `${esc(p.short)} ${p.houses.length}`).join(' · ')}</div></div>
      <div class="card"><div class="sub">Let</div><div class="money-big">${houses.filter((h) => h.status === 'occupied').length}<span class="sub"> of ${houses.length}</span></div>
        <div class="sub">${vacant.length ? 'Vacant: ' + vacant.map((h) => esc(h.address)).join(', ') : 'None known vacant'}</div></div>
      <div class="card"><div class="sub">Needs attention</div><div class="money-big">${attention}</div><div class="sub">flags across all houses</div></div>
    </section>
    <section aria-label="Balance with Mid South">
      <div class="head" style="margin-bottom:10px"><h2>Balance with Mid South</h2>
        <div class="sub">Below zero: costs have run ahead of rent, and nothing is paid out until it recovers.</div></div>
      <div class="grid">${data.portfolios.map(balanceCard).join('')}</div>
    </section>
    ${pfs.map((p) => `
      <section style="display:flex;flex-direction:column;gap:12px">
        <div class="pf-head"><h2><span class="swatch" style="background:${p.color}"></span>${esc(p.name)}</h2>
          <span class="sub">${p.houses.length} houses · statements to ${fmtDate(p.data_through)}</span>
          <span class="right">${p.last_distribution ? `Last payout ${money(p.last_distribution.amount)} on ${fmtDate(p.last_distribution.date)}` : 'No payouts recorded'}</span></div>
        <div class="grid">${p.houses.map(houseCard).join('')}</div>
      </section>`).join('')}`;
  $view.querySelectorAll('[data-pf]').forEach((b) => b.onclick = () => { state.pf = b.dataset.pf; renderStatus(); });
}

function balanceCard(p) {
  const neg = p.balance < 0;
  const series = p.balance_series;
  const scale = Math.max(1000, ...series.map((x) => Math.abs(x.balance)));
  const cols = series.map((x) => {
    const h = Math.max(3, Math.abs(x.balance) / scale * 100).toFixed(1);
    return `<div class="col" title="${monthLabel(x.date)}: ${money(x.balance)}">
      <div class="up">${x.balance >= 0 ? `<div class="p" style="height:${h}%"></div>` : ''}</div>
      <div class="down">${x.balance < 0 ? `<div class="n" style="height:${h}%"></div>` : ''}</div></div>`;
  }).join('');
  return `<div class="card" style="display:flex;flex-direction:column;gap:10px">
    <div style="display:flex;align-items:center;gap:8px"><span class="swatch" style="background:${p.color}"></span><h3>${esc(p.short)}</h3>
      <span class="pill ${neg ? 'neg' : 'pos'}" style="margin-left:auto">${neg ? 'Below zero' : 'In credit'}</span></div>
    <div><span class="money-big ${neg ? 'neg-text' : ''}">${money(p.balance)}</span> <span class="sub">at ${fmtDate(p.balance_as_of)}</span></div>
    <div class="bars" role="img" aria-label="${esc(p.short)} month-end balances: ${series.map((x) => monthLabel(x.date) + ' ' + money(x.balance)).join(', ')}">${cols}</div>
    <div class="bars-labels">${series.map((x) => `<span>${fmtDate(x.date, { month: 'narrow' })}</span>`).join('')}</div>
  </div>`;
}

function houseCard(h) {
  const tenantLine = h.status === 'occupied' ? `${esc(h.tenant)}${h.since ? ' · since ' + fmtDate(h.since, { month: 'short', year: 'numeric' }) : ''}`
    : h.status === 'vacant' ? `Vacant since ${fmtDate(h.since)}` : `Last known tenant: ${esc(h.tenant || 'unknown')}`;
  const pay = h.payment ? `<span style="color:${h.payment.state === 'paid' ? '#1F6B3A' : '#8A5A00'}">${esc(h.payment.text)}</span>` : '<span class="sub">—</span>';
  return `<article class="card house">
    <div class="top"><div><h3>${esc(h.address)}</h3><div class="sub">${tenantLine}</div></div>
      <span class="pill ${h.status}">${h.status === 'occupied' ? 'Let' : h.status === 'vacant' ? 'Vacant' : 'Unconfirmed'}</span></div>
    <dl><div><dt>Rent</dt><dd class="mono">${h.rent ? money(h.rent, 0) + '/mo' : '—'}</dd></div>
        <div><dt>${h.payment ? esc(h.payment.month) + ' rent' : 'This month'}</dt><dd>${pay}</dd></div></dl>
    <div class="recent"><div class="label-sm">Recent</div>
      ${h.recent.length ? h.recent.map((e) => `<div class="row"><span class="d">${fmtDate(e.date, { day: 'numeric', month: 'short', year: '2-digit' })}</span><span>${esc(e.title)}${e.amount && e.type !== 'rent_change' ? ' · ' + money(e.amount) : ''}</span></div>`).join('') : '<span class="sub">Nothing recorded recently</span>'}
    </div>
    ${h.flags.map((f) => `<div class="flag ${f.level}">${esc(f.text)}</div>`).join('')}
    <a href="#timeline" data-goto="${esc(h.key)}" style="font-size:13px;font-weight:600">Open timeline</a>
  </article>`;
}

/* ---------------------------------------------------------------- timeline */
const SHAPES = {
  repair: (amt, on) => `<i style="width:${amt >= 5000 ? 20 : amt >= 500 ? 15 : 11}px;height:${amt >= 5000 ? 20 : amt >= 500 ? 15 : 11}px;border-radius:50%;background:#16191D;box-shadow:0 0 0 2px #fff"></i>`,
  make_ready: () => '<i style="width:14px;height:14px;border-radius:2px;background:#D97A1E;box-shadow:0 0 0 2px #fff"></i>',
  late: () => '<i style="width:15px;height:13px;background:#C98A00;clip-path:polygon(50% 0,100% 100%,0 100%)"></i>',
  returned: () => '<i style="width:15px;height:13px;background:#B42318;clip-path:polygon(50% 0,100% 100%,0 100%)"></i>',
  move_in: () => '<i style="width:11px;height:11px;background:#2563A8;transform:rotate(45deg)"></i>',
  move_out: () => '<i style="width:11px;height:11px;background:#fff;border:2px solid #2563A8;transform:rotate(45deg)"></i>',
  lease: () => '<i style="width:11px;height:11px;background:#2563A8;transform:rotate(45deg)"></i>',
  renewal: () => '<i style="width:11px;height:11px;background:#7FA2D0;transform:rotate(45deg)"></i>',
  eviction: () => '<i style="width:14px;height:14px;background:#8A1C14;border-radius:2px;transform:rotate(45deg)"></i>',
  transfer: () => '<i style="width:3px;height:34px;background:#6B7280"></i>',
};
const EVENT_LABEL = { repair: 'Repair', make_ready: 'Make-ready', late: 'Late or missing rent', returned: 'Returned payment',
  move_in: 'Moved in', move_out: 'Moved out', lease: 'Lease', renewal: 'Renewal', eviction: 'Eviction', legal: 'Legal',
  transfer: 'Ownership transfer', rent_change: 'Rent change', assistance: 'Rental assistance', theft: 'Theft',
  vandalism: 'Vandalism', repair_request: 'Repair request', update: 'Update from Mid South', inspection: 'Inspection',
  code_violation: 'Code violation', insurance: 'Insurance', maintenance: 'Maintenance', utility: 'Utilities' };
const HIDDEN = new Set(['maintenance', 'utility', 'rent_change']);
const PAYMENT_TYPES = new Set(['late', 'returned', 'assistance']);

async function renderTimeline() {
  const data = await api('/api/timeline');
  const today = new Date(data.today + 'T00:00:00');
  const allStarts = data.groups.flatMap((g) => g.rows.map((r) => new Date(r.first + 'T00:00:00')));
  const ranges = { all: new Date(Math.min(...allStarts)), '10y': addYears(today, -10), '3y': addYears(today, -3), '1y': addYears(today, -1) };
  const r0 = ranges[state.zoom].getTime(), r1 = addMonths(today, 2).getTime();
  const pct = (s) => ((new Date(s + 'T00:00:00').getTime() - r0) / (r1 - r0)) * 100;
  const clip = (a, b) => [Math.max(pct(a), 0), Math.min(pct(b), 100)];

  const ticks = [];
  if (state.zoom === '1y') {
    for (let d = new Date(new Date(r0).getFullYear(), new Date(r0).getMonth() + 1, 1); d.getTime() < r1; d = addMonths(d, 1))
      ticks.push({ p: (d.getTime() - r0) / (r1 - r0) * 100, l: d.toLocaleDateString('en-GB', { month: 'short' }) });
  } else {
    const step = state.zoom === 'all' ? 2 : 1;
    for (let y = new Date(r0).getFullYear() + 1; y <= today.getFullYear(); y += step) {
      const d = new Date(y, 0, 1); ticks.push({ p: (d.getTime() - r0) / (r1 - r0) * 100, l: String(y) });
    }
  }
  const tickHtml = (labels) => ticks.map((t) => `<div class="tl-tick" style="left:${t.p}%">${labels ? `<span>${t.l}</span>` : ''}</div>`).join('');
  let selected = null;

  const rowHtml = (r) => {
    const segs = r.segments.map((s, i) => {
      const [a, b] = clip(s.start, s.end); if (b <= a) return '';
      const cls = s.kind === 'tenant' ? `tenant ${i % 2 ? 'alt' : ''}` : s.kind;
      return `<div class="seg-bar ${cls}" style="left:${a}%;width:${b - a}%" title="${esc(s.label)} · ${fmtDate(s.start)} to ${fmtDate(s.end)}${s.kind === 'unconfirmed' ? ' (not confirmed: statements missing)' : ''}">${b - a > 5 ? esc(s.label) : ''}</div>`;
    }).join('');
    const gaps = r.gaps.map((g) => { const [a, b] = clip(g.start, g.end); return b > a ? `<div class="gap" style="left:${a}%;width:${b - a}%" title="No statements ${fmtDate(g.start)} to ${fmtDate(g.end)}"></div>` : ''; }).join('');
    const rents = r.rents.map((x) => { const p = pct(x.date); return p >= 0 && p < 100 ? `<div class="rent-step" style="left:${p}%">${money(x.rent, 0)}</div>` : ''; }).join('');
    const marks = r.events.filter((e) => !HIDDEN.has(e.type) && (state.showPay || !PAYMENT_TYPES.has(e.type))).map((e, i) => {
      const p = pct(e.date); if (p < 0 || p > 100) return '';
      const id = `${r.key}|${e.date}|${e.type}|${i}`;
      const on = state.sel === id; if (on) selected = { ...e, address: r.address };
      const shape = (SHAPES[e.type] || ((a) => '<i style="width:12px;height:12px;border-radius:50%;background:#6B7280;box-shadow:0 0 0 2px #fff"></i>'))(e.amount || 0, on);
      return `<button class="mark ${on ? 'sel' : ''}" style="left:${p}%" data-sel="${esc(id)}" aria-label="${esc((EVENT_LABEL[e.type] || e.type) + ', ' + fmtDate(e.date) + ': ' + e.title)}" title="${esc(fmtDate(e.date) + ': ' + e.title)}">${shape}</button>`;
    }).join('');
    const todayP = pct(data.today);
    return `<div class="tl-row" id="row-${esc(r.key)}"><div class="tl-name"><b>${esc(r.address)}</b><small>${r.still_owned ? '' : 'no longer in portfolio'}</small></div>
      <div class="tl-track">${tickHtml(false)}${segs}${gaps}${rents}${marks}<div class="today-line" style="left:${todayP}%"></div></div></div>`;
  };

  const body = data.groups.map((g) => `<div class="tl-group"><span class="swatch" style="background:${g.color}"></span>${esc(g.name)}</div>${g.rows.map(rowHtml).join('')}`).join('');
  $view.innerHTML = `
    <div class="head">
      <div><h1>Timeline</h1><div class="sub">Every tenancy, empty spell, payment problem and repair, house by house. Click a marker for the detail and its statement.</div></div>
      <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center">
        <button class="btn ${state.showPay ? 'on' : ''}" id="payToggle" aria-pressed="${state.showPay}">Payment markers: ${state.showPay ? 'on' : 'off'}</button>
        <div class="seg" role="group" aria-label="Zoom">${[['all', 'All'], ['10y', '10Y'], ['3y', '3Y'], ['1y', '1Y']].map(([k, l]) =>
          `<button class="btn ${state.zoom === k ? 'on' : ''}" data-zoom="${k}" aria-pressed="${state.zoom === k}">${l}</button>`).join('')}</div>
      </div>
    </div>
    <div class="legend">
      <span><i style="width:26px;height:13px;border-radius:3px;background:#DCE7F5;border:1px solid #8FB0DA"></i>Tenancy</span>
      <span><i style="width:26px;height:13px;border-radius:3px;background:repeating-linear-gradient(135deg,#FCEBD9 0 5px,#EFB98A 5px 7px);border:1px solid #E0A06A"></i>Vacant</span>
      <span><i style="width:26px;height:13px;border-radius:3px;border:1px dashed #8FB0DA"></i>Not confirmed</span>
      <span><i style="width:26px;height:13px;border-radius:3px;background:repeating-linear-gradient(45deg,#E4E6EA 0 4px,#F3F4F6 4px 8px)"></i>No statements</span>
      <span>${SHAPES.repair(100)}Repair</span><span>${SHAPES.make_ready()}Make-ready</span><span>${SHAPES.late()}Late / missing rent</span>
      <span>${SHAPES.returned()}Returned payment</span><span>${SHAPES.move_in()}Move in</span><span>${SHAPES.move_out()}Move out</span><span>${SHAPES.eviction()}Eviction</span>
    </div>
    <section class="tl"><div class="tl-inner">
      <div class="tl-row"><div class="tl-name"><span class="label-sm">Property</span></div><div class="tl-track tl-axis">${tickHtml(true)}</div></div>
      ${body}
    </div></section>
    <section class="card" id="detail" aria-live="polite"></section>`;

  const detail = document.getElementById('detail');
  if (selected) {
    const src = selected.source || '';
    const link = src.startsWith('statement:') ? `<a href="/api/statements/${src.split(':')[1]}/pdf" target="_blank" rel="noopener">Open the statement PDF</a>`
      : src.startsWith('email:') ? 'Email from Mid South (see Documents)' : src ? esc(src) : 'Worked out from the rent payments on the statements';
    detail.innerHTML = `<div class="label-sm">${esc(EVENT_LABEL[selected.type] || selected.type)}</div>
      <h3 style="margin:6px 0">${esc(selected.address)} · ${fmtDate(selected.date)}</h3>
      <div>${esc(selected.title)}</div>${selected.detail ? `<div class="sub">${esc(selected.detail)}</div>` : ''}
      ${selected.amount != null ? `<div class="mono" style="margin-top:6px">${money(selected.amount)}</div>` : ''}
      <div class="sub" style="margin-top:6px">Source: ${link}</div>`;
  } else {
    detail.innerHTML = '<div class="sub">Click any marker to see what happened and where it came from. Grey stripes mean no statements were received for that period; they are not vacancies.</div>';
  }
  $view.querySelectorAll('[data-zoom]').forEach((b) => b.onclick = () => { state.zoom = b.dataset.zoom; renderTimeline(); });
  document.getElementById('payToggle').onclick = () => { state.showPay = !state.showPay; renderTimeline(); };
  $view.querySelectorAll('[data-sel]').forEach((b) => b.onclick = () => { state.sel = b.dataset.sel; renderTimeline(); });
  if (state.focus) { document.getElementById('row-' + state.focus)?.scrollIntoView({ block: 'center' }); state.focus = null; }
}

function addYears(d, n) { const x = new Date(d); x.setFullYear(x.getFullYear() + n); return x; }
function addMonths(d, n) { const x = new Date(d); x.setMonth(x.getMonth() + n); return x; }

/* --------------------------------------------------------------- analytics */
async function renderAnalytics() {
  const data = await api('/api/analytics');
  const years = data.years;
  if (!state.year) state.year = years[years.length - 1];
  const shown = years.slice(-8);
  const pf = data.portfolios;
  const sum = (y, k) => pf.reduce((t, p) => t + ((p.years[y] || {})[k] || 0), 0);
  const y = state.year;
  const inc = sum(y, 'income'), exp = sum(y, 'expenses'), fee = sum(y, 'mgmt_fees'), dr = sum(y, 'draws');
  const prevInc = sum(String(Number(y) - 1), 'income');
  const partial = pf.some((p) => (p.years[y] || {}).source === 'monthly');

  const stacked = (key, title, note) => {
    const totals = shown.map((yy) => sum(yy, key));
    const max = Math.max(1, ...totals) * 1.1;
    const cols = shown.map((yy, i) => `<div style="display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;gap:4px">
        <span class="mono" style="font-size:11px">${kmoney(totals[i])}</span>
        <div class="stack" style="height:${totals[i] / max * 100}%">${pf.filter((p) => (p.years[yy] || {})[key] > 0).map((p) =>
          `<div title="${esc(p.short)} ${yy}: ${money(p.years[yy][key])}" style="flex:${p.years[yy][key]} 1 0;background:${p.color}"></div>`).join('')}</div></div>`).join('');
    return `<figure class="card" style="margin:0;display:flex;flex-direction:column;gap:12px">
      <figcaption><h2>${title}</h2><div class="sub">${note}</div></figcaption>
      <div class="legend">${pf.map((p) => `<span><span class="swatch" style="background:${p.color}"></span>${esc(p.short)}</span>`).join('')}</div>
      <div class="chart"><div class="yaxis"><span>${kmoney(max)}</span><span>${kmoney(max / 2)}</span><span>$0</span></div>
        <div class="plot" style="grid-template-columns:repeat(${shown.length},minmax(0,1fr))">${cols}</div></div>
      <div class="xlabels" style="grid-template-columns:repeat(${shown.length},minmax(0,1fr))">${shown.map((yy) => `<span>${yy}</span>`).join('')}</div>
    </figure>`;
  };

  const props = data.properties.filter((p) => p.years[y]).sort((a, b) => (a.portfolio || '').localeCompare(b.portfolio || '') || a.address.localeCompare(b.address));
  $view.innerHTML = `
    <div class="head"><div><h1>Analytics</h1><div class="sub">How each portfolio and house has performed. Years are statement years (to November until 2024, calendar years from 2025).</div></div>
      <label class="sub">Year <select id="year" class="btn">${years.map((yy) => `<option ${yy === y ? 'selected' : ''}>${yy}</option>`).join('')}</select></label></div>
    ${partial ? `<div class="banner">${y} is built from monthly statements so far and is incomplete until the annual statements arrive.</div>` : ''}
    <section class="grid tight">
      <div class="card"><div class="sub">Rental income</div><div class="money-big">${money(inc, 0)}</div><div class="sub">${prevInc && !partial ? ((inc / prevInc - 1) * 100).toFixed(1) + '% on ' + (Number(y) - 1) : partial ? 'Year to date' : ''}</div></div>
      <div class="card"><div class="sub">Expenses</div><div class="money-big">${money(exp, 0)}</div><div class="sub">${inc ? Math.round(exp / inc * 100) + '% of income' : ''}</div></div>
      <div class="card"><div class="sub">Management fees</div><div class="money-big">${money(fee, 0)}</div></div>
      <div class="card"><div class="sub">Net operating income</div><div class="money-big">${money(inc - exp - fee, 0)}</div></div>
      <div class="card"><div class="sub">Paid out to owners</div><div class="money-big">${money(dr, 0)}</div></div>
      <div class="card"><div class="sub">Return on capital</div><div class="money-big">—</div><div class="sub">Needs purchase prices</div></div>
    </section>
    <section class="grid" style="grid-template-columns:repeat(auto-fit,minmax(460px,1fr))">
      ${stacked('income', 'Rental income by portfolio', 'Hover a segment for its value.')}
      ${stacked('draws', 'Paid out to owners, by owner', 'Cross-check against bank deposits.')}
    </section>
    <section class="card"><h2 style="margin-bottom:8px">By portfolio, ${y}</h2><div class="scroll"><table>
      <thead><tr><th>Portfolio</th><th>Income</th><th>Expenses</th><th>Mgmt fees</th><th>Net operating income</th><th>Expense ratio</th><th>Paid out</th></tr></thead>
      <tbody>${pf.filter((p) => p.years[y]).map((p) => { const r = p.years[y]; const noi = r.income - r.expenses - r.mgmt_fees;
        return `<tr><td><span class="swatch" style="background:${p.color}"></span>${esc(p.name)}</td><td>${money(r.income, 0)}</td><td>${money(r.expenses, 0)}</td><td>${money(r.mgmt_fees, 0)}</td><td>${money(noi, 0)}</td><td style="color:${r.income && r.expenses / r.income > .5 ? '#B42318' : 'inherit'}">${r.income ? Math.round(r.expenses / r.income * 100) + '%' : '—'}</td><td>${money(r.draws, 0)}</td></tr>`; }).join('')}</tbody>
    </table></div></section>
    <section class="card"><h2 style="margin-bottom:8px">By house, ${y} (calendar year, from the ledger)</h2><div class="scroll"><table>
      <thead><tr><th>House</th><th>Income</th><th>Repairs</th><th>Other costs</th><th>Mgmt fees</th><th>Net</th></tr></thead>
      <tbody>${props.map((p) => { const r = p.years[y];
        return `<tr><td><span class="swatch" style="background:${PF_COLORS[p.portfolio] || '#9AA1AB'}"></span>${esc(p.address)}</td><td>${money(r.income, 0)}</td><td>${money(r.repairs, 0)}</td><td>${money(r.expenses - r.repairs, 0)}</td><td>${money(r.mgmt_fees, 0)}</td><td>${money(r.income - r.expenses - r.mgmt_fees, 0)}</td></tr>`; }).join('')}</tbody>
    </table></div></section>`;
  document.getElementById('year').onchange = (e) => { state.year = e.target.value; renderAnalytics(); };
}

/* ----------------------------------------------------------------- summary */
async function renderSummary() {
  if (!state.month) { const t = new Date(); t.setDate(1); t.setMonth(t.getMonth() - 1); state.month = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}`; }
  $view.innerHTML = '<div class="sub">Loading…</div>';
  const path = `/api/summary?month=${state.month}&audience=${state.audience}`;
  const data = await api(path);
  const label = new Date(state.month + '-01T00:00:00').toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
  const factsHtml = data.facts.portfolios.map((p) => `<h3 style="margin-top:12px">${esc(p.portfolio)}</h3>
    ${typeof p.statement === 'string' ? `<div class="flag amber">${esc(p.statement)}</div>` : `<div class="sub">Rent ${money(p.statement.income)} · costs ${money(p.statement.expenses + p.statement.management_fees)} · paid out ${money(p.statement.paid_out_to_owner)} · balance ${money(p.statement.balance_end)}</div>`}
    ${p.houses.map((h) => `<div style="margin-top:6px"><b>${esc(h.house)}</b> · ${esc(h.tenant)} · rent received ${money(h.rent_received)}${h.events.length ? '<br><span class="sub">' + h.events.map((e) => esc(e.what)).join('; ') + '</span>' : ''}</div>`).join('')}`).join('');
  $view.innerHTML = `
    <div class="head"><div><h1>${label}</h1><div class="sub">Written from the statements and Mid South's emails for the month.</div></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn" id="prev" aria-label="Previous month">‹</button><button class="btn" id="next" aria-label="Next month">›</button>
        <div class="seg" role="group" aria-label="Version">${[['owner', 'Full summary'], ['family', 'Family version: Torgo']].map(([k, l]) =>
          `<button class="btn ${state.audience === k ? 'on' : ''}" data-aud="${k}" aria-pressed="${state.audience === k}">${l}</button>`).join('')}</div>
      </div></div>
    <div class="two"><div class="main">
      <article class="card">${data.text ? `<div class="letter" id="letter">${esc(data.text)}</div>`
        : `<div class="banner">${data.llm ? 'No summary written yet.' : 'Set ANTHROPIC_API_KEY to have Claude write this letter. The facts it would use:'}</div>${factsHtml}`}</article>
    </div><aside class="side">
      <section class="card" style="display:flex;flex-direction:column;gap:10px"><h2>Send</h2>
        <div class="sub">Copy the letter into an email, or open it in your mail app.</div>
        <button class="btn" id="copy" ${data.text ? '' : 'disabled'}>Copy text</button>
        <a class="btn" style="display:flex;align-items:center;justify-content:center;text-decoration:none" href="mailto:?subject=${encodeURIComponent((state.audience === 'family' ? 'Torgo houses, ' : 'Rentals, ') + label)}&body=${encodeURIComponent(data.text || '')}">Open in email</a>
        <button class="btn" id="regen" ${data.llm ? '' : 'disabled'}>Rewrite</button>
      </section>
      <section class="card"><h2>Facts used</h2><div style="font-size:14px">${factsHtml}</div></section>
    </aside></div>`;
  const shift = (n) => { const d = new Date(state.month + '-01T00:00:00'); d.setMonth(d.getMonth() + n); state.month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; renderSummary(); };
  document.getElementById('prev').onclick = () => shift(-1);
  document.getElementById('next').onclick = () => shift(1);
  $view.querySelectorAll('[data-aud]').forEach((b) => b.onclick = () => { state.audience = b.dataset.aud; renderSummary(); });
  document.getElementById('copy').onclick = () => navigator.clipboard.writeText(data.text || '');
  document.getElementById('regen').onclick = async () => { delete cache[path]; await api(path + '&refresh=true'); delete cache[path]; renderSummary(); };
}

/* --------------------------------------------------------------- documents */
async function renderDocuments() {
  delete cache['/api/documents']; delete cache['/api/emails'];
  const [docs, emails] = await Promise.all([api('/api/documents'), api('/api/emails')]);
  $view.innerHTML = `
    <div class="head"><div><h1>Documents and emails</h1><div class="sub">Every PDF received, whether it reconciled, and what was read from Mid South's emails.</div></div>
      <label class="btn" style="display:flex;align-items:center">Upload statement PDFs<input type="file" id="upload" accept="application/pdf" multiple hidden></label></div>
    <div id="uploadResult" class="sub"></div>
    <section class="card"><h2 style="margin-bottom:8px">Statements</h2><div class="scroll"><table>
      <thead><tr><th>File</th><th>Received</th><th>Status</th><th>Statements</th></tr></thead>
      <tbody>${docs.map((d) => `<tr><td>${esc(d.filename)}<div class="sub">${esc(d.source)}</div></td><td>${d.received_at ? fmtDate(d.received_at.slice(0, 10)) : '—'}</td>
        <td style="font-family:inherit">${esc(d.status)}${d.problems ? `<div class="sub err">${esc(d.problems)}</div>` : ''}</td>
        <td style="font-family:inherit">${d.statements.map((s) => `<a href="/api/statements/${s.id}/pdf" target="_blank" rel="noopener">${esc(s.portfolio || '?')} ${fmtDate(s.start)}–${fmtDate(s.end)}</a>`).join('<br>')}</td></tr>`).join('')}</tbody>
    </table></div></section>
    <section class="card"><h2 style="margin-bottom:8px">Emails from Mid South</h2><div class="scroll"><table>
      <thead><tr><th>Date</th><th>Subject</th><th>Kind</th><th>What was read</th></tr></thead>
      <tbody>${emails.map((e) => `<tr><td>${e.date ? fmtDate(e.date.slice(0, 10)) : ''}</td><td style="font-family:inherit">${esc(e.subject)}</td><td style="font-family:inherit">${esc(e.kind)}${e.status === 'needs_review' ? ' · needs review' : ''}</td><td style="font-family:inherit">${esc(e.summary || '')}</td></tr>`).join('')}</tbody>
    </table></div></section>`;
  document.getElementById('upload').onchange = async (e) => {
    const out = document.getElementById('uploadResult');
    const counts = {};
    const files = [...e.target.files];
    for (const [i, file] of files.entries()) {
      out.textContent = `Uploading ${i + 1} of ${files.length}: ${file.name}`;
      const fd = new FormData(); fd.append('file', file);
      const r = await fetch('/api/upload', { method: 'POST', body: fd });
      const j = r.ok ? await r.json() : { status: 'error' };
      counts[j.status] = (counts[j.status] || 0) + 1;
    }
    Object.keys(cache).forEach((k) => delete cache[k]);
    await renderDocuments();
    document.getElementById('uploadResult').textContent = 'Uploaded: ' + Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(', ');
  };
}

/* ------------------------------------------------------------------ router */
const VIEWS = { status: renderStatus, timeline: renderTimeline, analytics: renderAnalytics, summary: renderSummary, documents: renderDocuments };
async function route() {
  const name = (location.hash || '#status').slice(1);
  document.querySelectorAll('.topbar nav a').forEach((a) => a.classList.toggle('active', a.dataset.view === name));
  try { await (VIEWS[name] || renderStatus)(); }
  catch (err) { $view.innerHTML = `<div class="card err">Could not load: ${esc(err.message)}</div>`; }
}
document.addEventListener('click', (e) => { const g = e.target.closest('[data-goto]'); if (g) state.focus = g.dataset.goto; });
window.addEventListener('hashchange', route);
api('/api/status').then((d) => d.portfolios.forEach((p) => (PF_COLORS[p.key] = p.color))).catch(() => {});
route();
