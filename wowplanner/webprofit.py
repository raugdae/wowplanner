"""Page « Rentabilité » : ce que rapportent les métiers d'un de ses persos, aux prix de l'hôtel des ventes.

Calculs dans profit.py ; prix et catalogue des objets dans la base locale (cogs/auctions.py).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from aiohttp import web

from .auctions import money_text
from .db import Character
from .gamedata import is_primary, profession_label
from .profit import (
    AH_CUT, BONUS_LOOT, GATHERING, VENDOR_REAGENTS, CraftPlan, CraftStep, best_channel, craft_plan, gather_requirement,
    gathered_value, gathering_rows, out_of_reach, raw_unit, recipe_profits,
)
from .recipes import normalize
from .webui import _VIEWER, TABS_SCRIPT, esc
from .webauction import COIN_HEADS, LIST_SCRIPT, MONEY_JS, AuctionPages, item_icon, item_name, money_cells, number

# Au-delà, les recettes les moins rentables sont repliées.
SHOWN_RECIPES = 40
# Quantité maximale saisie par objet dans la calculatrice.
MAX_STOCK = 100_000
CHANNEL_LABELS = {"hdv": "HdV", "marchand": "Marchand"}


def bonus_mark(item_id: int) -> str:
    """Astérisque avec infobulle pour une ressource obtenue en bonus (chance de loot), vide sinon."""
    source = BONUS_LOOT.get(item_id)
    if source is None:
        return ""
    text = f"Chance de loot : pas de nœud à lui, s'obtient parfois en bonus {source}."
    return f'<span class="bonus" tabindex="0" title="{esc(text)}" aria-label="{esc(text)}">*</span>'


def channel_tag(channel: str | None) -> str:
    """Pastille « HdV » / « Marchand » : où l'argent est gagné ou dépensé."""
    if channel not in CHANNEL_LABELS:
        return ""
    return f'<span class="chan {channel}">{CHANNEL_LABELS[channel]}</span>'


# Précisions sur certaines récoltes.
GATHERING_NOTES = {"peche": " (le niveau de pêche requis n'est pas connu par poisson)"}


def signed_money(copper: int | None) -> str:
    """Bénéfice signé et coloré (vert / rouge), en texte po/pa/pc."""
    if copper is None:
        return '<span class="muted">?</span>'
    if copper == 0:
        return '<span class="muted">0</span>'
    sign, cls = ("+", "gain") if copper > 0 else ("−", "loss")
    return f'<span class="{cls}">{sign} {esc(money_text(abs(copper)))}</span>'


SOURCE_LABELS = {"hdv": "HdV", "marchand": "marchand"}


class ProfitPages(AuctionPages):
    """Pages « Rentabilité de mes métiers » et « Calculatrice HdV », toujours pour un perso du joueur connecté."""

    def register_profit(self, router: web.UrlDispatcher) -> None:
        router.add_get("/rentabilite", self.profit_page)
        router.add_get("/calculatrice", self.calculator_page)

    def _pick_character(
        self, request: web.Request, title: str, active: str, action: str, why: str,
    ) -> tuple[web.Response | None, Character | None, str]:
        """(page d'erreur, perso choisi, menu de choix du perso). Le perso : celui demandé, sinon le préféré, sinon le
        premier qui a un métier."""
        if not self.house:
            return self._disabled(request), None, ""
        viewer = _VIEWER.get()
        if self._web_user() is None or viewer is None:
            body = f'<h1 class="title">{title}</h1><p class="muted">Connexion Discord nécessaire : {esc(why)}</p>'
            return self._render(request, title, active, body), None, ""
        crafters = [c for c in viewer.characters if c.professions]
        if not crafters:
            body = (
                f'<h1 class="title">{title}</h1><p class="empty">Aucun de tes persos n\'a de métier connu. Les métiers '
                'viennent de l\'armurerie : ajoute tes persos dans <a href="/mes-persos">Mes persos</a>.</p>'
            )
            return self._render(request, title, active, body), None, ""
        wanted = request.query.get("perso", "")
        character = next((c for c in crafters if str(c.id) == wanted), None)
        if character is None:
            character = next((c for c in crafters if c.favorite), crafters[0])
        options = "".join(
            f'<option value="{c.id}"{" selected" if c.id == character.id else ""}>{"⭐ " if c.favorite else ""}'
            f'{esc(c.name)} — {esc(", ".join(profession_label(p) for p in c.professions))}</option>'
            for c in sorted(crafters, key=lambda c: (not c.favorite, normalize(c.name)))
        )
        picker = (
            f'<form method="get" action="{action}" class="filters"><select name="perso" data-autosubmit '
            f'aria-label="Perso">{options}</select><noscript><button class="act">Voir</button></noscript></form>'
        )
        return None, character, picker

    def _prices_when(self) -> str:
        snapshot = self.site.db.ah_snapshot_time()
        return f"{datetime.fromtimestamp(snapshot, self.tz):%H:%M le %d/%m}" if snapshot else "pas encore relevés"

    def _known_recipes(self, character: Character, profession: str | None = None) -> list:
        """Recettes connues du perso (d'un métier, ou de tous), avec leurs détails."""
        gid = self.site.guild_id()
        if gid is None:
            return []
        known = self.site.db.character_recipe_ids(character.id)
        return [r for r in self.site.db.guild_recipes(gid, profession) if r.id in known]

    async def profit_page(self, request: web.Request) -> web.Response:
        title = "Rentabilité de mes métiers"
        error, character, picker = self._pick_character(
            request, title, "rentabilite", "/rentabilite", "la page montre ce que rapportent les métiers de tes persos."
        )
        if error is not None:
            return error
        assert character is not None
        # Un onglet par métier (récolte et fabrication ensemble) ; sans JavaScript, tout reste affiché à la suite.
        tabs, panels = [], []
        professions = sorted(character.professions.items(), key=lambda p: (not is_primary(p[0]), p[0]))
        for key, skill in professions:
            level = f" · niveau {skill}" if skill is not None else ""
            sections = []
            if key in GATHERING:
                sections.append(self._gathering_section(key, skill, level))
            recipes = self._known_recipes(character, key)
            if recipes:
                sections.append(self._crafting_section(key, recipes, level))
            elif key not in GATHERING:
                sections.append(
                    f'<section class="card admin-sec"><h2>{esc(profession_label(key))}{esc(level)}</h2>'
                    '<p class="empty">Aucune recette connue dans l\'armurerie pour ce perso.</p></section>'
                )
            skill_badge = f'<span class="n">{skill}</span>' if skill is not None else ""
            tabs.append(f'<button type="button" data-tab="{esc(key)}">{esc(profession_label(key))}{skill_badge}</button>')
            panels.append(f'<div data-panel="{esc(key)}">{"".join(sections)}</div>')
        sections = [f'<div class="tabs" role="tablist">{"".join(tabs)}</div>', *panels]
        body = f"""
<h1 class="title">{title}</h1>
<p class="sub">Ce que rapportent les métiers de ton perso aux prix de l'<a href="/hdv">hôtel des ventes</a>
(n° {self.house}, prix de {self._prices_when()}). Vente au prix le plus bas actuel, commission de {AH_CUT * 100:.0f} %
déduite ; composants au prix le plus bas de l'HdV, ou au prix du marchand pour ceux qu'il vend (fioles, fils, teintures,
flux, épices…). « Marchand » : ce que le marchand te donne pour l'objet. 🧮 <a href="/calculatrice?perso={character.id}">
Calculer avec ton stock</a>.</p>
{picker}
{"".join(sections)}"""
        return self._render(request, title, "rentabilite", body, LIST_SCRIPT + PROFIT_SCRIPT + TABS_SCRIPT)

    # ------------------------------------------------------------ calculatrice

    def _stock_candidates(self, character: Character, recipes: list) -> list[tuple[str, list[tuple[Any, int | None]]]]:
        """Objets que le joueur peut avoir en stock, par groupe, avec le niveau de récolte s'il est connu :
        ressources qu'il récolte (à son niveau), puis composants de ses recettes (sauf ceux vendus par les
        marchands, achetés au besoin). Chaque groupe est trié par nom."""
        db = self.site.db
        groups: list[tuple[str, dict[int, int | None]]] = []
        seen: set[int] = set()
        for key, skill in sorted(character.professions.items()):
            if key not in GATHERING:
                continue
            subclass, skills, label = GATHERING[key]
            levels = {
                r["item_id"]: required
                for r, required, ok in gathering_rows(db.ah_tradeskill_on_sale(subclass), skills, skill)
                if ok and r["item_id"] not in seen
            }
            seen.update(levels)
            if levels:
                groups.append((f"{profession_label(key)} : {label.lower()}", levels))
        reagents = {
            item_id: None for r in recipes for _, _, item_id in r.reagents or []
            if isinstance(item_id, int) and item_id not in VENDOR_REAGENTS and item_id not in seen
        }
        if reagents:
            groups.append(("Composants de tes recettes", reagents))
        items = db.ah_items_map({i for _, levels in groups for i in levels})
        return [
            (label, sorted(((items[i], lvl) for i, lvl in levels.items() if i in items),
                           key=lambda pair: normalize(pair[0]["name"])))
            for label, levels in groups
        ]

    def _stock_table(self, character: Character, groups: list, inventory: dict[int, int]) -> str:
        """Saisie du stock : un tableau par ligne d'objet, groupé par catégorie, avec la valeur brute calculée au
        fil de la saisie (CALC_SCRIPT) ; les champs vides ne partent pas dans l'adresse de la page."""
        lines, total, any_out = [], 0, False
        for index, (label, rows) in enumerate(groups):
            lines.append(
                f'<tr class="grp" data-group="{index}"><th colspan="9"><button type="button" class="fold-toggle" '
                f'aria-expanded="true"><span class="arrow">▾</span> {esc(label)} <span class="n">{len(rows)}</span>'
                "</button></th></tr>"
            )
            for row, level in rows:
                unit = raw_unit(row)
                net = int(row["min_price"] * (1 - AH_CUT)) if row["min_price"] else None
                vendor = row["sell_price"] or 0
                best = channel_tag(best_channel(row)) or "—"
                qty = inventory.get(row["id"], 0)
                total += unit * qty
                value = esc(money_text(unit * qty)) if qty and unit else "—"
                requirement = gather_requirement(row["id"])
                if level is None and requirement is not None:
                    level = requirement[1]
                out = out_of_reach(row["id"], character.professions)
                any_out = any_out or out
                level_cell = str(level) if level is not None else "—"
                if out and requirement is not None:
                    why = f"Hors de ta compétence : {profession_label(requirement[0])} {requirement[1]} requis"
                    level_cell = f'<span class="out-tag" title="{esc(why)}">{level_cell} ⚠</span>'
                lines.append(
                    f'<tr class="stock-row{" out" if out else ""}" data-group="{index}" data-unit="{unit}" '
                    f'data-out="{int(out)}" data-name="{esc(normalize(row["name"]))}">'
                    f'<td><a class="ah-name" href="/hdv/objet/{row["id"]}">{item_icon(row)}<span>{item_name(row)}'
                    f'</span></a>{bonus_mark(row["id"])}</td><td class="num hide-sm">{level_cell}</td>'
                    f"{money_cells(net, row['id'] if net else None)}"
                    f'<td class="num muted hide-sm">{esc(money_text(vendor)) if vendor else "—"}</td>'
                    f'<td class="best">{best}</td>'
                    f'<td class="qty"><input type="number" name="q{row["id"]}" min="0" max="{MAX_STOCK}" '
                    f'inputmode="numeric" value="{qty or ""}" placeholder="0" aria-label="Stock : {esc(row["name"])}"></td>'
                    f'<td class="num value">{value}</td></tr>'
                )
        categories = "".join(
            f'<option value="{index}">{esc(label)} ({len(rows)})</option>' for index, (label, rows) in sorted(enumerate(groups), key=lambda g: normalize(g[1][0]))
        )
        skill_box = (
            '<label class="fav-filter" title="Ressources que ce perso ne peut pas récolter lui-même : métier absent ou '
            'niveau trop bas"><input type="checkbox" class="calc-skill"> Masquer ce qui est hors de ma compétence</label>'
            if any_out else ""
        )
        return f"""<form method="get" action="/calculatrice" class="calc-form" data-perso="{character.id}">
<input type="hidden" name="perso" value="{character.id}">
<div class="filters calc-tools"><select class="calc-category" aria-label="Catégorie">
<option value="">Toutes les catégories</option>{categories}</select>
<input type="search" class="calc-search" placeholder="Chercher une ressource…"
autocomplete="off" aria-label="Chercher une ressource"><label class="fav-filter"><input type="checkbox"
class="calc-mine"> Seulement ce que j'ai</label>{skill_box}<button class="act primary">🧮 Calculer</button>
<button type="button" class="act calc-clear">Vider</button></div>
<div class="table-wrap ah-scroll"><table class="ah-table calc-table"><thead>
<tr><th rowspan="2">Ressource</th><th rowspan="2" class="num hide-sm">Niv.</th>
<th colspan="3" class="group">Prix HdV (net)</th><th rowspan="2" class="num hide-sm">Marchand</th>
<th rowspan="2">Meilleure vente</th><th rowspan="2">Ton stock</th><th rowspan="2" class="num">Valeur brute</th></tr>
<tr>{COIN_HEADS}</tr></thead>
<tbody>{"".join(lines)}</tbody>
<tfoot><tr><td colspan="8" class="num">Total si tout est vendu brut :</td>
<td class="num calc-total">{esc(money_text(total)) if total else "—"}</td></tr></tfoot></table></div>
</form>"""

    async def calculator_page(self, request: web.Request) -> web.Response:
        title = "Calculatrice HdV"
        error, character, picker = self._pick_character(
            request, title, "calculatrice", "/calculatrice",
            "la calculatrice compare la vente de ton stock à ce que tes recettes en feraient.",
        )
        if error is not None:
            return error
        assert character is not None
        recipes = [r for r in self._known_recipes(character) if r.crafted_item_id]
        groups = self._stock_candidates(character, recipes)
        inventory: dict[int, int] = {}
        for key, value in request.query.items():
            if key.startswith("q") and key[1:].isdigit() and value.strip().isdigit():
                inventory[int(key[1:])] = min(int(value), MAX_STOCK)
        # Stock vu en jeu par l'addon (sacs + banque) : proposé, ou chargé avec ?jeu=1.
        game_meta, game_items = self.site.db.game_inventory(character.id)
        candidates = {row["id"] for _, rows in groups for row, _ in rows}
        game_stock = {i: min(n, MAX_STOCK) for i, n in game_items.items() if i in candidates}
        if request.query.get("jeu") and game_stock:
            inventory = game_stock
        game_link = ""
        if game_meta is not None:
            when = datetime.fromtimestamp(game_meta["updated_at"], self.tz).strftime("%d/%m à %H:%M")
            bank = "" if game_meta["bank_at"] else " (banque jamais ouverte avec l'addon)"
            game_link = (
                f'<p class="game-stock">🧩 <a href="/calculatrice?perso={character.id}&amp;jeu=1">Remplir avec ce que '
                f"l'addon a vu en jeu</a> : sacs et banque, relevé du {when}{bank}.</p>"
                if game_stock else
                f'<p class="muted">🧩 L\'addon n\'a vu aucun objet utile à la calculatrice (relevé du {when}).</p>'
            )

        if not any(rows for _, rows in groups):
            stock_form = (
                '<p class="empty">Rien à saisir : ce perso ne récolte pas de ressource en vente à l\'HdV et ses recettes '
                "n'utilisent pas de composant de l'HdV.</p>"
            )
        else:
            stock_form = self._stock_table(character, groups, inventory)

        result = ""
        if inventory:
            ids = set(inventory) | {r.crafted_item_id for r in recipes}
            ids |= {i for r in recipes for _, _, i in r.reagents or [] if isinstance(i, int)}
            items = self.site.db.ah_items_map(ids)
            plan = craft_plan(inventory, recipes, items)
            result = self._plan_html(plan, bool(recipes), inventory, items)

        no_craft = "" if recipes else (
            '<p class="muted">Ce perso n\'a pas de métier de fabrication : la calculatrice donne la valeur du stock '
            'vendu brut. Pour le faire transformer par un autre joueur, passe par l\'<a href="/atelier">atelier</a>.</p>'
        )
        body = f"""
<h1 class="title">{title}</h1>
<p class="sub">Indique ce que ton perso a en stock : la calculatrice compare la vente brute (au meilleur prix entre
l'<a href="/hdv">HdV</a>, commission de {AH_CUT * 100:.0f} % déduite, et le marchand) avec la fabrication par ses
recettes (composants vendus par les marchands achetés au besoin), aux prix de {self._prices_when()}.
💰 <a href="/rentabilite?perso={character.id}">Rentabilité de ses métiers</a>.</p>
{picker}
{no_craft}
{result}
<h2>Ton stock</h2>
{game_link}
{stock_form}"""
        return self._render(request, title, "calculatrice", body, LIST_SCRIPT + CALC_SCRIPT)

    @staticmethod
    def _sell_table(stock: dict[int, int], items: dict[int, Any]) -> str:
        """Ce qu'il reste à vendre brut, objet par objet : où (HdV ou marchand), à combien l'unité des deux côtés,
        et le total ; les objets les plus rentables d'abord."""
        rows, totals = [], {"hdv": 0, "marchand": 0}
        for item_id, qty in stock.items():
            row = items.get(item_id)
            channel = best_channel(row)
            if channel is None or qty <= 0:
                continue
            net = int(row["min_price"] * (1 - AH_CUT)) if row["min_price"] else 0
            vendor = row["sell_price"] or 0
            total = raw_unit(row) * qty
            totals[channel] += total
            rows.append((total, row, qty, channel, net, vendor))
        if not rows:
            return ""
        rows.sort(key=lambda r: (-r[0], normalize(r[1]["name"])))

        def unit(value: int, best: bool) -> str:
            if not value:
                return '<span class="muted">—</span>'
            return f'<b>{esc(money_text(value))}</b>' if best else f'<span class="muted">{esc(money_text(value))}</span>'

        lines = "".join(
            f'<tr><td><a class="ah-name" href="/hdv/objet/{row["id"]}">{item_icon(row)}<span>{item_name(row)}</span></a>'
            f'</td><td class="num">{number(qty)}</td><td>{channel_tag(channel)}</td>'
            f'<td class="num">{unit(net, channel == "hdv")}</td><td class="num">{unit(vendor, channel == "marchand")}</td>'
            f'<td class="num">{esc(money_text(total))}</td></tr>'
            for total, row, qty, channel, net, vendor in rows
        )
        summary = " · ".join(
            f"{channel_tag(ch)} {esc(money_text(v))}" for ch, v in totals.items() if v
        )
        return (
            f'<p class="sell-sum">{summary}</p>'
            '<div class="table-wrap"><table class="ah-table sell"><thead><tr><th>Objet</th><th class="num">Quantité</th>'
            '<th>Vendre</th>'
            f'<th class="num" title="Prix le plus bas actuel, commission de {AH_CUT * 100:.0f} % déduite">HdV, l\'unité</th>'
            '<th class="num" title="Ce que le marchand en donne">Marchand, l\'unité</th>'
            f'<th class="num">Total</th></tr></thead><tbody>{lines}</tbody></table></div>'
        )

    def _plan_html(self, plan: CraftPlan, can_craft: bool, inventory: dict[int, int], items: dict[int, Any]) -> str:
        def item_label(step: CraftStep) -> str:
            product = step.product
            name = item_name(product) if product is not None else esc(step.name)
            return f'<a class="ah-name" href="/hdv/objet/{step.product_id}">{item_icon(product)}<span>{name}</span></a>'

        def steps_table(steps: list[CraftStep], first: str) -> str:
            rows = "".join(
                f"<tr><td>{item_label(s)}</td><td class=\"num\">{number(s.crafts)}</td>"
                f'<td class="num">+ {esc(money_text(s.product_value))} {channel_tag(s.channel)}</td>'
                f'<td class="num">'
                + (f'− {esc(money_text(s.buy_cost))} {channel_tag("marchand")}' if s.buy_cost else '<span class="muted">—</span>')
                + f'</td><td class="num muted">{esc(money_text(s.used_value))}</td>'
                f'<td class="num">{signed_money(s.gain)}</td></tr>'
                for s in steps
            )
            return (
                f'<div class="table-wrap"><table class="ah-table steps"><thead><tr><th>{first}</th>'
                '<th class="num">Fabrications</th>'
                '<th class="num" title="Les objets fabriqués, vendus là où ils rapportent le plus (HdV : commission déduite)">'
                "Vente des objets fabriqués</th>"
                '<th class="num" title="Composants que les marchands vendent (fioles, fils…)">Achats de composants</th>'
                '<th class="num" title="Ce que ton stock utilisé aurait rapporté vendu brut">Stock utilisé, vendu brut</th>'
                '<th class="num">Gain vs vente brute</th></tr></thead>'
                f"<tbody>{rows}</tbody></table></div>"
            )

        verdict = (
            f'<p class="verdict gain">🛠️ Fabriquer rapporte <b>{esc(money_text(plan.gain))}</b> de plus que tout vendre '
            "brut.</p>" if plan.gain > 0 else
            '<p class="verdict">💰 Mieux vaut tout vendre brut : aucune recette ne rapporte plus que le stock lui-même'
            " aux prix actuels.</p>" if can_craft else ""
        )
        facts = (
            f'<div class="facts"><span class="fact"><small>Tout vendre brut</small><b>{esc(money_text(plan.raw_total))}</b>'
            f'</span><span class="fact"><small>Avec le plan conseillé</small><b>{esc(money_text(plan.total))}</b></span>'
            f'<span class="fact"><small>Différence</small><b>{signed_money(plan.gain)}</b></span></div>'
        )
        parts = [f'<section class="card admin-sec calc-result"><h2>Résultat</h2>{facts}{verdict}']
        if plan.steps:
            parts.append("<h3>Plan conseillé</h3>" + steps_table(plan.steps, "Fabriquer"))
        # Vente brute : le reste après le plan, ou tout le stock s'il n'y a rien à fabriquer.
        sell = self._sell_table(plan.leftovers if plan.steps else inventory, items)
        if sell:
            title = "Puis vendre le reste du stock" if plan.steps else "Vendre le stock"
            parts.append(
                f"<h3>{title} : où ?</h3><p class=\"muted\">Pour chaque objet, là où il rapporte le plus : l'HdV (au "
                f"prix le plus bas actuel, commission de {AH_CUT * 100:.0f} % déduite) ou le marchand (sans risque ni "
                "attente). Le prix en gras est celui retenu.</p>" + sell
            )
        if plan.options:
            parts.append(
                "<h3>Chaque recette seule</h3><p class=\"muted\">Avec tout ton stock pour elle seule ; une même "
                "ressource sert parfois à plusieurs recettes, d'où le plan ci-dessus.</p>"
                + steps_table(plan.options, "Recette")
            )
        elif can_craft:
            parts.append('<p class="muted">Aucune de tes recettes ne peut être fabriquée avec ce stock.</p>')
        if plan.unpriced:
            parts.append(
                f'<p class="muted">⚠️ {len(plan.unpriced)} objet(s) du stock sans prix (ni à l\'HdV ni chez le marchand) '
                "comptent pour 0.</p>"
            )
        parts.append("</section>")
        return "".join(parts)

    # ------------------------------------------------------------ récolte

    def _gathering_section(self, key: str, skill: int | None, level: str) -> str:
        subclass, skills, label = GATHERING[key]
        rows = gathering_rows(self.site.db.ah_tradeskill_on_sale(subclass), skills, skill)
        lines = []
        for row, required, reachable in rows:
            req = str(required) if required is not None else "?"
            value = gathered_value(row)
            vendor = money_text(value.vendor) if value.vendor else "—"
            margin = f"{value.margin:+.0f} %" if value.margin is not None else ""
            lines.append(
                f'<tr class="{"" if reachable else "later"}"><td><a class="ah-name" href="/hdv/objet/{row["item_id"]}">'
                f"{item_icon(row)}<span>{item_name(row)}</span></a>{bonus_mark(row['item_id'])}</td>"
                f'<td class="num">{req}</td>{money_cells(row["min_price"], row["item_id"])}<td class="gap"></td>'
                f"{money_cells(value.net)}<td class=\"num split muted\">{esc(vendor)}</td>"
                f'<td class="num">{signed_money(value.gain)}</td><td class="num">{esc(margin)}</td>'
                f'<td class="num">{number(row["quantity"])}</td></tr>'
            )
        reachable = sum(1 for r in rows if r[2])
        table = (
            '<div class="table-wrap ah-scroll"><table class="ah-table"><thead>'
            '<tr><th rowspan="2">Ressource</th><th rowspan="2" class="num">Niveau</th>'
            '<th colspan="3" class="group">Prix le plus bas</th><th rowspan="2" class="gap"></th>'
            '<th colspan="3" class="group">Vente HdV (net)</th><th rowspan="2" class="num split">Marchand</th>'
            '<th rowspan="2" class="num">Gain vs marchand</th><th rowspan="2" class="num">Marge</th>'
            '<th rowspan="2" class="num">En vente</th></tr>'
            f'<tr>{COIN_HEADS}{COIN_HEADS}</tr></thead><tbody>{"".join(lines)}</tbody></table></div>'
            if lines else '<p class="empty">Aucune de ces ressources n\'est en vente en ce moment.</p>'
        )
        return f"""<section class="card admin-sec"><h2>{esc(profession_label(key))}{esc(level)} · récolte</h2>
<p class="muted">{esc(label)} en vente à l'HdV{esc(GATHERING_NOTES.get(key, ""))} : {reachable} récoltable(s) à ton niveau (en premier, du plus cher au
moins cher), les autres grisées. Rien à payer pour une ressource récoltée : le gain et la marge comparent la vente à
l'HdV (commission de {AH_CUT * 100:.0f} % déduite) à la revente au marchand ; un gain négatif veut dire qu'il vaut mieux
la vendre au marchand.</p>{table}</section>"""

    # ------------------------------------------------------------ fabrication

    def _crafting_section(self, key: str, recipes: list, level: str) -> str:
        ids = {r.crafted_item_id for r in recipes if r.crafted_item_id}
        ids |= {x[2] for r in recipes for x in r.reagents or [] if x[2]}
        items = self.site.db.ah_items_map(ids)
        results, without_item = recipe_profits(recipes, items)
        lines = []
        for i, r in enumerate(results):
            parts = "".join(
                f"<li>{x.quantity}× {esc(x.name)} : "
                + (f"{esc(money_text(x.total))} <small>({SOURCE_LABELS[x.source]})</small>"
                   if x.total is not None else '<span class="muted">prix inconnu</span>')
                + "</li>"
                for x in r.reagents
            ) or "<li class=\"muted\">aucun composant</li>"
            missing = f' <span class="muted" title="Composants sans prix">+ {r.missing} ?</span>' if r.missing else ""
            product = r.product
            name = item_name(product) if product is not None else esc(r.name)
            icon = item_icon(product) if product is not None else '<span class="ah-icon none"></span>'
            per = f" ×{r.crafted_quantity:g}" if r.crafted_quantity != 1 else ""
            margin = f"{r.margin:+.0f} %" if r.margin is not None else ""
            vendor = money_text(r.vendor_value) if r.vendor_value else "—"
            hidden = " hidden" if i >= SHOWN_RECIPES else ""
            lines.append(
                f'<tr class="{"" if r.revenue is not None else "later"}"{hidden} data-extra="{int(i >= SHOWN_RECIPES)}">'
                f'<td><a class="ah-name" href="/hdv/objet/{r.product_id}">{icon}<span>{name}{esc(per)}</span></a>'
                f'<details class="parts"><summary>{len(r.reagents)} composant(s)</summary><ul>{parts}</ul></details></td>'
                f'{money_cells(r.revenue, r.product_id if r.revenue is not None else None)}<td class="gap"></td>'
                f"{money_cells(r.cost if r.reagents else 0)}<td class=\"num split\">{signed_money(r.profit)}{missing}</td>"
                f'<td class="num">{esc(margin)}</td><td class="num muted">{esc(vendor)}</td>'
                f'<td class="num">{number(r.available) if r.available is not None else "—"}</td></tr>'
            )
        more = len(results) - SHOWN_RECIPES
        more_button = (
            f'<p><button type="button" class="act show-more">Voir les {more} autres recettes</button></p>' if more > 0 else ""
        )
        note = (
            f" {without_item} recette(s) sans objet à vendre (enchantements…) ne sont pas comptées." if without_item else ""
        )
        table = (
            '<div class="table-wrap ah-scroll"><table class="ah-table profit"><thead>'
            '<tr><th rowspan="2">Objet fabriqué</th><th colspan="3" class="group">Vente HdV (net)</th>'
            '<th rowspan="2" class="gap"></th><th colspan="3" class="group">Coût des composants</th>'
            '<th rowspan="2" class="num split">Bénéfice</th><th rowspan="2" class="num">Marge</th>'
            '<th rowspan="2" class="num">Marchand</th><th rowspan="2" class="num">En vente</th></tr>'
            f'<tr>{COIN_HEADS}{COIN_HEADS}</tr></thead><tbody>{"".join(lines)}</tbody></table></div>{more_button}'
            if lines else '<p class="empty">Aucune recette de ce métier ne fabrique d\'objet à vendre.</p>'
        )
        return f"""<section class="card admin-sec"><h2>{esc(profession_label(key))}{esc(level)} · fabrication</h2>
<p class="muted">{len(results)} recette(s) connue(s), de la plus rentable à la moins rentable (bénéfice : vente nette
moins composants). Grisées : objet pas en vente en ce moment. « En vente » : quantité déjà proposée à l'HdV, pour juger
de la concurrence.{esc(note)}</p>{table}</section>"""


PROFIT_SCRIPT = """
<script>
document.querySelectorAll("button.show-more").forEach(b => b.addEventListener("click", () => {
  const section = b.closest("section");
  section.querySelectorAll('tr[data-extra="1"]').forEach(tr => tr.hidden = false);
  b.remove();
}));
</script>
"""

# Calculatrice : valeur brute de chaque ligne et total au fil de la saisie, recherche, « seulement ce que j'ai » ;
# le stock est gardé dans le navigateur (par perso) et seuls les champs remplis partent dans l'adresse de la page.
CALC_SCRIPT = """
<script>
(() => {
  const form = document.querySelector("form.calc-form");
  if (!form) return;
""" + MONEY_JS + """
  const key = "wp-calc-" + form.dataset.perso;
  const rows = [...form.querySelectorAll("tr.stock-row")];
  const inputs = rows.map(r => r.querySelector("input[type=number]"));
  const search = form.querySelector(".calc-search"), mine = form.querySelector(".calc-mine");
  const total = form.querySelector(".calc-total");
  const norm = s => s.normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
  function refresh() {
    let sum = 0;
    rows.forEach((row, i) => {
      const qty = Math.max(0, parseInt(inputs[i].value, 10) || 0), unit = +row.dataset.unit;
      sum += qty * unit;
      row.querySelector(".value").textContent = qty && unit ? moneyText(qty * unit) : "—";
    });
    total.textContent = sum ? moneyText(sum) : "—";
  }
  // Catégorie, recherche, « seulement ce que j'ai », et groupes repliés (gardés dans le navigateur, par perso).
  const category = form.querySelector(".calc-category"), skill = form.querySelector(".calc-skill");
  const foldKey = key + "-replies";
  let folded = new Set();
  try { folded = new Set(JSON.parse(localStorage.getItem(foldKey) || "[]")); } catch (e) {}
  function filter() {
    const q = norm(search.value.trim()), shown = new Set();
    rows.forEach((row, i) => {
      const ok = (!category.value || row.dataset.group === category.value)
        && (!q || row.dataset.name.includes(q))
        && (!mine.checked || parseInt(inputs[i].value, 10) > 0)
        && (!skill || !skill.checked || row.dataset.out !== "1");
      if (ok) shown.add(row.dataset.group);
      row.hidden = !ok || folded.has(row.dataset.group);
    });
    form.querySelectorAll("tr.grp").forEach(head => {
      head.hidden = !shown.has(head.dataset.group);
      head.querySelector("button").setAttribute("aria-expanded", String(!folded.has(head.dataset.group)));
    });
  }
  form.querySelectorAll("tr.grp button").forEach(b => b.addEventListener("click", () => {
    const group = b.closest("tr").dataset.group;
    if (folded.has(group)) folded.delete(group); else folded.add(group);
    try { localStorage.setItem(foldKey, JSON.stringify([...folded])); } catch (e) {}
    filter();
  }));
  category.addEventListener("change", filter);
  if (skill) {
    try { skill.checked = localStorage.getItem("wp-calc-skill") === "1"; } catch (e) {}
    skill.addEventListener("change", () => {
      try { localStorage.setItem("wp-calc-skill", skill.checked ? "1" : ""); } catch (e) {}
      filter();
    });
  }
  if (!inputs.some(i => i.value)) {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || "{}");
      inputs.forEach(i => { if (saved[i.name]) i.value = saved[i.name]; });
    } catch (e) {}
  }
  inputs.forEach(i => i.addEventListener("input", () => { refresh(); if (mine.checked) filter(); }));
  search.addEventListener("input", filter);
  mine.addEventListener("change", filter);
  form.addEventListener("submit", () => {
    const data = {};
    inputs.forEach(i => { if (+i.value > 0) data[i.name] = i.value; else i.disabled = true; });
    search.disabled = true;
    try { localStorage.setItem(key, JSON.stringify(data)); } catch (e) {}
  });
  form.querySelector(".calc-clear").addEventListener("click", () => {
    inputs.forEach(i => { i.value = ""; });
    try { localStorage.removeItem(key); } catch (e) {}
    refresh(); filter();
  });
  refresh(); filter();
})();
</script>
"""
