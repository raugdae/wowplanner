from __future__ import annotations

import discord

from .db import Event, Signup
from .gamedata import class_label
from .roles import LABELS, ROLES, RoleEmojis

COLORS = {"dungeon": 0x3498DB, "raid": 0xE67E22, "custom": 0x9B59B6}
CANCELLED_COLOR = 0x7F8C8D
# Au-delà, on n'affiche plus les places vides (raid 40 = trop long).
MAX_EMPTY_SLOTS_SHOWN = 6


def _clean(text: str, limit: int = 32) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(text[:limit]))


def player_name(signup: Signup, with_pseudo: bool = True) -> str:
    """Perso joué (et pseudo Discord), en texte : contrairement aux mentions, ça s'affiche partout."""
    pseudo = _clean(signup.display_name) if signup.display_name else f"<@{signup.user_id}>"
    if not signup.character_name:
        return pseudo
    text = f"**{_clean(signup.character_name, 32)}** · {class_label(signup.character_class or '')}"
    return f"{text} ({pseudo})" if with_pseudo else text


def kind_label(event: Event) -> str:
    if event.kind == "raid":
        return f"🏰 Raid · {event.size} joueurs"
    if event.kind == "dungeon":
        lvl = f" · niv. {event.levels}" if event.levels else ""
        return f"🗝️ Donjon · {event.size} joueurs{lvl}"
    return f"👥 {event.size} joueurs"


def _role_field_value(members: list[Signup], cap: int) -> str:
    empty = cap - len(members)
    value = ""
    # Les gros raids dépassent la limite de 1024 caractères par champ : on retire alors les pseudos.
    for with_pseudo in (True, False):
        entries = [f"`{i}.` {player_name(s, with_pseudo)}" for i, s in enumerate(members, 1)]
        if 0 < empty <= MAX_EMPTY_SLOTS_SHOWN:
            entries += [f"`{i}.` —" for i in range(len(members) + 1, cap + 1)]
        elif empty > 0 and not members:
            entries.append("*Personne pour l'instant*")
        value = "\n".join(entries) or "—"
        if len(value) <= 1024:
            break
    return value[:1024]


def build_event_embed(event: Event, signups: list[Signup], emojis: RoleEmojis) -> discord.Embed:
    title = f"❌ ANNULÉ — {event.instance}" if event.cancelled else event.instance
    color = CANCELLED_COLOR if event.cancelled else COLORS.get(event.kind, COLORS["custom"])

    lines = [
        f"📅 <t:{event.starts_at}:F> (<t:{event.starts_at}:R>)",
        kind_label(event),
        f"👑 Organisé par <@{event.creator_id}>",
    ]
    if event.voice_channel_id and not event.cancelled:
        lines.append(f"🔊 Vocal : <#{event.voice_channel_id}>")
    if event.description:
        lines.append("")
        lines.append(f">>> {event.description}")
    embed = discord.Embed(title=title, description="\n".join(lines), color=color)

    for role in ROLES:
        cap = event.caps[role]
        if cap <= 0:
            continue
        members = [s for s in signups if s.role == role]
        status = " · COMPLET" if len(members) >= cap else ""
        embed.add_field(
            name=f"{emojis.display(role)} {LABELS[role]} ({len(members)}/{cap}){status}",
            value=_role_field_value(members, cap),
            inline=True,
        )

    total = len(signups)
    if event.cancelled:
        embed.set_footer(text="Cette sortie a été annulée.")
    else:
        embed.add_field(
            name=f"Inscrits : {total}/{event.size}",
            value="Clique sur ton rôle ci-dessous pour t'inscrire.\nDéclare tes persos avec `/ajouter perso`.",
            inline=False,
        )
        embed.set_footer(text="Un seul rôle par joueur · clique sur un autre rôle pour changer")
    return embed
