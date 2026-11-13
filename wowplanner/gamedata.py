"""Classes, races et rôles jouables dans WoW Forever.

Combinaisons race/classe : modèle « Forever class by race » de warcraft.wiki.gg (11/2026).
Rôles : ceux de Classic, plus le Paladin tank que Forever rend viable (Seal of Fury,
Consecration de base). Le Chaman n'est pas compté comme tank : l'Amélioration peut
dépanner en petit groupe, mais ce n'est pas un rôle prévu.
"""
from __future__ import annotations

# clé -> (libellé, rôles possibles)
CLASSES: dict[str, tuple[str, tuple[str, ...]]] = {
    "guerrier": ("Guerrier", ("tank", "dps")),
    "paladin": ("Paladin", ("tank", "heal", "dps")),
    "druide": ("Druide", ("tank", "heal", "dps")),
    "pretre": ("Prêtre", ("heal", "dps")),
    "chaman": ("Chaman", ("heal", "dps")),
    "chasseur": ("Chasseur", ("dps",)),
    "voleur": ("Voleur", ("dps",)),
    "mage": ("Mage", ("dps",)),
    "demoniste": ("Démoniste", ("dps",)),
}

# clé -> (libellé, classes autorisées)
RACES: dict[str, tuple[str, frozenset[str]]] = {
    "humain": ("Humain", frozenset({"guerrier", "paladin", "chasseur", "voleur", "pretre", "mage", "demoniste"})),
    "nain": ("Nain", frozenset({"guerrier", "paladin", "chasseur", "voleur", "pretre", "chaman"})),
    "gnome": ("Gnome", frozenset({"guerrier", "voleur", "pretre", "mage", "demoniste"})),
    "elfe_nuit": ("Elfe de la nuit", frozenset({"guerrier", "chasseur", "voleur", "pretre", "druide"})),
    "orc": ("Orc", frozenset({"guerrier", "chasseur", "voleur", "chaman", "mage", "demoniste"})),
    "mort_vivant": ("Mort-vivant", frozenset({"guerrier", "paladin", "voleur", "pretre", "mage", "demoniste"})),
    "tauren": ("Tauren", frozenset({"guerrier", "chasseur", "chaman", "druide"})),
    "troll": ("Troll", frozenset({"guerrier", "chasseur", "voleur", "pretre", "chaman", "mage", "demoniste"})),
    # Mage seulement côté Alliance, Chaman seulement côté Horde : on ne gère pas la faction, on accepte les deux.
    "skyborne": ("Éolide", frozenset({"guerrier", "chasseur", "voleur", "chaman", "mage", "druide"})),
}


def class_label(key: str) -> str:
    return CLASSES[key][0] if key in CLASSES else key


def race_label(key: str) -> str:
    return RACES[key][0] if key in RACES else key


def roles_for(wow_class: str) -> tuple[str, ...]:
    return CLASSES[wow_class][1] if wow_class in CLASSES else ()


def can_play(wow_class: str, role: str) -> bool:
    return role in roles_for(wow_class)


def race_allows(race: str, wow_class: str) -> bool:
    return race in RACES and wow_class in RACES[race][1]


# Métiers (identiques à Classic d'après le wiki ; le « Camping » de Forever est un système, pas un métier).
# clé -> (libellé, principal ?)
PROFESSIONS: dict[str, tuple[str, bool]] = {
    "alchimie": ("Alchimie", True),
    "forge": ("Forge", True),
    "enchantement": ("Enchantement", True),
    "ingenierie": ("Ingénierie", True),
    "herboristerie": ("Herboristerie", True),
    "travail_cuir": ("Travail du cuir", True),
    "minage": ("Minage", True),
    "depecage": ("Dépeçage", True),
    "couture": ("Couture", True),
    "cuisine": ("Cuisine", False),
    "secourisme": ("Secourisme", False),
    "peche": ("Pêche", False),
}
MAX_PRIMARY_PROFESSIONS = 2
MAX_PROFESSION_SKILL = 300


def profession_label(key: str) -> str:
    return PROFESSIONS[key][0] if key in PROFESSIONS else key


def is_primary(profession: str) -> bool:
    return PROFESSIONS.get(profession, ("", False))[1]


# Identifiants Blizzard (API « static-forever », vérifiés le 13/11/2026) -> nos clés.
BLIZZARD_CLASS_IDS: dict[int, str] = {
    1: "guerrier", 2: "paladin", 3: "chasseur", 4: "voleur", 5: "pretre",
    7: "chaman", 8: "mage", 9: "demoniste", 11: "druide",
}
BLIZZARD_RACE_IDS: dict[int, str] = {
    1: "humain", 2: "orc", 3: "nain", 4: "elfe_nuit", 5: "mort_vivant", 6: "tauren", 7: "gnome", 8: "troll",
    95: "skyborne",  # Éolide de l'Ordre suprême
    96: "skyborne",  # Éolide sculpte-vents
}
BLIZZARD_PROFESSION_IDS: dict[int, str] = {
    129: "secourisme", 164: "forge", 165: "travail_cuir", 171: "alchimie", 182: "herboristerie",
    185: "cuisine", 186: "minage", 197: "couture", 202: "ingenierie", 333: "enchantement",
    356: "peche", 393: "depecage",
}
