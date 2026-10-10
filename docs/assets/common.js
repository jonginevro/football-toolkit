/* Shared shell for every page: brand + nav, data loading, small formatters.
 * Load it right after <header id="topbar" data-page="..."> so the nav renders
 * before the page paints. Exposes window.FT. */
window.FT = (() => {
  // One place to rename the site.
  const BRAND = "Football Toolkit";
  const SOURCE_URL = "https://github.com/jonginevro/breakout-board";

  const script = document.currentScript;
  const ROOT = new URL("../", script.src); // docs/

  const PAGES = [
    { key: "breakouts", href: "breakouts/", label: "Breakout Board",
      blurb: "Who's most likely to jump to a startable level over the rest of the season, weighted by how cheap they are." },
    { key: "vegas", href: "vegas/", label: "Vegas Rankings",
      blurb: "This week's lines turned into implied team totals, and every player's PPR scaled by how much Vegas likes his offense." },
    { key: "weather", href: "weather/", label: "Weather Report",
      blurb: "Game-time forecasts for every outdoor game and what wind, rain, snow or cold usually does to fantasy scoring." },
    { key: "trade", href: "trade/", label: "Trade Value Chart",
      blurb: "A week-by-week redraft trade value chart that updates after every game, with each player's trend." },
    { key: "upsets", href: "upsets/", label: "Upset Watch",
      blurb: "Three long shots a week with the most pointing their way: rest, travel, weather and injuries. Most will lose; that's the fun." },
    { key: "survivor", href: "survivor/", label: "Survivor Helper",
      blurb: "Mark the teams you've used and get this week's survivor pick, planned so you don't burn a team you'll need later." },
  ];

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? "—" : Number(v).toFixed(d));
  const signed = (v, d = 1) => {
    if (v == null || Number.isNaN(v)) return "—";
    const t = Math.abs(v).toFixed(d);
    return +t === 0 ? (0).toFixed(d) : `${v > 0 ? "+" : "−"}${t}`;
  };

  async function getJSON(path) {
    const res = await fetch(new URL(`data/${path}`, ROOT), { cache: "no-cache" });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return res.json();
  }

  /** {cols, rows} -> array of objects */
  const rows = (t) => t.rows.map((r) => Object.fromEntries(t.cols.map((c, i) => [c, r[i]])));

  const posTag = (pos) => `<span class="pos ${esc(pos)}">${esc(pos)}</span>`;

  function injTag(status) {
    if (!status) return "";
    const t = status === "Questionable" ? "Q" : status === "Doubtful" ? "D" : "O";
    return `<span class="inj ${t}" title="${esc(status)}">${t}</span>`;
  }

  function kickoff(iso, opts = {}) {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit", ...opts });
  }

  function updated(iso) {
    if (!iso) return "";
    return `Updated ${new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`;
  }

  function header() {
    const el = document.getElementById("topbar");
    if (!el) return;
    const active = el.dataset.page;
    const link = (p) => `<a href="${new URL(p.href, ROOT).pathname}" class="${p.key === active ? "active" : ""}">${esc(p.label)}</a>`;
    el.innerHTML = `
      <a class="brand" href="${ROOT.pathname}">${esc(BRAND)}</a>
      <nav aria-label="Tools">${PAGES.map(link).join("")}</nav>`;
    const page = PAGES.find((p) => p.key === active);
    document.title = page ? `${page.label} · ${BRAND}` : BRAND;
  }

  /** Every page's footer leads with the source code link. */
  function footer() {
    const p = document.querySelector("footer p");
    if (p) p.insertAdjacentHTML("afterbegin",
      `<a href="${SOURCE_URL}" target="_blank" rel="noopener">Source code on GitHub</a> · `);
  }

  header();
  document.addEventListener("DOMContentLoaded", footer);
  return { BRAND, ROOT, PAGES, esc, fmt, signed, getJSON, rows, posTag, injTag, kickoff, updated };
})();
