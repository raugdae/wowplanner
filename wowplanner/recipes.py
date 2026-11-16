"""Recettes d'un métier : recherche, regroupement (par type d'objet ou par famille de nom) et
composants dépliés. Utilisé par le site web et par l'atelier.
"""
from __future__ import annotations

import math
import unicodedata
from collections import Counter

from .db import GuildRecipe

# Une famille a sa section à partir de ce nombre de recettes ; les autres vont dans « Autres ».
MIN_FAMILY_SIZE = 3
# Profondeur max des sous-recettes dépliées (lin → rouleau → sac = 2).
MAX_SUBRECIPE_DEPTH = 3
OTHER_FAMILY = "Autres"


def normalize(text: str) -> str:
    """Minuscules sans accents : « Élixir » et « elixir » se valent pour la recherche et le tri."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def filter_recipes(recipes: list[GuildRecipe], search: str | None) -> list[GuildRecipe]:
    """Recettes dont le nom contient la recherche (sans tenir compte des accents), triées par nom."""
    query = normalize(search.strip()) if search and search.strip() else ""
    matched = [r for r in recipes if query in normalize(r.name)]
    return sorted(matched, key=lambda r: (normalize(r.name), r.id))


def _first_word(name: str) -> str:
    return name.split()[0] if name.split() else name


def _family_label(words: list[str]) -> str:
    """Libellé d'une famille, au pluriel. Les noms du jeu mélangent « Elixir » et « Élixir » :
    on préfère la graphie accentuée (la bonne), puis la plus fréquente."""
    counts = Counter(words)
    word = max(counts, key=lambda w: (w.casefold() != normalize(w), counts[w]))
    word = word[:1].upper() + word[1:]
    return plural(word)


def plural(word: str) -> str:
    """Pluriel français d'un nom de famille de recettes : Rouleau → Rouleaux, Cristal → Cristaux."""
    lower = word.casefold()
    if lower[-1:] in ("s", "x", "z"):
        return word
    if lower.endswith(("eau", "au", "eu")) and lower not in ("landau", "sarrau", "bleu", "pneu", "émeu"):
        return word + "x"
    if lower.endswith("al") and lower not in ("bal", "carnaval", "chacal", "festival", "récital", "régal"):
        return word[:-1] + "ux"
    return word + "s"


def group_by_family(recipes: list[GuildRecipe]) -> list[tuple[str, list[GuildRecipe]]]:
    """[(famille, recettes)], familles par ordre alphabétique, « Autres » à la fin."""
    families: dict[str, list[GuildRecipe]] = {}
    for recipe in recipes:
        families.setdefault(normalize(_first_word(recipe.name)), []).append(recipe)
    grouped: list[tuple[str, list[GuildRecipe]]] = []
    others: list[GuildRecipe] = []
    for key in sorted(families):
        members = families[key]
        if len(members) >= MIN_FAMILY_SIZE:
            grouped.append((_family_label([_first_word(r.name) for r in members]), members))
        else:
            others.extend(members)
    if others:
        label = OTHER_FAMILY if grouped else "Recettes"
        grouped.append((label, sorted(others, key=lambda r: (normalize(r.name), r.id))))
    return grouped


# Emplacements d'armure, dans l'ordre de la fiche du jeu.
_ARMOR_SLOT_ORDER = (
    "HEAD", "NECK", "SHOULDER", "CLOAK", "CHEST", "ROBE", "BODY", "TABARD", "WRIST", "HAND", "WAIST", "LEGS", "FEET",
    "FINGER", "TRINKET", "SHIELD", "HOLDABLE",
)


def recipe_category(recipe: GuildRecipe) -> tuple[tuple, str] | None:
    """(clé de tri, libellé) d'après l'objet fabriqué ; None si l'objet n'est pas encore connu."""
    item = recipe.item or {}
    if recipe.crafted_item_id is None:
        # Enchantements (pas d'objet) : « Enchantement de bracelets - Endurance » → « Enchantement de bracelets ».
        head = recipe.name.split(" - ")[0].strip() if " - " in recipe.name else "Enchantements"
        return (8, normalize(head)), head
    cls = item.get("class")
    if cls is None:
        return None
    if cls == 7:
        return (0,), "Composants d'artisanat"
    if cls == 5:
        return (1,), "Réactifs"
    if cls == 0:
        sub = item.get("subclass_name") or "Consommables"
        sub = "Consommables divers" if normalize(sub) in ("autre", "consommable", "divers") else sub
        return (2, normalize(sub)), sub
    if cls == 4:
        slot = item.get("slot") or ""
        order = _ARMOR_SLOT_ORDER.index(slot) if slot in _ARMOR_SLOT_ORDER else len(_ARMOR_SLOT_ORDER)
        return (3, order), f"Armure : {item.get('slot_name') or 'divers'}"
    if cls == 2:
        return (4,), "Armes"
    if cls == 6:
        return (5,), "Projectiles"
    if cls in (1, 11):
        return (6,), "Sacs et carquois"
    return (7, normalize(item.get("class_name") or "")), item.get("class_name") or OTHER_FAMILY


def group_by_category(recipes: list[GuildRecipe]) -> list[tuple[str, list[GuildRecipe]]]:
    """[(catégorie, recettes)] selon le type d'objet fabriqué (composants d'artisanat, potions, armure : torse…).
    Repli sur les familles de noms tant que les objets ne sont pas connus (avant la récupération des détails)."""
    categories: dict[str, tuple[tuple, list[GuildRecipe]]] = {}
    unknown: list[GuildRecipe] = []
    for recipe in recipes:
        found = recipe_category(recipe)
        if found is None:
            unknown.append(recipe)
            continue
        key, label = found
        categories.setdefault(label, (key, []))[1].append(recipe)
    if not any(r.crafted_item_id is not None for rs in (v[1] for v in categories.values()) for r in rs) and unknown:
        return group_by_family(recipes)  # rien de classé par objet : l'ancien regroupement par nom
    grouped = [
        (label, sorted(members, key=lambda r: (normalize(r.name), r.id)))
        for label, (_, members) in sorted(categories.items(), key=lambda kv: (kv[1][0], kv[0]))
    ]
    if unknown:
        grouped.append((OTHER_FAMILY, sorted(unknown, key=lambda r: (normalize(r.name), r.id))))
    return grouped


CraftedBy = dict[int, GuildRecipe]  # id d'objet → recette du serveur qui le fabrique


def crafted_by_map(recipes: list[GuildRecipe]) -> CraftedBy:
    """Objets fabricables par les recettes connues sur le serveur (tous métiers confondus)."""
    mapping: CraftedBy = {}
    for recipe in sorted(recipes, key=lambda r: r.id):  # en cas de doublon, toujours la même
        if recipe.crafted_item_id and recipe.reagents is not None:
            mapping.setdefault(recipe.crafted_item_id, recipe)
    return mapping


def expand_reagents(
    reagents: list[tuple[int, str, int | None]],
    crafted_by: CraftedBy,
    depth: int = 0,
    seen: frozenset[int] = frozenset(),
) -> list[tuple[int, int, str]]:
    """[(profondeur, quantité, composant)] : les composants qu'une recette du serveur fabrique sont
    suivis de leurs propres composants (profondeur + 1), quantités recalculées.
    Ex. : 3× Rouleau d'étoffe de lin → 6× Étoffe de lin. Partagé par Discord et le site web."""
    rows = []
    for qty, name, item_id in reagents:
        rows.append((depth, qty, name))
        sub = crafted_by.get(item_id) if item_id is not None else None
        if sub is None or sub.id in seen or depth >= MAX_SUBRECIPE_DEPTH or not sub.reagents:
            continue
        crafts = math.ceil(qty / (sub.crafted_quantity or 1))  # fabrications nécessaires
        scaled = [(sub_qty * crafts, sub_name, sub_id) for sub_qty, sub_name, sub_id in sub.reagents]
        rows.extend(expand_reagents(scaled, crafted_by, depth + 1, seen | {sub.id}))
    return rows


def reagent_lines(
    reagents: list[tuple[int, str, int | None]],
    crafted_by: CraftedBy,
    seen: frozenset[int] = frozenset(),
) -> list[str]:
    """Version texte pour Discord (« ↳ » sous le composant fabriqué)."""
    return [
        # Espaces cadratin : Discord écrase les espaces simples en début de ligne.
        f"{chr(0x2003) * (2 * depth)}{'↳ ' if depth else ''}{qty}× {name}"
        for depth, qty, name in expand_reagents(reagents, crafted_by, seen=seen)
    ]
