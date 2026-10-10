/* Home: a card per tool with a live peek at its current data. */
(() => {
  "use strict";
  const { esc, fmt, signed, posTag, PAGES, ROOT } = FT;
  const $ = (s) => document.querySelector(s);
  const sigmoid = (x) => 1 / (1 + Math.exp(-x));

  const list = (items) => `<ul class="peek">${items.join("")}</ul>`;
  const li = (left, right) => `<li><span>${left}</span><span class="r">${right}</span></li>`;

  // Same default scoring the Breakout Board uses (no slider changes, up to year 7).
  async function breakouts() {
    const [meta, board] = await Promise.all([FT.getJSON("meta.json"), FT.getJSON("board.json")]);
    const v = meta.value;
    const score = (r) => {
      const p = sigmoid(r.base + (r.notes || 0) + r.talent + r.role + r.profile + r.ceiling);
      const z = (Math.log10(Math.max(r.ecr ?? v.unranked, 1)) - Math.log10(v.peak_rank)) / v.sigma;
      return 100 * p * (v.floor + (1 - v.floor) * Math.exp(-0.5 * z * z));
    };
    const top = FT.rows(board).filter((r) => r.exp <= 6).map((r) => ({ r, s: score(r) }))
      .sort((a, b) => b.s - a.s).slice(0, 3);
    return list(top.map(({ r, s }) => li(`${posTag(r.pos)}${esc(r.name)}`, fmt(s))));
  }

  async function vegas() {
    const d = await FT.getJSON("vegas.json");
    const top = FT.rows(d).filter((r) => !r.final).slice(0, 3);
    return list(top.map((r) => li(`${posTag(r.pos)}${esc(r.name)}`, `${fmt(r.vegas)} PPR`)));
  }

  async function weather() {
    const d = await FT.getJSON("weather.json");
    // games arrive worst-first; games with a forecast come before domes and finished games
    const top = [...d.games.filter((g) => g.conditions), ...d.games.filter((g) => !g.conditions)].slice(0, 3);
    const label = (g) => (g.level != null ? d.levels[g.level] : g.final ? "Final" : "No forecast yet");
    return list(top.map((g) => li(`${esc(g.away)} @ ${esc(g.home)}`, esc(label(g)))));
  }

  async function trade() {
    const d = await FT.getJSON("trade.json");
    const w = d.weeks.find((x) => x.week === d.current);
    const all = FT.rows({ cols: d.cols, rows: w.rows });
    const risers = all.filter((r) => r.trend > 0).sort((a, b) => b.trend - a.trend);
    // fill out to three lines with the top values (week 1 has no trend yet)
    const rows = [...risers, ...all.filter((r) => !(r.trend > 0))].slice(0, 3);
    return list(rows.map((r) => li(`${posTag(r.pos)}${esc(r.name)}`,
      r.trend > 0 ? `<span class="pos-c">${signed(r.trend)}</span> → ${fmt(r.value)}` : fmt(r.value))));
  }

  async function upsets() {
    const d = await FT.getJSON("upsets.json");
    const ml = (v) => (v > 0 ? `+${Math.round(v)}` : `${Math.round(v)}`);
    // the picks first, then the next-best long shots so there are always three lines
    const ids = [...d.picks, ...d.games.filter((g) => g.long_shot && !g.final && !d.picks.includes(g.id)).map((g) => g.id)];
    const rows = ids.slice(0, 3).map((id) => d.games.find((g) => g.id === id));
    return list(rows.map((g) => li(`${esc(g.dog)} <span class="muted">${g.dog === g.home ? "vs" : "@"} ${esc(g.fav)}</span>`,
      ml(g.dog_ml))));
  }

  async function survivor() {
    const d = await FT.getJSON("survivor.json");
    const w = d.weeks.find((x) => x.games.some((g) => !g.final));
    if (!w) return '<p class="peek-empty">The season is over.</p>';
    const sides = w.games.filter((g) => !g.final).flatMap((g) => [
      { team: g.home, opp: g.away, at: "vs", p: g.p_home }, { team: g.away, opp: g.home, at: "@", p: 1 - g.p_home }]);
    return list(sides.sort((a, b) => b.p - a.p).slice(0, 3).map((s) =>
      li(`${esc(s.team)} <span class="muted">${s.at} ${esc(s.opp)}</span>`, `${Math.round(s.p * 100)}% to win`)));
  }

  const PEEK = { breakouts: ["Top of the board", breakouts], vegas: ["Vegas likes most", vegas],
                 weather: ["Worst conditions", weather], trade: ["Rising this week", trade],
                 upsets: ["This week's long shots", upsets],
                 survivor: ["Safest picks this week", survivor] };

  $("#tools").innerHTML = PAGES.map((p) => `<a class="tool-card" href="${new URL(p.href, ROOT).pathname}">
      <h3>${esc(p.label)}</h3><p>${esc(p.blurb)}</p>
      <div class="peek-wrap"><span class="peek-l">${esc(PEEK[p.key][0])}</span><div id="peek-${p.key}" class="muted">Loading…</div></div>
      <span class="go">Open ${esc(p.label)} →</span></a>`).join("");

  for (const p of PAGES) {
    PEEK[p.key][1]().then((html) => { $(`#peek-${p.key}`).outerHTML = html; })
      .catch(() => { $(`#peek-${p.key}`).textContent = "Not available right now."; });
  }
})();
