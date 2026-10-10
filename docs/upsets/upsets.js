/* Upset Watch: three long shots with the most signals pointing their way. */
(() => {
  "use strict";
  const { esc, fmt, signed, kickoff } = FT;
  const $ = (s) => document.querySelector(s);
  const pct = (p) => `${Math.round(p * 100)}%`;
  const ml = (v) => (v == null ? "—" : v > 0 ? `+${Math.round(v)}` : `${Math.round(v)}`);
  const money = (v) => `${v < 0 ? "−" : "+"}$${Math.abs(v).toLocaleString()}`;
  const tone = (v) => (Math.abs(v) < 0.05 ? "muted" : v > 0 ? "pos-c" : "neg-c");
  let D;

  const vs = (g) => `${g.dog === g.home ? "vs" : "@"} ${esc(g.fav)}`;

  function renderPicks() {
    const picks = D.picks.map((id) => D.games.find((g) => g.id === id));
    $("#picks").innerHTML = picks.map((g, i) => `<article class="pick">
        <div class="pick-top">
          <span class="pick-n">${i + 1}</span>
          <div class="pick-who"><b>${esc(g.dog)}</b> <span class="muted">${vs(g)}</span>
            <div class="muted pick-meta">${esc(kickoff(g.kickoff))}</div></div>
          <div class="pick-odds"><b>${ml(g.dog_ml)}</b><span>${pct(g.p_mkt)} per Vegas</span></div>
        </div>
        <ul class="reasons">${g.reasons.map((r) => `<li><span>${esc(r.text)}</span>
          <span class="num ${tone(r.pts)}">${signed(r.pts)}</span></li>`).join("")}</ul>
        <div class="pick-score"><span>Upset score</span><b class="${tone(g.score)}">${signed(g.score)}</b></div>
      </article>`).join("")
      || '<p class="muted">No long shot has more for it than against it this week.</p>';
  }

  function renderTrack() {
    const t = D.track.total;
    if (!t.picks) { $("#track").innerHTML = ""; return; }
    const ss = D.track.seasons;
    $("#track").innerHTML = `<div class="track-text">
        <span class="peek-l">Track record</span>
        Taking these picks every week from ${ss[0].season} to ${ss.at(-1).season} would have won <b>${t.wins} of ${t.picks}</b>
        (Vegas expected ${fmt(t.expected, 0)}). $100 on each: <b class="${tone(t.profit)}">${money(t.profit)}</b>.
      </div>
      <div class="track-seasons">${ss.map((s) => `<span title="${s.season}: ${s.wins} of ${s.picks} won, ${money(s.profit)}"
        class="${tone(s.profit)}"><i>${String(s.season).slice(2)}</i>${s.wins}/${s.picks}</span>`).join("")}</div>`;
  }

  function renderGames() {
    const row = (g) => {
      const top = g.reasons.find((r) => r.pts > 0) || g.reasons[0];
      const res = g.final ? ` <span class="lvl ${g.dog_won ? "calm" : "indoor"}">${g.dog_won ? "Won" : "Lost"} ${g.result.away}–${g.result.home}</span>` : "";
      return `<tr class="${g.final ? "is-final" : ""} ${D.picks.includes(g.id) ? "is-pick" : ""}">
        <td><b>${esc(g.dog)}</b> <span class="muted">${vs(g)}</span>${res}</td>
        <td class="num">${ml(g.dog_ml)}</td>
        <td class="num muted">${pct(g.p_mkt)}</td>
        <td class="num"><b class="${tone(g.score)}">${signed(g.score)}</b></td>
        <td class="hide-sm muted">${top ? esc(top.text) : "—"}</td></tr>`;
    };
    const shots = D.games.filter((g) => g.long_shot), close = D.games.filter((g) => !g.long_shot);
    $("#games tbody").innerHTML = shots.map(row).join("") +
      (close.length ? `<tr class="divider"><td colspan="5">Close games (not long shots)</td></tr>${close.map(row).join("")}` : "");
    $("#games-sub").textContent = `Long shots are underdogs Vegas gives a ${pct(D.long_shot[0])}–${pct(D.long_shot[1])} chance. ` +
      `Picks are the three with the highest upset score above zero.`;
  }

  function renderMethod() {
    const rows = Object.values(D.record).sort((a, b) => b.pts - a.pts);
    $("#record tbody").innerHTML = rows.map((r) => `<tr>
        <td>${esc(r.label)}</td><td class="num muted">${r.games.toLocaleString()}</td>
        <td class="num">${pct(r.actual)}</td><td class="num muted">${pct(r.expected)}</td>
        <td class="num"><span class="${tone(r.pts)}">${signed(r.pts)}</span></td></tr>`).join("");
    $("#method").innerHTML = `<p>Each spot's weight is how much more (or less) often underdogs in it have won than Vegas
        expected, across ${D.n_games.toLocaleString()} regular-season games since ${D.since}, shrunk toward zero when the
        sample is small. A team's upset score adds up every spot it's in. Injury news has no history to learn from, so it
        gets fixed weights: the favorite's starting QB out is +5, another key starter +1; the same for the underdog counts
        against it.</p>
      <p>The track record replays the picks for each past season using only the seasons before it, without injuries.</p>`;
    const e = D.eval;
    $("#eval-note").textContent = e.games
      ? `For context: a model combining every spot with the Vegas odds, tested season by season on ${e.seasons[0]}–${e.seasons[1]}, ` +
        `was ${e.model < e.vegas ? "slightly better" : "slightly worse"} than the odds alone (log loss ${e.model} vs ${e.vegas}). ` +
        `The market prices most of this already, which is why these are interesting long shots rather than sure things.`
      : "";
  }

  async function init() {
    D = await FT.getJSON("upsets.json");
    $("#asof").textContent = `${D.season} · week ${D.week}`;
    $("#generated").textContent = `${FT.updated(D.generated)}.`;
    renderPicks();
    renderTrack();
    renderGames();
    renderMethod();
  }

  init().catch((err) => { console.error(err); $("#asof").textContent = "Couldn't load this week's games."; });
})();
