/* Trade value chart: one row per value, a name + trend slot per position,
 * shaded by tier. Every week of the season is in trade.json; trend is the
 * change from the week before. */
(() => {
  "use strict";
  const { esc, fmt, signed, injTag, posTag } = FT;
  const $ = (s) => document.querySelector(s);
  const COLS = ["RB", "WR", "TE", "QB"];
  const S = { data: null, week: null, q: "" };

  const weekRows = (wk) => FT.rows({ cols: S.data.cols, rows: S.data.weeks.find((w) => w.week === wk).rows });

  function trendCell(t) {
    if (t == null) return '<td class="num tr new" title="Not on last week\'s chart">new</td>';
    if (Math.abs(t) < 0.25) return '<td class="num tr muted">0.0</td>';
    const a = Math.min(Math.abs(t) / 10, 1) * 0.55 + 0.12;
    const rgb = t > 0 ? "63,207,142" : "247,86,59";
    return `<td class="num tr" style="background:rgba(${rgb},${a.toFixed(2)})">${signed(t)}</td>`;
  }

  function renderChart() {
    const list = weekRows(S.week);
    const q = S.q.trim().toLowerCase();
    const hit = (r) => q && (r.name.toLowerCase().includes(q) || r.team.toLowerCase() === q);

    // group by value, then stack same-value players at a position onto extra rows
    const byVal = new Map();
    for (const r of list) {
      if (!byVal.has(r.value)) byVal.set(r.value, Object.fromEntries(COLS.map((p) => [p, []])));
      byVal.get(r.value)[r.pos].push(r);
    }
    const html = [];
    for (const [v, slots] of [...byVal.entries()].sort((a, b) => b[0] - a[0])) {
      const n = Math.max(...COLS.map((p) => slots[p].length));
      const tier = slots[COLS.find((p) => slots[p].length)][0].tier;
      for (let i = 0; i < n; i++) {
        const cells = COLS.map((p) => {
          const r = slots[p][i];
          if (!r) return '<td class="nm-c"></td><td class="tr"></td>';
          const title = `${r.name} · ${r.team} · ${fmt(r.ppg)} PPR/g over ${r.games} g${r.ecr ? ` · ECR ${r.ecr}` : ""}`;
          return `<td class="nm-c ${hit(r) ? "hl" : ""}" title="${esc(title)}">${esc(r.name)}${injTag(r.injury)}</td>${trendCell(r.trend)}`;
        }).join("");
        html.push(`<tr class="t${tier}"><td class="num val">${v.toFixed(1)}</td>${cells}</tr>`);
      }
    }
    $("#trade tbody").innerHTML = html.join("");
    if (q) document.querySelector("#trade .hl")?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function renderMovers() {
    const list = weekRows(S.week).filter((r) => r.trend != null);
    const item = (r) => `<li><span>${posTag(r.pos)}${esc(r.name)} <span class="muted">${esc(r.team)}</span></span>
      <span class="r"><span class="${r.trend > 0 ? "pos-c" : "neg-c"}">${signed(r.trend)}</span> → ${fmt(r.value)}</span></li>`;
    const up = [...list].sort((a, b) => b.trend - a.trend).filter((r) => r.trend > 0).slice(0, 10);
    const down = [...list].sort((a, b) => a.trend - b.trend).filter((r) => r.trend < 0).slice(0, 10);
    const none = S.week === 1 ? "Week 1 is the starting point." : "No changes.";
    $("#risers").innerHTML = up.map(item).join("") || `<li class="muted">${none}</li>`;
    $("#fallers").innerHTML = down.map(item).join("") || `<li class="muted">${none}</li>`;
  }

  function renderWeek() {
    document.querySelectorAll("#week-chips .chip").forEach((c) => c.classList.toggle("on", +c.dataset.week === S.week));
    const w = S.data.weeks.find((x) => x.week === S.week);
    const live = S.week === S.data.current;
    $("#asof").textContent = `${S.data.season} · week ${S.week}${live ? " · updates after every game" : ""}`;
    $("#generated").textContent = live ? `${FT.updated(S.data.generated)}.` : `Rankings from ${w.ecr_date}.`;
    renderChart();
    renderMovers();
  }

  function legend() {
    const t = S.data.tiers;
    $("#tier-legend").innerHTML = t.map((lo, i) => {
      const hi = i === 0 ? null : t[i - 1];
      return `<span class="tchip t${i + 1}" title="${hi ? `${lo}–${hi}` : `${lo}+`}">${i + 1}</span>`;
    }).join("");
  }

  function method() {
    const s = S.data.settings;
    $("#trade-method").innerHTML = `
      <p>Every player gets two ranks each week. The <b>market</b> rank is his spot in FantasyPros' overall expert
        consensus from the snapshot published before that week (rest-of-season rankings once games start), so
        quarterbacks land where a 1QB league prices them. The <b>production</b> rank orders players by points per
        game above a replacement-level starter at their position (QB12, RB30, WR36, TE12), using this season's games
        blended with last season's.</p>
      <p>Each rank goes through the same curve, <code>${s.top} × e<sup>−(rank − 1) / ${s.decay}</sup></code>, and the value
        is ${Math.round(s.market_weight * 100)}% market and ${Math.round((1 - s.market_weight) * 100)}% production, rounded
        to the nearest half point. Trend is the change from the previous week's chart. Past weeks are rebuilt
        from what was known at the time, and the current week also counts games already played, so values move
        after every game.</p>
      <p>Hover a name for his PPR/g, games and expert rank.</p>`;
  }

  async function init() {
    S.data = await FT.getJSON("trade.json");
    S.week = S.data.current;
    $("#week-chips").innerHTML = S.data.weeks.map((w) => `<span class="chip" data-week="${w.week}">${w.week}</span>`).join("");
    $("#week-chips").addEventListener("click", (e) => {
      const c = e.target.closest(".chip"); if (c) { S.week = +c.dataset.week; renderWeek(); }
    });
    let t;
    $("#search").addEventListener("input", (e) => { S.q = e.target.value; clearTimeout(t); t = setTimeout(renderChart, 150); });
    legend();
    method();
    renderWeek();
  }

  init().catch((err) => { console.error(err); $("#asof").textContent = "Couldn't load trade values."; });
})();
