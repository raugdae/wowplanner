"""Mise en forme des recettes d'un métier : filtre de recherche et pages pour Discord.

Une recette tient sur deux lignes dans un bloc de code (police à chasse fixe) :

    Élixir de Force mineure         Hollie, Grommash
      └ 1 Feuillargent · 1 Fiole vide

Un vrai tableau « recette | compo 1 | compo 2 | … | crafteurs » ferait plus de 100 caractères
de large : Discord le replierait (≈ 60 caractères sur PC, 40 sur mobile) et l'alignement
serait perdu.
"""
from __future__ import annotations

import unicodedata

from .db import GuildRecipe

NAME_WIDTH = 30
CRAFTERS_WIDTH = 24
# Limite Discord : 4096 caractères par description d'embed (blocs de code compris).
PAGE_CHARS = 3900


def normalize(text: str) -> str:
    """Minuscules sans accents : « Élixir » et « elixir » se valent pour la recherche et le tri."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def filter_recipes(recipes: list[GuildRecipe], search: str | None) -> list[GuildRecipe]:
    """Recettes dont le nom contient la recherche (sans tenir compte des accents), triées par nom."""
    query = normalize(search.strip()) if search and search.strip() else ""
    matched = [r for r in recipes if query in normalize(r.name)]
    return sorted(matched, key=lambda r: (normalize(r.name), r.id))


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def crafters_text(names: list[str]) -> str:
    """Prénoms des persos (gain de place), « +N » au-delà de la largeur disponible."""
    first_names = [n.split()[0] for n in names]
    shown: list[str] = []
    for i, name in enumerate(first_names):
        rest = len(first_names) - i - 1
        candidate = ", ".join([*shown, name]) + (f" +{rest}" if rest else "")
        if shown and len(candidate) > CRAFTERS_WIDTH:
            return ", ".join(shown) + f" +{len(first_names) - len(shown)}"
        shown.append(name)
    return ", ".join(shown)


def recipe_lines(recipe: GuildRecipe) -> str:
    head = f"{_cut(recipe.name, NAME_WIDTH).ljust(NAME_WIDTH)}  {crafters_text(recipe.crafters)}"
    if recipe.reagents is None:
        detail = "  └ composants inconnus pour l'instant"
    elif not recipe.reagents:
        detail = "  └ aucun composant"
    else:
        detail = "  └ " + " · ".join(f"{qty} {name}" for qty, name in recipe.reagents)
    return f"{head.rstrip()}\n{detail}"


def build_pages(recipes: list[GuildRecipe]) -> list[str]:
    """Découpe en pages ; chaque page est un bloc de code prêt à mettre dans une description d'embed."""
    pages: list[str] = []
    current: list[str] = []
    size = 0
    for recipe in recipes:
        block = recipe_lines(recipe)
        if current and size + len(block) + 1 > PAGE_CHARS - 8:  # 8 = les deux « ``` » et leurs retours
            pages.append("```\n" + "\n".join(current) + "\n```")
            current, size = [], 0
        current.append(block)
        size += len(block) + 1
    if current:
        pages.append("```\n" + "\n".join(current) + "\n```")
    return pages
