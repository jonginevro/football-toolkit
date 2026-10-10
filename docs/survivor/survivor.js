/* Survivor Helper. Plans the next few weeks at once: each team can be used
 * once, and the plan maximizes the chance of winning every week (the product
 * of the win chances). That's an assignment problem, solved exactly with the
 * Hungarian algorithm on -log(win chance). Every option this week is scored by
 * forcing it into week 1 and re-planning the rest. */
(() => {
  "use strict";
  const { esc } = FT;
  const $ = (s) => document.querySelector(s);
  const STORE = "survivor-v1";
  const pct = (p) => `${Math.round(p * 100)}%`;
  const SKIPS = [["div", "Division games"], ["thursday", "Thursday games"], ["road", "Road teams"], ["intl", "International games"]];
  const S = { data: null, used: new Set(), skip: new Set(), horizon: 5 };

  function load() {
    try {
      const s = JSON.parse(localStorage.getItem(STORE) || "null");
      if (s && s.season === S.data.season) {
        S.used = new Set(s.used || []);
        S.skip = new Set(s.skip || []);
        if (s.horizon) S.horizon = s.horizon;
      }
    } catch (_) { /* storage unavailable */ }
  }
  function save() {
    try {
      localStorage.setItem(STORE, JSON.stringify({ season: S.data.season, used: [...S.used], skip: [...S.skip], horizon: S.horizon }));
    } catch (_) { /* storage unavailable */ }
  }

  /** week -> team -> {p, opp, home, flags} for games still to be played */
  function options() {
    return S.data.weeks.map((w) => {
      const m = new Map();
      for (const g of w.games) {
        if (g.final) continue;
        for (const home of [true, false]) {
          const team = home ? g.home : g.away;
          m.set(team, { team, opp: home ? g.away : g.home, home, p: home ? g.p_home : 1 - g.p_home,
            div: g.div, thursday: g.thursday, intl: g.intl, source: g.source, kickoff: g.kickoff });
        }
      }
      return { week: w.week, teams: m };
    });
  }

  const allowed = (o) => o && !S.used.has(o.team) &&
    !(S.skip.has("div") && o.div) && !(S.skip.has("thursday") && o.thursday) &&
    !(S.skip.has("road") && !o.home) && !(S.skip.has("intl") && o.intl);

  /** Hungarian algorithm (min cost, square matrix). Returns col assigned to each row. */
  function hungarian(cost) {
    const n = cost.length, INF = 1e18;
    const u = new Array(n + 1).fill(0), v = new Array(n + 1).fill(0);
    const p = new Array(n + 1).fill(0), way = new Array(n + 1).fill(0);
    for (let i = 1; i <= n; i++) {
      p[0] = i;
      let j0 = 0;
      const minv = new Array(n + 1).fill(INF), used = new Array(n + 1).fill(false);
      do {
        used[j0] = true;
        const i0 = p[j0];
        let delta = INF, j1 = 0;
        for (let j = 1; j <= n; j++) {
          if (used[j]) continue;
          const cur = cost[i0 - 1][j - 1] - u[i0] - v[j];
          if (cur < minv[j]) { minv[j] = cur; way[j] = j0; }
          if (minv[j] < delta) { delta = minv[j]; j1 = j; }
        }
        for (let j = 0; j <= n; j++) {
          if (used[j]) { u[p[j]] += delta; v[j] -= delta; } else minv[j] -= delta;
        }
        j0 = j1;
      } while (p[j0] !== 0);
      do { const j1 = way[j0]; p[j0] = p[j1]; j0 = j1; } while (j0);
    }
    const ans = new Array(n).fill(-1);
    for (let j = 1; j <= n; j++) if (p[j] > 0) ans[p[j] - 1] = j - 1;
    return ans;
  }

  const BLOCKED = 1e6;

  /** Best plan over `weeks`, optionally forcing a team in the first week. */
  function plan(weeks, teams, force) {
    const n = teams.length;
    const cost = Array.from({ length: n }, (_, i) => teams.map((t) => {
      if (i >= weeks.length) return 0; // padding rows
      const o = weeks[i].teams.get(t);
      if (i === 0 && force && t !== force) return BLOCKED;
      return allowed(o) ? -Math.log(Math.max(o.p, 1e-4)) : BLOCKED;
    }));
    const a = hungarian(cost);
    const picks = weeks.map((w, i) => {
      const o = w.teams.get(teams[a[i]]);
      return cost[i][a[i]] >= BLOCKED ? { week: w.week, team: null, p: 0 } : { week: w.week, ...o };
    });
    return { picks, survival: picks.reduce((s, x) => s * x.p, 1) };
  }

  function render() {
    const opts = options().filter((w) => w.teams.size);
    if (!opts.length) { $("#rec").innerHTML = '<p class="muted">The season is over.</p>'; return; }
    const weeks = opts.slice(0, S.horizon);
    const teams = S.data.teams;
    const now = weeks[0];
    const cands = [...now.teams.values()].filter(allowed).map((o) => {
      const pl = plan(weeks, teams, o.team);
      const later = opts.slice(1).map((w) => ({ week: w.week, o: w.teams.get(o.team) })).filter((x) => x.o)
        .sort((a, b) => b.o.p - a.o.p)[0];
      return { ...o, plan: pl, later };
    }).sort((a, b) => b.plan.survival - a.plan.survival || b.p - a.p);

    renderRec(cands, now);
    renderTable(cands);
  }

  const tags = (o) => [o.home ? null : "road", o.div ? "division" : null, o.thursday ? "Thursday" : null,
    o.intl ? "international" : null].filter(Boolean).map((t) => `<span class="tag">${t}</span>`).join("");

  function renderRec(cands, now) {
    const best = cands[0];
    if (!best) {
      $("#rec").innerHTML = `<div class="sv-card"><p class="muted">No team fits your rules this week. Loosen a skip rule or un-mark a team.</p></div>`;
      return;
    }
    const safest = [...cands].sort((a, b) => b.p - a.p)[0];
    let saving = "";
    if (safest.team !== best.team) {
      const n = best.plan.picks.length;
      const later = best.plan.picks.find((x) => x.team === safest.team);
      saving = `<p class="sv-why">${esc(safest.team)} is the bigger favorite this week (${pct(safest.p)}), but taking it now
        drops your ${n}-week survival from ${pct(best.plan.survival)} to ${pct(safest.plan.survival)}${later
          ? `, because the plan needs ${esc(safest.team)} in week ${later.week}` : ""}.</p>`;
    }
    const path = best.plan.picks.map((x) => `<span class="sv-step ${x.team ? "" : "none"}"><i>Wk ${x.week}</i>
        <b>${x.team ? esc(x.team) : "—"}</b><span>${x.team ? pct(x.p) : "no pick"}</span></span>`).join("");
    $("#rec").innerHTML = `<div class="sv-card">
        <div class="sv-main">
          <div><span class="peek-l">Pick this week</span>
            <div class="sv-team">${esc(best.team)} <span class="muted">${best.home ? "vs" : "@"} ${esc(best.opp)}</span></div>
            <div class="muted sv-meta">${esc(FT.kickoff(best.kickoff))} · ${tags(best) || "home"}</div></div>
          <div class="sv-p"><b>${pct(best.p)}</b><span>to win this week</span></div>
          <div class="sv-p"><b>${pct(best.plan.survival)}</b><span>to survive ${best.plan.picks.length > 1 ? `all ${best.plan.picks.length} weeks` : "the week"}</span></div>
        </div>
        ${saving}
        ${best.plan.picks.length > 1 ? `<div class="sv-path"><span class="peek-l">The plan</span><div>${path}</div></div>` : ""}
      </div>`;
  }

  function renderTable(cands) {
    const top = cands[0]?.plan.survival || 1;
    $("#options tbody").innerHTML = cands.map((c, i) => `<tr class="${i === 0 ? "is-pick" : ""}">
        <td><b>${esc(c.team)}</b> <span class="muted">${c.home ? "vs" : "@"} ${esc(c.opp)}</span></td>
        <td class="num">${pct(c.p)}</td>
        <td><div class="scorebar"><span class="bar"><i style="width:${(c.plan.survival / top) * 100}%"></i></span><b>${pct(c.plan.survival)}</b></div></td>
        <td class="num hide-sm muted">${c.later ? `${pct(c.later.o.p)} in wk ${c.later.week}` : "—"}</td>
        <td class="hide-sm">${tags(c)}</td></tr>`).join("")
      || '<tr><td colspan="5" class="muted">No team fits your rules this week.</td></tr>';
  }

  function controls() {
    const grid = $("#team-grid");
    const paint = () => {
      grid.querySelectorAll(".team").forEach((b) => b.classList.toggle("used", S.used.has(b.dataset.team)));
      $("#clear-used").hidden = !S.used.size;
    };
    grid.innerHTML = S.data.teams.map((t) => `<button class="team" data-team="${t}" type="button">${t}</button>`).join("");
    grid.addEventListener("click", (e) => {
      const b = e.target.closest(".team"); if (!b) return;
      const t = b.dataset.team;
      if (S.used.has(t)) S.used.delete(t); else S.used.add(t);
      paint(); save(); render();
    });
    $("#clear-used").addEventListener("click", () => { S.used.clear(); paint(); save(); render(); });

    const sk = $("#skip-chips");
    sk.innerHTML = SKIPS.map(([k, label]) => `<span class="chip" data-k="${k}">${label}</span>`).join("");
    const paintSk = () => sk.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", S.skip.has(c.dataset.k)));
    sk.addEventListener("click", (e) => {
      const c = e.target.closest(".chip"); if (!c) return;
      if (S.skip.has(c.dataset.k)) S.skip.delete(c.dataset.k); else S.skip.add(c.dataset.k);
      paintSk(); save(); render();
    });
    const hz = $("#horizon");
    hz.value = [...hz.options].some((o) => +o.value === S.horizon) ? S.horizon : 5;
    hz.addEventListener("change", () => { S.horizon = +hz.value; save(); render(); });
    paint(); paintSk();
  }

  function method() {
    const d = S.data;
    $("#method").innerHTML = `
      <p>Survivor rules: pick one team to win each week, never the same team twice, and one loss knocks you out. The best pick
        isn't always this week's biggest favorite. Spending a great team in a week with other safe options can leave you
        short later.</p>
      <p>Win chances come from the Vegas moneylines (bookmaker's cut removed) wherever lines are posted, usually this week
        and next. Later weeks use power ratings fitted to every spread posted this season, with a ${d.home_edge}-point home edge.
        The plan picks one team per week for the weeks you choose so that the chance of winning every one of them is as
        high as possible, with no team used twice and your skip rules applied. Each option in the table is scored by locking
        it in this week and re-planning the rest.</p>
      <p>Your used teams and settings are saved in this browser only.</p>`;
  }

  async function init() {
    S.data = await FT.getJSON("survivor.json");
    $("#asof").textContent = `${S.data.season} · week ${S.data.week}`;
    $("#generated").textContent = `${FT.updated(S.data.generated)}.`;
    load();
    controls();
    method();
    render();
  }

  init().catch((err) => { console.error(err); $("#asof").textContent = "Couldn't load the schedule."; });
})();
