/* Vegas page: game lines -> implied team totals -> Vegas-adjusted PPR. */
(() => {
  "use strict";
  const { esc, fmt, signed, posTag, injTag, kickoff } = FT;
  const $ = (s) => document.querySelector(s);
  const POS = ["QB", "RB", "WR", "TE"];
  const S = { data: null, players: [], pos: new Set(POS), q: "", sort: "vegas", topN: 50 };

  const favorite = (g) => (g.spread == null ? "No line"
    : g.spread === 0 ? "Pick'em"
    : g.spread > 0 ? `${g.home} −${fmt(g.spread)}` : `${g.away} −${fmt(-g.spread)}`);

  function renderGames() {
    const games = S.data.games;
    if (!games.length) { $("#games").innerHTML = '<p class="muted">No games on the schedule this week.</p>'; return; }
    const maxImp = Math.max(...games.flatMap((g) => [g.away_imp || 0, g.home_imp || 0]), 1);
    $("#games").innerHTML = games.map((g) => {
      const side = (team, imp, score) => `<div class="g-team">
          <span class="g-abbr">${esc(team)}</span>
          <span class="g-bar"><i style="width:${imp ? (imp / maxImp) * 100 : 0}%"></i></span>
          <span class="g-num">${g.final ? `<b>${score}</b>` : imp != null ? fmt(imp) : "—"}</span>
        </div>`;
      const meta = g.final ? "Final" : kickoff(g.kickoff);
      return `<div class="game ${g.final ? "is-final" : ""}">
        <div class="g-head"><span>${esc(meta)}</span><span>${esc(favorite(g))} · O/U ${fmt(g.total)}</span></div>
        ${side(g.away, g.away_imp, g.away_score)}
        ${side(g.home, g.home_imp, g.home_score)}
      </div>`;
    }).join("");
  }

  function renderPlayers() {
    const q = S.q.trim().toLowerCase();
    let list = S.players.filter((r) => S.pos.has(r.pos) && !r.final &&
      (!q || r.name.toLowerCase().includes(q) || r.team.toLowerCase() === q || r.opp.toLowerCase() === q));
    list.sort((a, b) => b[S.sort] - a[S.sort] || b.vegas - a.vegas);
    const maxV = Math.max(...S.players.map((r) => r.vegas), 1);
    $("#players tbody").innerHTML = list.slice(0, S.topN).map((r, i) => {
      const boost = (r.mult - 1) * 100;
      const img = r.headshot ? `<img loading="lazy" src="${esc(r.headshot)}" alt="" onerror="this.style.visibility='hidden'">` : "";
      return `<tr>
        <td class="num muted">${i + 1}</td>
        <td><div class="player">${img}<div><div class="nm">${esc(r.name)}${injTag(r.injury)}</div>
          <div class="sub">${posTag(r.pos)}${esc(r.team)}</div></div></div></td>
        <td class="muted">${r.home ? "vs" : "@"} ${esc(r.opp)}</td>
        <td class="num">${fmt(r.implied)}</td>
        <td class="num muted hide-sm">${fmt(r.usual)}</td>
        <td class="num"><span class="${Math.abs(boost) < 0.5 ? "muted" : boost > 0 ? "pos-c" : "neg-c"}">${signed(boost, 0)}%</span></td>
        <td class="num hide-sm">${fmt(r.ppg)}</td>
        <td><div class="scorebar"><span class="bar"><i style="width:${(r.vegas / maxV) * 100}%"></i></span><b>${fmt(r.vegas)}</b></div></td>
      </tr>`;
    }).join("") || '<tr><td colspan="8" class="muted">No players match.</td></tr>';
  }

  function controls() {
    const chips = $("#pos-chips");
    chips.innerHTML = POS.map((p) => `<span class="chip on" data-pos="${p}">${p}</span>`).join("");
    chips.addEventListener("click", (e) => {
      const c = e.target.closest(".chip"); if (!c) return;
      const p = c.dataset.pos;
      if (S.pos.has(p) && S.pos.size > 1) S.pos.delete(p); else S.pos.add(p);
      chips.querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", S.pos.has(x.dataset.pos)));
      renderPlayers();
    });
    $("#sort").addEventListener("change", (e) => { S.sort = e.target.value; renderPlayers(); });
    $("#search").addEventListener("input", (e) => { S.q = e.target.value; renderPlayers(); });
    $("#topn").addEventListener("change", (e) => { S.topN = +e.target.value; renderPlayers(); });
  }

  async function init() {
    S.data = await FT.getJSON("vegas.json");
    S.players = FT.rows(S.data);
    $("#asof").textContent = `${S.data.season} · week ${S.data.week} lines`;
    $("#generated").textContent = `${FT.updated(S.data.generated)}.`;
    $("#vegas-note").textContent = `Team total comes from the spread and over/under. Usual is his team's average points this season, ` +
      `blended with the league average (${fmt(S.data.league_avg)}) so one blowout doesn't swing it. Vegas PPR = PPR/g × team total ÷ usual. ` +
      `Players listed Out or on IR are left off; games already played drop out of the list.`;
    controls();
    renderGames();
    renderPlayers();
  }

  init().catch((err) => { console.error(err); $("#asof").textContent = "Couldn't load this week's lines."; });
})();
