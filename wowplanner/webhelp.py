"""Page d'aide du site (/aide) : un chapitre par partie du site, pensé pour quelqu'un qui n'a pas l'habitude
d'internet. Publique (aucune donnée du serveur), avec captures d'écran annotées (static/aide/, générées par
tools/aide_captures.py sur des données de démonstration), recherche, et deux petits outils (pièces, rôles).

Les captures : static/aide/<nom>.webp, et static/aide/shots.json qui donne pour chacune sa taille et la position
(en %) des repères numérotés.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from . import __version__
from .gamedata import CLASSES, roles_for
from .recipes import normalize
from .roles import LABELS
from .webui import _VIEWER, esc, page

if TYPE_CHECKING:
    from .web import WebSite

SHOTS_DIR = Path(__file__).parent / "static" / "aide"
IMAGE_NAME = re.compile(r"^[a-z0-9-]+\.webp$")
ROLE_ICONS = {"tank": "🛡️", "heal": "⛑️", "dps": "⚔️"}


def _load_shots() -> dict:
    try:
        return json.loads((SHOTS_DIR / "shots.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


SHOTS = _load_shots()


# ---------------------------------------------------------------- petits blocs


def shot(name: str, caption: str, legend: list[tuple[str, str]] = ()) -> str:
    """Capture d'écran avec repères numérotés (1, 2, 3…) et leur légende. Sans capture : la légende seule."""
    info = SHOTS.get(name)
    items, marks, zones = [], [], []
    for n, (key, text) in enumerate(legend, 1):
        items.append(f'<li data-n="{n}"><span class="hn">{n}</span><span>{text}</span></li>')
        box = (info or {}).get("spots", {}).get(key)
        if box and len(box) == 4:
            # La zone désignée (allumée au survol) et son numéro, posé dans son coin haut gauche.
            x, y, w, h = box
            zones.append(f'<span class="hzone" data-n="{n}" style="left:{x}%;top:{y}%;width:{w}%;height:{h}%"></span>')
            marks.append(
                f'<button type="button" class="hmark" data-n="{n}" style="left:clamp(11px,{x}%,calc(100% - 11px));'
                f'top:clamp(11px,{y}%,calc(100% - 11px))" aria-label="Repère {n}">{n}</button>'
            )
    legend_html = f'<ol class="hlegend">{"".join(items)}</ol>' if items else ""
    if not info:
        return f'<figure class="hshot"><figcaption>{caption}</figcaption>{legend_html}</figure>'
    img = (
        f'<img src="/static/aide/{name}.webp?v={__version__}" width="{info["w"]}" height="{info["h"]}" '
        f'alt="Capture d\'écran : {esc(re.sub("<[^>]+>", "", caption))}" loading="lazy">'
    )
    zoom = (
        '<button type="button" class="hzoom" aria-label="Agrandir l\'image">🔍 Agrandir</button>' if info["h"] >= 150 else ""
    )
    return (
        f'<figure class="hshot"><div class="hpic" style="max-width:{info["w"]}px"><div class="hclip">{img}'
        f'{"".join(zones)}</div>{"".join(marks)}{zoom}</div>'
        f"<figcaption>{caption}</figcaption>{legend_html}</figure>"
    )


def steps(*items: str) -> str:
    return '<ol class="hsteps">' + "".join(f"<li>{i}</li>" for i in items) + "</ol>"


def tip(text: str) -> str:
    return f'<div class="hbox hb-tip"><b>💡 Astuce</b><p>{text}</p></div>'


def warn(text: str) -> str:
    return f'<div class="hbox hb-warn"><b>⚠️ Attention</b><p>{text}</p></div>'


def note(text: str) -> str:
    return f'<div class="hbox hb-note"><b>ℹ️ Bon à savoir</b><p>{text}</p></div>'


def go(href: str, label: str) -> str:
    return f'<p><a class="btn hgo" href="{href}">{label} →</a></p>'


def k(text: str) -> str:
    """Touche du clavier."""
    return f"<kbd>{esc(text)}</kbd>"


def ui(text: str) -> str:
    """Bouton ou mot tel qu'il apparaît à l'écran."""
    return f'<span class="hui">{text}</span>'


def table(head: list[str], rows: list[list[str]]) -> str:
    h = "".join(f"<th>{c}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="table-wrap"><table class="htable"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def faq(question: str, answer: str) -> str:
    return f'<details class="fold hfaq"><summary>{question}</summary><div class="fold-body">{answer}</div></details>'


# ---------------------------------------------------------------- chapitres


@dataclass
class Section:
    key: str
    title: str
    body: str


@dataclass
class Chapter:
    key: str
    icon: str
    title: str
    summary: str
    sections: list[Section] = field(default_factory=list)
    admin: bool = False


def _role_widget() -> str:
    """Petit outil : choisir une classe → les rôles qu'elle peut tenir (peut figurer plusieurs fois dans la page)."""
    options = "".join(f'<option value="{esc(key)}">{esc(v[0])}</option>' for key, v in CLASSES.items())
    data = {key: [f"{ROLE_ICONS[r]} {LABELS[r]}" for r in roles_for(key)] for key in CLASSES}
    return f"""<div class="hwidget hw-role">
<label>Ta classe <select aria-label="Classe"><option value="">Choisis…</option>{options}</select></label>
<p class="hw-out" aria-live="polite">Choisis une classe pour voir les rôles qu'elle peut tenir.</p>
<script type="application/json">{json.dumps(data, ensure_ascii=False)}</script></div>"""


def _coin_widget() -> str:
    return """<div class="hwidget" id="coin-widget">
<p class="muted">Tape un prix pour le voir dans les deux sens :</p>
<div class="hw-coins"><label>po<input type="number" min="0" id="hw-po" value="1" inputmode="numeric"></label>
<label>pa<input type="number" min="0" max="99" id="hw-pa" value="23" inputmode="numeric"></label>
<label>pc<input type="number" min="0" max="99" id="hw-pc" value="45" inputmode="numeric"></label></div>
<p class="hw-out" id="hw-coin-out" aria-live="polite"></p></div>"""


def _first_steps() -> str:
    items = [
        ("login", "Me connecter avec mon compte Discord", "#debut-connexion"),
        ("menu", "Ouvrir mon menu (en haut à droite) et choisir un thème de couleurs", "#debut-menu"),
        ("persos", "Vérifier que mes persos sont bien là (menu → Gérer mes persos)", "#persos-ajouter"),
        ("fav", "Choisir mon perso préféré avec l'étoile ☆", "#persos-favori"),
        ("sortie", "M'inscrire à une sortie", "#sorties-inscrire"),
        ("fiche", "Regarder la fiche de mon perso (équipement, talents)", "#guilde-fiche"),
    ]
    lis = "".join(
        f'<li><label><input type="checkbox" data-step="{key}"> {text}</label> <a href="{href}">comment ?</a></li>'
        for key, text, href in items
    )
    return f"""<div class="hwidget hcheck" id="first-steps"><div class="hprog"><span id="hprog-bar"></span></div>
<p class="muted"><span id="hprog-n">0</span> / {len(items)} fait(s) · coche au fur et à mesure (c'est retenu sur cet
appareil).</p><ul>{lis}</ul></div>"""


def chapters() -> list[Chapter]:
    debut = Chapter("debut", "🏁", "Bien démarrer", "Ce qu'est le site, se connecter, se repérer et les gestes de base.", [
        Section("site", "Le site en deux mots", f"""
<p>WoW Planner est le site de notre serveur Discord pour <b>WoW Forever</b>. Il rassemble au même endroit :</p>
<ul class="hlist">
<li>📅 les <b>sorties</b> en donjon et en raid, pour s'inscrire avec son perso ;</li>
<li>🛡️ la <b>guilde</b> : tous les persos du serveur, leur équipement, leurs talents et leurs métiers ;</li>
<li>🔨 l'<b>atelier</b>, pour demander à quelqu'un de fabriquer un objet ;</li>
<li>💰 l'<b>hôtel des ventes</b> (HdV) : les prix, et ce que rapportent tes métiers ;</li>
<li>🏰 les <b>donjons</b> : à quel niveau les faire, où est l'entrée, quels boss.</li>
</ul>
<p>Le site et le bot Discord sont reliés : ce que tu fais ici apparaît sur Discord, et l'inverse.
Tu n'as rien à installer, il suffit d'un navigateur (Chrome, Firefox, Edge, Safari…), sur ordinateur comme sur
téléphone.</p>
<h3>Tes premiers pas</h3>
{_first_steps()}"""),
        Section("connexion", "Se connecter", f"""
<p>Le site est réservé aux membres du serveur Discord. Pour entrer, on utilise ton compte Discord : pas de mot de
passe en plus à retenir.</p>
{shot("connexion", "La page qui s'affiche quand tu n'es pas connecté.", [("btn", "Le bouton pour te connecter.")])}
{steps(
    f"Clique sur le bouton {ui('Se connecter avec Discord')}.",
    "Tu arrives sur une page de Discord. Si Discord te demande ton e-mail et ton mot de passe, ce sont ceux de ton "
    "compte Discord (le site ne les voit jamais).",
    f"La première fois, Discord te demande si tu autorises <b>WoW Planner</b> à voir ton nom d'utilisateur : "
    f"clique sur {ui('Autoriser')}.",
    "Tu reviens automatiquement sur le site, connecté. Ton pseudo apparaît en haut à droite.",
)}
{note("Tu restes connecté pendant <b>30 jours</b> sur cet appareil (ordinateur, téléphone…). Ensuite, il suffit de "
      "recliquer sur le bouton. Si tu quittes le serveur Discord, l'accès au site s'arrête tout seul.")}
{tip("Les pages <b>Donjons</b> et cette page d'aide se consultent même sans être connecté.")}"""),
        Section("barre", "Se repérer : la barre du haut", f"""
<p>En haut de chaque page, la même barre te permet d'aller partout. Clique sur un mot pour ouvrir la page.
La page où tu es est soulignée.</p>
{shot("barre", "La barre du haut, présente sur toutes les pages.", [
    ("brand", "<b>WoW Planner</b> : te ramène à la page d'accueil (la Guilde)."),
    ("sorties", "<b>Sorties</b> : les donjons et raids prévus, pour t'inscrire."),
    ("guilde", "<b>Guilde</b> : la liste de tous les persos du serveur."),
    ("metiers", "<b>Métiers</b> : qui a quel métier, et les recettes."),
    ("atelier", "<b>Atelier</b> : commander un objet à un artisan."),
    ("hdv", "<b>Hôtel des ventes</b> : les prix de l'HdV."),
    ("donjons", "<b>Donjons</b> : niveaux, entrées et boss."),
    ("aide", "<b>Aide</b> : la page que tu lis."),
    ("menu", "<b>Ton menu</b> : ton pseudo, tes persos, le thème et la déconnexion."),
])}
{tip("Sur téléphone, la barre passe sur plusieurs lignes : tous les mots sont là, un peu serrés.")}"""),
        Section("menu", "Ton menu (en haut à droite)", f"""
<p>Clique sur ton pseudo, en haut à droite : un menu s'ouvre. Pour le fermer, clique n'importe où ailleurs (ou
appuie sur {k("Échap")}).</p>
{shot("menu", "Le menu ouvert.", [
    ("chars", "Tes persos : clique sur un nom pour ouvrir sa fiche. Ton perso préféré ⭐ est en premier."),
    ("gerer", "<b>Gérer mes persos</b> : ajouter, supprimer, choisir le rôle et le préféré."),
    ("rentab", "<b>Rentabilité de mes métiers</b> : ce que tes métiers rapportent."),
    ("calc", "<b>Calculatrice HdV</b> : vendre tel quel ou fabriquer ?"),
    ("theme", "<b>Thème</b> : les couleurs du site (Alliance, Hurlevent, Forgefer, Darnassus, Gnomeregan)."),
    ("admin", "<b>Administration</b> : seulement pour les modérateurs du Discord."),
    ("logout", "<b>Déconnexion</b> : pour quitter le site sur cet appareil (utile sur un ordinateur partagé)."),
])}
{note("Le thème choisi est retenu sur cet appareil. Il ne change que les couleurs, pas le contenu.")}"""),
        Section("gestes", "Les gestes de base", f"""
<p>Si tu n'as pas l'habitude des sites internet, voici tout ce qu'il faut savoir pour utiliser celui-ci.</p>
{table(["Pour…", "Sur ordinateur", "Sur téléphone"], [
    ["Ouvrir une page, un lien, appuyer sur un bouton", "Clic gauche de la souris", "Toucher avec le doigt"],
    ["Revenir à la page d'avant", f"Flèche ← en haut à gauche du navigateur, ou {k('Alt')} + {k('←')}",
     "Geste ou bouton « retour » du téléphone"],
    ["Voir le bas de la page", "Molette de la souris", "Glisser le doigt vers le haut"],
    ["Voir une infobulle (explication qui apparaît)", "Poser la souris dessus sans cliquer (« survoler »)",
     "Toucher l'élément une fois"],
    ["Choisir dans une liste déroulante (▾)", "Clic dessus, puis clic sur le choix", "Toucher, puis choisir"],
    ["Cocher / décocher une case ☐", "Clic dans la case ou sur son texte", "Toucher la case"],
    ["Écrire dans un champ", "Clic dans le champ, puis taper", "Toucher le champ : le clavier s'ouvre"],
    ["Agrandir le texte", f"{k('Ctrl')} + {k('+')} (et {k('Ctrl')} + {k('-')} pour réduire, {k('Ctrl')} + {k('0')} pour revenir)",
     "Écarter deux doigts sur l'écran"],
    ["Recharger la page (voir les dernières infos)", f"{k('F5')}, ou la flèche ↻ du navigateur", "Tirer la page vers le bas"],
    ["Chercher un mot dans la page", f"{k('Ctrl')} + {k('F')}", "Menu du navigateur → « Rechercher dans la page »"],
])}
<h3>Les éléments que tu vas croiser</h3>
<ul class="hlist">
<li><b>Les champs de recherche</b> (cadre avec un texte gris, par ex. « Chercher un perso… ») : tape quelques
lettres, la liste se filtre <i>tout de suite</i>, pas besoin d'appuyer sur Entrée. Pas besoin non plus des accents ni
des majuscules : « etoffe » trouve « Étoffe ».</li>
<li><b>Les listes déroulantes</b> (cadre avec une petite flèche ▾) : elles proposent des choix. Sur certaines pages,
la page se met à jour dès que tu choisis.</li>
<li><b>Les sections repliables</b> (titre précédé de ▸) : clique sur le titre pour ouvrir ou fermer.</li>
<li><b>Les onglets</b> (boutons alignés comme des intercalaires) : chacun montre une partie de la page.</li>
<li><b>Les liens avec ↗</b> : ils ouvrent un autre site (Discord, un guide…), souvent dans un nouvel onglet. Pour revenir,
clique sur l'onglet de WoW Planner en haut de ton navigateur.</li>
<li><b>Les messages en couleur</b> en haut de page après une action : vert = c'est fait, rouge = ça n'a pas marché
(le message explique pourquoi).</li>
<li><b>Les questions de confirmation</b> (« Supprimer… ? ») : le site demande avant toute action qu'on ne peut pas
défaire. Clique sur <i>OK</i> pour confirmer, sur <i>Annuler</i> pour ne rien faire.</li>
</ul>"""),
        Section("mobile", "Sur téléphone", f"""
{shot("mobile", "Le site sur un téléphone.", [
    ("nav", "Les pages, sur plusieurs lignes."),
    ("menu", "Ton menu : touche ☰ ou ton pseudo."),
])}
<p>Tout le site marche sur téléphone. Les grands tableaux (Guilde, HdV…) peuvent être plus larges que l'écran :
<b>fais-les glisser de droite à gauche avec le doigt</b> pour voir les colonnes cachées.</p>
{tip("Pour retrouver le site facilement, ajoute-le à l'écran d'accueil de ton téléphone : dans le menu du navigateur, "
     "« Ajouter à l'écran d'accueil ». Il apparaîtra comme une application.")}"""),
    ])

    sorties = Chapter("sorties", "📅", "Sorties", "S'inscrire à un donjon ou un raid, créer et gérer une sortie.", [
        Section("lire", "Lire une sortie", f"""
<p>La page <b>Sorties</b> montre les donjons et raids prévus, du plus proche au plus lointain. Chaque sortie est une
carte :</p>
{shot("sortie", "Une sortie à laquelle tu n'es pas encore inscrit.", [
    ("titre", "Le donjon ou raid, le jour et l'heure, le niveau conseillé, l'organisateur et le nombre d'inscrits."),
    ("discord", "Le même message sur Discord."),
    ("roles", "Les places par rôle : qui est inscrit, et les places libres (—). « 1/1 » = rôle complet."),
    ("perso", "Le perso avec lequel tu t'inscris."),
    ("boutons", "Un bouton par rôle pour t'inscrire."),
])}
<p>Les noms des persos sont en couleur de classe (comme dans le jeu) : clique dessus pour ouvrir leur fiche.
À côté, en petit, la classe et le pseudo Discord du joueur.</p>"""),
        Section("inscrire", "S'inscrire", f"""
{steps(
    f"Va sur la page {ui('Sorties')}.",
    "Sur la carte de la sortie, choisis ton perso dans la liste déroulante. Ton perso préféré ⭐ est déjà choisi.",
    f"Clique sur le rôle que tu veux tenir : {ui('🛡️ Tank')}, {ui('⛑️ Heal')} ou {ui('⚔️ DPS')}.",
    "Un message vert confirme l'inscription. Ton nom apparaît dans la colonne du rôle, et la carte est entourée de jaune.",
)}
{note("Un rôle grisé (« complet ») n'a plus de place. Les rôles proposés dépendent aussi de ta classe : un mage ne peut "
      "être que DPS. Pas sûr de ce que ta classe peut faire ? Regarde le petit outil plus bas.")}
{tip("T'inscrire ici ou en cliquant les boutons du message sur Discord, c'est exactement pareil : les deux restent à jour.")}
<h3>Quel rôle pour ma classe ?</h3>
{_role_widget()}"""),
        Section("changer", "Changer de rôle, de perso, se désinscrire", f"""
{shot("sortie-inscrit", "Une sortie où tu es inscrit (et que tu organises).", [
    ("moi", "Toi : ton nom est en gras."),
    ("changer", "Choisis un autre perso ou clique un autre rôle pour changer."),
    ("quitter", f"{ui('Me désinscrire')} : tu libères ta place."),
    ("annuler", f"{ui('Annuler la sortie')} : seulement pour l'organisateur (et les modérateurs)."),
    ("retirer", "✕ : retirer quelqu'un de la sortie (organisateur et modérateurs)."),
])}
<ul class="hlist">
<li><b>Changer de rôle</b> : clique simplement sur l'autre rôle. Le rôle actuel est en jaune.</li>
<li><b>Changer de perso</b> : choisis l'autre perso dans la liste, puis clique sur le rôle.</li>
<li><b>Se désinscrire</b> : bouton {ui('Me désinscrire')}. Pense à le faire si tu ne peux plus venir, pour laisser la
place à quelqu'un d'autre !</li>
</ul>
{note("Avant la sortie, le bot t'envoie un rappel en message privé sur Discord (30 minutes avant, en général). Un salon "
      "vocal est aussi créé un peu avant pour le groupe.")}"""),
        Section("creer", "Créer une sortie", f"""
{shot("nouvelle-sortie", "Le formulaire « Nouvelle sortie », ouvert.", [
    ("instance", "Le donjon ou raid : tape quelques lettres et choisis dans la liste (ou écris un nom libre)."),
    ("date", "Le jour : clique pour ouvrir un calendrier."),
    ("heure", "L'heure de rendez-vous."),
    ("nombres", "Le nombre de joueurs, tanks, heals, DPS. Laisse vide pour la composition habituelle."),
    ("desc", "Un mot pour les joueurs (facultatif) : stuff conseillé, lieu de rendez-vous…"),
    ("bouton", "Crée la sortie et la poste sur Discord."),
])}
{steps(
    f"Sur la page {ui('Sorties')}, clique sur {ui('➕ Nouvelle sortie')} pour ouvrir le formulaire.",
    "Remplis le donjon, la date et l'heure. Le reste est facultatif.",
    f"Clique sur {ui('Créer la sortie et la poster sur Discord')}.",
    "La sortie apparaît sur le site et dans le salon des sorties de Discord. Tu en es l'organisateur.",
)}
{tip("Depuis la fiche d'un donjon (page Donjons), le bouton ➕ Créer une sortie ouvre ce formulaire déjà rempli.")}"""),
        Section("gerer", "Gérer ta sortie", f"""
<p>Si tu es l'organisateur d'une sortie (ou modérateur du Discord), tu as deux boutons en plus sur sa carte :</p>
<ul class="hlist">
<li>{ui('Annuler la sortie')} : la sortie est annulée et les inscrits sont prévenus sur Discord. Le site demande
confirmation avant.</li>
<li><b>✕</b> à côté d'un inscrit : le retire de la sortie (par exemple s'il ne répond plus).</li>
</ul>
{warn("Une sortie annulée ne peut pas être rétablie : il faudra en recréer une.")}
{go("/sorties", "Ouvrir la page Sorties")}"""),
    ])

    guilde = Chapter("guilde", "🛡️", "Guilde et fiches persos",
                     "La liste des persos, et tout ce que montre la fiche d'un perso.", [
        Section("liste", "La liste de la guilde", f"""
{shot("guilde", "La page Guilde.", [
    ("q", "Chercher un perso par son nom, sa classe ou sa race."),
    ("classe", "Ne garder qu'une classe…"),
    ("role", "…un rôle (tank, heal, DPS)…"),
    ("metier", "…ou un métier."),
    ("perso", "Clique sur un perso pour ouvrir sa fiche."),
    ("metiers", "Ses métiers et leur niveau (sur 300)."),
])}
<p>Les filtres se combinent : par exemple « Prêtre » + « Heal » montre les prêtres soigneurs. Le nombre de persos
affichés est rappelé sous le titre. Le ⭐ dans la colonne Rôles indique le rôle préféré du joueur.</p>"""),
        Section("fiche", "La fiche d'un perso", f"""
<p>La fiche reprend ce que montre le jeu : l'équipement porté autour du personnage, et ses caractéristiques à côté.
Les infos viennent de l'<b>armurerie Blizzard</b> et sont relues chaque nuit.</p>
{shot("fiche", "Le haut de la fiche d'un perso.", [
    ("titre", "Niveau, classe, race, spécialisation (points de talents) et rôles."),
    ("objet", "Un objet porté. Couleur = qualité (blanc, vert, bleu, violet). Survole-le pour le détail."),
    ("rendu", "Le perso tel qu'il apparaît en jeu."),
    ("spe", "La spécialisation pour laquelle les stats sont classées : change-la ici."),
    ("prio", "Les stats à privilégier pour cette spé, dans l'ordre."),
    ("stats", "Toutes les caractéristiques. Survole-en une pour savoir à quoi elle sert."),
])}
{note("« synchronisé avec l'armurerie le … » indique la date des infos. Si ton perso a changé (nouveau stuff, niveau), "
      "attends la synchro de la nuit : l'armurerie de Blizzard met elle-même un peu de temps à se mettre à jour, "
      "et il faut s'être déconnecté du jeu.")}"""),
        Section("infobulles", "Les infobulles", f"""
<p>Beaucoup d'éléments ont une explication cachée qui apparaît quand tu poses la souris dessus (sur téléphone : touche
l'élément).</p>
<div class="hgrid2">
{shot("infobulle-objet", "Survol d'un objet : ses stats, comme dans le jeu.", [])}
{shot("infobulle-stat", "Survol d'une caractéristique : à quoi elle sert, pour ta classe.", [])}
</div>
<p>Les stats marquées ★ ou surlignées sont celles qui comptent le plus pour la spé choisie.</p>"""),
        Section("talents", "Les talents", f"""
{shot("talents", "Les trois arbres de talents.", [
    ("arbre", "Un arbre de talents, avec le nombre de points dépensés."),
    ("talent", "Un talent : rang actuel / rang maximum. Survole-le pour sa description."),
])}
<p>Les talents en couleur sont ceux qui ont des points ; les gris sont vides. Le titre de la fiche résume la répartition
(par ex. « 0 / 0 / 22 »).</p>"""),
        Section("equipement", "L'équipement fabricable par la guilde", f"""
<p>Sous la fiche, la section {ui('🛠️ Équipement fabricable par la guilde')} liste les objets que les autres membres
savent fabriquer et que ce perso peut porter, emplacement par emplacement.</p>
{shot("equipement", "La section ouverte.", [
    ("case", "Coche pour ne garder que ce qui est <b>mieux</b> que l'objet porté."),
    ("groupe", "Un emplacement, avec l'objet porté actuellement en rappel."),
    ("carte", "Un objet fabricable : stats, niveau requis, qui sait le faire."),
])}
{tip("Le lien 🛒 Commander d'une carte ouvre directement l'atelier pour le demander à l'artisan.")}"""),
        Section("recettes", "Métiers et recettes d'un perso", f"""
{shot("recettes", "Les recettes d'un perso, rangées par métier.", [
    ("q", "Chercher une recette, un composant ou un effet (ex. « agilité », « soins »)."),
    ("plier", "Tout ouvrir ou tout fermer d'un coup."),
    ("onglets", "Un onglet par métier, avec le nombre de recettes."),
    ("famille", "Les recettes sont rangées par type d'objet : clique sur un titre pour l'ouvrir."),
])}
<p>Chaque carte de recette montre l'objet fabriqué, ses composants (avec les quantités) et les persos qui la connaissent.
Seules les recettes vues dans l'armurerie de Blizzard apparaissent.</p>
{go("/", "Ouvrir la page Guilde")}"""),
    ])

    persos = Chapter("persos", "👤", "Mes persos", "Ajouter tes persos, choisir ton préféré et ton rôle.", [
        Section("page", "La page Mes persos", f"""
<p>On y arrive par ton menu (en haut à droite) → {ui('Gérer mes persos')}. Elle liste tes persos, qu'ils aient été
ajoutés ici ou sur Discord.</p>
{shot("mes-persos", "La page Mes persos.", [
    ("etoile", "L'étoile : ton perso préféré."),
    ("role", "Le rôle que tu préfères jouer avec ce perso."),
    ("supprimer", "Supprimer le perso du site."),
    ("nom", "Le nom d'un nouveau perso à ajouter."),
    ("ajouter", "Le bouton pour l'ajouter."),
])}"""),
        Section("ajouter", "Ajouter un perso", f"""
{steps(
    "Dans le champ <b>Nom du perso</b>, tape le nom <b>exact</b> de ton perso, comme en jeu (avec les accents si besoin). "
    "Sur WoW Forever les persos ont un prénom et un nom : « Hollie Tétine ».",
    "Pendant que tu tapes, le site cherche le perso dans l'armurerie de Blizzard et affiche ce qu'il trouve "
    "(classe, race, niveau). Tant qu'il ne l'a pas trouvé, le bouton reste grisé.",
    "Choisis éventuellement ton rôle préféré.",
    f"Clique sur {ui('Ajouter')}. Le perso apparaît dans le tableau, avec ses métiers et son équipement.",
)}
{warn("Si le site ne trouve pas ton perso : vérifie l'orthographe, et qu'il a été joué récemment. Un perso tout neuf "
      "(ou pas joué depuis longtemps) peut mettre un moment à apparaître dans l'armurerie de Blizzard.")}
{note("Classe, race, niveau et métiers viennent de l'armurerie : tu n'as rien à remplir à la main, et c'est mis à jour "
      "chaque nuit.")}"""),
        Section("favori", "Le perso préféré ⭐", """
<p>Clique sur l'étoile ☆ d'un perso pour en faire ton <b>préféré</b> : elle devient ★. Ce perso est alors proposé en
premier pour t'inscrire aux sorties (sur le site comme sur Discord), et il est en tête de ton menu.</p>
<p>Un seul préféré à la fois : en choisir un autre remplace le précédent. Reclique sur ★ pour ne plus en avoir.</p>"""),
        Section("role", "Le rôle préféré", f"""
<p>La liste déroulante <b>Rôle préféré</b> enregistre le rôle que tu joues d'habitude avec ce perso (tank, heal, DPS).
Il est indiqué avec un ⭐ dans la page Guilde, pour que les organisateurs sachent sur qui compter. Le choix est
enregistré dès que tu le changes.</p>
<h3>Quel rôle pour ma classe ?</h3>{_role_widget()}"""),
        Section("supprimer", "Supprimer un perso", f"""
<p>Le bouton {ui('Supprimer')} retire le perso du site (et ses métiers). Le site demande confirmation avant. Tes
inscriptions aux sorties restent, mais sans le nom du perso.</p>
{note("Chaque nuit, les persos ajoutés sur Discord qui restent introuvables dans l'armurerie au bout de 2 jours sont "
      "retirés automatiquement (tu es prévenu en message privé). Ça évite les fautes de frappe qui traînent.")}
{go("/mes-persos", "Ouvrir Mes persos")}"""),
    ])

    metiers = Chapter("metiers", "⚒️", "Métiers et atelier",
                      "Trouver qui sait fabriquer quoi, et commander un objet.", [
        Section("metiers", "La page Métiers", f"""
{shot("metiers", "Une case par métier.", [
    ("tuile", "Un métier : nombre de persos qui l'ont et de recettes connues sur le serveur. Clique pour le détail."),
])}
<p>La page d'un métier montre <b>qui l'a</b> (avec son niveau sur 300), puis toutes les recettes connues sur le
serveur, avec une recherche.</p>
{tip("La recherche marche aussi sur les effets : tape « endurance » dans Couture pour trouver tout ce qui en donne.")}"""),
        Section("commander", "Commander un objet", f"""
<p>L'<b>atelier</b> sert à demander à un artisan du serveur de te fabriquer un objet.</p>
{steps(
    f"Va sur la page {ui('Atelier')}.",
    f"Tape le nom de l'objet (un bout suffit : « mangouste », « sac en lin ») et clique sur {ui('Chercher')}.",
    f"Dans les résultats, clique sur {ui('🛒 Commander')} à côté de l'objet voulu.",
    "Choisis l'artisan (s'il y en a plusieurs), la quantité, et ajoute un petit mot si tu veux.",
    f"Clique sur {ui('📨 Envoyer la commande')}. L'artisan reçoit un message privé sur Discord.",
)}
{shot("commande", "Le formulaire de commande.", [
    ("recette", "L'objet et ses composants."),
    ("artisan", "Qui va le fabriquer."),
    ("quantite", "Combien tu en veux."),
    ("mot", "Un mot pour l'artisan (facultatif)."),
    ("envoyer", "Envoyer la commande."),
])}
{note("Les composants et la livraison se règlent entre vous <b>dans le jeu</b> (courrier, échange). Le site sert juste "
      "à demander et à suivre.")}
{tip("Tu peux aussi commander depuis une carte de recette (page Métiers) ou depuis l'équipement fabricable d'une fiche "
     "perso : cherche le lien 🛒 Commander.")}"""),
        Section("suivre", "Suivre ses commandes", f"""
{shot("atelier", "La page Atelier, en bas : tes commandes.", [
    ("recherche", "Chercher un objet à commander."),
    ("recues", "Ce qu'on t'a demandé de fabriquer."),
    ("passees", "Ce que tu as commandé."),
])}
<p>Une commande passe par ces étapes :</p>
{table(["Statut", "Ce que ça veut dire", "Qui peut agir"], [
    ["⏳ En attente de réponse", "L'artisan n'a pas encore répondu.", "L'artisan : <b>Accepter</b> ou <b>Refuser</b>. Toi : <b>Annuler ma commande</b>."],
    ["🔨 Acceptée, en préparation", "L'artisan s'en occupe.", "L'artisan : <b>C'est prêt</b> ou <b>Abandonner</b>. Toi : <b>Annuler ma commande</b>."],
    ["✅ Prête", "C'est fabriqué : récupère-la en jeu.", "—"],
    ["❌ Refusée", "L'artisan ne peut pas (ou a abandonné).", "—"],
    ["🚫 Annulée", "Tu as annulé.", "—"],
])}
<p>Chacun est prévenu par message privé Discord à chaque étape, et peut répondre sur Discord ou ici.</p>
{go("/atelier", "Ouvrir l'atelier")}"""),
    ])

    hdv = Chapter("hdv", "💰", "Hôtel des ventes", "Les prix de l'HdV, les favoris et l'historique des prix.", [
        Section("monnaie", "Lire un prix : po, pa, pc", f"""
<p>Dans WoW, l'argent se compte en trois pièces : <b>po</b> (pièces d'or), <b>pa</b> (pièces d'argent) et
<b>pc</b> (pièces de cuivre). <b>1 po = 100 pa</b> et <b>1 pa = 100 pc</b>. Sur le site, chaque prix est en trois
colonnes, une par pièce, pour comparer d'un coup d'œil.</p>
{_coin_widget()}"""),
        Section("liste", "La liste des prix", f"""
{shot("hdv", "La page Hôtel des ventes.", [
    ("q", "Chercher un objet par son nom."),
    ("type", "Ne montrer qu'un type d'objets (artisanat, armures…). Un second choix apparaît ensuite pour préciser."),
    ("tri", "L'ordre : par nom, par prix, par quantité…"),
    ("fav", "Ne montrer que tes favoris."),
    ("etoile", "Ajouter / retirer l'objet de tes favoris."),
    ("bas", "Le prix le plus bas en ce moment, pour <b>une</b> unité."),
    ("median", "Le prix « du milieu » des annonces : plus fiable que le plus bas si une seule annonce est bradée."),
    ("dispo", "Combien d'exemplaires sont en vente, et en combien d'annonces."),
    ("var", "L'évolution du prix le plus bas sur 24 h : ▲ rouge = plus cher, ▼ vert = moins cher."),
])}
<p>Les prix sont relevés chez Blizzard <b>toutes les heures</b> (la date est sous le titre). Ce sont ceux de notre
hôtel des ventes de l'Alliance. Les objets sont en couleur de qualité (gris, blanc, vert, bleu, violet).</p>
{tip("Avec beaucoup de résultats, des boutons ← Précédents / Suivants → en bas de page permettent de tourner les pages.")}"""),
        Section("cours", "Le cours d'un objet", f"""
{shot("hdv-survol", "Survole un prix : la courbe des 7 derniers jours apparaît.", [])}
{shot("hdv-objet", "Clique sur un objet : sa fiche détaillée.", [
    ("periode", "La période de la courbe : 24 h à 90 jours."),
    ("courbe", "Le prix le plus bas (trait plein) et médian. Survole la courbe pour lire une date précise."),
])}
<p>La fiche d'un objet montre aussi les derniers relevés, son prix chez le marchand, et les recettes du serveur qui
l'utilisent ou le fabriquent.</p>
{tip("Avant de vendre, regarde la courbe : si le prix est au plus bas de la semaine, attendre quelques jours peut rapporter plus.")}"""),
        Section("ventes", "Les ventes et les heures de demande", f"""
<p>Dans le même graphique, sous la courbe des prix, des <b>barres bleues</b> montrent combien d'exemplaires se sont vendus chaque heure : survole le graphique pour lire le prix et les ventes d'une même heure.
Plus haut sur la fiche, la case {ui('Vendus (24 h)')} donne le total de la dernière journée.</p>
<p>Tout en bas, le graphique <b>« Quand ça se vend »</b> range les ventes par heure de la journée (moyenne sur la
dernière semaine) : on voit d'un coup d'œil les heures où les acheteurs sont là. L'heure actuelle est en jaune.
Survole (ou touche) une barre pour lire le chiffre exact.</p>
{note("Ce sont des <b>estimations</b> : Blizzard ne dit pas ce qui est vendu. Le site compare les annonces d'une heure "
      "à l'autre : une annonce qui disparaît alors qu'il lui restait plusieurs heures a été achetée (ou, plus "
      "rarement, retirée par son vendeur). Les annonces qui arrivaient à leur fin ne sont pas comptées.")}
{tip("Pour vendre vite, mets tes annonces juste avant les heures où ça se vend le plus.")}
{go("/hdv", "Ouvrir l'hôtel des ventes")}"""),
    ])

    argent = Chapter("argent", "📈", "Rentabilité et calculatrice",
                     "Ce que rapportent tes métiers, et que faire de ton stock.", [
        Section("rentabilite", "Rentabilité de mes métiers", f"""
<p>On y arrive par ton menu → {ui('💰 Rentabilité de mes métiers')}. La page calcule, aux prix actuels de l'HdV,
ce que rapporte chaque recette que ton perso connaît.</p>
{shot("rentabilite", "La rentabilité d'un perso.", [
    ("perso", "Le perso à étudier (seuls ceux qui ont un métier sont proposés)."),
    ("onglets", "Un onglet par métier."),
    ("vente", "Ce que rapporte la vente de l'objet fabriqué, commission de l'HdV déduite."),
    ("cout", "Ce que coûtent les composants (au prix de l'HdV, ou du marchand s'il les vend)."),
    ("benef", "Le bénéfice : vente moins composants. En haut de liste, les plus rentables."),
])}
<ul class="hlist">
<li><b>Marge</b> : le bénéfice en pourcentage du coût.</li>
<li><b>Marchand</b> : ce qu'un marchand PNJ te donne pour l'objet (le minimum garanti).</li>
<li><b>En vente</b> : combien il y en a déjà à l'HdV. Beaucoup = concurrence, ça risque de partir lentement.</li>
<li>Les lignes grisées : l'objet n'est pas en vente en ce moment, donc pas de prix fiable.</li>
<li>Pour les métiers de <b>récolte</b> (herboristerie, minage, dépeçage, pêche), la page liste les ressources que
tu peux récolter à ton niveau, de la plus chère à la moins chère.</li>
</ul>
{warn("Ce sont des estimations aux prix du dernier relevé : les prix bougent, et ce qui est en vente ne se vend pas "
      "forcément tout de suite.")}"""),
        Section("calculatrice", "La calculatrice HdV", f"""
<p>Tu as des sacs pleins de ressources ? La calculatrice compare deux choses : <b>tout vendre tel quel</b>, ou
<b>fabriquer</b> avec tes recettes puis vendre.</p>
{steps(
    f"Ouvre ton menu → {ui('🧮 Calculatrice HdV')} et choisis ton perso.",
    "Dans le tableau <b>Ton stock</b>, tape la quantité de chaque ressource que tu as (cherche-la avec le champ de "
    "recherche, ou filtre par catégorie). La valeur se calcule en direct.",
    f"Clique sur {ui('🧮 Calculer')}.",
    "En haut apparaît le <b>Résultat</b> : combien rapporte la vente brute, combien rapporte le plan conseillé, et "
    "quelles recettes fabriquer dans quel ordre.",
)}
{shot("calc-stock", "Le tableau du stock.", [
    ("cat", "Filtrer par catégorie."),
    ("q", "Chercher une ressource."),
    ("mine", "Ne montrer que ce que tu as renseigné."),
    ("qte", "Ta quantité."),
    ("calc", "Lancer le calcul."),
])}
{shot("calc-resultat", "Le résultat : la vente brute, le plan conseillé (quoi fabriquer, dans quel ordre) et ce "
      "qu'il rapporte de plus.", [
    ("faits", "Vente brute, plan conseillé, et la différence."),
    ("plan", "Le plan conseillé : les recettes à fabriquer, dans l'ordre."),
])}
<ul class="hlist">
<li><b>Masquer ce qui est hors de ma compétence</b> : cache les ressources que ton perso ne peut pas récolter
lui-même.</li>
<li>Un <b>astérisque *</b> signale une ressource obtenue « en bonus » (par chance), par exemple les gemmes en minant.</li>
<li>{ui('Vider')} remet toutes les quantités à zéro.</li>
</ul>
{tip("Pas de métier de fabrication ? La calculatrice donne quand même la valeur de ton stock vendu brut. Pour le faire "
     "transformer par quelqu'un, passe par l'atelier.")}
{go("/calculatrice", "Ouvrir la calculatrice")}"""),
    ])

    donjons = Chapter("donjons", "🏰", "Donjons", "Quels donjons à quel niveau, où est l'entrée, quels boss.", [
        Section("liste", "La liste des donjons", f"""
{shot("donjons", "La page Donjons, avec un niveau choisi.", [
    ("q", "Chercher un donjon ou une zone."),
    ("perso", "Choisis un de tes persos : son niveau se remplit tout seul…"),
    ("niveau", "…ou tape un niveau à la main."),
    ("tranche", "Coche pour ne garder que les donjons de ce niveau."),
    ("ligne", "En surbrillance : les donjons faits pour ce niveau. Clique sur une ligne pour la fiche du donjon."),
    ("barre", "La barre montre la tranche de niveaux du donjon, et le trait ton niveau."),
    ("qui", "Les persos du serveur qui ont le bon niveau : de quoi monter un groupe."),
])}
<p>Les donjons « bientôt à ta portée » (2 niveaux au-dessus) sont légèrement marqués. Le badge <b>Nouveau</b> signale
les donjons propres à WoW Forever. Plus bas, le tableau des <b>raids</b> donne leur taille et leur date d'ouverture.</p>
{note("Les niveaux sont des conseils, pas des interdictions : on peut entrer avant, mais ce sera difficile.")}"""),
        Section("fiche", "La fiche d'un donjon", f"""
{shot("donjon", "La fiche d'un donjon.", [
    ("faits", "Niveaux, taille du groupe et nombre de boss."),
    ("creer", "Créer une sortie pour ce donjon (formulaire prérempli)."),
    ("entree", "Comment trouver l'entrée."),
    ("way", "Les coordonnées : clique pour copier la commande /way."),
    ("guide", "La carte détaillée et les stratégies, sur un site de guides."),
    ("qui", "Les persos du serveur qui ont le bon niveau."),
    ("route", "Les boss dans l'ordre habituel ; ◇ = boss optionnel."),
])}
<h3>À quoi sert le bouton /way ?</h3>
<p>Il copie une commande comme <code>/way Marche de l'Ouest 42 72</code>. Si tu as l'addon <b>TomTom</b> dans le jeu,
colle-la dans la fenêtre de discussion ({k("Ctrl")} + {k("V")} puis {k("Entrée")}) : une flèche te guide jusqu'à
l'entrée. Sans TomTom, les deux nombres sont les coordonnées sur la carte du jeu (de gauche à droite, puis de haut
en bas).</p>
{go("/donjons", "Ouvrir la page Donjons")}"""),
    ])

    discord = Chapter("discord", "🤖", "Le bot Discord", "Ce qu'on peut faire directement sur Discord.", [
        Section("commandes", "Les commandes du bot", f"""
<p>Sur Discord, tape <code>/</code> dans un salon du serveur : la liste des commandes apparaît. Les principales :</p>
{table(["Commande", "À quoi elle sert"], [
    ["<code>/ajouter event</code>", "Créer une sortie (comme ➕ Nouvelle sortie sur le site)."],
    ["<code>/ajouter perso</code>", "Déclarer un de tes persos."],
    ["<code>/supprimer perso</code>", "Retirer un de tes persos."],
    ["<code>/supprimer event</code>", "Annuler une de tes sorties."],
    ["<code>/supprimer inscrit</code>", "Retirer quelqu'un de ta sortie."],
    ["<code>/liste events</code>", "Les prochaines sorties."],
    ["<code>/commander</code>", "Commander un objet à un artisan (comme l'atelier du site)."],
    ["<code>/ajouter battletag</code>", "Enregistrer ton BattleTag pour que les autres t'ajoutent en ami (il n'apparaît jamais sur le site)."],
    ["<code>/liste battletags</code>", "Les BattleTags des joueurs du serveur."],
])}
<p>Dans le salon des sorties, chaque sortie a des <b>boutons</b> pour s'inscrire dans un rôle ou se désinscrire, comme
sur le site. Le panneau de l'atelier a deux boutons : {ui('🛒 Commander')} et {ui('📦 Mes commandes')}.</p>"""),
        Section("lien", "Site ou Discord ?", """
<p>Les deux font la même chose et restent synchronisés : utilise ce qui t'arrange. Le site est plus confortable pour
<b>consulter</b> (fiches, prix, recettes), Discord pratique pour s'inscrire vite depuis son téléphone. Les messages
privés du bot (rappels, commandes) arrivent toujours sur Discord.</p>"""),
    ])

    faq_ch = Chapter("faq", "❓", "Questions et soucis", "Les problèmes fréquents, et le vocabulaire.", [
        Section("questions", "Questions fréquentes", "".join([
            faq("Le site me dit « Réservé aux membres ».",
                "<p>Tu n'es pas connecté (ou ta connexion a expiré après 30 jours). Clique sur <b>Se connecter avec "
                "Discord</b>. Si le site te répond « Accès refusé », c'est que ton compte Discord n'est pas membre du "
                "serveur : vérifie que tu es connecté à Discord avec le bon compte.</p>"),
            faq("Mon perso n'apparaît pas / le site ne le trouve pas.",
                "<p>Le nom doit être <b>exactement</b> celui du jeu, prénom et nom, accents compris. Le perso doit aussi "
                "exister dans l'armurerie de Blizzard : déconnecte-toi du jeu avec lui, puis réessaie un peu plus tard "
                "(parfois le lendemain).</p>"),
            faq("Mes métiers, mon niveau ou mon équipement ne sont pas à jour.",
                "<p>Le site relit l'armurerie de Blizzard <b>chaque nuit</b>. L'armurerie elle-même se met à jour quand "
                "tu te déconnectes du jeu. Patiente jusqu'au lendemain ; si rien ne bouge après 2 jours, préviens un "
                "modérateur.</p>"),
            faq("Mon perso n'a aucune recette.",
                "<p>Seules les recettes que Blizzard montre dans l'armurerie sont connues du site. Si ton perso vient "
                "d'apprendre un métier, attends la synchro de la nuit.</p>"),
            faq("Je ne peux pas m'inscrire dans un rôle (bouton grisé).",
                "<p>Soit le rôle est complet, soit ta classe ne peut pas le tenir (un mage ne peut pas tanker). Utilise "
                "l'outil « Quel rôle pour ma classe ? » dans le chapitre Sorties.</p>"),
            faq("J'ai cliqué et rien ne s'est passé.",
                "<p>Attends quelques secondes (certaines actions passent par Discord). Puis recharge la page "
                f"({k('F5')}, ou tirer vers le bas sur téléphone). Un message en haut de la page indique si l'action a "
                "marché ou pourquoi elle a échoué.</p>"),
            faq("Les prix de l'HdV sont anciens.",
                "<p>La date des données est écrite sous le titre de la page. Ils sont relevés toutes les heures ; si "
                "l'API de Blizzard ne répond plus, le site garde les derniers prix connus et le signale par ⚠️.</p>"),
            faq("La page est toute petite / trop grande.",
                f"<p>Sur ordinateur : {k('Ctrl')} + {k('+')} pour agrandir, {k('Ctrl')} + {k('-')} pour réduire, "
                f"{k('Ctrl')} + {k('0')} pour revenir à la normale. Sur téléphone : écarte ou pince deux doigts.</p>"),
            faq("Je ne vois pas tout le tableau sur mon téléphone.",
                "<p>Fais glisser le tableau vers la gauche avec le doigt : les colonnes de droite apparaissent.</p>"),
            faq("Je n'aime pas les couleurs.",
                "<p>Ouvre ton menu (en haut à droite) → <b>Thème</b>, et choisis-en un autre.</p>"),
            faq("Mes infos personnelles sont-elles visibles ?",
                "<p>Le site ne montre que les persos, leurs métiers et ce qui concerne le jeu. Il ne voit de ton compte "
                "Discord que ton pseudo, jamais ton e-mail ni tes messages. Les BattleTags ne sont jamais affichés sur "
                "le site.</p>"),
            faq("Je ne trouve pas la réponse à ma question.",
                "<p>Demande sur le Discord du serveur : quelqu'un t'aidera !</p>"),
        ])),
        Section("lexique", "Petit lexique", table(["Mot", "Signification"], [
            ["<b>Sortie</b>", "Un rendez-vous pour faire un donjon ou un raid en groupe."],
            ["<b>Donjon</b>", "Une zone pour un groupe de 5 joueurs (parfois 10)."],
            ["<b>Raid</b>", "Un grand donjon pour 10, 20 ou 40 joueurs, au niveau 60."],
            ["<b>Tank</b> 🛡️", "Celui qui encaisse les coups et attire les monstres sur lui."],
            ["<b>Heal</b> ⛑️", "Le soigneur du groupe."],
            ["<b>DPS</b> ⚔️", "Ceux qui font les dégâts (« dégâts par seconde »)."],
            ["<b>Spé</b>", "Spécialisation : l'arbre de talents principal d'un perso (ex. Sacré, Ombre)."],
            ["<b>Stuff</b>", "L'équipement porté."],
            ["<b>Niveau d'objet</b>", "La puissance d'un objet : plus il est haut, mieux c'est."],
            ["<b>Armurerie</b>", "Le site de Blizzard qui donne les infos des persos ; le nôtre s'en sert chaque nuit."],
            ["<b>Synchro</b>", "La mise à jour automatique des infos depuis l'armurerie (chaque nuit à 4 h)."],
            ["<b>HdV</b>", "Hôtel des ventes : le marché du jeu entre joueurs."],
            ["<b>po / pa / pc</b>", "Pièces d'or, d'argent, de cuivre. 1 po = 100 pa = 10 000 pc."],
            ["<b>Marchand</b>", "Un vendeur PNJ (personnage du jeu) : il achète tout à prix fixe, et vend certains composants."],
            ["<b>Composants</b>", "Ce qu'il faut pour fabriquer un objet (étoffe, minerai, fioles…)."],
            ["<b>Récolte</b>", "Les métiers qui ramassent des ressources : herboristerie, minage, dépeçage, pêche."],
            ["<b>MP</b>", "Message privé (sur Discord)."],
            ["<b>Infobulle</b>", "Le petit cadre d'explication qui apparaît quand on survole quelque chose."],
            ["<b>Survoler</b>", "Poser le pointeur de la souris sur un élément sans cliquer."],
            ["<b>/way</b>", "Une commande de l'addon TomTom qui affiche une flèche vers des coordonnées."],
        ])),
    ])

    admin = Chapter("admin", "🛠️", "Administration", "Pour les modérateurs : synchro, persos des membres.", [
        Section("page", "La page Administration", f"""
<p>Visible seulement des membres qui ont la permission « Gérer le serveur » sur Discord, depuis le menu →
{ui('🛠️ Administration')}.</p>
{shot("admin", "La page Administration.", [
    ("sync", "Relancer toute la synchro maintenant (sinon chaque nuit à 4 h). Ça peut prendre plusieurs minutes."),
    ("q", "Chercher un perso, un joueur ou une classe."),
    ("role", "Changer le rôle préféré d'un perso."),
    ("suppr", "Supprimer un perso : son joueur est prévenu en MP."),
])}
<ul class="hlist">
<li><b>Ajouter un perso à un membre</b> : en bas de la page, choisis le membre puis tape le nom du perso (vérifié dans
l'armurerie). Le membre est prévenu en MP.</li>
<li>Les persos marqués ⚠️ ont été ajoutés sur Discord mais restent introuvables : ils seront retirés automatiquement
au bout de 2 jours.</li>
<li>Sur la page Sorties, tu peux annuler n'importe quelle sortie et retirer n'importe quel inscrit.</li>
<li>Le panneau de l'atelier se poste sur Discord avec <code>/admin atelier</code> dans le salon voulu.</li>
</ul>"""),
    ], admin=True)

    return [debut, sorties, guilde, persos, metiers, hdv, argent, donjons, discord, faq_ch, admin]


HELP_SCRIPT = """
<script>
(() => {
  const root = document.querySelector(".help");
  if (!root) return;
  root.classList.add("js");
  const chapters = [...root.querySelectorAll(".help-ch")];
  const links = [...root.querySelectorAll(".help-nav a[data-ch]")];
  const q = document.getElementById("help-q"), info = document.getElementById("help-found");
  const norm = s => s.normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
  function show(key, anchor) {
    if (!chapters.some(c => c.dataset.ch === key)) key = chapters[0].dataset.ch;
    chapters.forEach(c => c.hidden = c.dataset.ch !== key);
    links.forEach(a => a.classList.toggle("active", a.dataset.ch === key));
    const target = anchor && document.getElementById(anchor);
    if (target) target.scrollIntoView({block: "start"});
    else if (!q.value) window.scrollTo({top: 0});
  }
  function fromHash() {
    const id = decodeURIComponent(location.hash.slice(1));
    if (q.value) { q.value = ""; search(); }
    show(id.split("-")[0], id.includes("-") ? id : null);
  }
  function search() {
    const text = norm(q.value.trim());
    root.classList.toggle("searching", !!text);
    if (!text) { info.hidden = true; fromHashQuiet(); return; }
    let n = 0;
    chapters.forEach(c => {
      let shown = 0;
      c.querySelectorAll(".help-sec").forEach(s => {
        const ok = s.dataset.search.includes(text);
        s.hidden = !ok; if (ok) shown++;
      });
      c.hidden = !shown; n += shown;
    });
    info.hidden = false;
    info.textContent = n ? n + " passage(s) trouvé(s) pour « " + q.value.trim() + " »" : "Rien trouvé : essaie un autre mot.";
  }
  function fromHashQuiet() {
    chapters.forEach(c => c.querySelectorAll(".help-sec").forEach(s => s.hidden = false));
    const id = decodeURIComponent(location.hash.slice(1));
    show(id.split("-")[0], null);
  }
  q.addEventListener("input", search);
  window.addEventListener("hashchange", fromHash);
  fromHash();

  // Repères des captures : survol ou clic sur un numéro ↔ la ligne de légende.
  root.querySelectorAll(".hshot").forEach(fig => {
    // Survol : surbrillance passagère ; clic : reste allumé (re-clic pour éteindre).
    let pinned = "";
    const set = n => {
      fig.classList.toggle("focus", !!n);
      fig.querySelectorAll("[data-n]").forEach(el => el.classList.toggle("on", el.dataset.n === n));
    };
    fig.querySelectorAll(".hmark, .hlegend li").forEach(el => {
      el.addEventListener("mouseenter", () => set(el.dataset.n));
      el.addEventListener("mouseleave", () => set(pinned));
      el.addEventListener("click", () => { pinned = pinned === el.dataset.n ? "" : el.dataset.n; set(pinned); });
    });
  });

  // Agrandir une capture.
  const box = document.getElementById("help-lightbox"), big = box.querySelector("img");
  root.querySelectorAll(".hpic").forEach(pic => {
    const open = () => { big.src = pic.querySelector("img").src; big.alt = pic.querySelector("img").alt; box.showModal(); };
    const zoom = pic.querySelector(".hzoom");
    if (zoom) zoom.addEventListener("click", open);
    pic.querySelector("img").addEventListener("click", open);
  });
  box.addEventListener("click", () => box.close());

  // Premiers pas : cases retenues sur l'appareil.
  const checks = [...root.querySelectorAll("#first-steps input[data-step]")];
  let done = {};
  try { done = JSON.parse(localStorage.getItem("wp-help-steps") || "{}"); } catch (e) {}
  const progress = () => {
    const n = checks.filter(c => c.checked).length;
    document.getElementById("hprog-n").textContent = n;
    document.getElementById("hprog-bar").style.width = (n / checks.length * 100) + "%";
  };
  checks.forEach(c => {
    c.checked = !!done[c.dataset.step];
    c.addEventListener("change", () => {
      done[c.dataset.step] = c.checked;
      try { localStorage.setItem("wp-help-steps", JSON.stringify(done)); } catch (e) {}
      progress();
    });
  });
  if (checks.length) progress();

  // Quel rôle pour ma classe ?
  root.querySelectorAll(".hw-role select").forEach(sel => {
    const out = sel.closest(".hwidget").querySelector(".hw-out");
    const data = JSON.parse(sel.closest(".hwidget").querySelector("script").textContent);
    sel.addEventListener("change", () => {
      const roles = data[sel.value];
      out.textContent = roles ? sel.options[sel.selectedIndex].text + " : " + roles.join(" · ") : "Choisis une classe pour voir les rôles qu'elle peut tenir.";
    });
  });

  // Pièces : po / pa / pc ↔ total en cuivre.
  const po = document.getElementById("hw-po"), pa = document.getElementById("hw-pa"), pc = document.getElementById("hw-pc");
  if (po) {
    const out = document.getElementById("hw-coin-out");
    const coins = () => {
      const total = (+po.value || 0) * 10000 + (+pa.value || 0) * 100 + (+pc.value || 0);
      const g = Math.floor(total / 10000), s = Math.floor(total / 100) % 100, c = total % 100;
      out.innerHTML = `<b>${g} po ${s} pa ${c} pc</b> = ${total.toLocaleString("fr-FR")} pièces de cuivre.`;
    };
    [po, pa, pc].forEach(i => i.addEventListener("input", coins));
    coins();
  }
})();
</script>
"""


class HelpPages:
    def __init__(self, site: WebSite):
        self.site = site

    def register(self, router: web.UrlDispatcher) -> None:
        router.add_get("/aide", self.help_page)
        router.add_get("/static/aide/{name}", self.image)

    async def image(self, request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        path = SHOTS_DIR / name
        if not IMAGE_NAME.match(name) or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    async def help_page(self, request: web.Request) -> web.Response:
        viewer = _VIEWER.get()
        is_admin = viewer is not None and viewer.admin
        shown = [c for c in chapters() if not c.admin or is_admin]
        nav, bodies = [], []
        for i, ch in enumerate(shown):
            nav.append(
                f'<li><a href="#{ch.key}" data-ch="{ch.key}"><span class="hi">{ch.icon}</span>'
                f"<span>{esc(ch.title)}</span></a></li>"
            )
            toc = "".join(f'<li><a href="#{ch.key}-{s.key}">{esc(s.title)}</a></li>' for s in ch.sections)
            secs = "".join(
                f'<article class="help-sec" id="{ch.key}-{s.key}" '
                f'data-search="{esc(normalize(s.title + " " + re.sub("<[^>]+>", " ", s.body)))}">'
                f'<h2><a class="hanchor" href="#{ch.key}-{s.key}" aria-label="Lien vers cette partie">#</a>'
                f"{esc(s.title)}</h2>{s.body}</article>"
                for s in ch.sections
            )
            prev_ = shown[i - 1] if i > 0 else None
            next_ = shown[i + 1] if i + 1 < len(shown) else None
            pager = '<nav class="help-pager">' + (
                f'<a class="btn" href="#{prev_.key}">← {prev_.icon} {esc(prev_.title)}</a>' if prev_ else "<span></span>"
            ) + (f'<a class="btn" href="#{next_.key}">{next_.icon} {esc(next_.title)} →</a>' if next_ else "<span></span>") + "</nav>"
            bodies.append(
                f'<section class="help-ch" data-ch="{ch.key}" id="{ch.key}"><div class="help-head">'
                f'<span class="help-icon">{ch.icon}</span><div><h1 class="title">{esc(ch.title)}</h1>'
                f'<p class="sub">{esc(ch.summary)}</p></div></div>'
                f'<nav class="help-toc"><b>Dans ce chapitre :</b><ol>{toc}</ol></nav>{secs}{pager}</section>'
            )
        login_hint = ""
        if viewer is not None and not viewer.user:
            login_hint = (
                '<p class="muted">Tu n\'es pas connecté : les captures montrent le site tel que le voient les membres '
                "(données d'exemple).</p>"
            )
        body = f"""
<div class="help">
<aside class="help-nav">
<p class="help-kicker title">Aide</p>
<input id="help-q" type="search" placeholder="Chercher dans l'aide (ex. inscrire, prix, recette)…" autocomplete="off"
aria-label="Chercher dans l'aide">
<ul>{"".join(nav)}</ul>
<p class="muted small">Les captures d'écran utilisent des persos et des données d'exemple.</p>
</aside>
<div class="help-main">{login_hint}<p id="help-found" class="help-found" hidden></p>{"".join(bodies)}</div>
</div>
<dialog id="help-lightbox" aria-label="Image agrandie"><img alt=""><p class="muted">Clique n'importe où pour fermer</p></dialog>"""
        return page("Aide", "aide", body, HELP_SCRIPT)
