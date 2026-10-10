/* Weather page: one card per outdoor game, worst conditions first. */
(() => {
  "use strict";
  const { esc, kickoff } = FT;
  const $ = (s) => document.querySelector(s);
  const LEVEL_CLASS = ["indoor", "calm", "minor", "watch", "major"];

  function card(g, levels) {
    const c = g.conditions;
    const lvl = g.level;
    const badge = lvl == null ? "" : `<span class="lvl ${LEVEL_CLASS[lvl]}">${esc(levels[lvl])}</span>`;
    const stats = c ? `<div class="wx-stats">
        <div><b>${c.temp}°</b><span>temp</span></div>
        <div><b>${c.wind}</b><span>wind mph</span></div>
        <div><b>${c.gust}</b><span>gust mph</span></div>
        <div><b>${c.precip_prob ?? "—"}${c.precip_prob != null ? "%" : ""}</b><span>${c.snow > 0 ? `${c.snow}" snow` : "rain"}</span></div>
      </div>` : "";
    const imp = g.impacts.map((i) => `<li class="l${i.level}"><span>${esc(i.text)}</span>
        ${i.who.length ? `<span class="who">${i.who.map((p) => `<i>${esc(p)}</i>`).join("")}</span>` : ""}</li>`).join("");
    const calm = c && !g.impacts.length ? '<p class="muted wx-ok">Nothing here should change how you set your lineup.</p>' : "";
    return `<article class="wx-card ${LEVEL_CLASS[lvl] || ""}">
      <header><div><b>${esc(g.away)} @ ${esc(g.home)}</b>
        <span class="muted">${esc(kickoff(g.kickoff))} · ${esc(g.stadium)}</span></div>${badge}</header>
      ${stats}
      ${imp ? `<ul class="wx-imp">${imp}</ul>` : calm}
      ${g.note && c ? `<p class="wx-note">${esc(g.note)}</p>` : ""}
    </article>`;
  }

  async function init() {
    const d = await FT.getJSON("weather.json");
    $("#asof").textContent = `${d.season} · week ${d.week}`;
    $("#generated").textContent = `${FT.updated(d.generated)}.`;

    const withFc = d.games.filter((g) => g.conditions);
    const rest = d.games.filter((g) => !g.conditions);
    const count = (l) => withFc.filter((g) => g.level === l).length;
    const indoor = rest.filter((g) => g.level === 0).length;
    const pills = [[4, "major"], [3, "watch"], [2, "minor"], [1, "calm"]]
      .filter(([l]) => count(l)).map(([l, cls]) => `<span class="lvl ${cls}">${count(l)} ${esc(d.levels[l]).toLowerCase()}</span>`);
    if (indoor) pills.push(`<span class="lvl indoor">${indoor} indoors</span>`);
    $("#wx-summary").innerHTML = pills.join("");

    $("#wx-games").innerHTML = withFc.map((g) => card(g, d.levels)).join("")
      || '<p class="muted">No outdoor forecasts yet for this week.</p>';

    const groups = {};
    for (const g of rest) (groups[g.note || "Other"] ||= []).push(g);
    $("#wx-quiet").innerHTML = Object.entries(groups).map(([note, gs]) => `<div class="wx-row">
        <span class="muted">${esc(note)}</span>
        <span>${gs.map((g) => `<span class="pill">${esc(g.away)} @ ${esc(g.home)}</span>`).join("")}</span></div>`).join("");
  }

  init().catch((err) => { console.error(err); $("#asof").textContent = "Couldn't load the forecast."; });
})();
