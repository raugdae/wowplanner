"""Donjons et raids de WoW Forever, pour la page « Donjons » du site.

L'API Blizzard n'expose pas le Journal des donjons pour Forever (index vide, 404 sur les instances ;
seul le retail l'a, avec ses propres niveaux et boss). La liste est donc écrite ici, d'après :
- les tranches annoncées par Blizzard (forum, sept. 2026, Krol'dok corrigé en 40-45) ;
- le récapitulatif PC Games du 4 nov. 2026 et le guide Warcraft Tavern (tranches du jeu à la sortie).
Les tranches sont des niveaux conseillés, pas des verrous d'entrée.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SOURCES_CHECKED = "nov. 2026"


@dataclass(frozen=True)
class Dungeon:
    name: str  # nom français
    english: str
    zone: str
    low: int
    high: int
    players: int = 5
    new: bool = False  # nouveau dans Forever
    side: str | None = None  # « alliance » / « horde » : entrée dans une capitale ou un territoire d'une faction


@dataclass(frozen=True)
class Raid:
    name: str
    english: str
    zone: str
    players: int
    bosses: int | None
    opens: date | None  # None : pas encore de date
    new: bool = False
    note: str = ""


DUNGEONS: tuple[Dungeon, ...] = (
    Dungeon("Gouffre de Ragefeu", "Ragefire Chasm", "Orgrimmar", 13, 18, side="horde"),
    Dungeon("La Salle des Thanes", "Hall of Thanes", "Forgefer (Dun Morogh)", 13, 20, new=True, side="alliance"),
    Dungeon("Ruines de Lordaeron", "Ruins of Lordaeron", "Clairières de Tirisfal", 15, 22, new=True, side="horde"),
    Dungeon("Cavernes des lamentations", "Wailing Caverns", "Les Tarides", 15, 24),
    Dungeon("Les Mortemines", "The Deadmines", "Marche de l'Ouest", 17, 26),
    Dungeon("Donjon d'Ombrecroc", "Shadowfang Keep", "Forêt des Pins-Argentés", 20, 30),
    Dungeon("Profondeurs de Brassenoire", "Blackfathom Deeps", "Orneval", 24, 32),
    Dungeon("La Prison", "The Stockade", "Hurlevent", 24, 32, side="alliance"),
    Dungeon("Site de fouilles des Paluns", "Excavation Site: Wetlands", "Les Paluns", 26, 33, new=True),
    Dungeon("Cité de Dalaran", "City of Dalaran", "Montagnes d'Alterac", 28, 35, new=True),
    Dungeon("Gnomeregan", "Gnomeregan", "Dun Morogh", 29, 38),
    Dungeon("Kraal de Tranchebauge", "Razorfen Kraul", "Les Tarides", 29, 38),
    Dungeon("Monastère écarlate : Cimetière", "Scarlet Monastery: Graveyard", "Clairières de Tirisfal", 30, 38),
    Dungeon("Monastère écarlate : Bibliothèque", "Scarlet Monastery: Library", "Clairières de Tirisfal", 33, 41),
    Dungeon("La Cité engloutie", "The Drowned City", "Strangleronce", 35, 40, new=True),
    Dungeon("Monastère écarlate : Armurerie", "Scarlet Monastery: Armory", "Clairières de Tirisfal", 36, 44),
    Dungeon("Souilles de Tranchebauge", "Razorfen Downs", "Les Tarides", 37, 46),
    Dungeon("Monastère écarlate : Cathédrale", "Scarlet Monastery: Cathedral", "Clairières de Tirisfal", 38, 46),
    Dungeon("Bastion de Krol'dok", "Krol'dok Stronghold", "Rives Claires", 40, 45, new=True),
    Dungeon("Uldaman", "Uldaman", "Terres ingrates", 41, 51),
    Dungeon("Zul'Farrak", "Zul'Farrak", "Tanaris", 44, 54),
    Dungeon("Maraudon", "Maraudon", "Désolace", 46, 55),
    Dungeon("Prison d'Alcaz", "Alcaz Prison", "Marécage d'Âprefange", 48, 53, new=True),
    Dungeon("Le temple englouti", "Sunken Temple", "Marais des Chagrins", 50, 60),
    Dungeon("Profondeurs de Rochenoire", "Blackrock Depths", "Mont Rochenoire", 52, 60),
    Dungeon("Hache-Tripes : Est", "Dire Maul: East", "Féralas", 54, 60),
    Dungeon("Repaire des Noiregueules", "Blackmaw Hold", "Azshara", 55, 60, new=True),
    Dungeon("Pic de Rochenoire inférieur", "Lower Blackrock Spire", "Mont Rochenoire", 55, 60),
    Dungeon("Hache-Tripes : Nord", "Dire Maul: North", "Féralas", 56, 60),
    Dungeon("Hache-Tripes : Ouest", "Dire Maul: West", "Féralas", 56, 60),
    Dungeon("Scholomance", "Scholomance", "Maleterres de l'Ouest", 58, 60),
    Dungeon("Terrasse du Façonneur", "Shaper's Terrace", "Cratère d'Un'Goro", 58, 60, new=True),
    Dungeon("Stratholme : Porte principale", "Stratholme: Main Gate", "Maleterres de l'Est", 58, 60),
    Dungeon("Stratholme : Entrée de service", "Stratholme: Service Gate", "Maleterres de l'Est", 58, 60),
    Dungeon("Pic de Rochenoire supérieur", "Upper Blackrock Spire", "Mont Rochenoire", 59, 60, players=10),
)

RAID_LEVEL = 60
RAIDS: tuple[Raid, ...] = (
    Raid("Profondeurs des tertres", "Barrow Deeps", "Mont Hyjal, Berceau-de-l'Hiver ou Repaire des Noiregueules",
         10, 8, date(2026, 12, 9), new=True),
    Raid("Sommet d'Hyjal", "Hyjal Summit", "Mont Hyjal (près de Nordrassil)", 20, 13, date(2026, 12, 9), new=True),
    Raid("Repaire d'Onyxia", "Onyxia's Lair", "Marécage d'Âprefange", 40, 1, date(2026, 12, 9),
         note="Harmonisation : chaîne de quêtes de l'Amulette de Drakefeu."),
    Raid("Cœur du Magma", "Molten Core", "Mont Rochenoire", 40, None, None, note="Annoncé pour plus tard."),
)

LEVEL_MIN = 10
LEVEL_MAX = 60


def in_range(dungeon: Dungeon, level: int | None) -> bool:
    return level is not None and dungeon.low <= level <= dungeon.high


def raid_status(raid: Raid, today: date | None = None) -> str:
    today = today or date.today()
    if raid.opens is None:
        return "À venir"
    if raid.opens <= today:
        return "Ouvert"
    return f"Ouvre le {raid.opens:%d/%m/%Y}"
