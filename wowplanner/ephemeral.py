"""Nettoyage des réponses privées (« Seul toi peux voir ceci ») du bot.

Ces messages s'empilent dans le salon. Quand un joueur lance une nouvelle commande ou clique
sur un bouton de sortie, on efface la réponse privée précédente qu'il avait reçue du bot.

Limite Discord : une réponse privée ne peut être supprimée que pendant 15 minutes après
l'interaction qui l'a créée (ensuite le jeton expire). Au-delà, elle reste jusqu'à ce que
le joueur la ferme ou recharge Discord.
"""
from __future__ import annotations

import datetime
import logging

import discord

log = logging.getLogger(__name__)

# Marge avant l'expiration du jeton (15 min) pour ne pas tenter une suppression vouée à l'échec.
SAFETY_MARGIN = datetime.timedelta(seconds=30)


class EphemeralCleaner:
    def __init__(self) -> None:
        # joueur -> dernière interaction dont la réponse est une réponse privée du bot
        self._last: dict[int, discord.Interaction] = {}

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if not self._creates_new_response(interaction):
            return
        self.forget_expired()
        previous = self._last.get(interaction.user.id)
        self._last[interaction.user.id] = interaction
        if previous is None or previous.id == interaction.id:
            return
        if discord.utils.utcnow() >= previous.expires_at - SAFETY_MARGIN:
            return  # trop tard : Discord ne permet plus de la supprimer
        try:
            await previous.delete_original_response()
        except discord.HTTPException:
            pass  # déjà fermée par le joueur, ou pas de réponse : rien à faire

    def forget_expired(self) -> None:
        now = discord.utils.utcnow()
        for user_id, inter in list(self._last.items()):
            if now >= inter.expires_at:
                del self._last[user_id]

    @staticmethod
    def _creates_new_response(interaction: discord.Interaction) -> bool:
        """Commande slash, ou clic sur un bouton d'un message public d'un salon (les boutons de sortie).

        Exclus, car le clic modifie le message au lieu d'en créer un nouveau (et « supprimer la
        réponse » supprimerait ce message) :
        - les clics dans un message privé du salon (choix du perso, confirmation d'annulation) ;
        - les clics dans les MP du bot (pages de recettes) : il ne faut jamais effacer un MP.
        """
        if interaction.type == discord.InteractionType.application_command:
            return True
        if interaction.type == discord.InteractionType.component:
            message = interaction.message
            return interaction.guild_id is not None and message is not None and not message.flags.ephemeral
        return False  # autocomplétion, formulaires…
