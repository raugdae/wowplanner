"""Atelier : commandes d'objets entre persos, sans commande à taper.

- Panneau épinglé (/admin atelier) avec deux boutons : 🛒 Commander, 📦 Mes commandes.
- 🛒 ouvre une petite fenêtre (objet, quantité, note) ; le bot trouve la recette et l'artisan,
  montre un récap avec les composants, puis envoie la commande en MP à l'artisan.
- L'artisan accepte ou refuse, puis indique « C'est prêt » ; le client est prévenu en MP.
- Raccourci : /commander objet:… (avec autocomplétion).

Sécurité : Discord dit qui clique. Seul le propriétaire du perso artisan agit en artisan, seul
le client peut annuler. Les boutons des MP marchent encore après un redémarrage (DynamicItem).
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..db import Crafter, Order
from ..gamedata import class_label
from ..orders import (
    MAX_QUANTITY,
    STATUS_COLORS,
    STATUS_LABELS,
    TRANSITIONS,
    Candidate,
    allowed_actions,
    orderable,
    parse_quantity,
    scaled_reagents,
    search,
)
from ..recipes import crafted_by_map, normalize

if TYPE_CHECKING:
    from ..bot import WowPlannerBot
    from .armory import ArmoryCog

log = logging.getLogger(__name__)

PANEL_ORDER_ID = "wowplanner:order:new"
PANEL_MINE_ID = "wowplanner:order:mine"
MAX_CHOICES = 25

NOTIFY_REQUESTER = {
    "accept": "👍 **{crafter}** a accepté ta commande. Tu recevras un MP quand elle sera prête.",
    "refuse": "❌ **{crafter}** ne peut pas faire ta commande.",
    "drop": "❌ **{crafter}** a dû abandonner ta commande.",
    "done": "✅ Ta commande est prête ! Vois avec **{crafter}** en jeu pour la récupérer (courrier ou échange).",
}
NOTIFY_CRAFTER = {"cancel": "🚫 **{requester}** a annulé sa commande."}


# ===================================================================== affichage


def order_embed(order: Order) -> discord.Embed:
    number = f" #{order.id}" if order.id else ""
    embed = discord.Embed(
        title=f"🛠️ Commande{number} · {order.quantity}× {order.recipe_name}"[:256],
        description=f"💬 « {order.note} »" if order.note else None,
        color=STATUS_COLORS.get(order.status, 0x99AAB5),
    )
    embed.add_field(name="Client", value=f"{order.requester_name}\n<@{order.requester_id}>", inline=True)
    embed.add_field(name="Artisan", value=f"{order.crafter_name}\n<@{order.crafter_user_id}>", inline=True)
    if order.id:
        embed.add_field(name="Statut", value=STATUS_LABELS.get(order.status, order.status), inline=True)
    embed.add_field(name="Composants", value=order.reagents_text or "—", inline=False)
    embed.set_footer(text="Composants et livraison se règlent entre vous en jeu (courrier, échange).")
    return embed


class OrderActionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"wowplanner:order:(?P<action>[a-z]+):(?P<id>\d+)",
):
    """Bouton d'action sur une commande (Accepter, C'est prêt, Annuler…), valable même après redémarrage."""

    def __init__(self, action: str, order_id: int):
        t = TRANSITIONS[action]
        style = {
            "accept": discord.ButtonStyle.success, "done": discord.ButtonStyle.success,
        }.get(action, discord.ButtonStyle.secondary if action != "cancel" else discord.ButtonStyle.danger)
        super().__init__(
            discord.ui.Button(
                label=t.label, emoji=t.emoji, style=style, custom_id=f"wowplanner:order:{action}:{order_id}"
            )
        )
        self.action = action
        self.order_id = order_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        action = match["action"]
        if action not in TRANSITIONS:
            raise ValueError(action)
        return cls(action, int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: OrdersCog = interaction.client.get_cog("OrdersCog")  # type: ignore[union-attr]
        await cog.handle_action(interaction, self.action, self.order_id)


def order_view(order: Order, viewer_id: int, extra: discord.ui.Item | None = None) -> discord.ui.View | None:
    actions = allowed_actions(order, viewer_id)
    if not actions and extra is None:
        return None
    view = discord.ui.View(timeout=None if extra is None else 600)
    for action in actions:
        view.add_item(OrderActionButton(action, order.id))
    if extra is not None:
        view.add_item(extra)
    return view


# ===================================================================== panneau


class AtelierPanel(discord.ui.View):
    """Message épinglé : boutons fixes, persistants."""

    def __init__(self, cog: OrdersCog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Commander", emoji="🛒", style=discord.ButtonStyle.primary, custom_id=PANEL_ORDER_ID)
    async def order(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(OrderModal(self.cog))

    @discord.ui.button(label="Mes commandes", emoji="📦", style=discord.ButtonStyle.secondary, custom_id=PANEL_MINE_ID)
    async def mine(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.show_mine(interaction)


def panel_embed() -> discord.Embed:
    return discord.Embed(
        title="🛠️ Atelier — besoin d'un objet fabriqué ?",
        description=(
            "**🛒 Commander** : tape le nom de l'objet (un bout suffit, ex. *mangouste*), le bot trouve "
            "qui sait le faire et lui envoie ta commande en MP.\n"
            "**📦 Mes commandes** : suivre, annuler, ou gérer celles qu'on t'a passées.\n\n"
            "Seules les recettes débloquées par les persos du serveur (vues dans l'armurerie) sont proposées. "
            "Tu reçois un MP quand l'artisan accepte, puis quand c'est prêt."
        ),
        color=0xF2C75C,
    )


class OrderModal(discord.ui.Modal, title="🛒 Commander un objet"):
    objet = discord.ui.TextInput(label="Quel objet ?", placeholder="ex. : mangouste, sac en lin…", min_length=2, max_length=80)
    quantite = discord.ui.TextInput(label="Combien ?", default="1", required=False, max_length=4)
    note = discord.ui.TextInput(
        label="Un mot pour l'artisan (facultatif)",
        style=discord.TextStyle.paragraph,
        placeholder="J'ai les composants, je te les envoie par courrier…",
        required=False,
        max_length=300,
    )

    def __init__(self, cog: OrdersCog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        quantity = parse_quantity(self.quantite.value)
        if quantity is None:
            await interaction.response.send_message(
                f"La quantité doit être un nombre entre 1 et {MAX_QUANTITY}.", ephemeral=True
            )
            return
        await self.cog.start(interaction, self.objet.value, quantity, self.note.value.strip() or None)


# ===================================================================== brouillon


class OrderDraft(discord.ui.View):
    """Réponse privée : choix de l'objet, puis de l'artisan, puis récap et envoi."""

    def __init__(self, cog: OrdersCog, interaction: discord.Interaction, candidates: list[Candidate], quantity: int, note: str | None):
        super().__init__(timeout=900)
        self.cog = cog
        self.user = interaction.user
        self.guild_id = interaction.guild_id or 0
        self.candidates = candidates
        self.quantity = quantity
        self.note = note
        self.candidate: Candidate | None = candidates[0] if len(candidates) == 1 else None
        self.crafter: Crafter | None = None
        if self.candidate and len(self.candidate.crafters) == 1:
            self.crafter = self.candidate.crafters[0]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user.id

    def draft_order(self) -> Order:
        assert self.candidate and self.crafter
        recipe = self.candidate.recipe
        return Order(
            guild_id=self.guild_id,
            requester_id=self.user.id,
            requester_name=getattr(self.user, "display_name", None) or self.user.name,
            recipe_id=recipe.id,
            recipe_name=recipe.name,
            quantity=self.quantity,
            crafter_character_id=self.crafter.character_id,
            crafter_name=self.crafter.name,
            crafter_user_id=self.crafter.user_id,
            reagents_text=scaled_reagents(recipe, self.quantity, self.cog.crafted_by(self.guild_id)),
            note=self.note,
        )

    def render(self) -> dict:
        self.clear_items()
        if self.candidate is None:
            shown = self.candidates[:MAX_CHOICES]
            select = discord.ui.Select(
                placeholder="Quel objet exactement ?",
                options=[
                    discord.SelectOption(
                        label=c.recipe.name[:100],
                        value=str(c.recipe.id),
                        description=", ".join(x.name for x in c.crafters)[:100],
                    )
                    for c in shown
                ],
            )
            select.callback = self._picked_recipe
            self.add_item(select)
            self._add_abort()
            more = len(self.candidates) - len(shown)
            text = f"🔎 {len(self.candidates)} objets correspondent, lequel veux-tu ?"
            if more > 0:
                text += f"\n(Seuls les {MAX_CHOICES} premiers sont listés : précise ta recherche si le tien n'y est pas.)"
            return {"content": text, "embed": None, "view": self}

        if self.crafter is None:
            select = discord.ui.Select(
                placeholder="Qui doit le fabriquer ?",
                options=[
                    discord.SelectOption(label=c.name[:100], value=str(c.character_id), description=class_label(c.wow_class))
                    for c in self.candidate.crafters[:MAX_CHOICES]
                ],
            )
            select.callback = self._picked_crafter
            self.add_item(select)
            self._add_back_to_recipes()
            self._add_abort()
            return {
                "content": f"**{self.candidate.recipe.name}** : plusieurs persos savent le faire, choisis l'artisan.",
                "embed": None,
                "view": self,
            }

        send = discord.ui.Button(label="Envoyer la commande", emoji="📨", style=discord.ButtonStyle.success)
        send.callback = self._send
        self.add_item(send)
        if len(self.candidate.crafters) > 1:
            other = discord.ui.Button(label="Autre artisan", style=discord.ButtonStyle.secondary)
            other.callback = self._change_crafter
            self.add_item(other)
        self._add_back_to_recipes()
        self._add_abort()
        return {"content": "Vérifie et envoie :", "embed": order_embed(self.draft_order()), "view": self}

    def _add_back_to_recipes(self) -> None:
        if len(self.candidates) > 1:
            back = discord.ui.Button(label="Autre objet", style=discord.ButtonStyle.secondary)
            back.callback = self._change_recipe
            self.add_item(back)

    def _add_abort(self) -> None:
        abort = discord.ui.Button(label="Laisser tomber", style=discord.ButtonStyle.secondary)
        abort.callback = self._abort
        self.add_item(abort)

    async def _picked_recipe(self, interaction: discord.Interaction) -> None:
        value = int(interaction.data["values"][0])  # type: ignore[index]
        self.candidate = next(c for c in self.candidates if c.recipe.id == value)
        self.crafter = self.candidate.crafters[0] if len(self.candidate.crafters) == 1 else None
        await interaction.response.edit_message(**self.render())

    async def _picked_crafter(self, interaction: discord.Interaction) -> None:
        assert self.candidate
        value = int(interaction.data["values"][0])  # type: ignore[index]
        self.crafter = next(c for c in self.candidate.crafters if c.character_id == value)
        await interaction.response.edit_message(**self.render())

    async def _change_crafter(self, interaction: discord.Interaction) -> None:
        self.crafter = None
        await interaction.response.edit_message(**self.render())

    async def _change_recipe(self, interaction: discord.Interaction) -> None:
        self.candidate = self.crafter = None
        await interaction.response.edit_message(**self.render())

    async def _abort(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.edit_message(content="OK, pas de commande.", embed=None, view=None)

    async def _send(self, interaction: discord.Interaction) -> None:
        self.stop()
        order = self.cog.db.create_order(self.draft_order())
        delivered = await self.cog.notify_new(order)
        text = f"📨 Commande **#{order.id}** envoyée à **{order.crafter_name}**. Tu recevras un MP dès sa réponse."
        if not delivered:
            text = (
                f"📨 Commande **#{order.id}** enregistrée, mais **{order.crafter_name}** n'accepte pas les MP du bot : "
                "préviens l'artisan : la commande est aussi dans ses 📦 Mes commandes."
            )
        await interaction.response.edit_message(content=text, embed=order_embed(order), view=order_view(order, self.user.id))


# ===================================================================== cog


class OrdersCog(commands.Cog):
    def __init__(self, bot: WowPlannerBot):
        self.bot = bot
        self.db = bot.db

    async def cog_load(self) -> None:
        self.bot.add_view(AtelierPanel(self))
        self.bot.add_dynamic_items(OrderActionButton)

    @property
    def armory(self) -> ArmoryCog | None:
        return self.bot.get_cog("ArmoryCog")  # type: ignore[return-value]

    def crafted_by(self, guild_id: int):
        return crafted_by_map(self.db.guild_recipes(guild_id))

    def candidates(self, guild_id: int, requester_id: int) -> list[Candidate]:
        return orderable(self.db.guild_recipes(guild_id), self.db.recipe_crafters(guild_id), requester_id)

    # ------------------------------------------------------------ passer commande

    def recipe_choices(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if interaction.guild_id is None:
            return []
        found = search(self.candidates(interaction.guild_id, interaction.user.id), current) if current.strip() else \
            sorted(self.candidates(interaction.guild_id, interaction.user.id), key=lambda c: normalize(c.recipe.name))
        return [
            app_commands.Choice(name=f"{c.recipe.name} — {', '.join(x.name for x in c.crafters)}"[:100], value=f"#{c.recipe.id}")
            for c in found[:MAX_CHOICES]
        ]

    async def start(self, interaction: discord.Interaction, query: str, quantity: int, note: str | None) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("À utiliser sur le serveur.", ephemeral=True)
            return
        self.db.touch_member(interaction.guild_id, interaction.user.id)
        await interaction.response.defer(ephemeral=True, thinking=True)
        if self.armory is not None:  # composants des recettes encore jamais lues
            await self.armory.fetch_recipe_details(self.db.recipes_missing_details())

        candidates = self.candidates(interaction.guild_id, interaction.user.id)
        query = query.strip()
        if query.startswith("#") and query[1:].isdigit():  # choix de l'autocomplétion
            found = [c for c in candidates if c.recipe.id == int(query[1:])]
        else:
            found = search(candidates, query)
        if not found:
            await interaction.followup.send(
                f"🤷 Personne d'autre que toi ne sait faire « {query.lstrip('#')} » sur le serveur. Seules les recettes "
                "débloquées par les persos (vues dans l'armurerie) peuvent être commandées : essaie un autre mot, "
                "ou regarde `/liste recettes`.",
                ephemeral=True,
            )
            return
        draft = OrderDraft(self, interaction, found, quantity, note)
        await interaction.followup.send(ephemeral=True, **draft.render())

    async def _dm(self, user_id: int, content: str, embed: discord.Embed, view: discord.ui.View | None):
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            kwargs = {"content": content, "embed": embed}
            if view is not None:
                kwargs["view"] = view
            return await user.send(**kwargs)
        except discord.HTTPException:
            log.info("MP impossible à %s pour une commande", user_id)
            return None

    async def notify_new(self, order: Order) -> bool:
        message = await self._dm(
            order.crafter_user_id,
            f"🛠️ **{order.requester_name}** te passe une commande pour **{order.crafter_name}** :",
            order_embed(order),
            order_view(order, order.crafter_user_id),
        )
        if message is None:
            return False
        self.db.set_order_dm(order.id, message.channel.id, message.id)
        return True

    # ------------------------------------------------------------ actions

    async def handle_action(self, interaction: discord.Interaction, action: str, order_id: int) -> None:
        order = self.db.get_order(order_id)
        if order is None:
            await interaction.response.send_message("Cette commande n'existe plus.", ephemeral=True)
            return
        transition = TRANSITIONS[action]
        if action not in allowed_actions(order, interaction.user.id):
            # Bouton périmé (commande déjà traitée) ou pas la bonne personne : on montre l'état réel.
            if interaction.user.id in (order.requester_id, order.crafter_user_id):
                await interaction.response.edit_message(embed=order_embed(order), view=order_view(order, interaction.user.id))
            else:
                await interaction.response.send_message("Cette commande ne te concerne pas.", ephemeral=True)
            return
        if not self.db.set_order_status(order.id, transition.to_status, transition.from_status):
            order = self.db.get_order(order_id) or order
            await interaction.response.edit_message(embed=order_embed(order), view=order_view(order, interaction.user.id))
            return
        order = self.db.get_order(order_id) or order
        await interaction.response.edit_message(embed=order_embed(order), view=order_view(order, interaction.user.id))

        # Le MP de l'artisan suit l'état de la commande, d'où qu'on ait cliqué.
        clicked = interaction.message.id if interaction.message else None
        if order.crafter_dm_message_id and order.crafter_dm_message_id != clicked and order.crafter_dm_channel_id:
            try:
                dm = self.bot.get_partial_messageable(order.crafter_dm_channel_id).get_partial_message(
                    order.crafter_dm_message_id
                )
                await dm.edit(embed=order_embed(order), view=order_view(order, order.crafter_user_id))
            except discord.HTTPException:
                pass

        if action in NOTIFY_REQUESTER:
            await self._dm(
                order.requester_id,
                NOTIFY_REQUESTER[action].format(crafter=order.crafter_name),
                order_embed(order),
                order_view(order, order.requester_id),
            )
        if action in NOTIFY_CRAFTER:
            await self._dm(
                order.crafter_user_id, NOTIFY_CRAFTER[action].format(requester=order.requester_name), order_embed(order), None
            )

    # ------------------------------------------------------------ mes commandes

    def mine_embed(self, user_id: int, orders: list[Order]) -> discord.Embed:
        embed = discord.Embed(title="📦 Mes commandes", color=0xF2C75C)
        received = [o for o in orders if o.crafter_user_id == user_id]
        placed = [o for o in orders if o.requester_id == user_id]

        def line(o: Order, other: str) -> str:
            return f"`#{o.id}` {o.quantity}× **{o.recipe_name}** · {other} · {STATUS_LABELS[o.status]}"

        if received:
            embed.add_field(
                name="📥 On t'a demandé",
                value="\n".join(line(o, f"pour {o.requester_name} ({o.crafter_name})") for o in received)[:1024],
                inline=False,
            )
        if placed:
            embed.add_field(
                name="📤 Tu as commandé",
                value="\n".join(line(o, f"chez {o.crafter_name}") for o in placed)[:1024],
                inline=False,
            )
        if not orders:
            embed.description = "Aucune commande pour l'instant. Clique sur 🛒 **Commander** pour en passer une."
        else:
            embed.set_footer(text="Choisis une commande en cours dans le menu pour l'accepter, la terminer ou l'annuler.")
        return embed

    def mine_view(self, user_id: int, orders: list[Order]) -> discord.ui.View | None:
        actionable = [o for o in orders if allowed_actions(o, user_id)][:MAX_CHOICES]
        if not actionable:
            return None
        view = discord.ui.View(timeout=600)
        select = discord.ui.Select(
            placeholder="Gérer une commande…",
            options=[
                discord.SelectOption(
                    label=f"#{o.id} · {o.quantity}× {o.recipe_name}"[:100],
                    value=str(o.id),
                    description=(f"pour {o.requester_name}" if o.crafter_user_id == user_id else f"chez {o.crafter_name}")[:100],
                )
                for o in actionable
            ],
        )

        async def picked(interaction: discord.Interaction) -> None:
            order = self.db.get_order(int(interaction.data["values"][0]))  # type: ignore[index]
            if order is None:
                await interaction.response.edit_message(content="Cette commande n'existe plus.", embed=None, view=None)
                return
            back = discord.ui.Button(label="◀ Toutes mes commandes", style=discord.ButtonStyle.secondary)

            async def go_back(inter: discord.Interaction) -> None:
                fresh = self.db.user_orders(inter.user.id)
                await inter.response.edit_message(embed=self.mine_embed(inter.user.id, fresh), view=self.mine_view(inter.user.id, fresh))

            back.callback = go_back
            await interaction.response.edit_message(embed=order_embed(order), view=order_view(order, interaction.user.id, back))

        select.callback = picked
        view.add_item(select)
        return view

    async def show_mine(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is not None:
            self.db.touch_member(interaction.guild_id, interaction.user.id)
        orders = self.db.user_orders(interaction.user.id)
        kwargs = {"embed": self.mine_embed(interaction.user.id, orders), "ephemeral": True}
        view = self.mine_view(interaction.user.id, orders)
        if view is not None:
            kwargs["view"] = view
        await interaction.response.send_message(**kwargs)

    # ------------------------------------------------------------ panneau

    async def post_panel(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            await interaction.response.send_message("Impossible de poster ici.", ephemeral=True)
            return
        try:
            message = await channel.send(embed=panel_embed(), view=AtelierPanel(self))  # type: ignore[union-attr]
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas le droit d'écrire dans ce salon.", ephemeral=True)
            return
        try:
            await message.pin(reason="Panneau de l'atelier")
            pinned = " et épinglé"
        except discord.HTTPException:
            pinned = " (pas pu l'épingler : il me manque « Gérer les messages », épingle-le à la main)"
        await interaction.response.send_message(f"🛠️ Panneau de l'atelier posté{pinned}.", ephemeral=True)


async def setup(bot: WowPlannerBot) -> None:
    await bot.add_cog(OrdersCog(bot))
