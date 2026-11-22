"""Addon WoW « WowPlanner » et son client local (dossiers addon/ et client/ du dépôt).

Le jeu ne laisse aucun addon parler au réseau : le client local fait le lien.
- site → jeu : il télécharge les prix de l'HdV (/api/addon/prix) et les écrit dans Interface/AddOns/WowPlanner/
  Data.lua, lu par l'addon à la connexion ou au /reload ;
- jeu → site : il lit ce que l'addon a enregistré (WTF/…/SavedVariables/WowPlanner.lua : sacs, banque, argent,
  métiers, recettes) et l'envoie à /api/addon/inventaire.

Le client s'identifie par un jeton personnel créé sur la page « Addon WoW » du site (seule son empreinte est gardée).
Ce module : jetons et lecture des données envoyées par le client (sans base ni réseau, testable seul).
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any

from .gamedata import PROFESSIONS
from .recipes import normalize

TOKEN_PREFIX = "wp_"
# Garde-fous sur ce qu'un client peut envoyer.
MAX_CHARACTERS = 60
MAX_ITEMS = 3000
MAX_RECIPES = 1500
MAX_COUNT = 10_000_000

# Noms des métiers dans les clients anglais (les noms français sont ceux de PROFESSIONS).
_ENGLISH = {
    "alchemy": "alchimie", "blacksmithing": "forge", "enchanting": "enchantement", "engineering": "ingenierie",
    "herbalism": "herboristerie", "leatherworking": "travail_cuir", "mining": "minage", "skinning": "depecage",
    "tailoring": "couture", "cooking": "cuisine", "first aid": "secourisme", "fishing": "peche",
}
_BY_NAME = {normalize(label): key for key, (label, _) in PROFESSIONS.items()} | _ENGLISH


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode()).hexdigest()


def profession_key(name: str) -> str | None:
    """« Dépeçage », « depecage » ou « Skinning » → « depecage » ; None pour les autres compétences (armes…)."""
    return _BY_NAME.get(normalize(name or "").strip())


class PayloadError(ValueError):
    """Données du client illisibles (message pour le client)."""


@dataclass
class GameRecipe:
    item: int | None  # objet fabriqué
    spell: int | None  # sort (enchantements : pas d'objet)
    name: str


@dataclass
class GameCharacter:
    name: str
    level: int | None = None
    money: int | None = None
    updated_at: int = 0
    bags: dict[int, int] = field(default_factory=dict)
    bank: dict[int, int] | None = None  # None : banque jamais ouverte avec l'addon
    bank_at: int | None = None
    professions: dict[str, int | None] | None = None  # clé de PROFESSIONS -> niveau ; None : pas relevés
    recipes: dict[str, list[GameRecipe]] | None = None  # clé de PROFESSIONS -> recettes ; None : jamais vues


def _int(value: Any, low: int = 0, high: int = MAX_COUNT) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = int(value)
    return value if low <= value <= high else None


def _counts(raw: Any) -> dict[int, int]:
    if not isinstance(raw, dict):
        return {}
    if len(raw) > MAX_ITEMS:
        raise PayloadError("Trop d'objets pour un même perso.")
    out: dict[int, int] = {}
    for key, value in raw.items():
        item, count = _int(int(key) if str(key).isdigit() else None, 1, 10_000_000), _int(value, 1)
        if item and count:
            out[item] = count
    return out


def parse_inventory(payload: Any) -> list[GameCharacter]:
    """Persos envoyés par le client : {"characters": [{"name", "level", "money", "updated_at", "bags": {id: n},
    "bank": {id: n} | null, "bank_at", "professions": {nom: niveau} | null, "recipes": {nom du métier:
    [{"item", "spell", "name"}]} | null}]}. Ce qui est mal formé est ignoré, le reste est gardé."""
    if not isinstance(payload, dict) or not isinstance(payload.get("characters"), list):
        raise PayloadError("Format inattendu : il manque la liste des persos.")
    entries = payload["characters"]
    if len(entries) > MAX_CHARACTERS:
        raise PayloadError("Trop de persos d'un coup.")
    found: list[GameCharacter] = []
    for raw in entries:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"].strip():
            continue
        c = GameCharacter(
            name=raw["name"].strip()[:40], level=_int(raw.get("level"), 1, 100), money=_int(raw.get("money"), 0, 10**12),
            updated_at=_int(raw.get("updated_at"), 0, 2**40) or 0, bags=_counts(raw.get("bags")),
        )
        if isinstance(raw.get("bank"), dict):
            c.bank, c.bank_at = _counts(raw["bank"]), _int(raw.get("bank_at"), 0, 2**40)
        if isinstance(raw.get("professions"), dict):
            c.professions = {}
            for name, skill in raw["professions"].items():
                key = profession_key(str(name))
                if key:
                    c.professions[key] = _int(skill, 1, 1000)
        if isinstance(raw.get("recipes"), dict):
            c.recipes, total = {}, 0
            for name, items in raw["recipes"].items():
                key = profession_key(str(name))
                if not key or not isinstance(items, list):
                    continue
                total += len(items)
                if total > MAX_RECIPES:
                    raise PayloadError("Trop de recettes pour un même perso.")
                c.recipes[key] = [
                    GameRecipe(_int(r.get("item"), 1, 10_000_000), _int(r.get("spell"), 1, 10_000_000),
                               str(r.get("name") or "")[:120])
                    for r in items if isinstance(r, dict)
                ]
        found.append(c)
    return found


def match_recipes(seen: list[GameRecipe], known: list[Any]) -> tuple[set[int], int]:
    """Recettes du site (lignes id, name, name_en, crafted_item_id d'un même métier) qui correspondent à celles vues
    en jeu : par objet fabriqué, sinon par nom (français ou anglais). Renvoie (ids reconnus, nombre non reconnues)."""
    by_item: dict[int, list[int]] = {}
    by_name: dict[str, int] = {}
    for r in known:
        if r["crafted_item_id"]:
            by_item.setdefault(r["crafted_item_id"], []).append(r["id"])
        for name in (r["name"], r["name_en"]):
            if name:
                by_name.setdefault(normalize(name), r["id"])
    ids: set[int] = set()
    missing = 0
    for g in seen:
        hits = by_item.get(g.item or 0)
        if not hits and g.name and normalize(g.name) in by_name:
            hits = [by_name[normalize(g.name)]]
        if hits:
            ids.update(hits)
        else:
            missing += 1
    return ids, missing
