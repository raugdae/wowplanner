"""Rôles (Tank / Heal / DPS), compositions par défaut et correspondance des émotes."""
from __future__ import annotations

from typing import Union

import discord

ROLES: tuple[str, ...] = ("tank", "heal", "dps")
LABELS: dict[str, str] = {"tank": "Tank", "heal": "Heal", "dps": "DPS"}

# Compositions classiques selon la taille du groupe (tank, heal, dps).
_PRESETS: dict[int, tuple[int, int, int]] = {
    5: (1, 1, 3),
    10: (2, 3, 5),
    20: (3, 5, 12),
    25: (3, 6, 16),
    40: (4, 10, 26),
}


def default_composition(size: int) -> dict[str, int]:
    if size in _PRESETS:
        tank, heal, dps = _PRESETS[size]
    else:
        tank = min(size, max(1, round(size * 0.1)))
        heal = min(size - tank, max(1, round(size * 0.25)))
        dps = size - tank - heal
    return {"tank": tank, "heal": heal, "dps": dps}


def resolve_composition(
    players: int | None,
    default_size: int | None,
    tanks: int | None,
    heals: int | None,
    dps: int | None,
) -> dict[str, int]:
    """Calcule le nombre de places par rôle.

    - Si les trois rôles sont donnés, ils font foi (et doivent correspondre à `players` s'il est donné).
    - Sinon on part de la composition par défaut pour `players` (ou la taille de l'instance)
      et le premier rôle non précisé (DPS, puis Heal, puis Tank) complète le groupe.
    """
    given = {"tank": tanks, "heal": heals, "dps": dps}

    if all(v is not None for v in given.values()):
        total = sum(given.values())  # type: ignore[arg-type]
        if total == 0:
            raise ValueError("Il faut au moins une place dans le groupe.")
        if players is not None and players != total:
            raise ValueError(
                f"Incohérence : {tanks} tank(s) + {heals} heal(s) + {dps} DPS = {total}, "
                f"mais {players} joueurs demandés."
            )
        return given  # type: ignore[return-value]

    size = players if players is not None else default_size
    if size is None:
        raise ValueError(
            "Instance inconnue : précise le nombre de `joueurs` (ou les trois rôles tanks/heals/dps)."
        )

    comp = default_composition(size)
    for role, value in given.items():
        if value is not None:
            comp[role] = value

    filler = next(r for r in ("dps", "heal", "tank") if given[r] is None)
    comp[filler] = size - sum(comp[r] for r in ROLES if r != filler)
    if comp[filler] < 0:
        raise ValueError(
            f"Trop de places réservées : impossible de caser tout ça dans un groupe de {size} joueurs."
        )
    return comp


AnyEmoji = Union[discord.PartialEmoji, discord.Emoji, str]


def _norm(name: str | None) -> str:
    # Les émotes unicode arrivent parfois avec ou sans le sélecteur de variante U+FE0F.
    return (name or "").replace("️", "")


def to_partial(emoji: AnyEmoji) -> discord.PartialEmoji:
    if isinstance(emoji, discord.PartialEmoji):
        return emoji
    if isinstance(emoji, str):
        return discord.PartialEmoji.from_str(emoji)
    return discord.PartialEmoji(name=emoji.name, id=emoji.id, animated=emoji.animated)


class RoleEmojis:
    """Associe chaque rôle à son émote (unicode ou émote personnalisée `<:nom:id>`)."""

    def __init__(self, mapping: dict[str, str]):
        self._emojis = {role: discord.PartialEmoji.from_str(mapping[role]) for role in ROLES}

    def __getitem__(self, role: str) -> discord.PartialEmoji:
        return self._emojis[role]

    def display(self, role: str) -> str:
        return str(self._emojis[role])

    def role_for(self, emoji: AnyEmoji) -> str | None:
        emoji = to_partial(emoji)
        for role, expected in self._emojis.items():
            if expected.id is not None:
                if emoji.id == expected.id:
                    return role
            elif emoji.id is None and _norm(emoji.name) == _norm(expected.name):
                return role
        return None
