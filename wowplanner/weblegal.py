"""Conditions d'utilisation (/conditions) et politique de confidentialité (/confidentialite) : pages publiques,
liées en pied de chaque page. Textes écrits pour être lus par tout le monde, pas par des juristes.

À tenir à jour quand le site change de données ou de fonctionnement (et changer UPDATED).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

from .webui import page

if TYPE_CHECKING:
    from .web import WebSite

EDITOR = "Raugdae"
UPDATED = "20 novembre 2026"
REPO = "https://github.com/raugdae/wowplanner"


def _doc(icon: str, title: str, intro: str, sections: list[tuple[str, str, str]], other: str) -> str:
    toc = "".join(f'<li><a href="#{key}">{name}</a></li>' for key, name, _ in sections)
    body = "".join(f'<section id="{key}"><h2>{name}</h2>{html}</section>' for key, name, html in sections)
    return (
        f'<div class="legal"><div class="help-head"><span class="help-icon">{icon}</span><div>'
        f'<h1 class="title">{title}</h1><p>{intro}</p></div></div>'
        f'<p class="legal-date">Dernière mise à jour : {UPDATED}</p>'
        f'<nav class="legal-toc"><b>Sommaire</b><ol>{toc}</ol></nav>{body}'
        f'<p class="legal-other">{other}</p></div>'
    )


TERMS = [
    ("objet", "1. À quoi sert WoW Planner", f"""
<p>WoW Planner est un outil de guilde pour <b>WoW Forever</b> : un bot Discord et ce site, qui servent à organiser
les sorties (donjons, raids), à retrouver les persos et les métiers des membres, à passer des commandes d'artisanat
entre joueurs et à suivre les prix de l'hôtel des ventes.</p>
<p>Il est édité par <b>{EDITOR}</b>, un joueur de la guilde, sur son temps libre. Il est <b>gratuit</b> : pas de
publicité, pas d'abonnement, rien à acheter. Utiliser le site ou le bot veut dire que tu acceptes ces conditions.</p>"""),
    ("acces", "2. Qui peut l'utiliser", """
<ul>
<li>Le site et le bot sont <b>réservés aux membres du serveur Discord de la guilde</b>. La connexion se fait avec
ton compte Discord ; si tu quittes le serveur, l'accès se ferme tout seul.</li>
<li>Des <b>exceptions</b> peuvent être accordées par un administrateur (par exemple un accès invité en lecture seule
pour quelqu'un qui n'a pas Discord).</li>
<li>Il faut avoir <b>au moins 13 ans</b>, comme pour Discord.</li>
<li>Les pages <a href="/aide">Aide</a> et <a href="/donjons">Donjons</a> sont publiques : tout le monde peut les lire.</li>
</ul>"""),
    ("conduite", "3. Les règles de bonne conduite", """
<p>En résumé : <b>sois correct avec les autres</b>. Concrètement, on ne fait pas :</p>
<ul>
<li>de propos insultants, haineux ou harcelants, dans les descriptions de sorties, les notes de commande ou ailleurs ;</li>
<li>d'abus des outils : commandes bidon ou en masse, inscriptions pour bloquer une place, faux persos, inscrire
quelqu'un sans son accord… ;</li>
<li>de tentative de casser le site ou le bot, d'accéder à ce qui ne te concerne pas, ou de le surcharger exprès ;</li>
<li>de partage de ton accès avec quelqu'un d'autre.</li>
</ul>
<p>Tu as trouvé un bug ou une faille ? Signale-le à un administrateur plutôt que d'en profiter, merci !</p>"""),
    ("sanctions", "4. Si les règles ne sont pas respectées", """
<p>En cas d'abus, un administrateur peut, selon la gravité : supprimer un contenu (sortie, commande, note…),
<b>limiter l'accès à certains outils</b>, ou <b>suspendre l'accès</b> au site et au bot. Dans la mesure du possible,
on en parle d'abord avec la personne concernée.</p>"""),
    ("contenus", "5. Ce que tu publies", """
<p>Tu es responsable de ce que tu écris (descriptions de sorties, notes de commande, persos déclarés). Ces textes
sont visibles par les autres membres de la guilde. N'y mets pas d'informations personnelles (adresse, numéro de
téléphone, vrai nom…) : ce n'est pas fait pour ça.</p>"""),
    ("echanges", "6. Les échanges entre joueurs", """
<p>Les commandes d'artisanat, les prix et l'or échangés <b>se passent dans le jeu, entre joueurs</b>. Le site aide à
s'organiser mais ne garantit rien : si un échange tourne mal, ça se règle entre les joueurs concernés (ou avec les
officiers de la guilde), pas avec WoW Planner.</p>"""),
    ("infos", "7. Les informations affichées", """
<p>Les prix de l'hôtel des ventes, les fiches de l'armurerie, les guides de donjons et les calculs de rentabilité
sont donnés <b>à titre indicatif</b>. Ils viennent de sources extérieures (Blizzard, guides de la communauté) et
peuvent être en retard ou inexacts. Vérifie en jeu avant de dépenser ton or !</p>"""),
    ("dispo", "8. Disponibilité", """
<p>Le site est maintenu bénévolement. Il peut être en panne, en maintenance, changer ou s'arrêter à tout moment,
sans préavis. Aucune garantie n'est donnée et l'éditeur ne peut pas être tenu responsable d'une perte (de données,
de temps ou d'or virtuel…) liée à son utilisation, dans les limites prévues par la loi.</p>"""),
    ("blizzard", "9. Blizzard et WoW Forever", """
<p>WoW Planner est un <b>projet de fans</b>, sans aucun lien avec Blizzard Entertainment ni avec l'équipe de
WoW Forever, qui ne l'ont ni approuvé ni ne le soutiennent. <i>World of Warcraft</i>, <i>Warcraft</i> et les
images du jeu sont des marques et des contenus de Blizzard Entertainment, Inc. Les données du jeu sont lues via
l'API officielle de Blizzard, dans le respect de ses conditions.</p>
<p>Le bot utilise Discord : ton utilisation de Discord reste soumise aux conditions de Discord.</p>"""),
    ("code", "10. Le code source", f"""
<p>Le code de WoW Planner est <b>libre</b>, publié sous licence MIT : tu peux le consulter, le réutiliser et le
modifier, à condition de garder la mention de licence. Il est disponible sur
<a href="{REPO}" rel="noopener">GitHub</a>. Cette licence concerne le code, pas les contenus de Blizzard.</p>"""),
    ("changements", "11. Changements de ces conditions", """
<p>Ces conditions peuvent évoluer avec le site. La date de mise à jour est indiquée en haut de la page ; pour un
changement important, on le signale sur le Discord de la guilde.</p>"""),
    ("droit", "12. Droit applicable et contact", f"""
<p>Ces conditions sont soumises au <b>droit suisse</b>. En cas de souci, on préfère toujours en discuter : contacte
<b>{EDITOR}</b> en message privé sur le Discord de la guilde, ou un administrateur.</p>"""),
]

PRIVACY = [
    ("resume", "En bref", """
<div class="hbox hb-tip"><b>Le minimum, et uniquement du jeu.</b>
<ul>
<li>On ne garde que ce qui sert au fonctionnement de la guilde : ton identifiant Discord et tes infos de jeu
(persos, métiers, inscriptions, commandes).</li>
<li>Pas d'adresse mail, pas de mot de passe, pas de vrai nom, pas de publicité, pas de mesure d'audience,
<b>rien n'est vendu ni partagé</b> à des fins commerciales.</li>
<li>Tu peux demander à <b>tout effacer</b> quand tu veux.</li>
</ul></div>"""),
    ("responsable", "1. Qui s'occupe de tes données", f"""
<p>Le responsable est <b>{EDITOR}</b>, éditeur de WoW Planner, en Suisse. Pour toute question ou demande :
un message privé à <b>{EDITOR}</b> sur le Discord de la guilde, ou à un administrateur, qui transmettra.</p>
<p>Cette politique suit la loi suisse sur la protection des données (LPD) et, pour les joueurs qui vivent dans
l'Union européenne, le RGPD.</p>"""),
    ("donnees", "2. Ce qu'on enregistre, et pourquoi", """
<div class="table-wrap"><table class="htable">
<thead><tr><th>Donnée</th><th>D'où elle vient</th><th>À quoi elle sert</th></tr></thead>
<tbody>
<tr><td>Ton <b>identifiant Discord</b> (un numéro) et ton <b>pseudo</b> sur le serveur</td>
<td>Discord, quand tu utilises le bot ou te connectes au site (on ne demande à Discord que ton identité, jamais
ton e-mail ni tes messages)</td>
<td>Savoir quels persos, inscriptions et commandes sont à toi, vérifier que tu es membre du serveur, afficher
ton pseudo dans les listes d'inscrits et les commandes</td></tr>
<tr><td>Tes <b>persos</b> : nom, classe, race, rôle préféré, métiers et niveaux, recettes connues</td>
<td>Toi (commande <code>/ajouter perso</code> ou le site)</td>
<td>Les listes de la guilde, la recherche d'artisans, les commandes</td></tr>
<tr><td>La <b>fiche publique</b> de tes persos : niveau, équipement, talents, statistiques, apparence</td>
<td>L'armurerie publique de Blizzard (API officielle)</td>
<td>Les fiches persos du site</td></tr>
<tr><td>Tes <b>inscriptions aux sorties</b> et les sorties que tu crées</td><td>Toi</td>
<td>Organiser les sorties, prévenir les inscrits</td></tr>
<tr><td>Tes <b>commandes d'artisanat</b> (objet, quantité, note)</td><td>Toi</td>
<td>Les transmettre à l'artisan, suivre leur avancement</td></tr>
<tr><td>Tes <b>favoris</b> de l'hôtel des ventes</td><td>Toi</td><td>Ta liste de suivi des prix</td></tr>
<tr><td>Ton <b>BattleTag</b>, seulement si tu l'ajoutes</td><td>Toi (commande <code>/ajouter battletag</code>)</td>
<td>Que les membres puissent t'ajouter en ami ; il n'est visible que sur le Discord, <b>jamais sur le site</b></td></tr>
</tbody></table></div>
<p>On utilise ces données parce que tu as choisi de participer aux outils de la guilde, et uniquement pour ça.
Elles sont visibles par les <b>autres membres de la guilde</b> (c'est le but : voir qui vient, qui sait
fabriquer quoi), jamais publiées en dehors.</p>"""),
    ("cookies", "3. Cookies et stockage dans ton navigateur", """
<p>Le site n'utilise <b>que des cookies techniques</b>, indispensables pour qu'il marche, donc pas de bandeau à
accepter :</p>
<ul>
<li><b>session</b> : te garde connecté, pendant 30 jours au plus (ou jusqu'à la déconnexion) ;</li>
<li><b>connexion</b> : protège le passage par Discord pendant la connexion, 10 minutes ;</li>
<li><b>message</b> : affiche le résultat d'une action (« Perso enregistré »…), 2 minutes.</li>
</ul>
<p>Quelques préférences restent <b>uniquement dans ton navigateur</b> (rien n'est envoyé au serveur) : le thème
clair ou sombre, les cases cochées de l'aide, les réglages de la calculatrice. Tu peux les effacer en vidant les
données du site dans ton navigateur.</p>
<p>Aucun cookie publicitaire, aucun outil de statistiques ou de pistage.</p>"""),
    ("tiers", "4. Où sont les données, et qui d'autre intervient", """
<ul>
<li><b>Hébergement</b> : un serveur loué chez <b>Hostinger</b>, dans un centre de données en <b>Allemagne</b>
(Union européenne). Comme tout serveur web, il peut garder brièvement des journaux techniques (adresse IP,
page demandée) pour la sécurité et le dépannage.</li>
<li><b>Discord</b> sert à la connexion et au bot ; il applique sa propre politique de confidentialité.</li>
<li><b>Blizzard</b> : le site lit l'armurerie et l'hôtel des ventes via l'API officielle. Les images du jeu
(icônes, portraits) sont chargées directement depuis les serveurs de Blizzard : ton navigateur s'y connecte donc
pour les afficher, sans qu'on leur transmette quoi que ce soit sur toi.</li>
</ul>
<p>Rien d'autre : pas de revente, pas de partenaire, pas de publicité.</p>"""),
    ("duree", "5. Combien de temps on les garde", """
<p>Tant que tu utilises les outils de la guilde. Les sorties passées et les commandes terminées restent en
historique. Une copie de sauvegarde de la base est faite de temps en temps pour éviter les pertes ; elle est
gardée sur le même genre de serveur et remplacée au fil des sauvegardes.</p>"""),
    ("droits", "6. Tes droits", """
<p>Tu peux à tout moment :</p>
<ul>
<li><b>voir</b> ce qu'on a sur toi (presque tout est déjà visible sur le site, page « Mes persos ») ;</li>
<li><b>corriger</b> tes infos (sur le site ou avec les commandes du bot) ;</li>
<li><b>supprimer</b> un perso ou ton BattleTag toi-même (<code>/supprimer perso</code>,
<code>/supprimer battletag</code>) ;</li>
<li>demander à <b>tout effacer</b> : persos, inscriptions, commandes, favoris, BattleTag. Un message à l'éditeur
suffit, sans avoir à te justifier.</li>
</ul>
<p>Si tu estimes que tes données sont mal traitées, tu peux aussi t'adresser au Préposé fédéral à la protection des
données et à la transparence (PFPDT) en Suisse, ou à l'autorité de protection des données de ton pays.</p>"""),
    ("changements", "7. Changements", """
<p>Si le site se met à enregistrer de nouvelles données, cette page sera mise à jour avant, et le changement
signalé sur le Discord de la guilde.</p>"""),
]


class LegalPages:
    def __init__(self, site: WebSite):
        self.site = site

    def register(self, router: web.UrlDispatcher) -> None:
        router.add_get("/conditions", self.terms)
        router.add_get("/confidentialite", self.privacy)

    async def terms(self, request: web.Request) -> web.Response:
        body = _doc("📜", "Conditions d'utilisation", "Les règles du jeu pour utiliser WoW Planner, en clair.", TERMS,
                    'Voir aussi la <a href="/confidentialite">politique de confidentialité</a>.')
        return page("Conditions d'utilisation", "", body)

    async def privacy(self, request: web.Request) -> web.Response:
        body = _doc("🔒", "Confidentialité", "Quelles données WoW Planner garde sur toi, pourquoi, et comment les effacer.",
                    PRIVACY, 'Voir aussi les <a href="/conditions">conditions d\'utilisation</a>.')
        return page("Confidentialité", "", body)
