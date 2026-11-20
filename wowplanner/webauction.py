"""Page « Hôtel des ventes » du site : prix des objets en vente, recherche, types, favoris, cours de chaque objet.

Les prix viennent de la base locale (relevés par cogs/auctions.py) : la page marche même si l'API de Blizzard ne
répond plus, avec les derniers prix connus. Au survol d'un prix, une petite courbe des 7 derniers jours ; un clic
ouvre la fiche de l'objet, avec sa courbe sur la période choisie et le tableau des relevés.
"""
from __future__ import annotations

import hmac
import json
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from aiohttp import web

from .armory import icon_url
from .auctions import money_parts, money_text
from .recipes import normalize
from .webui import QUALITY_COLORS, esc
from .webmember import MemberPages

PAGE_SIZE = 50
PERIODS = {"24h": (1, "24 heures"), "3j": (3, "3 jours"), "7j": (7, "7 jours"), "30j": (30, "30 jours"),
           "90j": (90, "90 jours")}
DEFAULT_PERIOD = "7j"
SORTS = {"nom": "Nom", "prix": "Prix croissant", "-prix": "Prix décroissant", "quantite": "Plus disponibles",
         "annonces": "Plus d'annonces"}


def number(value: int) -> str:
    """12345 → « 12 345 » (espace fine insécable, comme en français)."""
    return f"{value:,}".replace(",", " ")


def money_html(copper: int | None) -> str:
    """Prix en po / pa / pc, chaque pièce dans sa couleur (le texte reste lisible sans les couleurs)."""
    if copper is None:
        return '<span class="muted">—</span>'
    gold, silver, cop = money_parts(copper)
    parts = []
    if gold:
        parts.append(f'<span class="mg">{number(gold)}</span>')
    if silver:
        parts.append(f'<span class="ms">{silver}</span>')
    if cop or not parts:
        parts.append(f'<span class="mc">{cop}</span>')
    return f'<span class="money" title="{esc(money_text(copper))}">{"".join(parts)}</span>'


COIN_HEADS = '<th class="coin mg">po</th><th class="coin ms">pa</th><th class="coin mc">pc</th>'


def money_cells(copper: int | None, item_id: int | None = None) -> str:
    """Prix en trois colonnes alignées (po, pa, pc) ; les zéros de tête restent vides. Avec `item_id`, chaque
    chiffre est un lien vers la fiche de l'objet (courbe des 7 jours au survol)."""
    if copper is None:
        return '<td class="coin muted">—</td><td class="coin"></td><td class="coin"></td>'
    gold, silver, cop = money_parts(copper)
    shown = [gold > 0, gold > 0 or silver > 0, True]
    cells = []
    for value, show, cls in zip((gold, silver, cop), shown, ("mg", "ms", "mc")):
        text = (number(value) if value else '<span class="zero">0</span>') if show else ""
        if text and item_id is not None:
            text = f'<a class="price" href="/hdv/objet/{item_id}" data-item="{item_id}">{text}</a>'
        cells.append(f'<td class="coin {cls}">{text}</td>')
    return "".join(cells)


def change_html(now: int, before: int | None) -> str:
    """Variation du prix le plus bas sur 24 h (hausse en rouge pour l'acheteur, baisse en vert), avec flèche."""
    if not before:
        return '<span class="muted">—</span>'
    pct = (now - before) / before * 100
    if abs(pct) < 0.5:
        return '<span class="muted">= 0 %</span>'
    arrow, cls = ("▲", "up") if pct > 0 else ("▼", "down")
    return f'<span class="chg {cls}">{arrow} {abs(pct):.0f} %</span>'


def item_icon(row: Any) -> str:
    url = row["icon"] if row is not None else None
    if url and str(url).startswith("https://"):
        return f'<img class="ah-icon" src="{esc(icon_url(url))}" alt="" loading="lazy" referrerpolicy="no-referrer">'
    return '<span class="ah-icon none"></span>'


def item_name(row: Any) -> str:
    name = row["name"] or f"Objet n° {row['item_id']}"
    color = QUALITY_COLORS.get(row["quality"] or "", "inherit")
    return f'<span style="color:{color}">{esc(name)}</span>'


def _nice_step(span: float) -> float:
    """Pas « rond » pour ~4 graduations (1, 2, 5 × 10^n)."""
    raw = max(span / 4, 1)
    power = 10 ** (len(str(int(raw))) - 1)
    for mult in (1, 2, 5, 10):
        if raw <= mult * power:
            return mult * power
    return 10 * power


def price_chart_svg(points: list[tuple[int, int, int, int, int]], days: int, tz: Any) -> str:
    """Courbe du prix le plus bas (trait plein) et du prix médian (pointillé) : SVG sans bibliothèque, graduations
    rondes, dates en bas ; la couche de survol (curseur + infobulle) est ajoutée par CHART_SCRIPT."""
    width, height, left, right, top, bottom = 820, 300, 78, 16, 16, 34
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [p[1] for p in points] + [p[2] for p in points]
    low, high = min(values), max(values)
    step = _nice_step(high - low or high or 1)
    y0 = max(int(low // step * step), 0)
    y1 = int(-(-high // step) * step) or step
    if y1 <= y0:
        y1 = y0 + step
    t0, t1 = points[0][0], points[-1][0]
    if t1 <= t0:
        t1 = t0 + 3600
    x = lambda t: left + (t - t0) / (t1 - t0) * plot_w  # noqa: E731
    y = lambda v: top + (1 - (v - y0) / (y1 - y0)) * plot_h  # noqa: E731

    grid = []
    tick = y0
    while tick <= y1 + 1e-9:
        gy = y(tick)
        grid.append(
            f'<line class="grid" x1="{left}" x2="{width - right}" y1="{gy:.1f}" y2="{gy:.1f}"/>'
            f'<text class="axis" x="{left - 8}" y="{gy + 4:.1f}" text-anchor="end">{esc(money_text(int(tick)))}</text>'
        )
        tick += step
    labels = []
    count = 6
    for i in range(count):
        t = t0 + (t1 - t0) * i / (count - 1)
        when = datetime.fromtimestamp(t, tz)
        text = when.strftime("%H:%M" if days <= 1 else "%d/%m %Hh" if days <= 3 else "%d/%m")
        anchor = "start" if i == 0 else "end" if i == count - 1 else "middle"
        labels.append(f'<text class="axis" x="{x(t):.1f}" y="{height - 10}" text-anchor="{anchor}">{text}</text>')

    def path(index: int) -> str:
        return "M" + " L".join(f"{x(p[0]):.1f},{y(p[index]):.1f}" for p in points)

    single = len(points) == 1
    dots = (
        f'<circle class="s1" cx="{x(t0):.1f}" cy="{y(points[0][1]):.1f}" r="4"/>'
        f'<circle class="s2" cx="{x(t0):.1f}" cy="{y(points[0][2]):.1f}" r="4"/>'
        if single else ""
    )
    data = json.dumps({
        "x0": t0, "x1": t1, "y0": y0, "y1": y1, "left": left, "top": top, "w": plot_w, "h": plot_h,
        "points": [[p[0], p[1], p[2], p[3]] for p in points],
    })
    return f"""<div class="chart-wrap"><svg class="price-chart" viewBox="0 0 {width} {height}" role="img"
aria-label="Courbe des prix, voir le tableau des relevés pour les valeurs">
{"".join(grid)}{"".join(labels)}
<path class="s2" d="{path(2)}"/><path class="s1" d="{path(1)}"/>{dots}
<g class="hover" hidden><line class="cross" y1="{top}" y2="{top + plot_h}"/><circle class="s2" r="5"/><circle class="s1" r="5"/></g>
<rect class="hit" x="{left}" y="{top}" width="{plot_w}" height="{plot_h}"/>
</svg><div class="chart-tip" hidden></div><script type="application/json" class="chart-data">{data.replace("</", "<" + chr(92) + "/")}</script></div>"""


WEEKDAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def _bars_svg(css: str, label: str, bars: list[tuple[float, float, float, str, bool]], x0: float, x1: float,
              axis: list[tuple[float, str, str]], height: int = 150) -> str:
    """Barres [(début, fin, valeur, infobulle, en évidence)] sur l'axe x0 → x1, mêmes marges que la courbe des prix
    (les deux graphiques s'alignent). Infobulle au survol par CHART_SCRIPT."""
    width, left, right, top, bottom = 820, 78, 16, 10, 28
    plot_w, plot_h = width - left - right, height - top - bottom
    high = max((b[2] for b in bars), default=0)
    step = max(_nice_step(high or 1), 1)
    y1 = int(-(-high // step) * step) or step
    x = lambda v: left + (min(max(v, x0), x1) - x0) / ((x1 - x0) or 1) * plot_w  # noqa: E731
    y = lambda v: top + (1 - v / y1) * plot_h  # noqa: E731
    grid, tick = [], 0
    while tick <= y1:
        grid.append(
            f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y(tick):.1f}" y2="{y(tick):.1f}"/>'
            f'<text class="axis" x="{left - 8}" y="{y(tick) + 4:.1f}" text-anchor="end">{number(int(tick))}</text>'
        )
        tick += step
    ticks = "".join(
        f'<text class="axis" x="{x(v):.1f}" y="{height - 8}" text-anchor="{anchor}">{esc(text)}</text>'
        for v, text, anchor in axis
    )
    shapes = []
    for start, end, value, tip, on in bars:
        bx, bw = x(start), x(end) - x(start)
        if bw <= 0:
            continue
        gap = min(1.0, bw / 4)
        shapes.append(
            f'<g class="bar{" on" if on else ""}" data-tip="{esc(tip)}"><rect class="hitbar" x="{bx:.1f}" y="{top}" '
            f'width="{bw:.1f}" height="{plot_h}"/><rect class="fill" x="{bx + gap / 2:.1f}" y="{y(value):.1f}" '
            f'width="{max(bw - gap, 0.6):.1f}" height="{max(y(0) - y(value), 0):.1f}"/></g>'
        )
    return f"""<div class="chart-wrap bars-wrap"><svg class="price-chart {css}" viewBox="0 0 {width} {height}" role="img"
aria-label="{esc(label)}">{"".join(grid)}{ticks}{"".join(shapes)}</svg><div class="chart-tip" hidden></div></div>"""


def sales_chart_svg(sales: list[tuple[int, int, int]], x0: int, x1: int, days: int, tz: Any) -> str:
    """Ventes estimées sous la courbe des prix : vendus par heure (moyenne du jour pour les jours compactés)."""
    bars = []
    for ts, sold, hours in sales:
        when = datetime.fromtimestamp(ts, tz)
        day = f"{WEEKDAYS[when.weekday()]} {when:%d/%m}"
        if hours > 1:
            tip = f"{day} : ≈ {number(sold)} vendus dans la journée ({sold / hours:.1f} par heure en moyenne)"
            bars.append((ts, ts + 86400, sold / hours, tip, False))
        else:
            tip = f"{day}, {when.hour}h–{(when.hour + 1) % 24}h : ≈ {number(sold)} vendu{'s' if sold > 1 else ''}"
            bars.append((ts, ts + 3600, sold, tip, False))
    axis = []
    for i in range(6):
        t = x0 + (x1 - x0) * i / 5
        when = datetime.fromtimestamp(t, tz)
        anchor = "start" if i == 0 else "end" if i == 5 else "middle"
        axis.append((t, when.strftime("%H:%M" if days <= 1 else "%d/%m %Hh" if days <= 3 else "%d/%m"), anchor))
    return _bars_svg("sales-chart", "Ventes estimées par heure", bars, x0, x1, axis)


def hour_profile(sales: list[tuple[int, int, int]], tz: Any) -> tuple[list[float], int] | None:
    """Moyenne des ventes par heure de la journée (heure locale) sur les heures relevées ; None sans au moins une
    journée de relevés. Renvoie (24 moyennes, nombre d'heures relevées)."""
    hourly = [(ts, sold) for ts, sold, hours in sales if hours == 1]
    if len(hourly) < 24:
        return None
    totals, counts = [0] * 24, [0] * 24
    for ts, sold in hourly:
        h = datetime.fromtimestamp(ts, tz).hour
        totals[h] += sold
        counts[h] += 1
    return [totals[h] / counts[h] if counts[h] else 0.0 for h in range(24)], len(hourly)


def hour_profile_svg(averages: list[float], current_hour: int) -> str:
    bars = [
        (h, h + 1, avg, f"Entre {h}h et {(h + 1) % 24}h : ≈ {avg:.1f} vendus en moyenne", h == current_hour)
        for h, avg in enumerate(averages)
    ]
    axis = [(h + 0.5, f"{h}h", "middle") for h in range(0, 24, 3)]
    return _bars_svg("hours-chart", "Ventes moyennes selon l'heure de la journée", bars, 0, 24, axis, 170)


# Prix en JS (même format que money_text) et petite courbe au survol d'un prix de la liste.
MONEY_JS = """
const moneyText = c => {
  c = Math.max(0, Math.round(c));
  const g = Math.floor(c / 10000), s = Math.floor(c / 100) % 100, k = c % 100, out = [];
  if (g) out.push(g.toLocaleString("fr-FR") + " po");
  if (s) out.push(s + " pa");
  if (k || !out.length) out.push(k + " pc");
  return out.join(" ");
};
"""

LIST_SCRIPT = """
<script>
(() => {
""" + MONEY_JS + """
  // Favoris : bascule sans recharger la page (le formulaire marche aussi sans JavaScript).
  document.querySelectorAll("form.ah-fav").forEach(f => f.addEventListener("submit", async e => {
    e.preventDefault();
    const b = f.querySelector("button");
    try {
      const r = await fetch(f.action, {method: "POST", body: new FormData(f), headers: {Accept: "application/json"}});
      const d = await r.json();
      if (typeof d.favorite !== "boolean") throw new Error();
      b.classList.toggle("on", d.favorite);
      b.textContent = d.favorite ? "★" : "☆";
      b.setAttribute("aria-pressed", d.favorite ? "true" : "false");
      b.title = d.favorite ? "Retirer des favoris" : "Ajouter aux favoris";
    } catch (err) { f.submit(); }
  }));
  // Petite courbe des 7 derniers jours au survol d'un prix (clic : fiche de l'objet).
  const pop = document.createElement("div");
  pop.className = "spark-pop"; pop.hidden = true; document.body.append(pop);
  const cache = new Map();
  let timer = null, current = null;
  const svgNS = "http://www.w3.org/2000/svg";
  function draw(d) {
    const pts = d.points;
    if (!pts.length) return '<p class="muted">Pas encore d\\'historique.</p>';
    const W = 260, H = 96, P = 6;
    const vals = pts.flatMap(p => [p[1], p[2]]);
    const lo = Math.min(...vals), hi = Math.max(...vals), span = (hi - lo) || 1;
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0] || t0 + 1, tspan = (t1 - t0) || 1;
    const X = t => P + (t - t0) / tspan * (W - 2 * P), Y = v => P + (1 - (v - lo) / span) * (H - 2 * P);
    const line = i => "M" + pts.map(p => X(p[0]).toFixed(1) + "," + Y(p[i]).toFixed(1)).join(" L");
    const last = pts[pts.length - 1];
    return `<div class="spark-title">${d.name} · 7 derniers jours</div>
      <svg viewBox="0 0 ${W} ${H}" class="spark"><path class="s2" d="${line(2)}"/><path class="s1" d="${line(1)}"/>
      <circle class="s1" cx="${X(last[0]).toFixed(1)}" cy="${Y(last[1]).toFixed(1)}" r="3.5"/></svg>
      <div class="spark-legend"><span><i class="k1"></i>plus bas</span><span><i class="k2"></i>médian</span></div>
      <div class="spark-range">de ${moneyText(lo)} à ${moneyText(hi)}</div>`;
  }
  function place(el) {
    const r = el.getBoundingClientRect();
    const left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - 290);
    pop.style.left = Math.max(window.scrollX + 8, left) + "px";
    pop.style.top = (window.scrollY + r.bottom + 6) + "px";
  }
  async function show(el) {
    const id = el.dataset.item;
    current = id;
    place(el);
    if (!cache.has(id)) {
      pop.innerHTML = '<p class="muted">Chargement…</p>'; pop.hidden = false;
      try {
        const r = await fetch(`/api/hdv/${id}/historique?jours=7`, {headers: {Accept: "application/json"}});
        cache.set(id, await r.json());
      } catch (e) { pop.hidden = true; return; }
    }
    if (current !== id) return;
    const d = cache.get(id);
    const name = document.createElement("span"); name.textContent = d.name || "";
    pop.innerHTML = draw({...d, name: name.innerHTML});
    pop.hidden = false;
  }
  document.querySelectorAll("a.price[data-item]").forEach(a => {
    a.addEventListener("mouseenter", () => { clearTimeout(timer); timer = setTimeout(() => show(a), 220); });
    a.addEventListener("mouseleave", () => { clearTimeout(timer); current = null; pop.hidden = true; });
    a.addEventListener("focus", () => show(a));
    a.addEventListener("blur", () => { current = null; pop.hidden = true; });
  });
})();
</script>
"""

# Fiche d'un objet : curseur et infobulle sur la courbe.
CHART_SCRIPT = """
<script>
(() => {
""" + MONEY_JS + """
  document.querySelectorAll(".chart-wrap").forEach(wrap => {
    const raw = wrap.querySelector(".chart-data");
    if (!raw) return;
    const d = JSON.parse(raw.textContent), svg = wrap.querySelector("svg"), tip = wrap.querySelector(".chart-tip");
    const hover = svg.querySelector("g.hover"), cross = hover.querySelector("line");
    const [c2, c1] = hover.querySelectorAll("circle");
    const X = t => d.left + (t - d.x0) / ((d.x1 - d.x0) || 1) * d.w;
    const Y = v => d.top + (1 - (v - d.y0) / ((d.y1 - d.y0) || 1)) * d.h;
    const fmt = t => new Date(t * 1000).toLocaleString("fr-FR", {weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"});
    function move(e) {
      const box = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
      const sx = (e.clientX - box.left) / box.width * vb.width;
      let best = d.points[0];
      for (const p of d.points) if (Math.abs(X(p[0]) - sx) < Math.abs(X(best[0]) - sx)) best = p;
      const px = X(best[0]);
      cross.setAttribute("x1", px); cross.setAttribute("x2", px);
      c1.setAttribute("cx", px); c1.setAttribute("cy", Y(best[1]));
      c2.setAttribute("cx", px); c2.setAttribute("cy", Y(best[2]));
      hover.removeAttribute("hidden");
      tip.innerHTML = `<b>${fmt(best[0])}</b><div><i class="k1"></i>Plus bas : ${moneyText(best[1])}</div>
        <div><i class="k2"></i>Médian : ${moneyText(best[2])}</div><div class="muted">${best[3]} en vente</div>`;
      tip.hidden = false;
      const left = px / vb.width * box.width;
      tip.style.left = Math.min(Math.max(left - 90, 0), box.width - 190) + "px";
    }
    const hit = svg.querySelector("rect.hit");
    hit.addEventListener("mousemove", move);
    hit.addEventListener("touchstart", e => move(e.touches[0]), {passive: true});
    hit.addEventListener("mouseleave", () => { hover.setAttribute("hidden", ""); tip.hidden = true; });
  });
  // Barres des ventes : infobulle au survol (ou au toucher) d'une barre.
  document.querySelectorAll(".bars-wrap").forEach(wrap => {
    const svg = wrap.querySelector("svg"), tip = wrap.querySelector(".chart-tip");
    const clear = () => wrap.querySelectorAll("g.bar.hot").forEach(b => b.classList.remove("hot"));
    const show = g => {
      clear();
      g.classList.add("hot");
      tip.textContent = g.dataset.tip;
      tip.hidden = false;
      const box = svg.getBoundingClientRect(), r = g.querySelector("rect").getBoundingClientRect();
      tip.style.left = Math.min(Math.max(r.left - box.left + r.width / 2 - 95, 0), box.width - 190) + "px";
    };
    wrap.querySelectorAll("g.bar").forEach(g => {
      g.addEventListener("mouseenter", () => show(g));
      g.addEventListener("touchstart", () => show(g), {passive: true});
    });
    svg.addEventListener("mouseleave", () => { tip.hidden = true; clear(); });
  });
})();
</script>
"""


class AuctionPages(MemberPages):
    """Pages de l'hôtel des ventes (réutilise les outils de MemberPages : messages, jeton des formulaires)."""

    def register_auction(self, router: web.UrlDispatcher) -> None:
        router.add_get("/hdv", self.listing)
        router.add_get("/hdv/objet/{id}", self.item_page)
        router.add_post("/hdv/favori/{id}", self.toggle_favorite)
        router.add_get("/api/hdv/{id}/historique", self.history_api)

    @property
    def house(self) -> int:
        return int(getattr(self.site, "auction_house", 0) or 0)

    def _disabled(self, request: web.Request) -> web.Response:
        body = (
            '<h1 class="title">Hôtel des ventes</h1><p class="muted">Pas encore configuré : renseigne '
            "<code>AUCTION_HOUSE_ID</code> (et les clés Blizzard) dans le <code>.env</code> du bot.</p>"
        )
        return self._render(request, "Hôtel des ventes", "hdv", body)

    def _favorite_button(self, item_id: int, on: bool, back: str) -> str:
        csrf = self._csrf_field()
        if not csrf:
            return ""
        title = "Retirer des favoris" if on else "Ajouter aux favoris"
        return (
            f'<form method="post" action="/hdv/favori/{item_id}" class="inline ah-fav">{csrf}'
            f'<input type="hidden" name="retour" value="{esc(back)}">'
            f'<button class="fav{" on" if on else ""}" title="{title}" aria-label="{title}" '
            f'aria-pressed="{"true" if on else "false"}">{"★" if on else "☆"}</button></form>'
        )

    # ============================================================ liste

    async def listing(self, request: web.Request) -> web.Response:
        if not self.house:
            return self._disabled(request)
        db = self.site.db
        user = self._web_user()
        q = request.query
        query = q.get("q", "").strip()[:60]
        class_id = int(q["classe"]) if q.get("classe", "").isdigit() else None
        subclass_id = int(q["sous"]) if q.get("sous", "").isdigit() and class_id is not None else None
        sort = q.get("tri", "nom") if q.get("tri") in SORTS else "nom"
        only_fav = q.get("favoris") == "1" and user is not None
        page_no = max(int(q["page"]), 1) if q.get("page", "").isdigit() else 1

        rows, total = db.ah_listing(
            normalize(query), class_id, subclass_id, user.id if only_fav else None, sort,
            PAGE_SIZE, (page_no - 1) * PAGE_SIZE,
        )
        favorites = db.ah_favorite_ids(user.id) if user else set()
        back = request.path_qs
        lines = []
        for r in rows:
            kind = " · ".join(x for x in (r["class_name"], r["subclass_name"]) if x)
            lines.append(
                f"<tr><td>{self._favorite_button(r['item_id'], r['item_id'] in favorites, back)}</td>"
                f'<td><a class="ah-name" href="/hdv/objet/{r["item_id"]}">{item_icon(r)}<span>{item_name(r)}'
                f"<small>{esc(kind)}</small></span></a></td>"
                f'{money_cells(r["min_price"], r["item_id"])}<td class="gap"></td>{money_cells(r["median_price"])}'
                f'<td class="num split">{number(r["quantity"])}</td><td class="num">{number(r["listings"])}</td>'
                f'<td class="num">{change_html(r["min_price"], r["min_price_24h"])}</td></tr>'
            )

        classes = db.ah_classes()
        class_options = "".join(
            f'<option value="{cid}"{" selected" if cid == class_id else ""}>{esc(name)} ({sum(s[2] for s in subs)})</option>'
            for cid, name, subs in classes
        )
        sub_select = ""
        chosen = next((c for c in classes if c[0] == class_id), None)
        if chosen and chosen[2]:
            sub_options = "".join(
                f'<option value="{sid}"{" selected" if sid == subclass_id else ""}>{esc(name)} ({n})</option>'
                for sid, name, n in chosen[2]
            )
            sub_select = (
                f'<select name="sous" data-autosubmit aria-label="Sous-type"><option value="">Tous les '
                f"{esc(chosen[1].lower())}</option>{sub_options}</select>"
            )
        sort_options = "".join(
            f'<option value="{k}"{" selected" if k == sort else ""}>{esc(v)}</option>' for k, v in SORTS.items()
        )
        fav_box = (
            f'<label class="fav-filter"><input type="checkbox" name="favoris" value="1"{" checked" if only_fav else ""}'
            ' onchange="this.form.submit()"> ★ Mes favoris</label>' if user else ""
        )
        filters = f"""<form method="get" action="/hdv" class="filters ah-filters">
<input type="search" name="q" value="{esc(query)}" placeholder="Chercher un objet (ex. étoffe, mangouste, dragonnet)…"
autocomplete="off">
<select name="classe" data-autosubmit aria-label="Type"><option value="">Tous les types</option>{class_options}</select>
{sub_select}<select name="tri" data-autosubmit aria-label="Tri">{sort_options}</select>{fav_box}
<button class="act primary">Chercher</button></form>"""

        pages = -(-total // PAGE_SIZE)
        nav = ""
        if pages > 1:
            def link(n: int, label: str) -> str:
                params = {k: v for k, v in q.items() if k != "page"}
                params["page"] = str(n)
                return f'<a class="act" href="/hdv?{esc(urlencode(params))}">{label}</a>'
            nav = '<div class="pager">' + (link(page_no - 1, "← Précédents") if page_no > 1 else "") + (
                f'<span class="muted">Page {page_no} / {pages}</span>'
            ) + (link(page_no + 1, "Suivants →") if page_no < pages else "") + "</div>"

        snapshot = db.ah_snapshot_time()
        if snapshot:
            age = time.time() - snapshot
            stale = " ⚠️ l'API de Blizzard ne répond plus : derniers prix connus" if age > 3 * 3600 else ""
            fresh = f"données de {datetime.fromtimestamp(snapshot, self.tz):%H:%M le %d/%m}{stale}"
        else:
            fresh = "premier relevé en cours (quelques minutes après le démarrage du bot)"
        empty = (
            "Aucun objet ne correspond." if snapshot else "Pas encore de prix : le bot fait son premier relevé."
        )
        table = (
            '<div class="table-wrap ah-scroll"><table class="ah-table"><thead>'
            '<tr><th rowspan="2" title="Favori">★</th><th rowspan="2">Objet</th>'
            '<th colspan="3" class="group">Prix le plus bas</th><th rowspan="2" class="gap"></th>'
            '<th colspan="3" class="group">Prix médian</th><th rowspan="2" class="num split">Disponibles</th>'
            '<th rowspan="2" class="num">Annonces</th><th rowspan="2" class="num">24 h</th></tr>'
            f"<tr>{COIN_HEADS}{COIN_HEADS}</tr></thead>"
            f'<tbody>{"".join(lines)}</tbody></table></div>'
            if lines else f'<p class="empty">{empty}</p>'
        )
        body = f"""
<h1 class="title">Hôtel des ventes</h1>
<p class="sub">Prix de l'hôtel des ventes de l'Alliance (n° {self.house}), relevés toutes les heures · {fresh} ·
{number(total)} objet(s). Prix à l'unité ; survole un prix pour son cours sur 7 jours, clique pour le détail.
💰 <a href="/rentabilite">Ce que rapportent tes métiers</a>.</p>
{filters}
{table}
{nav}"""
        return self._render(request, "Hôtel des ventes", "hdv", body, LIST_SCRIPT)

    # ============================================================ fiche

    async def item_page(self, request: web.Request) -> web.Response:
        if not self.house:
            return self._disabled(request)
        item_id = self._id(request)
        db = self.site.db
        row = db.ah_item(item_id)
        if row is None:
            raise web.HTTPNotFound(text="Objet inconnu.")
        user = self._web_user()
        period = request.query.get("periode", DEFAULT_PERIOD)
        if period not in PERIODS:
            period = DEFAULT_PERIOD
        days, period_label = PERIODS[period]
        now = int(time.time())
        points = db.ah_history(item_id, now - days * 86400)
        tz = self.tz
        sales = db.ah_sales_history(item_id, now - max(days, 7) * 86400)
        shown_sales = [r for r in sales if r[0] >= now - days * 86400]

        tabs = "".join(
            f'<a class="act{" on" if key == period else ""}" href="/hdv/objet/{item_id}?periode={key}">{esc(label)}</a>'
            for key, (_, label) in PERIODS.items()
        )
        if points:
            lows = [p[1] for p in points]
            meds = [p[2] for p in points]
            stats = (
                f'<div class="facts"><span class="fact"><small>Plus bas ({esc(period_label)})</small>{money_html(min(lows))}</span>'
                f'<span class="fact"><small>Plus haut ({esc(period_label)})</small>{money_html(max(lows))}</span>'
                f'<span class="fact"><small>Médian moyen</small>{money_html(sum(meds) // len(meds))}</span></div>'
            )
            chart = price_chart_svg(points, days, tz)
            legend = (
                '<div class="chart-legend"><span><i class="k1"></i>Prix le plus bas</span>'
                '<span><i class="k2"></i>Prix médian</span></div>'
            )
            table_rows = "".join(
                f"<tr><td>{datetime.fromtimestamp(t, tz):%d/%m %H:%M}</td>{money_cells(lo)}<td class=\"gap\"></td>"
                f'{money_cells(med)}<td class="num split">{number(qty)}</td><td class="num">{number(n)}</td></tr>'
                for t, lo, med, qty, n in reversed(points)
            )
            history = f"""{stats}{legend}{chart}{self._sales_block(shown_sales, points, days, tz)}
<details class="fold"><summary>Tableau des relevés<span class="n">{len(points)}</span></summary><div class="fold-body">
<div class="table-wrap ah-scroll"><table class="ah-table"><thead>
<tr><th rowspan="2">Relevé</th><th colspan="3" class="group">Plus bas</th><th rowspan="2" class="gap"></th>
<th colspan="3" class="group">Médian</th><th rowspan="2" class="num split">Disponibles</th>
<th rowspan="2" class="num">Annonces</th></tr><tr>{COIN_HEADS}{COIN_HEADS}</tr></thead>
<tbody>{table_rows}</tbody></table></div>
<p class="muted">Un relevé par heure sur les 7 derniers jours, puis un par jour (plus bas prix du jour, moyennes).</p>
</div></details>"""
        else:
            history = f'<p class="empty">Aucun relevé sur les {esc(period_label)} : l\'objet n\'était pas en vente.</p>'

        last_day = [r for r in sales if r[2] == 1 and r[0] >= now - 86400]
        sold_fact = (
            f'<span class="fact" title="Estimation : annonces achetées (ou retirées) sur les {len(last_day)} dernières '
            f'heures relevées"><small>Vendus (24 h)</small><b>≈ {number(sum(r[1] for r in last_day))}</b></span>'
            if last_day else ""
        )
        now_block = (
            f'<div class="facts"><span class="fact"><small>Prix le plus bas</small>{money_html(row["min_price"])}</span>'
            f'<span class="fact"><small>Prix médian</small>{money_html(row["median_price"])}</span>'
            f'<span class="fact"><small>Disponibles</small><b>{row["quantity"]}</b></span>'
            f'<span class="fact"><small>Annonces</small><b>{row["listings"]}</b></span>{sold_fact}</div>'
            if row["min_price"] is not None else '<p class="muted">Plus en vente pour l\'instant.</p>'
        )
        profile = hour_profile([r for r in sales if r[0] >= now - 7 * 86400], tz)
        if profile is not None and sum(profile[0]):
            averages, covered = profile
            best = max(range(24), key=lambda h: averages[h])
            demand = f"""<h2>Quand ça se vend</h2>
<p class="muted">Ventes moyennes selon l'heure de la journée, sur les {covered} dernières heures relevées
(7 jours au plus). Le plus actif : <b>entre {best}h et {(best + 1) % 24}h</b>. L'heure actuelle est en surbrillance.</p>
{hour_profile_svg(averages, datetime.now(tz).hour)}"""
        elif sales:
            demand = ('<h2>Quand ça se vend</h2><p class="muted">Pas encore assez de relevés : la demande heure par '
                      'heure apparaît après une journée complète.</p>')
        else:
            demand = ""
        vendor = (
            f' · vendu {money_text(row["sell_price"])} au marchand' if row["sell_price"] else ""
        )
        kind = " · ".join(x for x in (row["class_name"], row["subclass_name"]) if x)
        favorite = self._favorite_button(item_id, item_id in (db.ah_favorite_ids(user.id) if user else set()),
                                         request.path_qs)

        # Liens avec les recettes de la guilde : qui sait le fabriquer, et dans quelles recettes il sert.
        guild = ""
        gid = self.site.guild_id()
        if gid is not None:
            recipes = db.guild_recipes(gid)
            makers = [r for r in recipes if r.crafted_item_id == item_id]
            uses = [r for r in recipes if any(x[2] == item_id for x in r.reagents or [])]
            parts = []
            if makers:
                parts.append("<p>🔨 Fabriqué sur le serveur : " + ", ".join(
                    f'<b>{esc(r.name)}</b> ({esc(", ".join(r.crafters))}) · '
                    f'<a class="order-link" href="/atelier?recette={r.id}#commande">🛒 Commander</a>'
                    for r in makers
                ) + "</p>")
            if uses:
                parts.append("<p>🧪 Composant de : " + ", ".join(esc(r.name) for r in uses[:12])
                             + (f" et {len(uses) - 12} autre(s)" if len(uses) > 12 else "") + "</p>")
            guild = "".join(parts)

        body = f"""
<p class="crumb"><a href="/hdv">← Hôtel des ventes</a></p>
<div class="ah-head">{item_icon(row)}<div><h1 class="title">{item_name(row)} {favorite}</h1>
<p class="sub">{esc(kind)}{esc(vendor)}</p></div></div>
{now_block}
{guild}
<h2>Cours sur {esc(period_label)}</h2>
<div class="period-tabs">{tabs}</div>
{history}
{demand}"""
        title = row["name"] or f"Objet n° {item_id}"
        return self._render(request, title, "hdv", body, CHART_SCRIPT)

    @staticmethod
    def _sales_block(sales: list[tuple[int, int, int]], points: list, days: int, tz: Any) -> str:
        """Barres des ventes estimées, alignées sous la courbe des prix."""
        if not sales:
            return ""
        total = sum(r[1] for r in sales)
        head = (
            '<div class="chart-legend sales-legend"><span><i class="kb"></i>Ventes estimées par heure</span>'
            f'<span>≈ {number(total)} vendus sur la période</span></div>'
        )
        if not total:
            return head + '<p class="muted">Aucune vente repérée sur la période.</p>'
        x0 = points[0][0] if points else sales[0][0]
        x1 = points[-1][0] if points and points[-1][0] > x0 else sales[-1][0] + 3600
        note = (
            '<p class="muted small-note">Estimation : une annonce qui disparaît de l\'hôtel des ventes bien avant la '
            "fin de sa durée a été achetée (ou, plus rarement, retirée par le vendeur). Celles qui allaient expirer ne "
            "sont pas comptées : le vrai chiffre est plutôt un peu plus haut. Au-delà de 7 jours, une barre par jour "
            "(moyenne par heure).</p>"
        )
        return head + sales_chart_svg(sales, x0, x1, days, tz) + note

    # ============================================================ actions

    async def toggle_favorite(self, request: web.Request) -> web.StreamResponse:
        item_id = self._id(request)
        user = self._web_user()
        wants_json = "application/json" in request.headers.get("Accept", "")
        if user is None:
            raise web.HTTPForbidden(text="Connexion Discord nécessaire.")
        form = await request.post()
        if not self._same_origin(request) or not hmac.compare_digest(str(form.get("csrf", "")), self.csrf_token(user.id)):
            if wants_json:
                return web.json_response({"error": "csrf"}, status=403)
            raise web.HTTPForbidden(text="Formulaire expiré : recharge la page.")
        on = self.site.db.toggle_ah_favorite(user.id, item_id)
        if wants_json:
            return web.json_response({"favorite": on})
        back = str(form.get("retour") or "/hdv")
        return self.site._redirect(back if back.startswith("/hdv") else "/hdv")

    async def history_api(self, request: web.Request) -> web.Response:
        item_id = self._id(request)
        days = int(request.query["jours"]) if request.query.get("jours", "").isdigit() else 7
        days = min(max(days, 1), 90)
        row = self.site.db.ah_item(item_id)
        points = self.site.db.ah_history(item_id, int(time.time()) - days * 86400)
        name = (row["name"] if row is not None else None) or f"Objet n° {item_id}"
        return web.json_response({"name": name, "points": [list(p) for p in points]})
