from __future__ import annotations

import discord

from .db import Event, Signup
from .roles import LABELS, ROLES, RoleEmojis

COLORS = {"dungeon": 0x3498DB, "raid": 0xE67E22, "custom": 0x9B59B6}
CANCELLED_COLOR = 0x7F8C8D
# Au-delà, on n'affiche plus les places vides (raid 40 = trop long).
MAX_EMPTY_SLOTS_SHOWN = 6


def player_name(signup: Signup) -> str:
    """Pseudo en texte : contrairement aux mentions, il s'affiche partout (mobile compris)."""
    if signup.display_name:
        return discord.utils.escape_mentions(discord.utils.escape_markdown(signup.display_name[:32]))
    return f"<@{signup.user_id}>"


def kind_label(event: Event) -> str:
    if event.kind == "raid":
        return f"🏰 Raid · {event.size} joueurs"
    if event.kind == "dungeon":
        lvl = f" · niv. {event.levels}" if event.levels else ""
        return f"🗝️ Donjon · {event.size} joueurs{lvl}"
    return f"👥 {event.size} joueurs"


def build_event_embed(event: Event, signups: list[Signup], emojis: RoleEmojis) -> discord.Embed:
    title = f"❌ ANNULÉ — {event.instance}" if event.cancelled else event.instance
    color = CANCELLED_COLOR if event.cancelled else COLORS.get(event.kind, COLORS["custom"])

    lines = [
        f"📅 <t:{event.starts_at}:F> (<t:{event.starts_at}:R>)",
        kind_label(event),
        f"👑 Organisé par <@{event.creator_id}>",
    ]
    if event.description:
        lines.append("")
        lines.append(f">>> {event.description}")
    embed = discord.Embed(title=title, description="\n".join(lines), color=color)

    for role in ROLES:
        cap = event.caps[role]
        if cap <= 0:
            continue
        members = [s for s in signups if s.role == role]
        entries = [f"`{i}.` {player_name(s)}" for i, s in enumerate(members, 1)]
        empty = cap - len(members)
        if 0 < empty <= MAX_EMPTY_SLOTS_SHOWN:
            entries += [f"`{i}.` —" for i in range(len(members) + 1, cap + 1)]
        elif empty > 0 and not members:
            entries.append("*Personne pour l'instant*")
        status = " · COMPLET" if empty <= 0 else ""
        embed.add_field(
            name=f"{emojis.display(role)} {LABELS[role]} ({len(members)}/{cap}){status}",
            value=("\n".join(entries) or "—")[:1024],  # limite Discord par champ
            inline=True,
        )

    total = len(signups)
    if event.cancelled:
        embed.set_footer(text="Cette sortie a été annulée.")
    else:
        how = " / ".join(f"{emojis.display(r)} {LABELS[r]}" for r in ROLES if event.caps[r] > 0)
        embed.add_field(
            name=f"Inscrits : {total}/{event.size}",
            value=f"Réagis avec {how} pour t'inscrire.\nRetire ta réaction pour te désinscrire.",
            inline=False,
        )
        embed.set_footer(text="Un seul rôle par joueur · les rôles complets sont verrouillés")
    return embed
