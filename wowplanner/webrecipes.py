"""Cartes de recettes (pages Métiers, fiche perso, atelier) : effet de l'objet, composants dépliés,
artisans, lien « Commander »."""
from __future__ import annotations

from .db import GuildRecipe
from .recipes import expand_reagents, filter_recipes, group_by_category, normalize
from .webui import (
    _VIEWER,
    QUALITY_COLORS,
    esc,
)


def recipe_card(
    recipe: GuildRecipe, crafted_by: dict, crafter_links: dict[str, int] | None, order_link: bool = True,
) -> str:
    if recipe.reagents is None:
        reagents = '<li class="muted">composants inconnus pour l\'instant</li>'
    elif not recipe.reagents:
        reagents = '<li class="muted">aucun composant</li>'
    else:
        reagents = "".join(
            f'<li class="d{depth}">{qty}× {esc(name)}</li>'
            for depth, qty, name in expand_reagents(recipe.reagents, crafted_by, seen=frozenset({recipe.id}))
        )
    lines = []
    if recipe.description:
        lines.append(("effect", recipe.description))
    item = recipe.item or {}
    lines.extend((kind, text) for kind, text in item.get("lines", []))
    tip = "".join(f'<div class="{esc(kind)}">{esc(text)}</div>' for kind, text in lines)
    tip = f'<div class="tip">{tip}</div>' if tip else ""
    color = QUALITY_COLORS.get(item.get("quality") or "")
    title_style = f' style="color:{color}"' if color else ""
    who = ""
    if crafter_links is not None:
        links = ", ".join(
            f'<a href="/perso/{crafter_links[n]}">{esc(n)}</a>' if n in crafter_links else esc(n)
            for n in recipe.crafters
        )
        who = f'<div class="who">👥 {links}</div>'
    viewer = _VIEWER.get()
    if order_link and viewer is not None and viewer.user:
        who += f'<div class="who"><a class="order-link" href="/atelier?recette={recipe.id}#commande">🛒 Commander</a></div>'
    search = normalize(" ".join([recipe.name, *(r[1] for r in recipe.reagents or []), *(t for _, t in lines)]))
    return (
        f'<div class="card" data-search="{esc(search)}"><h4{title_style}>{esc(recipe.name)}</h4>'
        f"{tip}<ul>{reagents}</ul>{who}</div>"
    )


def recipes_by_family_html(recipes: list[GuildRecipe], crafted_by: dict, crafter_links: dict[str, int] | None) -> str:
    sections = []
    for family, members in group_by_category(filter_recipes(recipes, None)):
        cards = "".join(recipe_card(r, crafted_by, crafter_links) for r in members)
        sections.append(
            f'<details class="fold" data-section><summary><span>{esc(family)}</span>'
            f'<span class="n">{len(members)}</span></summary><div class="fold-body"><div class="cards">{cards}</div>'
            "</div></details>"
        )
    return "".join(sections)


