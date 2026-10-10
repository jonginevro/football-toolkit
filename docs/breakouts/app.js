/* Breakouts page — static front end.
 *
 * Every player's log-odds arrive pre-split into factor groups:
 *   logit = base + talent + role + profile + ceiling (+ notes on the live board)
 * so re-weighting a group is just multiplying its term. That's what lets the
 * sliders re-score the live board AND every past season instantly. */
(() => {
  "use strict";

  const GROUPS = ["talent", "role", "profile", "ceiling"];
  const POS = ["QB", "RB", "WR", "TE"];
  const STORE_KEY = "bb-settings";

  const S = {
    meta: null,
    board: [],
    hist: {},            // season -> preseason board rows
    histReady: false,
    mult: Object.fromEntries(GROUPS.map((g) => [g, 1])),
    pos: new Set(POS),
    q: "",
    maxExp: 6,
    tier: "",
    topN: 50,
    val: null,           // {floor, peak, sigma, unranked}; defaults from meta
    sort: "score",
    open: null,
    season: null,
    histShown: 20,
    histOpen: null,
    walkKey: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sigmoid = (x) => 1 / (1 + Math.exp(-x));
  const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? "—" : Number(v).toFixed(d));
  const pct = (p) => (p * 100 < 1 ? "<1" : Math.round(p * 100)) + "%";

  function rows(table) {
    return table.rows.map((r) => Object.fromEntries(table.cols.map((c, i) => [c, r[i]])));
  }

  /** The value "sweet spot": peaks at a market rank, falls off for stars
   *  (priced in) and for players nobody ranks. */
  function valueMult(r, val = S.val) {
    const rank = Math.max(r.ecr ?? val.unranked, 1);
    const z = (Math.log10(rank) - Math.log10(val.peak)) / val.sigma;
    return val.floor + (1 - val.floor) * Math.exp(-0.5 * z * z);
  }

  /** Board score: breakout chance weighted by value, 0–100. */
  function score(r, mult = S.mult, val = S.val) {
    return 100 * sigmoid(logit(r, mult)) * valueMult(r, val);
  }

  function saveSettings() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({ mult: S.mult, val: S.val, maxExp: S.maxExp, tier: S.tier, topN: S.topN }));
    } catch (_) { /* storage unavailable */ }
  }

  function logit(r, mult = S.mult) {
    let x = r.base + (r.notes || 0);
    for (const g of GROUPS) x += mult[g] * r[g];
    return x;
  }

  // ------------------------------------------------------------------ load
  const getJSON = FT.getJSON;

  async function init() {
    const [meta, board] = await Promise.all([getJSON("meta.json"), getJSON("board.json")]);
    S.meta = meta;
    S.val = { floor: meta.value.floor, peak: meta.value.peak_rank, sigma: meta.value.sigma, unranked: meta.value.unranked };
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
      if (saved) {
        for (const g of GROUPS) if (typeof saved.mult?.[g] === "number") S.mult[g] = saved.mult[g];
        if (saved.val) { S.val.floor = saved.val.floor ?? S.val.floor; S.val.peak = saved.val.peak ?? S.val.peak; }
        if (typeof saved.maxExp === "number") S.maxExp = saved.maxExp;
        if (typeof saved.tier === "string") S.tier = saved.tier;
        if (typeof saved.topN === "number") S.topN = saved.topN;
      }
    } catch (_) { /* storage unavailable: defaults are fine */ }
    S.board = rows(board);
    S.season = meta.history_seasons[meta.history_seasons.length - 1];

    const st = meta.mode === "preseason"
      ? `${meta.season} preseason`
      : `${meta.season} · going into week ${meta.week} · stats through week ${meta.stats_through}`;
    $("#asof").textContent = st;
    $("#generated").textContent = `Updated ${new Date(meta.generated).toLocaleString()}.`;

    buildSliders();
    buildBoardControls();
    buildHistoryControls();
    renderMethod();
    renderBoard();
    route();
    window.addEventListener("hashchange", route);

    // every preseason board is needed for the History page and the walkthrough
    const loaded = await Promise.all(meta.history_seasons.map((s) =>
      getJSON(`history/${s}.json`).catch(() => null)));
    for (const h of loaded) {
      if (!h) continue;
      S.hist[h.season] = rows(h);
    }
    S.histReady = true;
    renderHistory();
    setupWalk();
  }

  // ------------------------------------------------------------------ routing
  function route() {
    const tab = (location.hash || "#board").slice(1);
    const known = ["board", "history", "method"].includes(tab) ? tab : "board";
    for (const t of ["board", "history", "method"]) $(`#tab-${t}`).hidden = t !== known;
    document.querySelectorAll("#tabs a[data-tab]").forEach((a) =>
      a.classList.toggle("active", a.dataset.tab === known));
    $(".controls").hidden = known === "method";
    $("#filters").hidden = known !== "board";
  }

  // ------------------------------------------------------------------ tuner
  function buildSliders() {
    const box = $("#sliders");
    box.innerHTML = S.meta.groups.map((g) => `
      <div class="slider">
        <label for="w-${g.key}"><span><i class="dot" style="background:var(--g-${g.key})"></i>${esc(g.label)}</span>
          <span class="v" id="wv-${g.key}"></span></label>
        <input type="range" id="w-${g.key}" min="0" max="2" step="0.1" value="${S.mult[g.key]}" />
        <p>${esc(g.blurb)}</p>
      </div>`).join("");
    for (const g of GROUPS) {
      const input = $(`#w-${g}`);
      input.addEventListener("input", () => { S.mult[g] = +input.value; rescore(); });
    }
    const tog = $("#weights-toggle"), panel = $("#weights-panel");
    tog.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      tog.setAttribute("aria-expanded", String(!panel.hidden));
    });
    $("#reset").addEventListener("click", resetWeights);
    const emph = $("#v-emph"), peak = $("#v-peak");
    emph.value = 1 - S.val.floor;
    peak.value = S.val.peak;
    emph.addEventListener("input", () => { S.val.floor = 1 - +emph.value; rescore(); });
    peak.addEventListener("input", () => { S.val.peak = +peak.value; rescore(); });
    updateSliderLabels();
  }

  function rescore() {
    saveSettings();
    updateSliderLabels();
    renderBoard();
    renderReset();
    renderHistory();
    if (S.walkKey) renderWalk(S.walkKey);
  }

  function updateSliderLabels() {
    for (const g of GROUPS) $(`#wv-${g}`).textContent = `${S.mult[g].toFixed(1)}×`;
    $("#v-emph-v").textContent = `${Math.round((1 - S.val.floor) * 100)}%`;
    $("#v-peak-v").textContent = `ECR ${S.val.peak}`;
  }

  function defaults() {
    const v = S.meta.value;
    return { mult: Object.fromEntries(GROUPS.map((g) => [g, 1])),
             val: { floor: v.floor, peak: v.peak_rank, sigma: v.sigma, unranked: v.unranked } };
  }

  function resetWeights() {
    const d = defaults();
    S.mult = d.mult;
    S.val = d.val;
    for (const g of GROUPS) $(`#w-${g}`).value = 1;
    $("#v-emph").value = 1 - S.val.floor;
    $("#v-peak").value = S.val.peak;
    rescore();
  }

  function isDefault() {
    const d = defaults();
    return GROUPS.every((g) => S.mult[g] === 1) && S.val.floor === d.val.floor && S.val.peak === d.val.peak;
  }

  /** PPR/g change that season (players who didn't play have no change to report). */
  const gain = (r) => (r.season_g ? r.season_ppg - r.baseline : null);
  const mean = (xs) => { const v = xs.filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0; };
  const signed = (v) => {
    const t = Math.abs(v).toFixed(1);
    return +t === 0 ? "0.0" : `${v > 0 ? "+" : "−"}${t}`;
  };

  /** The board sorted by score, the top k's average change, and the whole pool's for comparison. */
  function evalRows(rs, mult = S.mult, val = S.val, k = 20) {
    const sorted = rs.map((r) => ({ r, p: logit(r, mult), s: score(r, mult, val) })).sort((a, b) => b.s - a.s);
    const top = sorted.slice(0, k);
    const ecrs = top.map((x) => x.r.ecr ?? val.unranked).sort((a, b) => a - b);
    return { sorted, topGain: mean(top.map((x) => gain(x.r))), poolGain: mean(rs.map(gain)),
             medEcr: ecrs[Math.floor(ecrs.length / 2)] };
  }

  /** Reset only shows once a scoring setting differs from the default. */
  function renderReset() {
    $("#reset").hidden = isDefault();
  }

  // ------------------------------------------------------------------ shared bits
  function contribStrip(r, mult = S.mult) {
    // scale: 2.5 log-odds fills half the strip
    const W = 80 / 2.5;
    const parts = GROUPS.map((g) => ({ g, v: mult[g] * r[g] }));
    if (r.notes) parts.push({ g: "notes", v: r.notes });
    const seg = (xs) => xs.map(({ g, v }) =>
      `<i style="width:${Math.min(Math.abs(v) * W, 80)}px;background:var(--g-${g})"></i>`).join("");
    const neg = parts.filter((x) => x.v < 0).sort((a, b) => a.v - b.v);
    const pos = parts.filter((x) => x.v > 0).sort((a, b) => b.v - a.v);
    return `<div class="contrib" title="Factor contributions (left = holding back, right = pushing up)">
      <div class="neg">${seg(neg.reverse())}</div><div class="pos-side">${seg(pos)}</div></div>`;
  }

  function groupRows(r, mult = S.mult) {
    const labels = Object.fromEntries(S.meta.groups.map((g) => [g.key, g.label]));
    const items = GROUPS.map((g) => [labels[g], mult[g] * r[g], g]);
    if (r.notes) items.push(["Your notes", r.notes, "notes"]);
    return items.map(([label, v, g]) => {
      const w = Math.min(Math.abs(v) / 3, 1) * 50;
      const left = v >= 0 ? 50 : 50 - w;
      return `<div class="grow"><span>${esc(label)}</span><span class="track">
        <span class="fill" style="left:${left}%;width:${w}%;background:var(--g-${g})"></span></span>
        <span class="num muted">${v >= 0 ? "+" : ""}${v.toFixed(2)}</span></div>`;
    }).join("");
  }

  function playerCell(r, withImg = true) {
    const img = withImg && r.headshot
      ? `<img loading="lazy" src="${esc(r.headshot)}" alt="" onerror="this.style.visibility='hidden'">` : "";
    const inj = FT.injTag(r.injury);
    const age = r.age ? ` · ${fmt(r.age)}y` : "";
    const yr = r.exp === 0 ? " · rookie" : ` · yr ${r.exp + 1}`;
    return `<div class="player">${img}<div><div class="nm">${esc(r.name)}${inj}</div>
      <div class="sub"><span class="pos ${r.pos}">${r.pos}</span>${esc(r.team)}${age}${yr}</div></div></div>`;
  }

  function why(r) {
    const up = (r.up || []).slice(0, 2).map(esc).join(" · ");
    const dn = (r.down || []).slice(0, 1).map((t) => `<span class="dn">but ${esc(t.charAt(0).toLowerCase() + t.slice(1))}</span>`);
    return [up, ...dn].filter(Boolean).join(" · ");
  }

  function chg(v) {
    if (v == null || Math.abs(v) < 0.05) return '<span class="muted">0.0</span>';
    return `<span class="${v > 0 ? "pos-c" : "neg-c"}">${v > 0 ? "+" : ""}${v.toFixed(1)}</span>`;
  }

  function depthText(d) { return d === 1 ? "Starter" : d === 2 ? "Backup" : d ? "Deep" : "Not listed"; }

  function detailRow(r, colspan, extra = "") {
    const pick = r.pick ? `#${r.pick}` : "Undrafted";
    return `<tr class="detail"><td colspan="${colspan}"><div class="detail-grid">
      <div><h5>Factor contributions (log-odds)</h5>${groupRows(r)}</div>
      <div><h5>Why</h5><ul>${(r.up || []).map((t) => `<li>${esc(t)}</li>`).join("")}
        ${(r.down || []).map((t) => `<li class="muted">${esc(t)}</li>`).join("")}</ul></div>
      <div><h5>Numbers</h5><dl class="kv">
        <dt>Established level</dt><dd>${fmt(r.baseline)} PPR/g</dd>
        <dt>Last season</dt><dd>${fmt(r.prior_ppg)} PPR/g</dd>
        ${r.ytd_g ? `<dt>This season</dt><dd>${fmt(r.ytd_ppg)} PPR/g in ${r.ytd_g} g</dd>` : ""}
        <dt>Share of team work</dt><dd>${Math.round((r.share || 0) * 100)}%</dd>
        <dt>Work up for grabs</dt><dd>${Math.round((r.open || 0) * 100)}%</dd>
        <dt>Depth chart</dt><dd>${depthText(r.depth)}</dd>
        <dt>Draft pick</dt><dd>${pick}</dd>
        ${extra}
      </dl></div></div></td></tr>`;
  }

  // ------------------------------------------------------------------ board
  function buildBoardControls() {
    const chips = $("#pos-chips");
    chips.innerHTML = POS.map((p) => `<span class="chip" data-pos="${p}">${p}</span>`).join("");
    const paintChips = () => chips.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", S.pos.has(x.dataset.pos)));
    paintChips();
    chips.addEventListener("click", (e) => {
      const c = e.target.closest(".chip");
      if (!c) return;
      const p = c.dataset.pos;
      if (S.pos.has(p)) { S.pos.delete(p); if (!S.pos.size) S.pos = new Set(POS); }
      else S.pos.add(p);
      paintChips();
      renderBoard();
    });
    const exp = $("#exp");
    exp.value = S.maxExp;
    $("#exp-v").textContent = `${S.maxExp} yrs`;
    exp.addEventListener("input", () => { S.maxExp = +exp.value; $("#exp-v").textContent = `${S.maxExp} yrs`; saveSettings(); renderBoard(); });
    $("#tier").value = S.tier;
    $("#tier").addEventListener("change", (e) => { S.tier = e.target.value; saveSettings(); renderBoard(); });
    $("#search").addEventListener("input", (e) => { S.q = e.target.value.trim().toLowerCase(); renderBoard(); });
    const topn = $("#topn");
    topn.value = S.topN;
    if (![...topn.options].some((o) => +o.value === S.topN)) { S.topN = 50; topn.value = 50; }
    topn.addEventListener("change", () => { S.topN = +topn.value; saveSettings(); renderBoard(); });
    document.querySelectorAll("#board th.sortable").forEach((th) => th.addEventListener("click", () => {
      S.sort = th.dataset.sort;
      renderBoard();
    }));
    $("#board tbody").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-id]");
      if (!tr) return;
      S.open = S.open === tr.dataset.id ? null : tr.dataset.id;
      renderBoard();
    });
  }

  function inTier(r) {
    const e = r.ecr ?? Infinity;
    if (S.tier === "start") return e <= 100;
    if (S.tier === "cheap") return e > 100 && e <= 250;
    if (S.tier === "deep") return e > 250;
    return true;
  }

  function renderBoard() {
    const scored = S.board.map((r) => ({ ...r, prob: sigmoid(logit(r)), score: score(r) }));
    const rankOf = new Map([...scored].sort((a, b) => b.score - a.score).map((r, i) => [r.id, i + 1]));
    let list = scored.filter((r) => S.pos.has(r.pos) && r.exp <= S.maxExp && inTier(r));
    if (S.q) list = list.filter((r) => r.name.toLowerCase().includes(S.q) || r.team.toLowerCase() === S.q);

    const key = S.sort;
    const asc = key === "ecr" || key === "own";  // cheapest / least rostered first
    list.sort((a, b) => {
      const va = a[key], vb = b[key];
      if (va == null && vb == null) return b.score - a.score;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (va === vb) return b.score - a.score;
      return asc ? va - vb : vb - va;
    });
    document.querySelectorAll("#board th.sortable").forEach((th) =>
      th.classList.toggle("sorted", th.dataset.sort === key));

    const max = Math.max(...scored.map((r) => r.score), 1);
    $("#board tbody").innerHTML = list.slice(0, S.topN).map((r) => {
      const row = `<tr data-id="${esc(r.id)}">
        <td class="num muted">${rankOf.get(r.id)}</td>
        <td>${playerCell(r)}</td>
        <td><div class="scorebar"><span class="bar"><i style="width:${(r.score / max) * 100}%"></i></span>
          <b>${r.score.toFixed(1)}</b></div></td>
        <td class="num">${pct(r.prob)}</td>
        <td class="num hide-sm">${r.ecr == null ? '<span class="muted" title="Not in FantasyPros rankings">—</span>' : r.ecr}</td>
        <td class="num hide-sm">${fmt(r.own, 0)}%</td>
        <td class="num hide-sm">${chg(r.own_chg)}</td>
        <td class="hide-sm"><div class="why">${why(r)}</div></td>
      </tr>`;
      if (S.open !== r.id) return row;
      const adds = r.adds7d == null ? '<span class="muted">not in Sleeper\'s top 100</span>'
        : `${r.adds24 == null ? "—" : Number(r.adds24).toLocaleString()} (24h) · ${Number(r.adds7d).toLocaleString()} (7d)`;
      const extra = `<dt>Value multiplier</dt><dd>×${valueMult(r).toFixed(2)} (ECR ${r.ecr ?? "unranked"})</dd>
        <dt>ESPN rostered</dt><dd>${fmt(r.own, 1)}% (${chg(r.own_chg)} this week)</dd>
        <dt>Sleeper adds</dt><dd>${adds}</dd>`;
      return row + detailRow(r, 8, extra);
    }).join("") || `<tr><td colspan="8" class="muted">No players match.</td></tr>`;
  }

  // ------------------------------------------------------------------ history
  // Preseason boards only: what the model said before each season, graded on
  // the full season.
  function buildHistoryControls() {
    const m = S.meta;
    $("#season-chips").innerHTML = m.history_seasons.map((s) =>
      `<span class="chip" data-season="${s}">${s}</span>`).join("");
    const pickSeason = (s) => { S.season = s; S.histShown = 20; S.histOpen = null; renderHistory(); };
    $("#season-chips").addEventListener("click", (e) => {
      const c = e.target.closest(".chip"); if (c) pickSeason(+c.dataset.season);
    });
    $("#season-bars").addEventListener("click", (e) => {
      const c = e.target.closest(".sbar"); if (c) pickSeason(+c.dataset.season);
    });
    $("#hist-more").addEventListener("click", () => { S.histShown += 20; renderHistory(); });
    $("#hist-board tbody").addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-id]"); if (!tr) return;
      S.histOpen = S.histOpen === tr.dataset.id ? null : tr.dataset.id; renderHistory();
    });
  }

  function changeCell(r) {
    const g = gain(r);
    if (g == null) return '<span class="muted">—</span>';
    const cls = signed(g) === "0.0" ? "muted" : g > 0 ? "pos-c" : "neg-c";
    return `<span class="${cls}">${signed(g)}</span>`;
  }

  function renderHistory() {
    document.querySelectorAll("#season-chips .chip").forEach((c) => c.classList.toggle("on", +c.dataset.season === S.season));
    if (!S.histReady) { $("#season-summary").innerHTML = '<p class="muted">Loading history…</p>'; return; }

    const rs = S.hist[S.season];
    if (!rs) { $("#season-summary").innerHTML = '<p class="muted">No board for that season.</p>'; return; }
    const ev = evalRows(rs, S.mult);
    const top20 = ev.sorted.slice(0, 20).map((x) => x.r).filter((r) => r.season_g);
    $("#hist-title").textContent = `The ${S.season} preseason board`;

    $("#season-summary").innerHTML = `
      <div class="kstat"><span class="kv">${fmt(mean(top20.map((r) => r.baseline)))} → ${fmt(mean(top20.map((r) => r.season_ppg)))}</span><span class="kl">top 20's average PPR/g, before → that season</span></div>
      <div class="kstat"><span class="kv">${signed(ev.topGain)}</span><span class="kl">top 20's average change</span></div>
      <div class="kstat"><span class="kv">${signed(ev.poolGain)}</span><span class="kl">average change, all ${rs.length} eligible</span></div>
      <div class="kstat"><span class="kv">${Math.round(ev.medEcr)}</span><span class="kl">median ECR of the top 20</span></div>`;

    $("#hist-board tbody").innerHTML = ev.sorted.slice(0, S.histShown).map(({ r, p, s: sc }, i) => {
      const row = `<tr data-id="${esc(r.id)}">
        <td class="num muted">${i + 1}</td><td>${playerCell(r, false)}</td>
        <td class="num"><b>${sc.toFixed(1)}</b></td><td class="num">${pct(sigmoid(p))}</td>
        <td class="num hide-sm">${r.ecr ?? '<span class="muted">—</span>'}</td>
        <td class="num">${r.exp === 0 ? '<span class="muted">rookie</span>' : fmt(r.baseline)}</td>
        <td class="num">${r.season_g ? fmt(r.season_ppg) : "—"}</td>
        <td class="num">${changeCell(r)}</td></tr>`;
      if (S.histOpen !== r.id) return row;
      const extra = `<dt>${S.season} season</dt><dd>${fmt(r.season_ppg)} PPR/g in ${r.season_g} g</dd>
        ${r.next_ppg != null ? `<dt>${S.season + 1} season</dt><dd>${fmt(r.next_ppg)} PPR/g</dd>` : ""}`;
      return row + detailRow(r, 8, extra);
    }).join("");
    $("#hist-more").hidden = S.histShown >= ev.sorted.length;

    const missed = ev.sorted.map((x, i) => ({ ...x, rank: i + 1 }))
      .filter((x) => x.rank > 20 && gain(x.r) != null)
      .sort((a, b) => gain(b.r) - gain(a.r)).slice(0, 12);
    $("#missed").innerHTML = missed.map(({ r, rank: rk }) => `<li>
      <span><span class="pos ${r.pos}">${r.pos}</span>${esc(r.name)} <span class="muted">${esc(r.team)}</span></span>
      <span class="r">${r.exp === 0 ? "rookie" : fmt(r.baseline)} → ${fmt(r.season_ppg)} · ranked #${rk}${r.ecr ? ` · ECR ${r.ecr}` : ""}</span></li>`).join("");

    $("#season-bars").innerHTML = S.meta.history_seasons.map((s) => {
      const w = S.hist[s];
      if (!w) return "";
      const e = evalRows(w, S.mult);
      return `<div class="sbar ${s === S.season ? "on" : ""}" data-season="${s}">
        <div class="yr">${s}</div><div class="hits">${signed(e.topGain)}</div>
        <div class="rand">all players ${signed(e.poolGain)}</div></div>`;
    }).join("");
  }

  // ------------------------------------------------------------------ method
  const FEAT = {
    log_pick: ["Draft capital", (r) => (r.pick ? `pick ${r.pick}` : "undrafted")],
    eff_rel: ["Points per touch", (r) => (r.exp === 0 && !r.ytd_g ? "no NFL touches yet"
      : r.eff != null ? `${Math.round(r.eff * 100)}% of ${r.pos} avg` : "—")],
    prior_ppg_rel: ["Last season", (r) => (r.exp === 0 ? "rookie, none" : `${fmt(r.prior_ppg)} PPR/g`)],
    own_share: ["Share of team work", (r) => `${Math.round((r.share || 0) * 100)}%`],
    open_opp: ["Work up for grabs", (r) => `${Math.round((r.open || 0) * 100)}% of team ${r.pos} work`],
    starter: ["Depth chart: starter", (r) => (r.depth === 1 ? "yes" : "no")],
    backup: ["Depth chart: next up", (r) => (r.depth === 2 ? "yes" : "no")],
    new_team: ["New team", (r) => (r.new_team ? "yes" : "no")],
    recent_delta: ["Usage trend, last 2 games", (r) => (r.recent ? `${r.recent > 0 ? "+" : ""}${Math.round(r.recent * 100)}% share` : "—")],
    rookie: ["Rookie", (r) => (r.exp === 0 ? "yes" : "no")],
    year2: ["Year 2", (r) => (r.exp === 1 ? "yes" : "no")],
    year3: ["Year 3", (r) => (r.exp === 2 ? "yes" : "no")],
    age_rel: ["Age", (r) => (r.age ? `${fmt(r.age)}` : "—")],
    baseline_rel: ["Current level", (r) => `${fmt(r.baseline)} PPR/g`],
  };
  const GROUP_OF = {};

  function exampleOptions() {
    const m = S.meta;
    const now = S.board.map((r) => ({ r, p: score(r) })).sort((a, b) => b.p - a.p).slice(0, 20);
    const ctxNow = m.week === 1 ? `${m.season} preseason` : `${m.season}, week ${m.week}`;
    const opts = [{ group: `Today's board (${ctxNow})`, items: now.map(({ r }, i) =>
      ({ key: `b:${r.id}`, label: `#${i + 1} ${r.name} (${r.pos}, ${r.team})` })) }];
    for (const s of [...m.history_seasons].reverse()) {
      const rs = S.hist[s];
      if (!rs) continue;
      const top = evalRows(rs, S.mult).sorted.slice(0, 12);
      opts.push({ group: `${s} preseason board`, items: top.map(({ r }, i) =>
        ({ key: `h:${s}:${r.id}`, label: `#${i + 1} ${r.name} (${r.pos})` })) });
    }
    return opts;
  }

  /** Quick picks: today's #1 and the top of the latest preseason board. */
  function quickPicks() {
    const picks = [];
    const now = S.board.map((r) => ({ r, p: score(r) })).sort((a, b) => b.p - a.p);
    if (now[0]) picks.push({ key: `b:${now[0].r.id}`, label: `Today's #1: ${now[0].r.name}` });
    const s = [...S.meta.history_seasons].reverse().find((x) => S.hist[x]);
    if (s) {
      const top = evalRows(S.hist[s], S.mult).sorted[0];
      if (top) picks.push({ key: `h:${s}:${top.r.id}`, label: `${s} preseason #1: ${top.r.name}` });
    }
    return picks;
  }

  function findExample(key) {
    const [kind, a, b] = key.split(":");
    if (kind === "b") return { r: S.board.find((x) => x.id === a), season: S.meta.season, week: S.meta.week, live: true };
    return { r: (S.hist[+a] || []).find((x) => x.id === b), season: +a, week: 1, live: false };
  }

  function renderMethod() {
    const m = S.meta;
    for (const g of m.groups) for (const f of Object.keys(g.weights)) GROUP_OF[f] = g.key;
    const t = m.thresholds;
    const bar = POS.map((p) => `<span class="pill"><span class="pos ${p}">${p}</span>${t.startable[p]}+ PPR/g, up ${t.jump[p]}</span>`).join("");

    // learned weights as a diverging bar chart (per one-standard-deviation change)
    const all = m.groups.flatMap((g) => Object.entries(g.weights).map(([f, w]) => ({ f, w, g: g.key })));
    const maxW = Math.max(...all.map((x) => Math.abs(x.w)));
    const featLabel = { ...Object.fromEntries(Object.entries(FEAT).map(([k, v]) => [k, v[0]])),
      age_rel_sq: "Age (curve)", baseline_rel_sq: "Current level (curve)" };
    const weights = m.groups.map((g) => `<div class="wgroup"><h5><i class="dot" style="background:var(--g-${g.key})"></i>${esc(g.label)}</h5>
      ${Object.entries(g.weights).map(([f, w]) => {
        const pctW = (Math.abs(w) / maxW) * 50;
        return `<div class="grow"><span>${esc(featLabel[f] || f)}</span><span class="track">
          <span class="fill" style="left:${w >= 0 ? 50 : 50 - pctW}%;width:${pctW}%;background:var(--g-${g.key})"></span></span>
          <span class="num muted">${w > 0 ? "+" : ""}${w.toFixed(2)}</span></div>`;
      }).join("")}</div>`).join("");

    $("#method").innerHTML = `
      <div class="walk">
        <h3>Follow one player through the model</h3>
        <p>Every player starts from the odds for a typical player at his position. Each factor pushes those
          odds up or down, then his price sets how much that chance is worth.</p>
        <div class="toolbar">
          <select id="ex-player"></select>
          <div class="chips" id="ex-quick"></div>
        </div>
        <div id="walk"></div>
      </div>

      <h3>What the chance is a chance of</h3>
      <p>The model was trained to estimate how likely a player is, from the week a board is made through the
        end of that season, to average a startable PPR line <em>and</em> clear his established level by this margin:</p>
      <div class="pills">${bar}</div>
      <p>"Established level" blends his per-game this season with last season's (weighted like 4 games).
        A healthy season two years back also counts, so a star coming back from injury is a bounce-back,
        not a breakout. Anyone already producing at 1.25× the startable bar is established and left off the board.</p>

      <h3>Checking it against past seasons</h3>
      <p>Every preseason board on the History page was scored by a model trained only on <em>earlier</em>
        seasons, using the depth chart published that week. Nothing from the future leaks in. The History page
        shows each of those boards next to what every player actually scored that season, so you can judge the
        calls yourself.</p>

      <h3>What the model learned</h3>
      <p>A logistic regression trained on every season from ${m.train_seasons[0]} to ${m.train_seasons[1]}, snapshotted
        ${m.train_weeks.map((w) => (w === 1 ? "preseason" : `week ${w}`)).join(", ")}. Bars show how much a
        one-standard-deviation change in each feature moves the log-odds.</p>
      <div class="weights">${weights}</div>

      <h3>Value: why the board leans niche</h3>
      <p>Chance alone favors high-profile rookies and second-year players, whose jumps everyone already
        expects. The board ranks by <code>score = chance × value</code>, where value peaks for players around
        FantasyPros rank ${m.value.peak_rank} (cheap but on the radar) and fades for stars, who are priced in,
        and for players nobody ranks. On the ${m.history_seasons[0]}–${m.history_seasons.at(-1)} preseason boards, priced with
        that August's rankings, the History page shows what this does to each season's top 20. Turn <em>Value emphasis</em> to 0% to rank by chance alone.</p>

      <h3>What's not in the score</h3>
      <p>ESPN roster % (and its weekly change) and Sleeper waiver adds are on the board for context. Manual
        notes in <code>config/manual_catalysts.yaml</code> (a new coaching staff, camp buzz) apply to the live
        board only, as a red "notes" bar.</p>`;

    if (!S.histReady) { $("#walk").innerHTML = '<p class="muted">Loading examples…</p>'; }
    else setupWalk();
  }

  function setupWalk() {
    const sel = $("#ex-player");
    sel.innerHTML = exampleOptions().map((g) => `<optgroup label="${esc(g.group)}">${
      g.items.map((it) => `<option value="${esc(it.key)}">${esc(it.label)}</option>`).join("")}</optgroup>`).join("");
    const quick = quickPicks();
    $("#ex-quick").innerHTML = quick.map((q) => `<span class="chip" data-key="${esc(q.key)}">${esc(q.label)}</span>`).join("");
    const show = (key) => { sel.value = key; renderWalk(key); };
    sel.onchange = () => renderWalk(sel.value);
    $("#ex-quick").onclick = (e) => { const c = e.target.closest(".chip"); if (c) show(c.dataset.key); };
    show(S.walkKey && findExample(S.walkKey).r ? S.walkKey : quick[0]?.key || sel.value);
  }

  function renderWalk(key) {
    S.walkKey = key;
    document.querySelectorAll("#ex-quick .chip").forEach((c) => c.classList.toggle("on", c.dataset.key === key));
    const { r, season, week, live } = findExample(key);
    if (!r) { $("#walk").innerHTML = ""; return; }
    const labels = Object.fromEntries(S.meta.groups.map((g) => [g.key, g.label]));
    const fc = Object.fromEntries(S.meta.features.map((f, i) => [f, (r.fc || [])[i] || 0]));
    const when = week === 1 ? `before the ${season} season` : `going into week ${week} of ${season}`;

    // cumulative path through the groups
    const steps = [];
    let x = r.base;
    const start = sigmoid(x);
    for (const g of GROUPS) {
      const d = S.mult[g] * r[g];
      steps.push({ g, from: sigmoid(x), to: sigmoid(x + d), d });
      x += d;
    }
    if (live && r.notes) { steps.push({ g: "notes", from: sigmoid(x), to: sigmoid(x + r.notes), d: r.notes }); x += r.notes; }
    const final = sigmoid(x);
    const scale = Math.max(final, start, ...steps.map((s) => s.to), 0.05) * 1.08;
    const at = (p) => `${(p / scale) * 100}%`;

    const stepHtml = steps.map((s) => {
      const lo = Math.min(s.from, s.to), hi = Math.max(s.from, s.to);
      const feats = s.g === "notes" ? [] : S.meta.features.filter((f) => GROUP_OF[f] === s.g)
        .map((f) => ({ f, c: S.mult[s.g] * fc[f] })).sort((a, b) => Math.abs(b.c) - Math.abs(a.c));
      const big = feats.filter((z) => Math.abs(z.c) >= 0.03);
      const minor = feats.length - big.length;
      const fl = big.map(({ f, c }) => `<li><span>${esc(FEAT[f][0])}: <b>${esc(FEAT[f][1](r))}</b></span>
        <span class="num ${c >= 0 ? "pos-c" : "neg-c"}">${c >= 0 ? "+" : ""}${c.toFixed(2)}</span></li>`).join("");
      const label = s.g === "notes" ? "Your notes" : labels[s.g];
      const mult = s.g !== "notes" && S.mult[s.g] !== 1 ? ` <span class="muted">(${S.mult[s.g].toFixed(1)}× from your sliders)</span>` : "";
      return `<div class="step">
        <div class="step-head"><span><i class="dot" style="background:var(--g-${s.g})"></i><b>${esc(label)}</b>${mult}</span>
          <span class="num">${pct(s.from)} → <b>${pct(s.to)}</b></span></div>
        <div class="step-track"><span class="seg ${s.d >= 0 ? "up" : "down"}" style="left:${at(lo)};width:calc(${at(hi)} - ${at(lo)});background:var(--g-${s.g})"></span>
          <span class="tick" style="left:${at(s.to)}"></span></div>
        ${fl || minor ? `<ul class="feats">${fl}${minor ? `<li class="muted"><span>${minor} other factor${minor > 1 ? "s" : ""} with almost no effect</span></li>` : ""}</ul>` : ""}
      </div>`;
    }).join("");

    let result = "";
    if (!live) {
      const rank = evalRows(S.hist[season], S.mult).sorted.findIndex((z) => z.r.id === r.id) + 1;
      result = `<div class="result">Ranked #${rank} on the ${season} preseason board. He went from ${fmt(r.baseline)} to
        <b>${r.season_g ? fmt(r.season_ppg) : "—"} PPR/g</b>${r.season_g ? ` over ${r.season_g} games` : ""} that season${
        r.next_ppg != null ? `, then ${fmt(r.next_ppg)} the year after` : ""}.</div>`;
    }

    const vm = valueMult(r);
    const valueStep = `<div class="step value">
      <div class="step-head"><span><i class="dot" style="background:var(--accent)"></i><b>Value</b>
        <span class="muted">${r.ecr ? `ECR ${r.ecr}` : "unranked by FantasyPros"} vs. the sweet spot at ${S.val.peak}</span></span>
        <span class="num">${pct(final)} × ${vm.toFixed(2)} = <b>${(100 * final * vm).toFixed(1)}</b></span></div>
      <p class="hint">${vm > 0.85 ? "Priced right in the sweet spot: cheap, but on the radar." :
        (r.ecr ?? S.val.unranked) < S.val.peak ? "Already priced like a starter, so he costs a high pick." :
        "Mostly off the radar. Cheap, but rarely worth a roster spot."}</p>
    </div>`;

    $("#walk").innerHTML = `<div class="walk-card">
      ${playerCell(r)}
      <div class="walk-final"><span class="muted">Breakout score ${esc(when)}</span><b>${(100 * final * vm).toFixed(1)}</b>
        <span class="muted">${pct(final)} chance</span></div>
    </div>
    <div class="step start">
      <div class="step-head"><span><b>Starting odds</b> <span class="muted">a typical ${r.pos} ${week === 1 ? "in the preseason" : `at week ${week}`}</span></span>
        <span class="num"><b>${pct(start)}</b></span></div>
      <div class="step-track"><span class="seg" style="left:0;width:${at(start)};background:#3a475e"></span></div>
    </div>
    ${stepHtml}
    ${valueStep}
    ${result}`;
  }

  init().catch((err) => {
    console.error(err);
    $("#asof").textContent = "Couldn't load data.";
  });
})();
