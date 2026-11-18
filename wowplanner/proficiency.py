"""Armures et armes que chaque classe peut porter dans WoW Forever (pour l'équipement conseillé du site).

Armes : liste des maîtres d'armes de Forever (Warcraft Tavern et RankedBoost, nov. 2026). Nouveautés par rapport à
Classic : haches à une main pour le Voleur, armes d'hast pour le Druide, armes à deux mains de base pour le Chaman.
Certaines s'apprennent chez un maître d'armes (10 pa, armes d'hast 1 po au niveau 20) selon la race de départ.

Armures : règle de Classic, rien d'autre n'a été annoncé pour Forever : mailles au niveau 40 pour le Chasseur et le
Chaman, plaques au niveau 40 pour le Guerrier et le Paladin ; boucliers pour Guerrier, Paladin et Chaman ; reliques
(libram, idole, totem) pour Paladin, Druide et Chaman.

Les objets sont reconnus par leur sous-type Blizzard (identifiant), sinon par son nom français.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

ARMOR_CLASS = 4
WEAPON_CLASS = 2

# Sous-types d'armure (classe d'objet 4).
MISC, CLOTH, LEATHER, MAIL, PLATE, SHIELD, LIBRAM, IDOL, TOTEM = 0, 1, 2, 3, 4, 6, 7, 8, 9
# Sous-types d'arme (classe d'objet 2).
AXE_1H, AXE_2H, BOW, GUN, MACE_1H, MACE_2H, POLEARM, SWORD_1H, SWORD_2H = 0, 1, 2, 3, 4, 5, 6, 7, 8
STAFF, FIST, WEAPON_MISC, DAGGER, THROWN, CROSSBOW, WAND, FISHING_POLE = 10, 13, 14, 15, 16, 18, 19, 20

ARMOR_LABELS = {
    MISC: "Divers", CLOTH: "Tissu", LEATHER: "Cuir", MAIL: "Mailles", PLATE: "Plaques", SHIELD: "Bouclier",
    LIBRAM: "Libram", IDOL: "Idole", TOTEM: "Totem",
}
WEAPON_LABELS = {
    AXE_1H: "Hache à une main", AXE_2H: "Hache à deux mains", BOW: "Arc", GUN: "Arme à feu",
    MACE_1H: "Masse à une main", MACE_2H: "Masse à deux mains", POLEARM: "Arme d'hast",
    SWORD_1H: "Épée à une main", SWORD_2H: "Épée à deux mains", STAFF: "Bâton", FIST: "Arme de pugilat",
    WEAPON_MISC: "Divers", DAGGER: "Dague", THROWN: "Arme de jet", CROSSBOW: "Arbalète", WAND: "Baguette",
    FISHING_POLE: "Canne à pêche",
}

# Armures : sous-type → niveau à partir duquel la classe peut le porter.
_BASE = {MISC: 1, CLOTH: 1}
CLASS_ARMOR: dict[str, dict[int, int]] = {
    "guerrier": {**_BASE, LEATHER: 1, MAIL: 1, PLATE: 40, SHIELD: 1},
    "paladin": {**_BASE, LEATHER: 1, MAIL: 1, PLATE: 40, SHIELD: 1, LIBRAM: 1},
    "chasseur": {**_BASE, LEATHER: 1, MAIL: 40},
    "chaman": {**_BASE, LEATHER: 1, MAIL: 40, SHIELD: 1, TOTEM: 1},
    "voleur": {**_BASE, LEATHER: 1},
    "druide": {**_BASE, LEATHER: 1, IDOL: 1},
    "mage": dict(_BASE),
    "pretre": dict(_BASE),
    "demoniste": dict(_BASE),
}

_ALWAYS = {WEAPON_MISC, FISHING_POLE}
CLASS_WEAPONS: dict[str, frozenset[int]] = {
    "guerrier": frozenset(_ALWAYS | {BOW, CROSSBOW, DAGGER, FIST, GUN, AXE_1H, MACE_1H, SWORD_1H, POLEARM, STAFF,
                                     THROWN, AXE_2H, MACE_2H, SWORD_2H}),
    "paladin": frozenset(_ALWAYS | {AXE_1H, MACE_1H, SWORD_1H, POLEARM, AXE_2H, MACE_2H, SWORD_2H}),
    "chasseur": frozenset(_ALWAYS | {BOW, CROSSBOW, DAGGER, FIST, GUN, AXE_1H, SWORD_1H, POLEARM, STAFF, THROWN,
                                     AXE_2H, SWORD_2H}),
    "voleur": frozenset(_ALWAYS | {BOW, CROSSBOW, DAGGER, FIST, GUN, AXE_1H, MACE_1H, SWORD_1H, THROWN}),
    "pretre": frozenset(_ALWAYS | {DAGGER, MACE_1H, STAFF, WAND}),
    "chaman": frozenset(_ALWAYS | {DAGGER, FIST, AXE_1H, MACE_1H, STAFF, AXE_2H, MACE_2H}),
    "mage": frozenset(_ALWAYS | {DAGGER, SWORD_1H, STAFF, WAND}),
    "demoniste": frozenset(_ALWAYS | {DAGGER, SWORD_1H, STAFF, WAND}),
    "druide": frozenset(_ALWAYS | {DAGGER, FIST, MACE_1H, POLEARM, STAFF, MACE_2H}),
}

# Noms français des sous-types (objets lus avant que le site garde leur identifiant), au singulier sans accents.
_ARMOR_NAMES = {
    "divers": MISC, "tissu": CLOTH, "cuir": LEATHER, "maille": MAIL, "plaque": PLATE, "bouclier": SHIELD,
    "libram": LIBRAM, "idole": IDOL, "totem": TOTEM,
}
_WEAPON_NAMES = {
    "hache a une main": AXE_1H, "hache a deux mains": AXE_2H, "arc": BOW, "arme a feu": GUN,
    "masse a une main": MACE_1H, "masse a deux mains": MACE_2H, "arme d'hast": POLEARM,
    "epee a une main": SWORD_1H, "epee a deux mains": SWORD_2H, "baton": STAFF, "arme de pugilat": FIST,
    "divers": WEAPON_MISC, "dague": DAGGER, "arme de jet": THROWN, "arbalete": CROSSBOW, "baguette": WAND,
    "canne a peche": FISHING_POLE,
}


def _singular(name: str) -> str:
    """« Haches à une main » → « hache a une main », « Armes d'hast » → « arme d'hast »."""
    text = unicodedata.normalize("NFD", name.lower().replace("’", "'"))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn").strip()
    return " ".join(re.sub(r"(?<=[a-z])s$", "", word) for word in text.split())


_ARMOR_BY_NAME = {_singular(k): v for k, v in _ARMOR_NAMES.items()}
_WEAPON_BY_NAME = {_singular(k): v for k, v in _WEAPON_NAMES.items()}


def item_kind(item: dict[str, Any] | None) -> tuple[int, int] | None:
    """(classe d'objet, sous-type) d'une arme ou d'une armure (voir armory.parse_item), sinon None."""
    if not item or item.get("class") not in (ARMOR_CLASS, WEAPON_CLASS) or item.get("slot") in (None, "NON_EQUIP"):
        return None
    subclass = item.get("subclass")
    if not isinstance(subclass, int):
        names = _ARMOR_BY_NAME if item["class"] == ARMOR_CLASS else _WEAPON_BY_NAME
        subclass = names.get(_singular(item.get("subclass_name") or ""))
        if subclass is None:
            return None
    return item["class"], subclass


def kind_label(kind: tuple[int, int]) -> str:
    labels = ARMOR_LABELS if kind[0] == ARMOR_CLASS else WEAPON_LABELS
    return labels.get(kind[1], "?")


def usable_from(wow_class: str, item: dict[str, Any] | None) -> int | None:
    """Niveau à partir duquel la classe peut porter l'objet (proficiency et niveau requis), None si jamais."""
    kind = item_kind(item)
    if kind is None:
        return None
    item_class, subclass = kind
    if item_class == ARMOR_CLASS:
        level = CLASS_ARMOR.get(wow_class, {}).get(subclass)
        if level is None:
            return None
    elif subclass in CLASS_WEAPONS.get(wow_class, frozenset()):
        level = 1
    else:
        return None
    required = (item or {}).get("req_level")
    return max(level, required) if isinstance(required, int) else level


# Emplacement d'objet (inventory_type de Blizzard) → emplacements du perso (voir gear.parse_equipment).
EQUIP_SLOTS: dict[str, tuple[str, ...]] = {
    "HEAD": ("HEAD",), "NECK": ("NECK",), "SHOULDER": ("SHOULDER",), "CLOAK": ("BACK",), "CHEST": ("CHEST",),
    "ROBE": ("CHEST",), "BODY": ("SHIRT",), "TABARD": ("TABARD",), "WRIST": ("WRIST",), "HAND": ("HANDS",),
    "WAIST": ("WAIST",), "LEGS": ("LEGS",), "FEET": ("FEET",), "FINGER": ("FINGER_1", "FINGER_2"),
    "TRINKET": ("TRINKET_1", "TRINKET_2"), "WEAPON": ("MAIN_HAND", "OFF_HAND"), "TWOHWEAPON": ("MAIN_HAND",),
    "WEAPONMAINHAND": ("MAIN_HAND",), "WEAPONOFFHAND": ("OFF_HAND",), "SHIELD": ("OFF_HAND",),
    "HOLDABLE": ("OFF_HAND",), "RANGED": ("RANGED",), "RANGEDRIGHT": ("RANGED",), "THROWN": ("RANGED",),
    "RELIC": ("RANGED",),
}
# Groupe d'emplacements (premier emplacement de EQUIP_SLOTS) → emplacements du perso à comparer.
EQUIP_SLOTS_OF_GROUP: dict[str, tuple[str, ...]] = {
    "FINGER_1": ("FINGER_1", "FINGER_2"), "TRINKET_1": ("TRINKET_1", "TRINKET_2"),
}
# Ordre d'affichage, comme la fiche du jeu.
SLOT_ORDER = (
    "HEAD", "NECK", "SHOULDER", "BACK", "CHEST", "SHIRT", "TABARD", "WRIST", "HANDS", "WAIST", "LEGS", "FEET",
    "FINGER_1", "FINGER_2", "TRINKET_1", "TRINKET_2", "MAIN_HAND", "OFF_HAND", "RANGED",
)
