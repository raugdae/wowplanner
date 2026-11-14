"""Fiches des donjons et raids : entrée, coordonnées et parcours des boss, pour la page de chaque instance.

L'API Blizzard n'a ni cartes ni coordonnées pour Forever : tout est relevé à la main, d'après les guides
Warcraft Tavern (un par donjon, nov. 2026) et le Journal retail de Blizzard pour les noms français des boss
classiques. Les coordonnées sont celles de la carte indiquée (format /way). Les cartes détaillées restent
chez les guides : on renvoie vers eux plutôt que de copier leurs images. Les vignettes viennent de Blizzard.
"""
from __future__ import annotations

from dataclasses import dataclass, field

GUIDE_BASE = "https://www.warcrafttavern.com/forever/guides/"
TILE_BASE = "https://render.worldofwarcraft.com/eu/zones/"


@dataclass(frozen=True)
class Boss:
    name: str
    where: str = ""
    optional: bool = False  # rare, invoqué, ou pas obligatoire pour finir


@dataclass(frozen=True)
class Guide:
    how: str  # comment arriver à l'entrée
    map_name: str | None = None  # carte des coordonnées
    coords: tuple[float, float] | None = None
    bosses: tuple[Boss, ...] = ()
    guide: str | None = None  # page Warcraft Tavern (avec la carte détaillée)
    tile: str | None = None  # vignette Blizzard (nom de fichier sur render.worldofwarcraft.com)
    notes: tuple[str, ...] = field(default=())

    @property
    def guide_url(self) -> str | None:
        return GUIDE_BASE + self.guide + "/" if self.guide else None

    @property
    def tile_url(self) -> str | None:
        return TILE_BASE + self.tile + "-small.jpg" if self.tile else None

    def way(self) -> str | None:
        """Commande /way (TomTom et autres) pour l'entrée."""
        if not self.coords:
            return None
        x, y = self.coords
        return f"/way {self.map_name} {x:g} {y:g}" if self.map_name else f"/way {x:g} {y:g}"


# Noms français officiels (Journal de Blizzard, mêmes boss qu'en classique) ; sinon le nom anglais des guides.
FRENCH_NAMES: dict[str, str] = {
    'Alzzin the Wildshaper': 'Alzzin le Modeleur',
    'Ambassador Flamelash': 'Ambassadeur Cinglefouet',
    'Amnennar the Coldbringer': 'Amnennar le Porte-Froid',
    'Ancient Stone Keeper': 'Ancien gardien en pierre',
    'Avatar of Hakkar': "Avatar d'Hakkar",
    "Bael'Gar": 'Bael’Gar',
    'Baron Silverlaine': 'Baron d’Argelaine',
    'Baroness Anastari': 'Baronne Anastari',
    'Captain Greenskin': 'Capitaine Vertepeau',
    'Captain Kromcrush': 'Capitaine Kromcrabouille',
    'Celebras the Cursed': 'Celebras le Maudit',
    'Charlga Razorflank': 'Charlga Trancheflanc',
    'Chief Ukorz Sandscalp': 'Chef Ukorz Scalpessable',
    'Commander Springvale': 'Commandant Printeval',
    'Cookie': 'Cuistot',
    'Crowd Pummeler 9-60': 'Disperseur de foule 9-60',
    'Darkmaster Gandling': 'Sombre Maître Gandling',
    'Electrocutioner 6000': 'Electrocuteur 6000',
    'Emperor Dagran Thaurissan': 'Empereur Dagran Thaurissan',
    'Fineous Darkvire': 'Fineous Sombrevire',
    'Galgann Firehammer': 'Galgann Martel-de-Feu',
    'General Angerforge': 'Général Forgehargne',
    'Gizrul the Slavener': "Gizrul l'esclavagiste",
    'Golem Lord Argelmach': 'Seigneur golem Argelmach',
    'Golemagg the Incinerator': 'Golemagg l’Incinérateur',
    'Grimlok': 'Grimelok',
    'Guard Fengus': 'Garde Fengus',
    "Guard Mol'dar": "Garde Mol'dar",
    "Guard Slip'kik": "Garde Slip'kik",
    'Hearthsinger Forresten': 'Chanteloge Forrestin',
    'High Inquisitor Whitemane': 'Grande inquisitrice Blanchetête',
    'High Interrogator Gerstahn': 'Grande Interrogatrice Gerstahn',
    'Highlord Omokk': 'Généralissime Omokk',
    'Houndmaster Grebmar': 'Maître-chien Grebmar',
    'Hurley Blackbreath': 'Hurley Soufflenoir',
    'Hydromancer Velratha': 'Hydromancienne Velratha',
    'Hydrospawn': 'Hydrogénos',
    'Illyanna Ravenoak': 'Illyanna Corvichêne',
    "Jammal'an the Prophet": "Jammal'an le Prophète",
    'King Gordok': 'Roi Gordok',
    'Lady Anacondra': 'Dame Anacondra',
    'Landslide': 'Glissement de terrain',
    'Lord Cobrahn': 'Seigneur Cobrahn',
    'Lord Incendius': 'Seigneur Incendius',
    'Lord Pythas': 'Seigneur Pythas',
    'Lord Roccor': 'Seigneur Roccor',
    'Lord Serpentis': 'Seigneur Serpentis',
    'Lord Vyletongue': 'Seigneur Vylelangue',
    'Magister Kalendris': 'Magistère Kalendris',
    'Magistrate Barthilas': 'Magistrat Barthilas',
    'Majordomo Executus': 'Chambellan Executus',
    'Maleki the Pallid': 'Maleki le Blafard',
    'Mekgineer Thermaplugg': 'Mekgénieur Thermojoncteur',
    'Mordresh Fire Eye': 'Mordresh Oeil-de-Feu',
    'Mother Smolderweb': 'Matriarche Couveuse',
    'Mr. Smite': 'M. Châtiment',
    'Mutanus the Devourer': 'Mutanus le Dévoreur',
    "Nekrum & Sezz'ziz": 'Nekrum et Sezz’ziz',
    'Noxxion': 'Noxcion',
    'Obsidian Sentinel': "Sentinelle d'obsidienne",
    'Overlord Wyrmthalak': 'Seigneur Wyrmthalak',
    'Phalanx': 'Phalange',
    'Postmaster Malown': 'Postier Malown',
    'Princess Theradras': 'Princesse Theradras',
    'Pyromancer Loregrain': 'Pyromancien Blé-du-savoir',
    'Quartermaster Zigris': 'Intendant Zigris',
    'Ramstein the Gorger': 'Ramstein Grandgosier',
    'Rattlegore': 'Cliquettripes',
    'Razorlash': 'Tranchefouet',
    "Rhahk'Zor": 'Rhahk’Zor',
    'Ring of Law': 'Cercle de la loi',
    'Rotgrip': 'Grippe-charogne',
    'Shade of Eranikus': "Ombre d'Eranikus",
    "Shadow Hunter Vosh'gajin": "Chasseresse des ombres Vosh'gajin",
    'Stomper Kreeg': 'Kreeg le Marteleur',
    'Sulfuron Harbinger': 'Messager de Sulfuron',
    'Tendris Warpwood': 'Tendris Crochebois',
    'The Lost Dwarves': 'Les nains perdus',
    'The Seven': 'Les sept',
    'The Unforgiven': 'Le Condamné',
    'Theka the Martyr': 'Theka le Martyr',
    'Timmy the Cruel': 'Timmy le Cruel',
    'Tinkerer Gizlock': 'Bricoleur Kadenaz',
    'Urok Doomhowl': 'Urok Hurleruine',
    'Verdan the Everliving': "Verdan l'Immortel",
    'Viscous Fallout': 'Retombée visqueuse',
    'War Master Voone': 'Maître de guerre Voone',
    'Wardens of the Dream': 'Protecteurs du Rêve',
    'Warder Stilgiss': 'Gardien Stilgiss',
    "Witch Doctor Zum'rah": "Féticheur Zum'rah",
    'Zevrim Thornhoof': 'Zevrim Sabot-de-Ronce',
}


def boss_name(boss: Boss) -> str:
    return FRENCH_NAMES.get(boss.name, boss.name)


B = Boss
SCARLET = "Au nord-est des Clairières de Tirisfal, dans le grand bâtiment du Monastère écarlate."
BLACKROCK = (
    "Au cœur du Mont Rochenoire, entre la Gorge des Vents brûlants et les Steppes ardentes : on y entre par l'un ou "
    "l'autre côté."
)
DIRE_MAUL = "Hache-Tripes, au centre de Féralas : les ailes partent de la cour centrale des ruines."

GUIDES: dict[str, Guide] = {
    "ragefire-chasm": Guide(
        "Dans la Faille de l'ombre, au centre d'Orgrimmar.", "Orgrimmar", (52.8, 49.6),
        (B("Oggleflint", "Petite salle au bout du chemin de droite, juste après l'entrée"),
         B("Taragaman the Hungerer", "Plateforme centrale"),
         B("Jergosh the Invoker", "Derrière ses gardes, à éliminer d'abord"),
         B("Bazzalan", "Tout au fond, sur la partie haute")),
        "ragefire-chasm", "ragefire-chasm"),
    "hall-of-thanes": Guide(
        "Sous Forgefer : depuis la Grande Forge, entrer dans la salle du trône de Magni, puis prendre à gauche le "
        "passage couvert de toiles. Attention, tomber dans le puits est mortel.", "Forgefer", (43.5, 52.0),
        (B("Faldrim Anvilmar", "Tourne autour du tombeau, au Repos d'Anvilmar"),
         B("Magmatus", "Caverne naturelle après le tombeau, avec un invocateur Sombrefer"),
         B("Plunder", "Patrouille dans le couloir de la Salle des Thanes (avant-dernière salle)"),
         B("Durgen Dirgehammer", "Reliquaire des rois, salle finale")),
        "hall-of-thanes"),
    "ruins-of-lordaeron": Guide(
        "Juste devant Fossoyeuse : passer la grande porte, puis monter l'escalier sur la gauche avant le donjon.",
        "Fossoyeuse", (72.4, 11.6),
        (B("Witherfang", "Ruelle près de l'entrée"),
         B("The Baron", "Arène à l'ouest des citoyens fantomatiques, derrière le trou dans le mur"),
         B("Viktor the Vile", "Maison incendiée avec cheminée, dans la cour après le cimetière", True),
         B("The Abandoned", "Statue de la cour après le cimetière", True),
         B("Bjork", "Partie nord-ouest"),
         B("Rath'mael", "Coin clôturé du cimetière")),
        "the-ruins-of-lordaeron"),
    "wailing-caverns": Guide(
        "Dans la grotte au-dessus de l'oasis des Eaux-Vives, au centre des Tarides : descendre jusqu'au grand bassin, "
        "le portail est là (élites autour).", "Les Tarides", (46.0, 36.3),
        (B("Lady Anacondra", "Corniches au-dessus de la grande caverne"),
         B("Lord Cobrahn", "Fosse aux crocs, première aile"),
         B("Kresh", "Dans le ruisseau de la caverne centrale"),
         B("Lord Pythas", "Grande aile"),
         B("Skum", "Gouffre sinueux"),
         B("Lord Serpentis", "Grande aile, en haut"),
         B("Verdan the Everliving", "Près de la cascade, après Serpentis"),
         B("Mutanus the Devourer", "Salle finale, sort du bassin (escorte du disciple de Naralex)"),
         B("Deviate Faerie Dragon", "Rare, n'importe où dans les grottes", True)),
        "wailing-caverns", "wailing-caverns"),
    "the-deadmines": Guide(
        "Dans le repaire Défias, le grand bâtiment au sud-ouest de Ruisselune, puis descendre le dédale de galeries "
        "jusqu'au portail.", "Marche de l'Ouest", (42.0, 72.0),
        (B("Rhahk'Zor", "Après les premiers tunnels"),
         B("Miner Johnson", "Rare, à gauche de la bifurcation après Rhahk'Zor", True),
         B("Sneed", "Dans son déchiqueteur, salle des bûcherons gobelins"),
         B("Gilnid", "La fonderie, avec ses artisans gobelins"),
         B("Mr. Smite", "Sur le navire"),
         B("Captain Greenskin", "Sur le pont du navire"),
         B("Edwin VanCleef", "Au sommet du navire, fin du donjon"),
         B("Cookie", "Pont inférieur, près de la passerelle", True)),
        "the-deadmines", "deadmines"),
    "shadowfang-keep": Guide(
        "Dans les montagnes juste au nord du village de Bois-du-Bûcher, dans la Forêt des Pins-Argentés.",
        "Forêt des Pins-Argentés", (44.5, 68.0),
        (B("Rethilgore", "Dès l'entrée : sa mort ouvre la porte de la cour"),
         B("Razorclaw the Butcher", "Cuisines, après la cour"),
         B("Baron Silverlaine", "Salle à manger, après ses gardes"),
         B("Commander Springvale", "Salle remplie de gardes"),
         B("Odo the Blindwatcher", "Remparts"),
         B("Deathsworn Captain", "Rare", True),
         B("Fenrus the Devourer", "Devant les appartements d'Arugal"),
         B("Wolf Master Nandos", "Devant la porte d'Arugal"),
         B("Archmage Arugal", "Dernière salle, avec trois worgens")),
        "shadowfang-keep", "shadowfang-keep"),
    "blackfathom-deeps": Guide(
        "Ruines elfiques englouties sur la grève de Zoram, au nord-ouest d'Orneval : traverser un bassin à la nage "
        "puis une grotte étroite pleine de nagas élites.", "Orneval", (14.5, 14.6),
        (B("Ghamoo-Ra", "Début du donjon"),
         B("Lady Sarevess", "Avec deux gardes"),
         B("Gelihast", "Salle des murlocs, derrière une pierre", True),
         B("Lorgus Jett", "Temple du Crépuscule"),
         B("Baron Aquanis", "Apparaît en ramassant la Pierre des profondeurs"),
         B("Twilight Lord Kelris", "Salle cérémonielle avant la fin"),
         B("Old Serra'kis", "Sous l'eau", True),
         B("Aku'mai", "Salle finale, après les braseros")),
        "blackfathom-deeps", "blackfathom-deeps"),
    "the-stockade": Guide(
        "Dans les canaux de Hurlevent, près du quartier des Mages.", "Hurlevent", (42.0, 58.0),
        (B("Targorr the Dread"), B("Kam Deepfury"), B("Hamhock"),
         B("Bazil Thredd"), B("Bruegal Ironknuckle", "Rare", True), B("Dextren Ward", "Dernière aile")),
        "the-stockade-dungeon-map-location-bosses", "the-stockade"),
    "excavation-site-wetlands": Guide(
        "En haut d'un chemin sinueux à gauche de Thelgen Rock (départ vers 53.9, 65.4). Alliance : par la route depuis "
        "Menethil ; Horde : depuis Fossoyeuse par les Pins-Argentés, Hillsbrad et les Hautes-terres d'Arathi.",
        "Les Paluns", (48.1, 56.5),
        (B("Saltspine", "Marais perdu"),
         B("Shadetooth", "Fourré du traqueur"),
         B("Highland Horror", "Au nord du site de fouilles perdu", True),
         B("Relic Guardian", "Site du gardien")),
        "excavation-site-wetlands"),
    "city-of-dalaran": Guide(
        "Alliance : depuis Austrivage, parler à l'émissaire Jaques et obtenir la clé des égouts auprès de l'image de "
        "l'archimage Modera. Horde : chaîne de quêtes à Moulin-de-Tarren, puis entrée depuis le Sépulcre.",
        "Forêt des Pins-Argentés", (69.3, 45.6),
        (B("Atrexis the Grave Knight", "Bas-fonds des égouts, après les trois grosses canalisations"),
         B("Lyn the Ignored", "Salle carrée au cercle d'invocation, près de la sortie des égouts", True),
         B("Mana Devourer", "Fort pourpre"),
         B("Arcane Anomaly", "Ancien débarcadère de Krasus, à droite de la sortie du Fort pourpre"),
         B("Fel Ancient", "Place Tisserune"),
         B("Arcanic Enigma", "Chemin du Renouveau, au nord-est"),
         B("Unstable Sentry", "Recoin de la bourse des magiciens"),
         B("Shade of the Archmage", "Chambre pourpre de la Citadelle pourpre")),
        "city-of-dalaran"),
    "gnomeregan": Guide(
        "Alliance : à l'ouest de Dun Morogh, ascenseur vers les tunnels extérieurs. Horde : transpondeur gobelin de "
        "Baie-du-Butin (quête de l'ingénieur en chef Scooty) qui téléporte devant l'entrée.", "Dun Morogh", (24.0, 40.0),
        (B("Grubbis", "Près de l'entrée, au bout du premier embranchement à gauche (événement d'Emi Courtemèche)"),
         B("Viscous Fallout", "Zone des déchets"),
         B("Electrocutioner 6000", "Plateforme en haut au centre de la baie de lancement"),
         B("Crowd Pummeler 9-60", "Laboratoires d'ingénierie"),
         B("Dark Iron Ambassador", "Près de la cour du Bricoleur", True),
         B("Mekgineer Thermaplugg", "Salle finale")),
        "gnomeregan", "gnomeregan"),
    "razorfen-kraul": Guide(
        "Au sud-ouest des Tarides.", "Les Tarides", (43.0, 90.0),
        (B("Roogug"), B("Aggem Thorncurse"), B("Death Speaker Jargba"),
         B("Overlord Ramtusk"),
         B("Earthcaller Halmgar", "Plateau après Brusquebroche", True),
         B("Agathelos the Raging", "Zone scellée, après ses gardiens"),
         B("Blind Hunter", "Au fond des grottes, après Agathelos", True),
         B("Charlga Razorflank", "Rampe devant sa hutte, boss final")),
        "razorfen-kraul", "razorfen-kraul"),
    "scarlet-monastery-graveyard": Guide(
        SCARLET + " Le Cimetière est le portail le plus à gauche.", "Clairières de Tirisfal", (82.3, 33.4),
        (B("Interrogator Vishas", "Salle de torture"),
         B("Ironspire", "Rare", True), B("Fallen Champion", "Rare", True), B("Azshir the Sleepless", "Rare", True),
         B("Bloodmage Thalnos", "Au fond de la crypte")),
        "scarlet-monastery-graveyard", "scarlet-monastery"),
    "scarlet-monastery-library": Guide(
        SCARLET + " La Bibliothèque est le portail le plus à droite.", "Clairières de Tirisfal", (82.3, 33.4),
        (B("Houndmaster Loksey", "Petite cour au sud de la première cour"),
         B("Arcanist Doan", "Grande salle ronde au bout des couloirs ; derrière lui, le coffre avec la clé écarlate")),
        "scarlet-monastery-library", "scarlet-monastery"),
    "the-drowned-city": Guide(
        "Sous l'eau au large de Strangleronce : nager au-delà du Récif infâme jusqu'au Creux englouti, près de l'île "
        "aux élémentaires ; l'entrée de la grotte est à côté d'une grande tablette.", "Strangleronce", (21.4, 27.9),
        (B("Zul'Alai", "En haut de la colline après l'entrée"),
         B("Umbra", "Près des marches qui mènent à Var'Taka", True),
         B("Var'Taka", "En haut des marches"),
         B("Captain Dreadrise", "Côté nord du bassin central"),
         B("Deathless Marrow", "Autel de la partie ouest"),
         B("Gill", "Sur le chemin de l'élémentaire primordial", True),
         B("Primeval Elemental", "Bassin sous-marin, au sud"),
         B("« Pyromancer » Braxton", "Quartier des pirates", True),
         B("Min'loth the Serpent", "Tout à l'ouest")),
        "the-drowned-city"),
    "scarlet-monastery-armory": Guide(
        SCARLET + " L'Armurerie est la porte fermée à droite : il faut la clé écarlate (Bibliothèque).",
        "Clairières de Tirisfal", (82.3, 33.4),
        (B("Herod", "Grande salle ronde au bout de l'aile"),),
        "scarlet-monastery-armory", "scarlet-monastery"),
    "razorfen-downs": Guide(
        "Au sud-est des Tarides, au bout d'un dédale de ronces plein de huran élites.", "Les Tarides", (43.0, 95.0),
        (B("Tuten'kash", "Salle du gong : on le fait venir en sonnant le gong"),
         B("Plaguemaw the Rotting", "Fin de l'escorte de Belnistrasz", True),
         B("Mordresh Fire Eye", "Sur un tas d'os entouré de squelettes"),
         B("Ragglesnout", "Rare", True),
         B("Glutton", "Sous la Spirale des ronces"),
         B("Amnennar the Coldbringer", "Boss final, près d'une tente")),
        "razorfen-downs", "razorfen-downs"),
    "scarlet-monastery-cathedral": Guide(
        SCARLET + " La Cathédrale est la porte de gauche : il faut la clé écarlate (Bibliothèque).",
        "Clairières de Tirisfal", (82.3, 33.4),
        (B("High Inquisitor Fairbanks", "Salle cachée à droite de la cathédrale", True),
         B("Scarlet Commander Mograine", "Autel au fond de la cathédrale"),
         B("High Inquisitor Whitemane", "Même autel : arrive en deuxième phase")),
        "scarlet-monastery-cathedral", "scarlet-monastery"),
    "kroldok-stronghold": Guide(
        "Une grotte à l'ouest des grandes portes du fort, sur la colline qui domine Sunnyglade, au nord des Rives "
        "Claires.", "Rives Claires", (37.5, 37.5),
        (B("Slavecrusher Grox", "Carrière ogre, en bas à droite après l'entrée"),
         B("Twilight Commander Zarmok", "Camp devant la grande porte"),
         B("War Handler Ashka", "Enclos à loups le long de la route"),
         B("Nar'gurk", "Cercle d'invocation en haut du chemin principal"),
         B("Bossman Toof", "Les deux ponts avant la dernière partie"),
         B("Overlord Mugg", "Grande maison au bout de la route sinueuse")),
        "kroldok-stronghold"),
    "uldaman": Guide(
        "Entrée principale au nord des Terres ingrates, près du Loch Modan, par des tunnels de fouilles pleins "
        "d'élites. Entrée arrière dans une grotte du Ravin de Ventepoussière.", "Terres ingrates", (44.0, 12.0),
        (B("The Lost Dwarves", "Première salle", True),
         B("Revelosh", "Grande caverne"),
         B("Ironaya", "Derrière la porte scellée (bâton de commandement)"),
         B("Obsidian Sentinel", "Salle des gardiens"),
         B("Ancient Stone Keeper", "Salle des gardiens"),
         B("Galgann Firehammer", "Atelier des Sombrefer"),
         B("Grimlok", "Salle des troggs"),
         B("Archaedas", "Salle finale, à réveiller avec le bâton")),
        "uldaman", "uldaman"),
    "zulfarrak": Guide("Au nord-ouest de Tanaris.", "Tanaris", (39.0, 20.0), (
        B("Zerillis", "Patrouille autour de l'autel des prêtres des ombres", True),
        B("Antu'sul", "Grotte derrière le mur fissuré, à droite de la salle de Theka"),
        B("Theka the Martyr", "Autour des tombes peu profondes"),
        B("Witch Doctor Zum'rah", "Après Theka, avec son chaudron et son coffre"),
        B("Nekrum & Sezz'ziz", "Bas des marches, fin de l'événement du sergent Bly"),
        B("Sergeant Bly", "Libéré des cages pendant l'événement des marches"),
        B("Chief Ukorz Sandscalp", "Derrière la porte que fait sauter Weegli"),
        B("Hydromancer Velratha", "Cour du bassin de Gahz'rilla, près de l'entrée"),
        B("Gahz'rilla", "Bassin de la cour : se fait venir au gong avec le maillet de Zul'Farrak", True),
        B("Sandarr Dunereaver", "Sur le chemin de la sortie", True),
        ), "zulfarrak", "zulfarrak"),
    "maraudon": Guide(
        "Passer la porte de pierre à l'ouest de la Vallée des lances, en Désolace : grottes extérieures pleines "
        "d'élites, puis à droite le portail orange, à gauche le portail violet.", "Désolace", (38.0, 58.0),
        (B("Noxxion", "Côté orange"),
         B("Razorlash", "Côté orange"),
         B("Lord Vyletongue", "Côté violet"),
         B("Celebras the Cursed", "Chutes empoisonnées"),
         B("Meshlok the Harvester", "En haut des chutes empoisonnées", True),
         B("Landslide", "En haut de la rampe en spirale, Chutes de Chant-de-terre"),
         B("Tinkerer Gizlock", "Bas de la rampe avant la princesse"),
         B("Rotgrip", "Dans l'eau sous la plateforme de la princesse"),
         B("Princess Theradras", "Fond de sa plateforme")),
        "maraudon", "maraudon"),
    "alcaz-prison": Guide(
        "Sur l'île d'Alcaz, au nord-est du Marécage d'Âprefange : depuis le ponton, prendre le chemin à gauche jusqu'au "
        "grand bâtiment ; le portail est au sous-sol.", "Marécage d'Âprefange", (75.0, 15.0),
        (B("Tidemistress Ca'zass", "Au bout du couloir principal, droit devant"),
         B("Overseer Wrex", "Grande salle ronde au bout du couloir de gauche"),
         B("The Questioner", "Salle fermée derrière la porte de droite, près de l'entrée"),
         B("Katerina the Cleaner", "Grande salle au bout du couloir du bas, après la porte à barreaux"),
         B("Commander Folkar", "Enchaîné dans la salle derrière Katerina", True),
         B("Zarla Ober / Blazeroar", "La plus grande salle, à côté de celle de Katerina")),
        "alcaz-island-prison"),
    "sunken-temple": Guide(
        "Au milieu du lac du Marais des Chagrins, à la nage. Horde depuis Pierrêche ; Alliance par le Défilé de "
        "Deuillevent ou depuis le Rempart-du-Néant.",
        bosses=(B("Atal'alarion", "Fosse aux ordures"),
                B("Les gardiens trolls", "Six plateformes autour de l'anneau du haut"),
                B("Jammal'an the Prophet", "Repaire des élus"),
                B("Wardens of the Dream", "Dragons verts (Weaver, Dreamscythe, Hazzas, Morphaz)"),
                B("Shade of Eranikus", "Fond du temple"),
                B("Avatar of Hakkar", "Petite salle à l'ouest de la Fosse du sacrifice (événement)", True)),
        guide="sunken-temple", tile="the-temple-of-atalhakkar"),
    "blackrock-depths": Guide(
        BLACKROCK + " Descendre la grande chaîne jusqu'au centre, puis par le tombeau de Forgewright et la carrière "
        "jusqu'au portail, dans le coin du fond.",
        bosses=(B("High Interrogator Gerstahn", "Quartier de détention, salle sud"),
                B("Lord Roccor", "Anneau nord du quartier de détention"),
                B("Houndmaster Grebmar", "Point bas du couloir circulaire"),
                B("Ring of Law", "Arène : un champion au hasard"),
                B("Bael'Gar", "Ouest de la route des Sombrefer"),
                B("Lord Incendius", "Pont central de la cité de Sombreforge"),
                B("Fineous Darkvire", "Rampe du Hall de l'artisanat"),
                B("Warder Stilgiss", "Le Coffre noir"),
                B("Pyromancer Loregrain", "Sanctuaire de Thaurissan"),
                B("General Angerforge", "Garnison ouest"),
                B("Golem Lord Argelmach", "La Manufacture"),
                B("Hurley Blackbreath", "Réserve du Sinistre Écluseur", True),
                B("Phalanx", "Sinistre Écluseur, sortie en face du bar"),
                B("Ambassador Flamelash", "Chambre de l'Enchantement"),
                B("The Seven", "Tombe des Invocateurs"),
                B("Magmus", "Fond du Hall de fer"),
                B("Emperor Dagran Thaurissan", "Siège impérial, avec la princesse Moira")),
        guide="blackrock-depths", tile="blackrock-depths"),
    "dire-maul-east": Guide(
        DIRE_MAUL + " Hache-Tripes Est se prend par le mur est de la cour ou par l'Allée d'Eldreth ; une troisième "
        "porte, au nord-est du camp Mojache, demande la clé en croissant.",
        bosses=(B("Pusillin", "Le diablotin qui fuit dans la première partie : il lâche la clé en croissant"),
                B("Lethtendris", "Quartier de Crochebois"),
                B("Hydrospawn", "Niveau inférieur, autour d'un bassin"),
                B("Zevrim Thornhoof", "Sa mort ouvre la porte du Conservatoire"),
                B("Alzzin the Wildshaper", "Dernière salle, derrière la porte du Conservatoire"),
                B("Isalien", "Invoquée dans la salle d'Alzzin (Brasero d'appel)", True)),
        guide="dire-maul-east", tile="dire-maul---warpwood-quarter"),
    "blackmaw-hold": Guide(
        "Un tunnel de furbolgs s'ouvre en Azshara (38.7, 33.4) ; le portail est tout au fond, déjà sur la carte du "
        "Berceau-de-l'Hiver.", "Berceau-de-l'Hiver", (66.6, 84.4),
        (B("Varrox Bleakhoof", "Optionnel", True),),
        "blackmaw-hold",
        notes=("Liste des boss encore incomplète dans les guides.",)),
    "lower-blackrock-spire": Guide(
        BLACKROCK + " Prendre la porte à côté de la pierre de rencontre du Pic Rochenoire et monter (élites), ou "
        "grimper la grande chaîne jusqu'au balcon du gnome Bodley et sauter devant le portail.",
        bosses=(B("Highlord Omokk", "Premier boss"),
                B("Shadow Hunter Vosh'gajin", "En haut de la grande rampe"),
                B("War Master Voone", "Au bout du long couloir des trolls"),
                B("Mother Smolderweb", "En haut du nid d'araignées"),
                B("Urok Doomhowl", "Tas de tributs des ogres (événement)", True),
                B("Quartermaster Zigris", "Après la salle d'Urok"),
                B("Halycon", "Repaire des worgs"),
                B("Gizrul the Slavener", "Juste après Halycon"),
                B("Overlord Wyrmthalak", "Salle finale")),
        guide="lower-blackrock-spire", tile="lower-blackrock-spire"),
    "dire-maul-north": Guide(
        DIRE_MAUL + " Hache-Tripes Nord : porte du mur nord de la cour (clé en croissant), ou par l'Athénaeum depuis "
        "Hache-Tripes Ouest.",
        bosses=(B("Guard Mol'dar", "Grande salle d'entrée", True),
                B("Stomper Kreeg", "Grande salle d'entrée", True),
                B("Guard Fengus", "Salle du coffre, derrière la porte de la cour gordok", True),
                B("Guard Slip'kik", "Passerelle sous les rampes", True),
                B("Captain Kromcrush", "Salle avant le roi", True),
                B("King Gordok", "Salle finale, avec Cho'Rush l'Observateur")),
        guide="dire-maul-north", tile="dire-maul---gordok-commons",
        notes=("En « tribut », on évite les gardes pour un meilleur butin chez le roi.",)),
    "dire-maul-west": Guide(
        DIRE_MAUL + " Hache-Tripes Ouest : porte du mur ouest de la cour, avec la clé en croissant (Pusillin, "
        "Hache-Tripes Est).",
        bosses=(B("Tendris Warpwood", "Premier boss de l'aile"),
                B("Illyanna Ravenoak", "Cour des Bien-nés, par les rampes au-dessus de Tendris"),
                B("Magister Kalendris", "En bas des rampes"),
                B("Tsu'zee", "Près de Kalendris", True),
                B("Immol'thar", "Prison d'Immol'thar : couper d'abord les cinq pylônes"),
                B("Lord Hel'nurath", "Invoqué dans la prison d'Immol'thar", True),
                B("Prince Tortheldrin", "L'Athénaeum, par le tunnel depuis la prison")),
        guide="dire-maul-west", tile="dire-maul---capital-gardens"),
    "scholomance": Guide(
        "Sur l'île de Caer Darrow, au sud-est des Maleterres de l'Ouest : Alliance depuis le camp du Noroît, Horde "
        "depuis Tirisfal. La porte s'ouvre avec la clé squelette (longue chaîne de quêtes).",
        bosses=(B("Kirtonos the Herald", "Patio (invoqué)", True),
                B("Jandice Barov", "Sous la salle des dragonnets", True),
                B("Rattlegore", "Sous-sol du Grand ossuaire"),
                B("Marduk Blackpool", "Salle d'observation", True),
                B("Vectus", "Salle d'observation", True),
                B("Ras Frostwhisper", "Laboratoire d'alchimie"),
                B("Lady Illucia Barov", "Dernière salle, aile basse gauche"),
                B("Lord Alexei Barov", "Dernière salle, aile basse centrale"),
                B("The Ravenian", "Dernière salle, aile basse droite"),
                B("Lorekeeper Polkelt", "Dernière salle, aile haute gauche"),
                B("Doctor Theolen Krastinov", "Dernière salle, aile haute centrale"),
                B("Instructor Malicia", "Dernière salle, aile haute droite"),
                B("Darkmaster Gandling", "Caveau de la famille Barov")),
        guide="scholomance", tile="scholomance"),
    "shapers-terrace": Guide(
        "Sur une colline qui domine le Refuge des marshals, au nord du Cratère d'Un'Goro.", "Cratère d'Un'Goro",
        (48.1, 6.1),
        (B("Bolt"), B("Cinder"), B("Snowtalon"), B("Nanaya")),
        "shapers-terrace",
        notes=("Ordre et emplacement des boss pas encore détaillés dans les guides.",)),
    "stratholme-main-gate": Guide(
        "Entrée principale au nord-ouest des Maleterres de l'Est. On peut aussi passer de l'entrée de service par la "
        "porte de la place du Roi (clé de la ville).",
        bosses=(B("Skul", "Près des portes d'entrée", True),
                B("The Unforgiven", "Place du marché"),
                B("Hearthsinger Forresten", "Patrouille dans la rue du marché", True),
                B("Postmaster Malown", "Après l'ouverture de la troisième boîte aux lettres", True),
                B("Timmy the Cruel", "Côté gauche de la cour écarlate"),
                B("Cannon Master Willey", "Petite armurerie du domaine écarlate"),
                B("Archivist Galford", "Sa bibliothèque, face à la dernière salle"),
                B("Balnazzar", "Dernière salle (grand croisé Dathrohan)")),
        guide="stratholme-living", tile="stratholme---main-gate"),
    "stratholme-service-gate": Guide(
        "Par la porte du Mur-de-l'Est, à l'est de l'entrée principale (clé de la ville, sur le magistrat Barthilas), "
        "ou en traversant le côté vivant.",
        bosses=(B("Magistrate Barthilas", "Près de l'église au début, ou avant la cour de Ramstein"),
                B("Nerub'enkan", "Sommet de la première ziggourat"),
                B("Baroness Anastari", "Sommet de la deuxième ziggourat"),
                B("Maleki the Pallid", "Sommet de la troisième ziggourat"),
                B("Ramstein the Gorger", "Place de l'Abattoir"),
                B("Baron Rivendare", "L'Abattoir, au fond de la place")),
        guide="stratholme-undead", tile="stratholme---service-entrance"),
    "upper-blackrock-spire": Guide(
        BLACKROCK + " Même accès que le bas du Pic Rochenoire ; il faut le sceau d'ascension.",
        bosses=(B("Pyroguard Emberseer", "Salle de l'autel Rochenoire (3 joueurs l'activent)"),
                B("Solakar Flamewreath", "La Couvée, événement du Père des flammes", True),
                B("Goraluk Anvilcrack", "Forge", True),
                B("Warchief Rend Blackhand", "Arrive sur Gyth"),
                B("The Beast", "La Fournaise"),
                B("General Drakkisath", "Salle finale")),
        guide="upper-blackrock-spire", tile="upper-blackrock-spire"),
    # Raids
    "barrow-deeps": Guide(
        "Trois entrées : Mont Hyjal, Berceau-de-l'Hiver ou Repaire des Noiregueules.",
        bosses=(B("Deepscar Matriarch"), B("Khalith the Dreadspinner"), B("Amethrax"), B("Ravus and Darlissa"),
                B("Elder Tangleclaw"), B("Well of Sorrow"), B("Del'lynar Songwood"), B("Sonya Darkhallow")),
        guide="raids"),
    "hyjal-summit": Guide(
        "Au sommet du Mont Hyjal, près de l'Arbre-Monde Nordrassil.",
        bosses=(B("Bandalar"), B("Ancient of Decay"), B("Time-Lost Battalion"), B("Sylvestris Dusksong"),
                B("Old Gloomlurker"), B("Gharalis the Abyssal"), B("Kathris the Haunted"), B("Anara Chillwind"),
                B("Elder Minderel"), B("Tracker Stillwind"), B("Council of Thorns"), B("Nythus the Dreambound"),
                B("The Wild King")),
        guide="raids"),
    "onyxias-lair": Guide(
        "Au sud du Marécage d'Âprefange. Harmonisation : chaîne de quêtes de l'Amulette de Drakefeu.",
        bosses=(B("Onyxia"),), guide="raids", tile="onyxias-lair"),
    "molten-core": Guide(
        "Au fond des Profondeurs de Rochenoire (portail près de Lothos Gratte-faille).",
        bosses=(B("Lucifron"), B("Magmadar"), B("Gehennas"), B("Garr"), B("Shazzrah"), B("Baron Geddon"),
                B("Sulfuron Harbinger"), B("Golemagg the Incinerator"), B("Majordomo Executus"), B("Ragnaros")),
        guide="raids", tile="molten-core"),
}
