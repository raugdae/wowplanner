"""Petit site web public, en lecture seule : persos, métiers et recettes du serveur.

Aucune info personnelle : ni pseudo Discord, ni identifiant Discord, ni BattleTag, et rien qui
permette de relier deux persos au même joueur. Seuls les persos (nom, classe, race, rôles),
leurs métiers et leurs recettes sont affichés.

Servi par aiohttp dans le même processus que le bot (même base SQLite, lue seulement). Activé
par WEB_PORT ; derrière Traefik en production (voir docker-compose.traefik.yml).
"""
from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Callable

from aiohttp import web

from .db import Character, Database, GuildRecipe
from .gamedata import CLASSES, PROFESSIONS, class_label, is_primary, profession_label, race_label, roles_for
from .recipes import crafted_by_map, expand_reagents, filter_recipes, group_by_family, normalize
from .roles import LABELS, ROLES

log = logging.getLogger(__name__)

CLASS_COLORS = {
    "guerrier": "#C79C6E", "paladin": "#F58CBA", "chasseur": "#ABD473", "voleur": "#FFF569", "pretre": "#FFFFFF",
    "chaman": "#3A8EF0", "mage": "#69CCF0", "demoniste": "#9482C9", "druide": "#FF7D0A",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


STYLE = """
:root { --bg:#14161b; --panel:#1d2027; --panel2:#252933; --text:#e6e6e6; --muted:#9aa0aa; --accent:#e0b04a;
        --line:#323744; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
a { color:inherit; text-decoration:none; }
a:hover { text-decoration:underline; }
header { background:var(--panel); border-bottom:1px solid var(--line); padding:12px 16px;
         display:flex; gap:20px; align-items:center; flex-wrap:wrap; position:sticky; top:0; z-index:5; }
header .brand { font-weight:700; color:var(--accent); font-size:17px; }
header nav { display:flex; gap:14px; }
header nav a { color:var(--muted); }
header nav a.active { color:var(--text); font-weight:600; }
main { max-width:1200px; margin:0 auto; padding:20px 16px 48px; }
h1 { margin:0 0 4px; font-size:24px; }
h2 { margin:28px 0 10px; font-size:18px; }
h3 { margin:20px 0 8px; font-size:14px; color:var(--accent); text-transform:uppercase; letter-spacing:.06em; }
.sub { color:var(--muted); margin:0 0 16px; }
.filters { display:flex; gap:8px; flex-wrap:wrap; margin:12px 0 16px; }
.filters input, .filters select { background:var(--panel); color:var(--text); border:1px solid var(--line);
  border-radius:8px; padding:8px 10px; font:inherit; }
.filters input { flex:1 1 220px; }
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:10px; }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); vertical-align:top; }
th { background:var(--panel); color:var(--muted); font-weight:600; font-size:13px; white-space:nowrap; }
tr:last-child td { border-bottom:none; }
tbody tr:hover { background:var(--panel); }
.num { text-align:right; font-variant-numeric:tabular-nums; }
.tag { display:inline-block; background:var(--panel2); border:1px solid var(--line); border-radius:999px;
       padding:1px 9px; margin:2px 4px 2px 0; font-size:13px; white-space:nowrap; }
.tag b { font-variant-numeric:tabular-nums; }
.muted { color:var(--muted); }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:10px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:10px 12px; }
.card h4 { margin:0 0 6px; font-size:15px; }
.card ul { list-style:none; margin:0; padding:0; }
.card li { padding:1px 0; }
.card li.d1 { padding-left:18px; color:var(--muted); }
.card li.d2 { padding-left:36px; color:var(--muted); }
.card li.d3 { padding-left:54px; color:var(--muted); }
.card li.d1::before, .card li.d2::before, .card li.d3::before { content:"↳ "; }
.card .who { margin-top:6px; font-size:13px; color:var(--muted); }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:10px; }
.tile { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px; display:block; }
.tile:hover { border-color:var(--accent); text-decoration:none; }
.tile .big { font-size:22px; font-weight:700; }
.empty { color:var(--muted); font-style:italic; }
footer { color:var(--muted); font-size:12px; text-align:center; padding:24px; }
"""

FILTER_SCRIPT = """
<script>
(() => {
  const norm = s => s.normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
  const q = document.getElementById("q");
  const selects = [...document.querySelectorAll("select[data-filter]")];
  const items = [...document.querySelectorAll("[data-search]")];
  const sections = [...document.querySelectorAll("[data-section]")];
  const count = document.getElementById("count");
  function apply() {
    const text = q ? norm(q.value.trim()) : "";
    let shown = 0;
    for (const el of items) {
      let ok = !text || el.dataset.search.includes(text);
      for (const s of selects) {
        if (s.value && !(el.dataset[s.dataset.filter] || "").split(" ").includes(s.value)) ok = false;
      }
      el.hidden = !ok;
      if (ok) shown++;
    }
    for (const sec of sections) sec.hidden = !sec.querySelector("[data-search]:not([hidden])");
    if (count) count.textContent = shown;
  }
  if (q) q.addEventListener("input", apply);
  selects.forEach(s => s.addEventListener("change", apply));
  apply();
})();
</script>
"""


def page(title: str, active: str, body: str, scripts: str = "") -> web.Response:
    nav = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>'
        for key, href, label in (("persos", "/", "Persos"), ("metiers", "/metiers", "Métiers"))
    )
    document = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · WoW Planner</title><style>{STYLE}</style></head>
<body><header><a class="brand" href="/">⚔️ WoW Planner</a><nav>{nav}</nav></header>
<main>{body}</main>
<footer>Données des persos déclarés sur le Discord, complétées par l'armurerie Blizzard (WoW Forever).</footer>
{scripts}</body></html>"""
    return web.Response(text=document, content_type="text/html")


def class_span(c: Character) -> str:
    return f'<span style="color:{CLASS_COLORS.get(c.wow_class, "inherit")}">{esc(class_label(c.wow_class))}</span>'


def roles_html(c: Character) -> str:
    return ", ".join(
        f"{esc(LABELS[r])} ⭐" if r == c.preferred_role else esc(LABELS[r]) for r in roles_for(c.wow_class)
    )


def professions_html(c: Character) -> str:
    if not c.professions:
        return '<span class="muted">—</span>'
    ordered = sorted(c.professions.items(), key=lambda kv: (not is_primary(kv[0]), kv[0]))
    return "".join(
        f'<span class="tag">{esc(profession_label(p))}' + (f" <b>{skill}</b>" if skill is not None else "") + "</span>"
        for p, skill in ordered
    )


def recipe_card(recipe: GuildRecipe, crafted_by: dict, crafter_links: dict[str, int] | None) -> str:
    if recipe.reagents is None:
        reagents = '<li class="muted">composants inconnus pour l\'instant</li>'
    elif not recipe.reagents:
        reagents = '<li class="muted">aucun composant</li>'
    else:
        reagents = "".join(
            f'<li class="d{depth}">{qty}× {esc(name)}</li>'
            for depth, qty, name in expand_reagents(recipe.reagents, crafted_by, seen=frozenset({recipe.id}))
        )
    who = ""
    if crafter_links is not None:
        links = ", ".join(
            f'<a href="/perso/{crafter_links[n]}">{esc(n)}</a>' if n in crafter_links else esc(n)
            for n in recipe.crafters
        )
        who = f'<div class="who">👥 {links}</div>'
    search = normalize(" ".join([recipe.name, *(r[1] for r in recipe.reagents or [])]))
    return (
        f'<div class="card" data-search="{esc(search)}"><h4>{esc(recipe.name)}</h4>'
        f"<ul>{reagents}</ul>{who}</div>"
    )


def recipes_by_family_html(recipes: list[GuildRecipe], crafted_by: dict, crafter_links: dict[str, int] | None) -> str:
    sections = []
    for family, members in group_by_family(filter_recipes(recipes, None)):
        cards = "".join(recipe_card(r, crafted_by, crafter_links) for r in members)
        sections.append(f'<section data-section><h3>{esc(family)}</h3><div class="cards">{cards}</div></section>')
    return "".join(sections)


class WebSite:
    def __init__(self, db: Database, guild_id: Callable[[], int | None]):
        self.db = db
        self._guild_id = guild_id
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------ données

    def guild_id(self) -> int | None:
        """Le serveur Discord affiché : GUILD_ID, ou le seul serveur connu."""
        configured = self._guild_id()
        if configured:
            return configured
        known = self.db.known_guild_ids()
        return known[0] if len(known) == 1 else None

    def _scope(self) -> int:
        gid = self.guild_id()
        if gid is None:
            raise web.HTTPServiceUnavailable(text="Serveur Discord non déterminé : renseigne GUILD_ID dans le .env.")
        return gid

    # ------------------------------------------------------------ pages

    async def characters(self, request: web.Request) -> web.Response:
        gid = self._scope()
        characters = sorted(self.db.guild_characters(gid), key=lambda c: normalize(c.name))
        rows = []
        for c in characters:
            search = normalize(" ".join([c.name, class_label(c.wow_class), race_label(c.race)]))
            rows.append(
                f'<tr data-search="{esc(search)}" data-classe="{esc(c.wow_class)}" '
                f'data-role="{" ".join(roles_for(c.wow_class))}" data-metier="{" ".join(c.professions)}">'
                f'<td><a href="/perso/{c.id}"><b>{esc(c.name)}</b></a></td>'
                f"<td>{class_span(c)}</td><td>{esc(race_label(c.race))}</td>"
                f"<td>{roles_html(c)}</td><td>{professions_html(c)}</td></tr>"
            )
        options = lambda items: "".join(f'<option value="{esc(k)}">{esc(v)}</option>' for k, v in items)  # noqa: E731
        body = f"""
<h1>Persos</h1>
<p class="sub"><span id="count">{len(characters)}</span> perso(s) · ⭐ rôle préféré</p>
<div class="filters">
  <input id="q" type="search" placeholder="Chercher un perso, une classe, une race…" autocomplete="off">
  <select data-filter="classe"><option value="">Toutes les classes</option>{options((k, v[0]) for k, v in CLASSES.items())}</select>
  <select data-filter="role"><option value="">Tous les rôles</option>{options((r, LABELS[r]) for r in ROLES)}</select>
  <select data-filter="metier"><option value="">Tous les métiers</option>{options((k, v[0]) for k, v in PROFESSIONS.items())}</select>
</div>
<div class="table-wrap"><table>
<thead><tr><th>Perso</th><th>Classe</th><th>Race</th><th>Rôles</th><th>Métiers</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="5" class="empty">Aucun perso déclaré.</td></tr>'}</tbody>
</table></div>"""
        return page("Persos", "persos", body, FILTER_SCRIPT)

    async def character(self, request: web.Request) -> web.Response:
        gid = self._scope()
        try:
            character_id = int(request.match_info["id"])
        except ValueError:
            raise web.HTTPNotFound(text="Perso introuvable.")
        character = next((c for c in self.db.guild_characters(gid) if c.id == character_id), None)
        if character is None:
            raise web.HTTPNotFound(text="Perso introuvable.")

        prof_rows = "".join(
            f'<tr><td><a href="/metier/{esc(p)}">{esc(profession_label(p))}</a></td>'
            f'<td class="num">{skill if skill is not None else "?"}</td></tr>'
            for p, skill in sorted(character.professions.items(), key=lambda kv: (not is_primary(kv[0]), kv[0]))
        )
        synced = ""
        if character.armory_synced_at:
            when = datetime.fromtimestamp(character.armory_synced_at).strftime("%d/%m/%Y")
            synced = f" · synchronisé avec l'armurerie le {when}"

        known = self.db.character_recipe_ids(character.id)
        all_recipes = self.db.guild_recipes(gid)
        crafted_by = crafted_by_map(all_recipes)
        recipes_html = ""
        for profession in sorted({p for p in PROFESSIONS}, key=lambda p: (not is_primary(p), p)):
            mine = [r for r in self.db.guild_recipes(gid, profession) if r.id in known]
            if mine:
                recipes_html += (
                    f"<h2>{esc(profession_label(profession))} — {len(mine)} recette(s)</h2>"
                    + recipes_by_family_html(mine, crafted_by, None)
                )
        if recipes_html:
            recipes_html = (
                '<div class="filters"><input id="q" type="search" '
                'placeholder="Chercher une recette ou un composant…" autocomplete="off"></div>' + recipes_html
            )
        else:
            recipes_html = '<p class="empty">Pas de recettes connues (perso absent de l\'armurerie, ou sans métier).</p>'

        body = f"""
<h1 style="color:{CLASS_COLORS.get(character.wow_class, "inherit")}">{esc(character.name)}</h1>
<p class="sub">{esc(class_label(character.wow_class))} {esc(race_label(character.race))} · {roles_html(character)}{synced}</p>
<h2>Métiers</h2>
{f'<div class="table-wrap" style="max-width:420px"><table><thead><tr><th>Métier</th><th class="num">Niveau</th></tr></thead><tbody>{prof_rows}</tbody></table></div>' if prof_rows else '<p class="empty">Aucun métier déclaré.</p>'}
{recipes_html}"""
        return page(character.name, "persos", body, FILTER_SCRIPT)

    async def professions(self, request: web.Request) -> web.Response:
        gid = self._scope()
        tiles = []
        for key, (label, primary) in PROFESSIONS.items():
            count = len(self.db.characters_with_profession(gid, key))
            recipes = len(self.db.guild_recipes(gid, key))
            kind = "" if primary else " (secondaire)"
            tiles.append(
                f'<a class="tile" href="/metier/{key}"><div class="big">{esc(label)}</div>'
                f'<div class="muted">{count} perso(s){kind} · {recipes} recette(s)</div></a>'
            )
        body = f'<h1>Métiers</h1><p class="sub">Qui a quel métier, et les recettes connues sur le serveur.</p><div class="grid">{"".join(tiles)}</div>'
        return page("Métiers", "metiers", body)

    async def profession(self, request: web.Request) -> web.Response:
        gid = self._scope()
        key = request.match_info["key"]
        if key not in PROFESSIONS:
            raise web.HTTPNotFound(text="Métier inconnu.")
        label = profession_label(key)

        holders = self.db.characters_with_profession(gid, key)
        who_rows = "".join(
            f'<tr><td><a href="/perso/{c.id}"><b>{esc(c.name)}</b></a></td><td>{class_span(c)}</td>'
            f'<td class="num">{skill if skill is not None else "?"}</td></tr>'
            for c, skill in holders
        )
        who = (
            f'<div class="table-wrap" style="max-width:560px"><table><thead><tr><th>Perso</th><th>Classe</th>'
            f'<th class="num">Niveau</th></tr></thead><tbody>{who_rows}</tbody></table></div>'
            if holders else '<p class="empty">Personne n\'a déclaré ce métier.</p>'
        )

        recipes = self.db.guild_recipes(gid, key)
        crafted_by = crafted_by_map(self.db.guild_recipes(gid))
        links = {c.name: c.id for c in self.db.guild_characters(gid)}
        recipes_html = (
            '<div class="filters"><input id="q" type="search" placeholder="Chercher une recette ou un composant…" '
            f'autocomplete="off"></div><p class="sub"><span id="count">{len(recipes)}</span> recette(s)</p>'
            + recipes_by_family_html(recipes, crafted_by, links)
            if recipes else '<p class="empty">Aucune recette connue (seuls les persos trouvés dans l\'armurerie en ont).</p>'
        )
        body = f"<h1>{esc(label)}</h1><h2>Qui l'a</h2>{who}<h2>Recettes</h2>{recipes_html}"
        return page(label, "metiers", body, FILTER_SCRIPT)

    # ------------------------------------------------------------ serveur

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.characters)
        app.router.add_get("/perso/{id}", self.character)
        app.router.add_get("/metiers", self.professions)
        app.router.add_get("/metier/{key}", self.profession)
        return app

    async def start(self, host: str, port: int) -> None:
        self._runner = web.AppRunner(self.app(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, port).start()
        log.info("Site web démarré sur %s:%d", host, port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
