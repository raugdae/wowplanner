"""Pages de consultation : Guilde (liste des persos), fiche d'un perso, Métiers, Donjons et fiche de chaque
donjon. Aucun identifiant Discord ni BattleTag ; les pages Donjons sont publiques, sans les persos du serveur
pour un visiteur non connecté."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from aiohttp import web

from . import dungeon_guides, dungeons, gear
from .gamedata import (
    CLASSES,
    PROFESSIONS,
    class_label,
    is_primary,
    profession_label,
    race_label,
    roles_for,
)
from .recipes import crafted_by_map, normalize
from .roles import LABELS, ROLES

if TYPE_CHECKING:
    from .web import WebSite
from .webcharacter import (
    SECONDARY_PROFESSIONS,
    armory_html,
    crafted_gear_html,
    professions_cells,
    professions_table,
    roles_html,
    talents_html,
)
from .webquests import hunt_banner, quests_section
from .webrecipes import (
    recipes_by_family_html,
)
from .webui import (
    _VIEWER,
    CLASS_COLORS,
    COPY_SCRIPT,
    DUNGEON_SCRIPT,
    FILTER_SCRIPT,
    FOLD_BUTTONS,
    GEAR_SCRIPT,
    PAGE_TABS_SCRIPT,
    ROW_LINK_SCRIPT,
    SPEC_SCRIPT,
    TABS_SCRIPT,
    avatar_html,
    class_span,
    esc,
    login_url,
    members_visible,
    page_tabs,
    page,
)


class GuildPages:
    def __init__(self, site: WebSite):
        self.site = site

    def register(self, router: web.UrlDispatcher) -> None:
        router.add_get("/", self.characters)
        router.add_get("/perso/{id}", self.character)
        router.add_get("/metiers", self.professions)
        router.add_get("/metier/{key}", self.profession)
        router.add_get("/donjons", self.dungeons)
        router.add_get("/donjon/{slug}", self.dungeon)


    async def characters(self, request: web.Request) -> web.Response:
        gid = self.site._scope()
        characters = sorted(self.site.db.guild_characters(gid), key=lambda c: normalize(c.name))
        rows = []
        for c in characters:
            search = normalize(" ".join([c.name, class_label(c.wow_class), race_label(c.race)]))
            rows.append(
                f'<tr data-search="{esc(search)}" data-classe="{esc(c.wow_class)}" '
                f'data-role="{" ".join(roles_for(c.wow_class))}" data-metier="{" ".join(c.professions)}">'
                f'<td><a class="who-cell" href="/perso/{c.id}">{avatar_html(c)}<b>{esc(c.name)}</b></a></td>'
                f'<td class="num">{c.level or ""}</td>'
                f"<td>{class_span(c)}</td><td>{esc(race_label(c.race))}</td>"
                f"<td>{roles_html(c)}</td>{professions_cells(c)}</tr>"
            )
        options = lambda items: "".join(f'<option value="{esc(k)}">{esc(v)}</option>' for k, v in items)  # noqa: E731
        body = f"""
<h1 class="title">Guilde</h1>
<p class="sub"><span id="count">{len(characters)}</span> perso(s) du serveur, par ordre alphabétique · ⭐ rôle préféré</p>
<div class="filters">
  <input id="q" type="search" placeholder="Chercher un perso, une classe, une race…" autocomplete="off">
  <select data-filter="classe"><option value="">Toutes les classes</option>{options(sorted(((k, v[0]) for k, v in CLASSES.items()), key=lambda kv: normalize(kv[1])))}</select>
  <select data-filter="role"><option value="">Tous les rôles</option>{options((r, LABELS[r]) for r in ROLES)}</select>
  <select data-filter="metier"><option value="">Tous les métiers</option>{options(sorted(((k, v[0]) for k, v in PROFESSIONS.items()), key=lambda kv: normalize(kv[1])))}</select>
</div>
<div class="table-wrap"><table>
<thead><tr><th>Perso</th><th class="num">Niv.</th><th>Classe</th><th>Race</th><th>Rôles</th>
<th colspan="2">Métiers principaux</th>{"".join(
    f'<th class="sec{" split" if i == 0 else ""}">{esc(profession_label(p))}</th>' for i, p in enumerate(SECONDARY_PROFESSIONS)
)}</tr></thead>
<tbody>{"".join(rows) or f'<tr><td colspan="{7 + len(SECONDARY_PROFESSIONS)}" class="empty">Aucun perso déclaré.</td></tr>'}</tbody>
</table></div>"""
        return page("Guilde", "persos", body, FILTER_SCRIPT)

    async def character(self, request: web.Request) -> web.Response:
        gid = self.site._scope()
        try:
            character_id = int(request.match_info["id"])
        except ValueError:
            raise web.HTTPNotFound(text="Perso introuvable.") from None
        character = next((c for c in self.site.db.guild_characters(gid) if c.id == character_id), None)
        if character is None:
            raise web.HTTPNotFound(text="Perso introuvable.")

        synced = ""
        if character.armory_synced_at:
            when = datetime.fromtimestamp(character.armory_synced_at).strftime("%d/%m/%Y")
            synced = f" · synchronisé avec l'armurerie le {when}"

        known = self.site.db.character_recipe_ids(character.id)
        all_recipes = self.site.db.guild_recipes(gid)
        crafted_by = crafted_by_map(all_recipes)
        tabs, panels = [], []
        for profession in sorted({p for p in PROFESSIONS}, key=lambda p: (not is_primary(p), p)):
            mine = [r for r in self.site.db.guild_recipes(gid, profession) if r.id in known]
            if mine:
                tabs.append(
                    f'<button type="button" data-tab="{esc(profession)}">{esc(profession_label(profession))}'
                    f'<span class="n">{len(mine)}</span></button>'
                )
                panels.append(
                    f'<div data-panel="{esc(profession)}">' + recipes_by_family_html(mine, crafted_by, None) + "</div>"
                )
        recipes_html = ""
        if tabs:
            recipes_html = (
                '<h2>Recettes</h2><div class="filters"><input id="q" type="search" '
                f'placeholder="Chercher une recette, un composant, un effet (ex. agilité)…" autocomplete="off">{FOLD_BUTTONS}</div>'
                f'<div class="tabs" role="tablist">{"".join(tabs)}</div>' + "".join(panels)
            )
        else:
            recipes_html = '<p class="empty">Pas de recettes connues (perso absent de l\'armurerie, ou sans métier).</p>'

        level = f"Niveau {character.level} · " if character.level else ""
        spec, talents_block = talents_html(character, self.site.db.talent_trees(character.wow_class))
        spec = f" · {esc(spec)}" if spec else ""
        render = ""
        if character.render_url and character.render_url.startswith("https://"):
            render = (
                f'<div class="render"><div class="frame"><img src="{esc(character.render_url)}" '
                f'alt="{esc(character.name)}" referrerpolicy="no-referrer"></div></div>'
            )
        professions_block = professions_table(character)
        spec_key = gear.detect_spec(character.talents, character.preferred_role, character.equipment)
        guessed = spec_key is None
        spec_key = spec_key or gear.default_spec(character.wow_class, character.preferred_role)
        icons = self.site.db.item_icons({i.get("id") for i in character.equipment or []})
        # Les arbres de talents vont sous l'équipement, dans la même colonne (à côté des caractéristiques).
        armory = armory_html(character, spec_key, icons, talents_block, guessed)
        if armory:
            talents_block = ""
        title = f"""<h1 class="title" style="color:{CLASS_COLORS.get(character.wow_class, "inherit")}">{esc(character.name)}</h1>
<p class="sub">{level}{esc(class_label(character.wow_class))} {esc(race_label(character.race))}{spec} · {roles_html(character)}{synced}</p>"""
        # Onglets : perso (équipement, stats et talents), ce que la guilde peut lui fabriquer, métiers et recettes.
        top = title if armory else f'<div class="hero"><div class="info">{title}</div>{render}</div>'
        viewer = _VIEWER.get()
        viewer_id = int(viewer.user["id"]) if viewer is not None and viewer.user else None
        top_stats = list(gear.PRIORITIES[spec_key][2][:3]) if spec_key in gear.PRIORITIES else []
        gear_block = crafted_gear_html(character, all_recipes, self.site.db.recipe_crafters(gid), viewer_id, top_stats)
        tabs = []
        if armory:
            tabs.append(("equipement", "⚔️ Équipement et talents", armory))
        elif talents_block:
            tabs.append(("talents", "✨ Talents", talents_block))
        if gear_block:
            tabs.append(("fabricable", "🔨 À lui fabriquer", gear_block))
        recipe_count = len(known)
        tabs.append(("metiers", "🛠️ Métiers et recettes" + (f'<span class="n">{recipe_count}</span>' if recipe_count else ""),
                     professions_block + recipes_html))
        body = f"""
{top}
{page_tabs(tabs, "Fiche du perso")}"""
        return page(character.name, "persos", body,
                    FILTER_SCRIPT + TABS_SCRIPT + SPEC_SCRIPT + GEAR_SCRIPT + PAGE_TABS_SCRIPT)

    async def professions(self, request: web.Request) -> web.Response:
        gid = self.site._scope()
        tiles = []
        for key, (label, primary) in PROFESSIONS.items():
            count = len(self.site.db.characters_with_profession(gid, key))
            recipes = len(self.site.db.guild_recipes(gid, key))
            kind = "" if primary else " (secondaire)"
            tiles.append(
                f'<a class="tile" href="/metier/{key}"><div class="big">{esc(label)}</div>'
                f'<div class="muted">{count} perso(s){kind} · {recipes} recette(s)</div></a>'
            )
        body = f'<h1 class="title">Métiers</h1><p class="sub">Qui a quel métier, et les recettes connues sur le serveur.</p><div class="grid">{"".join(tiles)}</div>'
        return page("Métiers", "metiers", body)

    async def profession(self, request: web.Request) -> web.Response:
        gid = self.site._scope()
        key = request.match_info["key"]
        if key not in PROFESSIONS:
            raise web.HTTPNotFound(text="Métier inconnu.")
        label = profession_label(key)

        holders = self.site.db.characters_with_profession(gid, key)
        who_rows = "".join(
            f'<tr><td><a class="who-cell" href="/perso/{c.id}">{avatar_html(c)}<b>{esc(c.name)}</b></a></td>'
            f'<td>{class_span(c)}</td>'
            f'<td class="num">{skill if skill is not None else "?"}</td></tr>'
            for c, skill in holders
        )
        who = (
            f'<div class="table-wrap" style="max-width:560px"><table><thead><tr><th>Perso</th><th>Classe</th>'
            f'<th class="num">Niveau</th></tr></thead><tbody>{who_rows}</tbody></table></div>'
            if holders else '<p class="empty">Personne n\'a déclaré ce métier.</p>'
        )

        recipes = self.site.db.guild_recipes(gid, key)
        crafted_by = crafted_by_map(self.site.db.guild_recipes(gid))
        links = {c.name: c.id for c in self.site.db.guild_characters(gid)}
        recipes_html = (
            '<div class="filters"><input id="q" type="search" placeholder="Chercher une recette, un composant, un effet (ex. agilité)…" '
            f'autocomplete="off">{FOLD_BUTTONS}</div><p class="sub"><span id="count">{len(recipes)}</span> recette(s)</p>'
            + recipes_by_family_html(recipes, crafted_by, links)
            if recipes else '<p class="empty">Aucune recette connue (seuls les persos trouvés dans l\'armurerie en ont).</p>'
        )
        tabs = [
            ("qui", "👥 Qui l'a" + (f'<span class="n">{len(holders)}</span>' if holders else ""), who),
            ("recettes", "📜 Recettes" + (f'<span class="n">{len(recipes)}</span>' if recipes else ""), recipes_html),
        ]
        body = f'<h1 class="title">{esc(label)}</h1>{page_tabs(tabs, "Métier")}'
        return page(label, "metiers", body, FILTER_SCRIPT + PAGE_TABS_SCRIPT)

    async def dungeons(self, request: web.Request) -> web.Response:
        # Page publique : les persos du serveur ne sont montrés qu'aux membres connectés.
        show_members = members_visible()
        characters = sorted(
            (c for c in self.site.db.guild_characters(self.site._scope()) if c.level),
            key=lambda c: (-(c.level or 0), normalize(c.name)),
        ) if show_members else []
        lo, hi = dungeons.LEVEL_MIN, dungeons.LEVEL_MAX
        span = hi - lo

        def players_in(low: int, high: int) -> str:
            """Cellule « persos dans la tranche » (vide pour un visiteur non connecté : colonne masquée)."""
            if not show_members:
                return ""
            inside = [c for c in characters if low <= (c.level or 0) <= high]
            if not inside:
                return '<td><span class="muted">—</span></td>'
            shown = "".join(
                f'<a href="/perso/{c.id}" title="{esc(c.name)} · niv. {c.level}">{avatar_html(c)}</a>' for c in inside[:8]
            )
            more = f'<span class="more">+{len(inside) - 8}</span>' if len(inside) > 8 else ""
            return f'<td><div class="who-avatars">{shown}{more}</div></td>'

        def name_cell(name: str, english: str, new: bool, zone: str, slug: str) -> str:
            badge = '<span class="badge-new">Nouveau</span>' if new else ""
            return (
                f'<td class="dname"><a href="/donjon/{slug}"><b>{esc(name)}{badge}</b></a>'
                f'<span class="en">{esc(english)}</span><span class="zm">📍 {esc(zone)}</span></td>'
            )

        rows = []
        for d in dungeons.DUNGEONS:
            start = max(d.low, lo)
            left = (start - lo) / span * 100
            width = max((d.high - start) / span * 100, 2)
            side = f'<div class="side {d.side}">Côté {d.side.capitalize()}</div>' if d.side else ""
            search = normalize(" ".join([d.name, d.english, d.zone]))
            rows.append(
                f'<tr data-search="{esc(search)}" data-low="{d.low}" data-high="{d.high}" data-href="/donjon/{d.slug}">'
                f'{name_cell(d.name, d.english, d.new, d.zone, d.slug)}<td class="zc">{esc(d.zone)}{side}</td>'
                f'<td class="lv"><b>{d.low}–{d.high}</b><div class="lbar">'
                f'<span style="left:{left:.1f}%;width:{width:.1f}%"></span><i></i></div></td>'
                f'<td class="num pc">{d.players}</td>{players_in(d.low, d.high)}</tr>'
            )
        raid_rows = []
        for r in dungeons.RAIDS:
            status = dungeons.raid_status(r)
            note = f'<div class="side">{esc(r.note)}</div>' if r.note else ""
            raid_rows.append(
                f'<tr data-href="/donjon/{r.slug}">{name_cell(r.name, r.english, r.new, r.zone, r.slug)}<td class="zc">{esc(r.zone)}{note}</td>'
                f'<td class="num">{r.players}</td><td class="num">{r.bosses or "?"}</td>'
                f'<td class="{"status-open" if status == "Ouvert" else "muted"}">{esc(status)}</td>'
                f"{players_in(dungeons.RAID_LEVEL, dungeons.RAID_LEVEL)}</tr>"
            )
        options = "".join(f'<option value="{c.level}">{esc(c.name)} ({c.level})</option>' for c in sorted(characters, key=lambda c: normalize(c.name)))
        if show_members:
            intro = "avec les persos du serveur qui sont dans la tranche"
            who_pick = f'<select id="lvl-who" aria-label="Perso"><option value="">Niveau d\'un perso…</option>{options}</select>'
            who_head, raid_head = "<th>Persos dans la tranche</th>", f"<th>Persos {dungeons.RAID_LEVEL}</th>"
        else:
            viewer = _VIEWER.get()
            intro = (
                f'<a href="{esc(login_url(viewer.path if viewer else "/donjons"))}">connecte-toi avec Discord</a> '
                "pour voir les persos du serveur qui sont dans chaque tranche"
            )
            who_pick = who_head = raid_head = ""
        body = f"""
<h1 class="title">Donjons</h1>
<p class="sub">{len(dungeons.DUNGEONS)} donjons de WoW Forever, du plus bas au plus haut niveau ; {intro}.
Choisis un niveau pour voir ce qui est à faire, et clique sur un donjon pour voir son entrée, ses boss et ses quêtes.</p>
{hunt_banner(self.site.db)}
<div class="filters">
  <input id="q" type="search" placeholder="Chercher un donjon, une zone…" autocomplete="off">
  <div class="lvl-pick">
    {who_pick}
    <input id="lvl" type="number" min="1" max="60" placeholder="Niveau" aria-label="Niveau">
    <label><input id="lvl-only" type="checkbox"> Seulement sa tranche</label>
  </div>
</div>
<div class="table-wrap"><table id="dungeons" class="dtable" data-min="{lo}" data-max="{hi}">
<thead><tr><th>Donjon</th><th class="zc">Zone</th><th>Niveaux</th><th class="num pc">Joueurs</th>
{who_head}</tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<h2>Raids</h2>
<div class="table-wrap"><table class="dtable">
<thead><tr><th>Raid</th><th class="zc">Accès</th><th class="num">Joueurs</th><th class="num">Boss</th><th>Ouverture</th>
{raid_head}</tr></thead>
<tbody>{"".join(raid_rows)}</tbody></table></div>
<p class="src">Niveaux conseillés, pas des verrous d'entrée. D'après Blizzard et les récapitulatifs de PC Games et
Warcraft Tavern ({dungeons.SOURCES_CHECKED}) : l'API Blizzard ne fournit pas le journal des donjons de Forever.</p>"""
        return page("Donjons", "donjons", body, FILTER_SCRIPT + DUNGEON_SCRIPT + ROW_LINK_SCRIPT)

    async def dungeon(self, request: web.Request) -> web.Response:
        """Fiche d'un donjon ou d'un raid : entrée, coordonnées, parcours des boss, persos du bon niveau
        (ces derniers seulement pour un membre connecté : la page est publique)."""
        slug = request.match_info["slug"]
        everything = [*dungeons.DUNGEONS, *dungeons.RAIDS]
        found = next((x for x in everything if x.slug == slug), None)
        if found is None:
            raise web.HTTPNotFound(text="Donjon inconnu.")
        guide = dungeon_guides.GUIDES.get(slug) or dungeon_guides.Guide("")
        is_raid = isinstance(found, dungeons.Raid)
        low, high = (dungeons.RAID_LEVEL, dungeons.RAID_LEVEL) if is_raid else (found.low, found.high)

        facts = [f'<span class="fact"><small>Niveaux</small><b>{low}–{high}</b></span>' if not is_raid else
                 f'<span class="fact"><small>Niveau</small><b>{low}</b></span>',
                 f'<span class="fact"><small>Joueurs</small><b>{found.players}</b></span>',
                 f'<span class="fact"><small>Boss</small><b>{len(guide.bosses) or "?"}</b></span>']
        if is_raid:
            facts.append(f'<span class="fact"><small>Ouverture</small><b>{esc(dungeons.raid_status(found))}</b></span>')
        side = getattr(found, "side", None)
        sub = esc(found.zone) + (f' · <span class="side {side}">Côté {side.capitalize()}</span>' if side else "")
        badge = '<span class="badge-new">Nouveau</span>' if found.new else ""
        tile = (
            f'<img class="dtile" src="{esc(guide.tile_url)}" alt="" referrerpolicy="no-referrer">'
            if guide.tile_url else '<div class="dtile none">🏰</div>'
        )

        # Entrée
        entry = [f"<p>{esc(guide.how)}</p>" if guide.how else ""]
        way = guide.way()
        if way:
            x, y = guide.coords
            entry.append(
                f'<div class="coords"><span class="pin">📍</span><div><b>{esc(guide.map_name)}</b>'
                f'<span class="muted"> · {x:g}, {y:g}</span></div>'
                f'<button type="button" class="copy" data-copy="{esc(way)}" title="Copier pour TomTom">'
                f"<code>{esc(way)}</code><span>Copier</span></button></div>"
            )
        else:
            entry.append('<p class="muted">Coordonnées exactes pas encore relevées.</p>')

        # Parcours des boss, façon tracé de donjon : étapes numérotées, les optionnels en pointillé.
        steps, n = [], 0
        for boss in guide.bosses:
            if boss.optional:
                mark, cls = "◇", " opt"
            else:
                n += 1
                mark, cls = str(n), ""
            name = dungeon_guides.boss_name(boss)
            same = name.replace("’", "'").casefold() == boss.name.replace("’", "'").casefold()
            en = f'<span class="en">{esc(boss.name)}</span>' if not same else ""
            tag = '<span class="otag">optionnel</span>' if boss.optional else ""
            where = f'<div class="where">{esc(boss.where)}</div>' if boss.where else ""
            steps.append(
                f'<li class="step{cls}"><span class="dot">{mark}</span><div class="sbody">'
                f"<b>{esc(name)}</b>{tag}{en}{where}</div></li>"
            )
        route = (
            '<ol class="route"><li class="step start"><span class="dot">⛩</span><div class="sbody"><b>Entrée</b></div></li>'
            + "".join(steps) + "</ol>"
            if steps else '<p class="empty">Boss pas encore documentés.</p>'
        )
        notes = "".join(f'<p class="muted">ℹ️ {esc(t)}</p>' for t in guide.notes)

        if members_visible():
            inside = [
                c for c in sorted(self.site.db.guild_characters(self.site._scope()), key=lambda c: (-(c.level or 0), normalize(c.name)))
                if c.level and low <= c.level <= high
            ]
            who = "".join(
                f'<a class="who-cell" href="/perso/{c.id}">{avatar_html(c)}<span><b>{esc(c.name)}</b>'
                f'<small class="muted"> {class_span(c)} · {c.level}</small></span></a>'
                for c in inside
            ) or '<p class="empty">Aucun perso du serveur dans la tranche.</p>'
        else:
            who = (
                f'<p class="muted">Réservé aux membres du serveur : <a href="{esc(login_url(request.path_qs))}">'
                "connecte-toi avec Discord</a> pour voir qui a le bon niveau.</p>"
            )

        link = (
            f'<a class="btn" href="{esc(guide.guide_url)}" target="_blank" rel="noopener noreferrer">'
            "🗺️ Carte détaillée et stratégies (Warcraft Tavern) ↗</a>"
            if guide.guide_url else ""
        )
        # Membre connecté : créer une sortie pour ce donjon (formulaire de la page Sorties prérempli).
        create = ""
        viewer = _VIEWER.get()
        if viewer is not None and viewer.user and self.site.actions is not None:
            match = self.site.actions.match_instance(found.english, found.name)
            params = {"instance": match or found.name}
            if not match:  # nom libre : la taille du groupe ne peut pas être devinée
                params["joueurs"] = str(found.players)
            create = f'<a class="btn create-ev" href="/sorties?{esc(urlencode(params))}#nouvelle">➕ Créer une sortie</a>'
        index = everything.index(found)
        prev_ = everything[index - 1] if index > 0 else None
        next_ = everything[index + 1] if index + 1 < len(everything) else None
        nav = '<nav class="dnav">' + (
            f'<a href="/donjon/{prev_.slug}">← {esc(prev_.name)}</a>' if prev_ else "<span></span>"
        ) + (f'<a href="/donjon/{next_.slug}">{esc(next_.name)} →</a>' if next_ else "<span></span>") + "</nav>"

        infos = f"""<div class="dgrid">
<section class="card"><h2>Entrée</h2>{"".join(entry)}{link}</section>
<section class="card"><h2>Persos dans la tranche</h2><div class="who-list">{who}</div></section>
</div>"""
        bosses = f"""<p class="sub">Dans l'ordre habituel ; ◇ = optionnel (rare, invoqué ou pas nécessaire pour finir).</p>
{route}{notes}"""
        count = len(guide.bosses)
        tabs = [
            ("infos", "🚪 Entrée", infos),
            ("boss", "💀 Boss" + (f'<span class="n">{count}</span>' if count else ""), bosses),
        ]
        quests = quests_section(self.site.db, slug, members_visible())
        if quests is not None:
            tabs.append(("quetes", "📜 Quêtes" + (f'<span class="n">{quests[0]}</span>' if quests[0] else ""), quests[1]))
        body = f"""
<p class="crumb"><a href="/donjons">← Tous les donjons</a></p>
<div class="dhero">{tile}<div>
<h1 class="title">{esc(found.name)}{badge}</h1>
<p class="sub">{esc(found.english)} · {sub}</p>
<div class="facts">{"".join(facts)}</div>{create}</div></div>
{page_tabs(tabs, "Fiche du donjon")}
<p class="src">Entrée et boss d'après les guides de Warcraft Tavern ({dungeons.SOURCES_CHECKED}) ; noms français du
Journal de Blizzard quand il les donne. Vignette : Blizzard. L'API Blizzard ne fournit ni carte ni coordonnées pour
Forever : la carte détaillée est sur le guide. Quêtes : API Blizzard ; donneurs, positions, niveaux et suites
relevés en jeu par les membres avec l'addon WoW Planner.</p>
{nav}"""
        return page(found.name, "donjons", body, COPY_SCRIPT + PAGE_TABS_SCRIPT)

