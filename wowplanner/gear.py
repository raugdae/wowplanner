"""Équipement, caractéristiques et priorité des stats d'un perso (sans Discord ni HTML).

Priorités de stats : guide « Stats and Attributes in WoW Forever » de stillsixty.com (mis à jour le
2 novembre 2026), le plus complet trouvé ; les autres guides divergent parfois sur l'ordre
toucher / critique. Caps de toucher contre un boss (niveau 63) : 16 % pour les sorts, 9 % en
mêlée et à distance.
"""
from __future__ import annotations

import re
from typing import Any

from .armory import parse_item
from .recipes import normalize

# Emplacements, dans l'ordre de la fiche du jeu.
LEFT_SLOTS = ("HEAD", "NECK", "SHOULDER", "BACK", "CHEST", "SHIRT", "TABARD", "WRIST")
RIGHT_SLOTS = ("HANDS", "WAIST", "LEGS", "FEET", "FINGER_1", "FINGER_2", "TRINKET_1", "TRINKET_2")
WEAPON_SLOTS = ("MAIN_HAND", "OFF_HAND", "RANGED")
SLOT_LABELS = {
    "HEAD": "Tête", "NECK": "Cou", "SHOULDER": "Épaules", "BACK": "Dos", "CHEST": "Torse", "SHIRT": "Chemise",
    "TABARD": "Tabard", "WRIST": "Poignets", "HANDS": "Mains", "WAIST": "Taille", "LEGS": "Jambes", "FEET": "Pieds",
    "FINGER_1": "Doigt", "FINGER_2": "Doigt", "TRINKET_1": "Bijou", "TRINKET_2": "Bijou",
    "MAIN_HAND": "Main droite", "OFF_HAND": "Main gauche", "RANGED": "À distance",
}

SPELL_HIT_CAP = 16.0
PHYSICAL_HIT_CAP = 9.0


def parse_equipment(data: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Objets portés, réduits à ce qu'affiche le site. None si l'équipement n'a pas pu être lu."""
    if data is None:
        return None
    items = []
    for item in data.get("equipped_items") or []:
        slot = (item.get("slot") or {}).get("type")
        if not slot:
            continue
        info = parse_item(item)
        lines = info["lines"]
        for enchant in item.get("enchantments") or []:
            text = enchant.get("display_string")
            if isinstance(text, str) and text.strip():
                lines.append(["enchant", text.strip()])
        set_name = ((item.get("set") or {}).get("display_string"))
        if isinstance(set_name, str) and set_name.strip():
            lines.append(["set", set_name.strip()])
        items.append({
            "slot": slot,
            "id": (item.get("item") or {}).get("id"),
            "name": item.get("name") or "?",
            "quality": (item.get("quality") or {}).get("type"),
            "ilvl": (item.get("level") or {}).get("value"),
            "two_hand": (item.get("inventory_type") or {}).get("type") == "TWOHWEAPON",
            "lines": lines,
        })
    return items


# Clés gardées depuis /statistics : valeur « effective » ou « value » selon la stat.
_STAT_KEYS = (
    "health", "power", "strength", "agility", "stamina", "intellect", "spirit", "armor", "attack_power",
    "ranged_attack_power", "spell_power", "spell_healing", "melee_crit", "spell_crit", "ranged_crit",
    "melee_hit", "spell_hit", "ranged_hit", "melee_haste", "spell_haste", "ranged_haste", "dodge", "parry",
    "block", "defense", "mana_regen", "mana_regen_combat", "expertise", "main_hand_dps",
)


def parse_stats(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    stats: dict[str, Any] = {}
    for key in _STAT_KEYS:
        value = data.get(key)
        if isinstance(value, dict):
            value = value.get("effective", value.get("value"))
        if isinstance(value, (int, float)):
            stats[key] = round(float(value), 2)
    stats["power_name"] = (data.get("power_type") or {}).get("name")
    return stats


# ------------------------------------------------------------------ priorités

# Jeton de priorité → (libellé, motif regex, sans accents, dans les infobulles d'objet).
TOKENS = {
    "hit": ("Toucher", "toucher"),
    "spell_power": ("Puissance des sorts", "puissance des sorts"),
    "healing": ("Puissance des soins", "soins"),
    "crit": ("Critique", "critique"),
    "intellect": ("Intelligence", "intelligence"),
    "spirit": ("Esprit", "esprit"),
    "stamina": ("Endurance", "endurance"),
    "strength": ("Force", "force"),
    "agility": ("Agilité", "agilite"),
    "haste": ("Hâte", "hate"),
    "attack_power": ("Puissance d'attaque", "puissance d.attaque"),
    "weapon_dps": ("DPS de l'arme", None),
    "weapon_skill": ("Compétence d'arme", "competence"),
    "expertise": ("Expertise", "expertise"),
    "mp5": ("Mana toutes les 5 s", "mana toutes les 5"),
    "defense": ("Défense", "defense"),
    "armor": ("Armure", "armure"),
    "avoidance": ("Esquive / parade / blocage", None),
    "block_value": ("Valeur de blocage", "valeur de blocage"),
}

# (nom affiché, type de toucher, priorités) ; type : spell, melee, ranged ou none (soigneurs, tanks).
PRIORITIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "balance": ("Équilibre", "spell", ("hit", "spell_power", "crit", "intellect", "haste", "spirit")),
    "feral_cat": ("Farouche (félin)", "melee", ("hit", "agility", "strength", "crit", "attack_power", "haste")),
    "feral_bear": ("Farouche (ours)", "none", ("stamina", "armor", "agility", "defense", "hit", "strength")),
    "resto_druid": ("Restauration", "none", ("healing", "spirit", "intellect", "crit", "haste", "stamina")),
    "holy_paladin": ("Sacré", "none", ("spell_power", "intellect", "crit", "mp5", "spirit", "stamina")),
    "prot_paladin": ("Protection", "none", (
        "stamina", "defense", "armor", "avoidance", "block_value", "hit", "spell_power", "intellect")),
    "ret": ("Vindicte", "melee", ("hit", "strength", "crit", "intellect", "spell_power", "agility", "stamina")),
    "assassination": ("Assassinat", "melee", ("hit", "agility", "crit", "attack_power", "expertise", "haste")),
    "combat": ("Combat", "melee", ("hit", "agility", "attack_power", "crit", "expertise", "haste")),
    "subtlety": ("Finesse", "melee", ("hit", "agility", "crit", "attack_power", "expertise")),
    "arcane": ("Arcane", "spell", ("hit", "intellect", "spell_power", "crit", "haste", "spirit")),
    "fire": ("Feu", "spell", ("hit", "spell_power", "crit", "intellect", "haste", "spirit")),
    "frost": ("Givre", "spell", ("hit", "spell_power", "crit", "intellect", "haste", "spirit")),
    "discipline": ("Discipline", "none", ("healing", "intellect", "crit", "spirit", "stamina")),
    "holy_priest": ("Sacré", "none", ("healing", "spirit", "intellect", "crit", "stamina")),
    "shadow": ("Ombre", "spell", ("hit", "spell_power", "crit", "intellect", "haste", "spirit")),
    "affliction": ("Affliction", "spell", ("hit", "spell_power", "crit", "stamina", "spirit", "intellect")),
    "demonology": ("Démonologie", "spell", ("hit", "spell_power", "crit", "stamina", "intellect")),
    "destruction": ("Destruction", "spell", ("hit", "spell_power", "crit", "intellect", "stamina")),
    "arms": ("Armes", "melee", ("weapon_dps", "hit", "strength", "crit", "agility", "weapon_skill")),
    "fury": ("Fureur (deux armes)", "melee", ("hit", "strength", "crit", "agility", "weapon_skill")),
    "fury_2h": ("Fureur (arme à deux mains)", "melee", ("weapon_dps", "hit", "strength", "crit", "agility")),
    "prot_warrior": ("Protection", "none", ("stamina", "defense", "armor", "avoidance", "block_value", "hit")),
    "beast_mastery": ("Maîtrise des bêtes", "ranged", ("hit", "agility", "crit", "attack_power", "intellect", "stamina")),
    "marksmanship": ("Précision", "ranged", ("hit", "agility", "crit", "intellect", "attack_power", "stamina")),
    "survival": ("Survie", "ranged", ("hit", "agility", "crit", "attack_power", "expertise", "intellect", "stamina")),
    "elemental": ("Élémentaire", "spell", ("hit", "spell_power", "crit", "intellect", "haste", "spirit")),
    "enhancement": ("Amélioration", "melee", ("hit", "strength", "crit", "intellect", "agility", "haste")),
    "enhancement_tank": ("Amélioration (tank)", "none", ("stamina", "armor", "hit", "strength", "agility", "intellect")),
    "resto_shaman": ("Restauration", "none", ("healing", "intellect", "crit", "mp5", "spirit", "haste")),
}

# Spés de Forever (identifiants Blizzard) → clé de PRIORITIES.
SPEC_IDS = {
    574: "balance", 134: "feral_cat", 573: "resto_druid",
    594: "holy_paladin", 267: "prot_paladin", 184: "ret",
    253: "assassination", 38: "combat", 39: "subtlety",
    237: "arcane", 8: "fire", 6: "frost",
    613: "discipline", 56: "holy_priest", 78: "shadow",
    355: "affliction", 354: "demonology", 593: "destruction",
    26: "arms", 256: "fury", 257: "prot_warrior",
    50: "beast_mastery", 163: "marksmanship", 51: "survival",
    375: "elemental", 373: "enhancement", 374: "resto_shaman",
}


def detect_spec(talents: list | None, preferred_role: str | None, equipment: list | None) -> str | None:
    """Spé principale : l'arbre le plus investi du groupe de talents actif, affinée par le rôle préféré
    (farouche ours / félin, amélioration tank) et l'arme (fureur à deux mains)."""
    groups = [g for g in talents or [] if g.get("active")] or list(talents or [])
    specs = [s for g in groups[:1] for s in g.get("specs", []) if s.get("points")]
    if not specs:
        return None
    key = SPEC_IDS.get(max(specs, key=lambda s: s["points"]).get("spec_id"))
    if key == "feral_cat" and preferred_role == "tank":
        return "feral_bear"
    if key == "enhancement" and preferred_role == "tank":
        return "enhancement_tank"
    if key == "fury" and any(i["slot"] == "MAIN_HAND" and i.get("two_hand") for i in equipment or []):
        return "fury_2h"
    return key


def hit_cap(kind: str) -> float | None:
    return {"spell": SPELL_HIT_CAP, "melee": PHYSICAL_HIT_CAP, "ranged": PHYSICAL_HIT_CAP}.get(kind)


def stat_keys(token: str, kind: str) -> tuple[str, ...]:
    """Lignes du panneau de caractéristiques qui correspondent à un jeton de priorité."""
    prefix = {"spell": "spell", "ranged": "ranged"}.get(kind, "melee")
    return {
        "hit": (f"{prefix}_hit",),
        "crit": (f"{prefix}_crit",),
        "haste": (f"{prefix}_haste",),
        "spell_power": ("spell_power",),
        "healing": ("spell_healing",),
        "attack_power": ("ranged_attack_power",) if kind == "ranged" else ("attack_power",),
        "weapon_dps": ("main_hand_dps",),
        "mp5": ("mana_regen_combat",),
        "avoidance": ("dodge", "parry", "block"),
    }.get(token, (token,))


def priority_ranks(spec: str | None) -> dict[str, int]:
    """{clé de stat du panneau : rang de priorité (1 = la plus importante)}."""
    if spec not in PRIORITIES:
        return {}
    _, kind, tokens = PRIORITIES[spec]
    ranks: dict[str, int] = {}
    for i, token in enumerate(tokens, 1):
        for key in stat_keys(token, kind):
            ranks.setdefault(key, i)
    return ranks


def stat_matcher(spec: str | None, top: int = 3) -> re.Pattern | None:
    """Repère, dans une ligne d'infobulle d'objet, les stats les plus prioritaires de la spé."""
    if spec not in PRIORITIES:
        return None
    words = [TOKENS[t][1] for t in PRIORITIES[spec][2][:top] if TOKENS[t][1]]
    return re.compile(r"\b(" + "|".join(words) + r")\b") if words else None


def line_has_priority(line: str, matcher: re.Pattern | None) -> bool:
    return bool(matcher and matcher.search(normalize(line)))
