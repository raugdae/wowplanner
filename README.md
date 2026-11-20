# WoW Planner

Bot Discord pour organiser des sorties donjon / raid sur **World of Warcraft: Forever**.

- `/ajouter event` publie un message de sortie : instance, date, nombre de joueurs et places par rôle. On peut aussi créer la sortie **depuis le site** (page Sorties) : le bot poste le même message dans le salon Discord.
- Les joueurs s'inscrivent avec les boutons sous le message : 🛡️ Tank, ⛑️ Heal, ⚔️ DPS, Se désinscrire. Ou depuis le site : les deux restent synchronisés.
- Chaque joueur déclare ses persos (`/ajouter perso`, ou la page « Mes persos » du site, qui vérifie le nom dans l'armurerie pendant la saisie). À l'inscription, le bot prend le perso capable de tenir le rôle, ou demande lequel s'il y en a plusieurs.
- Quand un rôle est complet, son bouton passe en gris et les nouvelles inscriptions sont refusées.
- Chaque perso peut avoir un rôle préféré. Ses métiers et recettes sont lus dans l'armurerie Blizzard. Pour consulter les persos, métiers, recettes et donjons, il y a **le site web**. Côté Discord, `/liste battletags` donne les BattleTag de tout le monde.
- 30 minutes avant le départ, chaque inscrit reçoit un rappel en MP.
- 15 minutes avant le départ, le bot crée un salon vocal pour la sortie et ajoute son lien au message. Le salon est supprimé quand il est vide, au plus tôt 30 minutes après le début.
- La liste des donjons et raids vient de [warcraft.wiki.gg](https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Forever) et se met à jour toute seule chaque nuit, avec le reste des données (voir « Synchro des données »).

## Commandes

Le bot ne garde que l'essentiel : les sorties, la déclaration des persos et l'atelier. Tout ce qui se consulte (persos, métiers, recettes, donjons, fiches d'armurerie) est sur **le site web**.

Les commandes suivent la logique **verbe + catégorie** :

| | event | perso | battletag | autre |
|---|---|---|---|---|
| **`/ajouter`** | crée une sortie | ✅ | ✅ | |
| **`/supprimer`** | annule la sortie | ✅ | ✅ | `inscrit` |
| **`/liste`** | `events` | | `battletags` | |

| Commande | Rôle |
|---|---|
| `/ajouter event instance date heure [joueurs] [tanks] [heals] [dps] [description]` | Crée une sortie. L'instance se cherche par nom ou abréviation (`brd`, `ony`, `sm cath`…). |
| `/ajouter perso nom [classe] [race] [role_prefere]` | Déclare un de tes persos. Seul le nom est obligatoire : classe et race sont lues dans l'armurerie si le perso y est (niveau 10+), sinon le bot les demande. La combinaison race/classe et le rôle préféré sont vérifiés. Un perso encore introuvable dans l'armurerie 2 jours après son ajout est retiré la nuit. Pour corriger un perso : le supprimer et le recréer (ou changer son rôle préféré sur le site). |
| `/ajouter battletag tag` | Enregistre ton BattleTag (`Nom#1234`), ou remplace l'ancien. |
| `/supprimer event sortie` | Annule la sortie après confirmation, et prévient les inscrits. Réservé à l'organisateur et aux modérateurs. |
| `/supprimer inscrit sortie joueur` | Désinscrit un joueur d'**une** sortie. Choisis la sortie d'abord : le champ `joueur` ne propose que ses inscrits. Les autres sorties du joueur ne changent pas. Réservé à l'organisateur et aux modérateurs. |
| `/supprimer perso perso` | Supprime un perso et ses métiers. Ses inscriptions en cours restent, avec ton pseudo à la place. |
| `/supprimer battletag` | Retire ton BattleTag. |
| `/liste events` | Prochaines sorties du serveur. |
| `/liste battletags` | Les BattleTag des joueurs du serveur. |

**Date** : `25/12/2026`, `25/12`, `aujourd'hui`, `demain`. **Heure** : `21:00`, `21h30`, `21h`.

**Composition** : si tu ne précises rien, le bot utilise la taille de l'instance avec une répartition classique :

| Taille | Tank | Heal | DPS |
|---|---|---|---|
| 5 (donjon) | 1 | 1 | 3 |
| 10 | 2 | 3 | 5 |
| 20 | 3 | 5 | 12 |
| 40 | 4 | 10 | 26 |

Tu peux surcharger n'importe quel rôle. Exemple : `tanks:2` sur Hyjal Summit garde 5 heals, et les DPS remplissent le reste (13). Un nom d'instance libre est accepté si tu donnes `joueurs` ou les trois rôles.

### Règles d'inscription

- Le message affiche les inscrits sous chaque rôle, dans l'ordre d'inscription : perso, classe et pseudo Discord. Sur les gros raids, le pseudo est retiré si la liste devient trop longue pour Discord.
- Un seul rôle par joueur. Cliquer sur un autre rôle te déplace, s'il reste de la place. Recliquer sur ton rôle permet de changer de perso sans perdre ta place.
- **Choix du perso** :
  - un seul de tes persos peut tenir le rôle : il est pris automatiquement ;
  - plusieurs : un menu visible seulement par toi demande lequel. Les persos dont c'est le rôle préféré ⭐ sont en tête, rien n'est présélectionné ;
  - aucun perso déclaré : tu es inscrit avec ton pseudo Discord ;
  - des persos, mais aucun pour ce rôle : inscription refusée, le bot liste ce que tes persos peuvent jouer.
- Les réponses du bot visibles seulement par toi ne s'empilent pas : à ta commande ou ton clic suivant, la précédente est effacée. Discord ne le permet que pendant 15 minutes ; au-delà, elle reste jusqu'à ce que tu la fermes ou recharges Discord.
- Si le bot redémarre, les boutons continuent de marcher. Les sorties créées avec l'ancienne version (inscription par réaction) sont converties au démarrage : les réactions sont retirées, les inscrits sont gardés.

### Classes et rôles

| Classe | Tank | Heal | DPS |
|---|:-:|:-:|:-:|
| Guerrier | ✅ | | ✅ |
| Paladin | ✅ | ✅ | ✅ |
| Druide | ✅ | ✅ | ✅ |
| Prêtre | | ✅ | ✅ |
| Chaman | | ✅ | ✅ |
| Chasseur, Voleur, Mage, Démoniste | | | ✅ |

Le Paladin tank est viable dans Forever (Seal of Fury, Consecration de base). Le Chaman n'est pas compté comme tank : l'Amélioration peut dépanner en petit groupe, mais ce n'est pas un rôle prévu. Les combinaisons race/classe suivent le [wiki](https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Forever), Éolides (Skyborne) compris, sans distinction de faction. Tout est dans `wowplanner/gamedata.py`.

### Métiers et BattleTag

- Les métiers ne se saisissent plus à la main : ils viennent de l'armurerie (niveau compris), à l'ajout du perso puis à chaque synchro. Sans clés Blizzard, les persos n'ont donc pas de métiers.
- `/liste battletags` ne montre que les joueurs vus sur le serveur : ceux qui y ont utilisé une commande du bot ou se sont inscrits à une sortie. La liste s'affiche seulement pour celui qui tape la commande.

### Rappel et salon vocal

- **Rappel** (`REMINDER_MINUTES`, 30 par défaut) : un MP à chaque inscrit, avec son rôle et le lien de la sortie. Pas de rappel si la sortie a été créée moins de 30 minutes avant le départ. Les joueurs qui ont fermé leurs MP ne le reçoivent pas.
- **Salon vocal** (`VOICE_CHANNEL_MINUTES`, 15 par défaut) : créé seulement s'il y a au moins un inscrit, dans la catégorie du salon des sorties (ou `VOICE_CATEGORY_ID`), limité au nombre de joueurs de la sortie. Il est ouvert à tous ceux qui peuvent voir la catégorie. Il est supprimé dès qu'il est vide, au plus tôt 30 minutes après le début, ou dès que la sortie est annulée (s'il est vide).
- Si le bot était éteint au moment prévu, le salon vocal est quand même créé à son retour, tant que la sortie a commencé depuis moins d'une heure. Rien n'est envoyé ni créé en double.
- Mettre `0` désactive la fonction correspondante.

### Commandes d'administration (`/admin`)

Pour gérer les persos des membres (qui ont la flemme 😄). **Réservé à la permission « Gérer le serveur »** : les
autres membres ne voient même pas `/admin`. Pour l'ouvrir à un rôle (ex. « Officier ») : *Paramètres du serveur →
Intégrations → WoW Planner → `/admin`*. Le bot revérifie la permission à chaque utilisation.

| Commande | Rôle |
|---|---|
| `/admin ajouter perso joueur nom [classe] [race] [role_prefere]` | Ajoute un perso à un membre, mêmes règles que `/ajouter perso`. Le membre reçoit un MP. |
| `/admin supprimer perso joueur perso` | Supprime un perso d'un membre (choisir le membre d'abord : le champ `perso` propose ses persos). Il reçoit un MP. |
| `/admin atelier` | Poste (et épingle) le panneau de l'atelier dans le salon courant. |
| `/admin sync` | Relit **tout** maintenant, sans attendre la synchro de nuit. Voir ci-dessous. |

### Synchro des données (nuit et `/admin sync`)

Tout ce qui vient de l'extérieur est mis à jour au même endroit (`cogs/sync.py`), en 6 étapes :
1. la liste des donjons et raids (wiki) ;
2. les priorités de stats (guide stillsixty) ;
3. les arbres de talents (Blizzard) ;
4. tous les persos déclarés : métiers, recettes, équipement, stats, talents, images (armurerie) ;
5. le **nettoyage** des persos ajoutés depuis Discord et toujours introuvables dans l'armurerie (voir plus bas) ;
6. les détails des recettes : noms français, composants, objets fabriqués (Blizzard).

**Nettoyage des persos introuvables** : un perso déclaré sur Discord (`/ajouter perso` ou `/admin ajouter perso`)
que l'armurerie ne connaît toujours pas **2 jours après son ajout** est retiré, et son joueur est prévenu en MP.
Les persos ajoutés depuis le site ne sont jamais retirés : ils ont été vérifiés dans l'armurerie à l'ajout.
Garde-fou : si l'armurerie ne trouve aucun perso du tout (panne ?), rien n'est retiré.
Seule une réponse « introuvable » compte : une armurerie qui ne répond pas ne retire rien.

- **Chaque nuit à 4 h** (fuseau `TIMEZONE`), tout seul. Les talents ne sont redemandés que s'ils ont plus d'une semaine, et seules les recettes nouvelles sont demandées. Si le bot était éteint à 4 h (ou au premier lancement), la synchro est rattrapée au démarrage dès que la dernière a plus de 20 h. Le bilan est dans les logs.
- **`/admin sync`** : la même chose tout de suite, mais en forçant les talents et **toutes** les recettes. L'avancement s'affiche étape par étape. Si ça dépasse 15 minutes, Discord ne permet plus de mettre à jour la réponse : le bilan arrive en MP.

Une étape en échec n'empêche pas les suivantes, et on garde alors les anciennes données. Sans clés Blizzard, les étapes 3 à 6 sont sautées. Une seule synchro à la fois.

**Quotas Blizzard** : 100 requêtes par seconde et 36 000 par heure. Le bot fait au plus 5 requêtes en parallèle et marque une pause d'une seconde entre deux persos ; s'il reçoit malgré tout un refus pour excès de requêtes, il patiente puis réessaie. Ordre de grandeur pour un `/admin sync` : environ 550 requêtes pour les talents, 6 par perso, 2 par recette. Avec 50 persos et 1 000 recettes, ça fait environ 3 000 requêtes, moins de 10 % du quota horaire. La synchro de nuit en fait beaucoup moins (persos et recettes nouvelles seulement).

Pour voir les persos d'un membre : le site web.

## Atelier : commandes entre persos

Pour demander à un autre joueur de fabriquer un objet, sans commande à taper. Un admin poste le panneau
une fois avec `/admin atelier` ; il reste épinglé avec deux boutons :

- **🛒 Commander** : une petite fenêtre demande l'objet (un bout du nom suffit : *mangouste*), la quantité et un
  mot pour l'artisan. Le bot trouve la recette et qui sait la faire (menu si plusieurs choix), montre un récap
  avec les composants nécessaires (sous-recettes dépliées, quantités recalculées), puis envoie la commande en MP
  à l'artisan.
- **📦 Mes commandes** : commandes passées et reçues, en cours et récentes ; un menu permet d'accepter, terminer
  ou annuler.

Côté artisan, le MP a les boutons **Accepter** / **Refuser**, puis **C'est prêt** / **Abandonner**. Le client
reçoit un MP à chaque étape et peut **annuler** tant que ce n'est pas prêt. Composants et livraison se règlent
entre eux en jeu (courrier, échange).

Seules les recettes **débloquées par les persos du serveur** (vues dans l'armurerie) sont proposées, et jamais
à ses propres persos. Pas de sécurité à ajouter : Discord dit qui clique ; seul le propriétaire du perso artisan
peut accepter ou terminer, seul le client peut annuler. Les boutons marchent encore après un redémarrage du bot.

Raccourci pour les habitués : `/commander objet:… [quantite] [note]`, avec autocomplétion.

## Installation

### 1. Créer le bot sur Discord

1. Ouvre <https://discord.com/developers/applications> et clique sur **New Application**.
2. Dans l'onglet **Bot**, clique sur **Reset Token** et copie le token. Aucun *Privileged Gateway Intent* n'est nécessaire.
3. Dans l'onglet **OAuth2 → URL Generator**, coche les scopes `bot` et `applications.commands`, puis ces permissions :
   View Channel, **Manage Channels** (pour les salons vocaux des sorties), Send Messages, Embed Links, **Manage Messages** (pour garder le salon des sorties propre), Read Message History.
   Tu peux aussi utiliser directement le lien suivant, en remplaçant `CLIENT_ID` :
   `https://discord.com/oauth2/authorize?client_id=CLIENT_ID&scope=bot+applications.commands&permissions=93200`
4. Ouvre le lien et invite le bot sur ton serveur.

### 2. Configurer

```bash
cp .env.example .env
# puis renseigne DISCORD_TOKEN, et GUILD_ID pour que les commandes apparaissent tout de suite
```

Pour utiliser des émotes du serveur à la place des émotes par défaut : `EMOJI_TANK=<:tank:123456789012345678>`. Pour trouver l'ID d'une émote, tape `\:tank:` dans Discord.

### 3. Configurer le salon des sorties

L'objectif est que, dans ce salon, les joueurs ne puissent que lancer les commandes et cliquer sur les boutons. Ça se règle dans Discord : **Modifier le salon → Permissions**.

**@everyone** :

| Permission | Réglage | Pourquoi |
|---|---|---|
| Voir le salon, Voir les anciens messages | ✅ | lire les sorties |
| Utiliser les commandes de l'application | ✅ | `/ajouter event`, etc. |
| Envoyer des messages | ❌ | pas de discussion dans le salon |
| Ajouter des réactions | ❌ | pas d'émotes sur les sorties |
| Créer des fils publics / privés, Envoyer des messages dans les fils | ❌ | pas de fils de discussion |

Les boutons marchent sans aucune permission particulière, et envoyer des messages n'est pas nécessaire pour les commandes slash : c'est le bot qui poste.

**Le rôle du bot** (ajoute-le dans les permissions du salon) : ✅ Voir le salon, Envoyer des messages, Intégrer des liens, Gérer les messages, Voir les anciens messages. Sinon l'interdiction posée sur @everyone s'applique aussi à lui.

En complément, indique l'ID du salon dans `.env` (clic droit sur le salon → *Copier l'identifiant*, après avoir activé le mode développeur dans Paramètres → Avancés) :

```
EVENT_CHANNEL_IDS=123456789012345678
```

Le bot n'acceptera `/ajouter event` que dans ce salon. Il supprimera aussi tout message qu'un joueur arriverait quand même à y poster, par exemple à cause d'une permission mal réglée sur un rôle. Les messages des modérateurs (permission « Gérer les messages ») restent en place.

## Déploiement

### Avec Docker (recommandé)

```bash
mkdir -p data && sudo chown 1000:1000 data   # le conteneur tourne avec l'utilisateur 1000
docker compose up -d --build
docker compose logs -f
```

`restart: unless-stopped` relance le bot après un crash ou un redémarrage du serveur. La base SQLite et le cache des instances sont dans `./data` : sauvegarde ce dossier.

### Sans Docker (systemd, Linux)

```bash
sudo useradd --system --home /opt/wowplanner wowplanner
sudo git clone <ton-repo> /opt/wowplanner && cd /opt/wowplanner
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env && sudo nano .env
sudo chown -R wowplanner: /opt/wowplanner
sudo cp deploy/wowplanner.service /etc/systemd/system/
sudo systemctl enable --now wowplanner
journalctl -u wowplanner -f
```

### En local (développement)

Il faut Python 3.11 ou plus récent.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS : source .venv/bin/activate)
pip install -r requirements.txt pytest
python -m pytest
python -m wowplanner
```

## Source des donjons et raids

Blizzard ne publie pas d'API pour WoW Forever. Le bot lit donc le tableau « Dungeons and raids » de la page [World of Warcraft: Forever](https://warcraft.wiki.gg/wiki/World_of_Warcraft:_Forever) du wiki communautaire, via son API MediaWiki :

- chaque nuit, avec la synchro de nuit ;
- à la demande avec `/admin sync`.

Le résultat est mis en cache dans `data/instances_cache.json`. Une liste intégrée (`wowplanner/instances_default.json`, à jour au 11/11/2026) sert de secours si le wiki est injoignable. Si la page change de structure et que le bot ne trouve plus qu'une liste suspecte (moins de 10 donjons ou aucun raid), la mise à jour est ignorée et l'ancienne liste est conservée.

## Armurerie WoW Forever

Facultatif : sans clés Blizzard, tout le reste du bot marche normalement.

**Activer** : crée un accès sur <https://develop.battle.net> (*Create Client*, gratuit) et renseigne
`BLIZZARD_CLIENT_ID`, `BLIZZARD_CLIENT_SECRET` et `BLIZZARD_REGION` dans `.env` (jamais dans `.env.example`, qui est
versionné).

**Ce que ça apporte**

- **Persos synchronisés** : quand un perso est trouvé, ses métiers (avec niveau), recettes connues, équipement,
  stats, talents et images sont repris de l'armurerie, pour le site. Synchro à `/ajouter perso`,
  chaque nuit pour tous les persos, et à la demande avec `/admin sync`.
- **Recettes** : les recettes connues sont relues à chaque synchro. Leurs détails (nom français, composants, objet
  fabriqué) sont demandés une seule fois puis gardés en base ; `/admin sync` les redemande tous.
- **Vérification à l'ajout** : `/ajouter perso` dit si le perso existe dans l'armurerie, et prévient si la classe ou
  la race déclarée ne correspond pas. Pas bloquant sur Discord, mais un perso encore introuvable après 2 jours est
  retiré par la synchro de nuit. Sur le site (« Mes persos »), le perso **doit** exister dans l'armurerie.

**Limites** (l'API n'est pas documentée officiellement pour Forever) : un perso n'apparaît qu'à partir du **niveau
10**, après une déconnexion, parfois avec plusieurs heures de retard. Les persos s'y adressent sans serveur, par
`prénom-nom` (`/profile/wow/character/grommash-hurlenfer?namespace=profile-forever-eu`). Si l'armurerie ne répond
pas, le bot le signale et continue.

**Tester l'accès** sans lancer le bot :

```bash
# Sur le VPS, avec Docker
docker compose run --rm wowplanner python -m wowplanner.armory_probe "Grommash Hurlenfer"
# En local
python -m wowplanner.armory_probe "Grommash Hurlenfer"
```

Le script vérifie le jeton et quelques données de jeu, interroge la fiche, les stats, l'équipement, les métiers, la
spé et l'image, puis enregistre chaque réponse brute dans `data/armory_probe/*.json`.

## Site web (facultatif)

Le site du serveur, pour parcourir les persos et les métiers, et (une fois connecté avec Discord) organiser les
sorties et gérer ses persos. Il peut être réservé aux membres du Discord (voir « Connexion avec Discord » plus bas) :

- **Sorties** : les prochaines sorties avec les inscrits par rôle, comme le message Discord. Connecté, on peut
  **s'inscrire** (choix du perso, puis du rôle ; seuls les rôles que le perso peut tenir sont actifs), changer de
  rôle ou de perso, se désinscrire, et **créer une sortie** (instance à chercher dans la liste ou nom libre, date,
  heure, composition, description). L'organisateur et les modérateurs (permission « Gérer les messages » ou « Gérer
  les événements » dans le salon) peuvent **annuler** la sortie (les inscrits sont prévenus sur Discord) ou
  **retirer un inscrit**. Tout passe par le bot : le message de la sortie est mis à jour dans le salon, comme après
  un clic sur ses boutons ; rappel en MP et salon vocal fonctionnent pareil. Ce qui est fait sur Discord apparaît
  sur le site au rechargement de la page. Une sortie créée depuis le site est postée dans le salon de
  `EVENT_CHANNEL_IDS` (au choix s'il y en a plusieurs), sinon dans celui de la dernière sortie ;
- **Menu du compte** (en haut à droite) : ton pseudo, la liste de tes persos (le préféré en tête, marqué ⭐) avec un
  lien vers chacun, le choix du thème, l'administration (pour les admins) et la déconnexion ;
- **Mes persos** (connecté) : tes persos, avec leur rôle préféré modifiable, un bouton pour les supprimer, ☆/★ pour
  choisir ton **perso préféré** (un seul, proposé en premier pour t'inscrire aux sorties, sur le site comme sur
  Discord), et l'ajout d'un perso. Dès 3 lettres tapées, le nom est **vérifié dans l'armurerie** pendant la saisie (classe, race
  et niveau affichés, rôles proposés selon la classe) ; le bouton « Ajouter » ne s'active que pour un perso trouvé.
  L'armurerie ne sait pas chercher un nom partiel : c'est le nom exact (prénom et nom) qui est vérifié ;
- **Atelier** (connecté) : l'atelier de Discord sur le site. On cherche un objet parmi les recettes débloquées par
  les persos des autres joueurs, on choisit l'artisan, la quantité et un mot ; l'artisan reçoit la commande **en MP
  sur Discord** avec ses boutons, comme depuis le panneau. « Mes commandes » liste celles reçues et passées, avec les
  mêmes actions (Accepter, Refuser, C'est prêt, Abandonner, Annuler) : l'autre partie est prévenue en MP et le MP de
  l'artisan se met à jour. Chaque recette des pages Métiers et chaque objet conseillé ont un lien « 🛒 Commander » ;
- **Hôtel des ventes** (avec `AUCTION_HOUSE_ID`, voir plus bas) : tous les objets en vente avec leur prix le plus
  bas et leur prix médian à l'unité, la quantité disponible, le nombre d'annonces et la variation sur 24 h ;
  recherche par nom, filtre par type et sous-type (Artisanat · Tissu, Consommable · Potion, Artisanat ·
  Enchantement…), tri, et **favoris** (☆ sur chaque ligne, case « Mes favoris »). Au survol d'un prix, une petite
  **courbe des 7 derniers jours** ; un clic ouvre la **fiche de l'objet** : sa courbe sur 24 h, 3, 7, 30 ou 90 jours
  (prix le plus bas en trait plein, médian en pointillé, valeurs au survol), le tableau des relevés, son prix chez le
  marchand, qui le fabrique sur le serveur (avec « Commander ») et dans quelles recettes il sert ;
- **Rentabilité de mes métiers** (menu du compte, et lien depuis l'hôtel des ventes) : pour un de ses persos, ce que
  rapportent ses métiers aux prix de l'hôtel des ventes.
  - *Fabrication* (alchimie, forge, couture, cuisine…) : chaque recette connue, de la plus rentable à la moins
    rentable : vente à l'HdV au prix le plus bas actuel, commission de 5 % déduite ; coût des composants (prix le plus
    bas de l'HdV, ou prix du marchand pour ceux qu'il vend : fioles, fils, teintures, flux, sel, épices…, liste dans
    `wowplanner/profit.py`) ; bénéfice et marge ; revente au marchand pour comparer ; quantité déjà en vente pour
    juger de la concurrence ; détail des composants. Les enchantements, qui ne créent pas d'objet, ne sont pas comptés.
  - *Récolte* (herboristerie, minage, dépeçage, pêche) : les ressources de ce type en vente à l'HdV, celles
    récoltables au niveau du perso d'abord (du plus cher au moins cher), avec le niveau requis (valeurs de Classic,
    « ? » pour les ressources propres à Forever) et la revente au marchand.

  Blizzard donne un prix d'achat « marchand » même pour des objets qu'aucun marchand ne vend : seuls les composants
  de la liste sont comptés au prix du marchand ;
- **Calculatrice HdV** (menu du compte) : pour un de ses persos, on saisit son stock (les ressources qu'il récolte à
  son niveau, et les composants de ses recettes ; gardé dans le navigateur, par perso). La calculatrice compare la
  **vente brute** de tout le stock (au meilleur prix entre l'HdV, commission déduite, et le marchand) avec un **plan
  de fabrication** : la recette qui rapporte le plus par fabrication d'abord, autant de fois que le stock le permet,
  puis la suivante, en achetant au marchand les composants qu'il vend (fioles…), le reste vendu brut. Elle montre le
  gain du plan, chaque étape (objets vendus, achats, valeur du stock utilisé) et chaque recette prise seule (une
  même plante sert parfois à plusieurs recettes). Par exemple : vendre ses Pacifiques, ou en faire des potions ?
- **Guilde** : tableau de tous les persos du serveur par ordre alphabétique (classe, race, rôles, métiers et
  niveaux), recherche et filtres par classe, rôle ou métier ;
- **fiche d'un perso** : façon fiche du jeu, son **équipement** autour de son rendu en pied (icônes, infobulles,
  enchantements) et ses **caractéristiques** (chacune expliquée au survol ou au toucher : à quoi elle sert, avec une
  remarque selon la classe du perso, ex. « Force : inutile pour un Mage »), avec les **stats à pousser en priorité** pour sa spé (devinée d'après
  ses talents et son rôle préféré, avec un menu pour voir les autres spés de la classe). Les priorités viennent du
  guide WoW Forever de stillsixty.com, **relu chaque nuit à 4 h** avec la synchro de nuit :
  si le guide change, le site suit ; si la page ne répond pas ou change de forme, on garde les dernières connues. Puis ses métiers en tableau, et ses recettes par **onglet de métier**, classées par type d'objet
  (composants d'artisanat, potions, armure : torse…) ;
  le portrait apparaît aussi dans les listes. Images hébergées par Blizzard, mises à jour à chaque synchro ;
  ses **talents** comme dans le jeu (les trois arbres, icônes, rangs, infobulle au survol ou au toucher, double
  spé). Les arbres sont récupérés une fois par semaine auprès de Blizzard, les talents du perso à chaque synchro ;
  et, en dépliant **« Équipement fabricable par la guilde »**, les objets que les persos du serveur savent fabriquer
  et que ce perso peut porter : type d'armure et d'arme de sa classe, niveau requis (jusqu'à 5 niveaux au-dessus du
  sien, marqués « bientôt »), par emplacement, avec l'objet porté pour comparer (▲ quand le niveau d'objet est
  meilleur, case « seulement les améliorations »), les stats prioritaires de sa spé, qui sait le fabriquer et un lien
  pour le commander. Les règles par classe sont dans `wowplanner/proficiency.py` : armes d'après les maîtres d'armes
  de Forever (nouveau : haches à une main pour le Voleur, armes d'hast pour le Druide) ; armures comme dans Classic
  (mailles au niveau 40 pour Chasseur et Chaman, plaques au niveau 40 pour Guerrier et Paladin), rien d'autre
  n'ayant été annoncé pour Forever ;
- **Métiers** : qui a chaque métier et à quel niveau, et toutes les recettes connues sur le serveur, avec recherche
  (nom de recette, composant ou effet, ex. *agilité*) et liens vers les persos qui savent les faire. Chaque recette
  montre ce que fait l'objet, comme l'infobulle du jeu : emplacement, armure, dégâts, stats, effets « Utiliser » /
  « Équipé », niveau requis, nom coloré selon la qualité (et l'effet pour les enchantements) ;
- **Donjons** : les 35 donjons de WoW Forever (dont les 9 nouveaux) avec zone et tranche de niveau conseillée, les
  persos du serveur qui sont dans chaque tranche, et un choix de niveau (ou d'un perso) qui met en avant ce qui est à
  faire. Plus les raids (joueurs, boss, date d'ouverture). L'API Blizzard n'a pas le journal des donjons de Forever :
  la liste est dans `wowplanner/dungeons.py`, à retoucher si Blizzard change des tranches ;
- **fiche d'un donjon ou d'un raid** (clic dans la liste) : comment trouver l'entrée, ses coordonnées avec une
  commande `/way` à copier (TomTom), le **parcours des boss** numéroté (optionnels à part, avec où les trouver), les
  persos du serveur du bon niveau, la vignette Blizzard et un lien vers la carte détaillée du guide Warcraft Tavern.
  Les fiches sont dans `wowplanner/dungeon_guides.py` (noms français officiels des boss quand Blizzard les donne).
  Connecté, un bouton **« Créer une sortie »** ouvre le formulaire de la page Sorties avec ce donjon déjà choisi ;
- **Administration** (membres qui ont « Gérer le serveur » sur Discord, comme pour `/admin`) : lancer la **synchro
  complète** (comme `/admin sync`, avec son avancement), voir **tous les persos des membres** avec leur joueur, leur
  origine (site ou Discord) et ceux absents de l'armurerie (avec la date à laquelle le nettoyage de nuit les retirera),
  changer leur rôle préféré, les **supprimer** ou en **ajouter** un à un membre (comme `/admin ajouter perso` et
  `/admin supprimer perso` : le membre est prévenu en MP). Sur la page Sorties, un admin peut annuler n'importe quelle
  sortie et retirer un inscrit. Le panneau de l'atelier reste à poster depuis Discord (`/admin atelier`), dans le
  salon voulu.
- **Aide** (publique, lien dans la barre du haut et sur la page de connexion) : le mode d'emploi complet du site,
  écrit pour quelqu'un qui n'a pas l'habitude d'internet. Un chapitre par partie du site, avec un menu à gauche, une
  recherche, des captures d'écran annotées (repères numérotés : survoler ou cliquer un numéro allume la zone, clic
  sur l'image pour l'agrandir), les gestes de base, une FAQ, un lexique et deux petits outils (convertisseur
  po/pa/pc, rôles possibles par classe). Le chapitre Administration n'apparaît qu'aux admins. Voir « Page d'aide ».

**Infos personnelles** : ni identifiant Discord, ni BattleTag. Seule la page Sorties montre le pseudo des inscrits
et de l'organisateur, comme le message de la sortie sur Discord. Le site lit la même base que le bot (dans le même
conteneur), donc il est toujours à jour. Il montre les persos du serveur `GUILD_ID` (ou du seul serveur connu du bot).

**Sécurité des formulaires** : chaque action (inscription, création, suppression…) porte un jeton propre au joueur
connecté, et le site refuse les envois venus d'un autre site. Les actions demandent la connexion Discord : sans
`DISCORD_CLIENT_SECRET`, le site reste en consultation seule (aucune action possible).

### Page d'aide

Le texte est dans `wowplanner/webhelp.py` (fonctions `shot`, `steps`, `tip`… pour les blocs). Les captures sont
dans `wowplanner/static/aide/` : une image `.webp` par capture et `shots.json`, qui donne la taille de chaque image
et la zone désignée par chaque repère. Elles sont prises sur un **site de démonstration** : persos et pseudos
inventés (sauf la fiche de Hollie Tétine, lue dans l'armurerie), vraies données de jeu et vrais prix de l'HdV.
Aucune donnée du serveur n'y apparaît, car la page est publique.

Pour les refaire après un changement du site (en local, avec les clés Blizzard dans `.env`) :

```
pip install playwright pillow aiohttp
python tools/aide/demo_build.py demo.db                 # base de démonstration (1 à 2 minutes)
python tools/aide/demo_server.py demo.db 8766           # site de démo, à laisser tourner
python tools/aide/captures.py http://127.0.0.1:8766     # toutes les captures (ou : … sortie menu hdv)
```

`captures.py` utilise le Chromium de Playwright (`playwright install chromium`), ou Chrome via `CHROME_PATH`.
La liste des captures (page, zone cadrée, repères) est en bas de `captures.py`. Le test `test_help_page` vérifie que
chaque capture citée dans l'aide existe et que chaque repère de légende est placé sur son image.

### Hôtel des ventes

Il faut les clés Blizzard (voir « Armurerie WoW Forever ») et, dans `.env`, le numéro de l'hôtel des ventes à
suivre : `AUCTION_HOUSE_ID=111` (hôtel de l'Alliance de notre serveur). Sans lui, la page est désactivée.

Forever n'a pas de royaumes dans l'API : les hôtels des ventes sont rangés sous les « règles de jeu »
(`/data/wow/ruleset/{n}/auctions/`, la même liste pour toutes les règles), 15 au total : Alliance 110, 111, 112,
119, 123 ; Horde 113, 114, 115, 120, 124 ; Flots noirs (neutre) 116, 117, 118, 121, 125. Pour trouver le sien : mettre
un objet en vente à un prix reconnaissable et chercher dans quel hôtel il apparaît.

- **Relevés** : toutes les 20 minutes, le bot demande les deux listes de Blizzard (objets uniques et ressources,
  environ 1 Mo chacune, mises à jour à peu près toutes les heures) et enregistre un relevé quand elles ont changé.
  Si l'API ne répond pas, la page garde les derniers prix connus (et le signale au bout de 3 h).
- **Base locale des objets** : tout le catalogue de Forever (nom, type, qualité, prix chez le marchand) est lu au
  premier démarrage par la recherche d'objets de l'API (environ 30 requêtes de 1 000 objets), relu chaque semaine,
  et complété objet par objet pour les nouveautés. Les icônes arrivent petit à petit (300 par relevé, les plus
  vendus d'abord).
- **Historique** : un relevé par heure pendant 7 jours, puis un par jour (plus bas prix du jour, moyennes) jusqu'à
  90 jours. Compter quelques dizaines de Mo dans la base pour ~7 000 objets.
- **Quotas** : 2 requêtes toutes les 20 minutes, plus le catalogue et les icônes : très loin des 36 000 par heure.

### Connexion avec Discord

Avec `DISCORD_CLIENT_SECRET` renseigné, le site est **réservé aux membres du serveur Discord** :

| Pages | Sans connexion | Connecté (membre du serveur) |
|---|---|---|
| Sorties, Mes persos, Guilde, fiches persos, Métiers, recettes, Administration | page « Réservé aux membres » avec un bouton de connexion | ✅ |
| Donjons et fiches des donjons | ✅ sans les persos du serveur | ✅ avec les persos dans chaque tranche |

- **Connexion** : bouton « Se connecter avec Discord ». Discord demande d'autoriser le site à voir le pseudo, et rien d'autre (droit `identify` : ni serveurs, ni messages, ni e-mail). Le bot vérifie ensuite que la personne est membre du serveur. Pas besoin de l'intent « membres » : c'est une simple requête à l'API.
- **Durée** : la session dure 30 jours. L'appartenance au serveur est revérifiée une fois par jour : quelqu'un qui quitte le serveur ou qui en est exclu perd l'accès dans les 24 h.
- **Cookies** : signés, donc impossibles à falsifier, et lisibles seulement par le site (`HttpOnly`, `Secure` en HTTPS). La clé de signature est créée au premier lancement dans `data/session_secret`. La supprimer déconnecte tout le monde.
- Sans `DISCORD_CLIENT_SECRET`, le site reste ouvert à tous, et un avertissement le rappelle dans les logs au démarrage.

**Mise en place** (5 minutes) :
1. Ouvre le [portail développeur Discord](https://discord.com/developers/applications), puis l'application du bot, onglet **OAuth2**.
2. Dans **Redirects**, ajoute `https://wow.ton-domaine.fr/auth/callback` (ton adresse, suivie de `/auth/callback`). Enregistre.
3. Copie le **Client Secret** (bouton *Reset Secret* s'il n'est pas affiché) dans `.env` : `DISCORD_CLIENT_SECRET=…`. Ne le committe jamais.
4. Vérifie que `WEB_DOMAIN` (avec Traefik) ou `WEB_URL` est renseigné : c'est l'adresse de retour envoyée à Discord.
5. Lance `docker compose up -d`. Les logs doivent afficher « Site réservé aux membres du serveur ».

**Accès invité (sans Discord)** : pour montrer le site à quelqu'un qui n'est pas sur le serveur. Il ouvre un lien
caché et entre un mot de passe, puis consulte tout le site **en lecture seule** : il n'a pas de persos ni de
menu d'administration (sauf avec `GUEST_AS`, ci-dessous), et tout envoi de formulaire est refusé. Dans `.env` :

```
GUEST_KEY=une-longue-chaine-au-hasard   # 16 caractères minimum, ex. : python -c "import secrets; print(secrets.token_urlsafe(24))"
GUEST_PASSWORD=le-mot-de-passe
```

- Le lien à donner est `https://wow.ton-domaine.fr/auth/invite/<GUEST_KEY>`. Il n'apparaît nulle part sur le site, et une clé fausse renvoie une page introuvable (404).
- `GUEST_AS` (facultatif) : l'invité voit le site **comme ce joueur**, désigné par son identifiant Discord ou le nom d'un de ses persos (ex. `GUEST_AS=Hollie Tétine`). Il voit alors ses persos, sa rentabilité, ses favoris HdV et l'administration si ce joueur y a droit, toujours sans rien pouvoir modifier.
- Changer `GUEST_PASSWORD` (puis redémarrer) déconnecte les invités déjà connectés. Vider l'une des deux variables désactive l'accès.
- Au-delà de 10 mots de passe faux en 15 minutes, les essais sont refusés pendant un moment.
- L'accès invité n'existe qu'avec la connexion Discord activée : sans `DISCORD_CLIENT_SECRET`, le site est de toute façon ouvert.

L'identifiant de l'application est repris automatiquement du bot (`DISCORD_CLIENT_ID` ne sert que pour en utiliser une autre). Si le secret est renseigné mais pas l'adresse du site, le site **ne démarre pas** plutôt que de rester ouvert par erreur.

**Avec Traefik** (réseau Docker externe partagé avec Traefik) : dans `.env`,

```
COMPOSE_FILE=docker-compose.yml:docker-compose.traefik.yml
WEB_DOMAIN=wow.ton-domaine.fr
# si besoin : TRAEFIK_NETWORK=…  TRAEFIK_ENTRYPOINT=…  TRAEFIK_CERTRESOLVER=…
```

puis `docker compose up -d --build`. `docker-compose.traefik.yml` ajoute les labels Traefik (HTTPS) et lance le site
sur le port interne 8080. Sans Docker : `WEB_PORT=8080` dans `.env`, et `WEB_URL=https://…` (adresse publique) pour
que le bot renvoie vers le site dans ses messages ; avec Traefik, `WEB_DOMAIN` suffit.

## Structure

```
wowplanner/
  __main__.py          point d'entrée (python -m wowplanner)
  bot.py               client Discord : extensions, site web, connexion au site, appartenance au serveur
  config.py            lecture du .env
  db.py                SQLite : tout l'accès à la base (sorties, persos, recettes, commandes, hôtel des ventes…)

  # Discord (cogs/)
  cogs/commands.py     déclaration de toutes les commandes slash (/ajouter, /supprimer, /liste, /admin, /commander)
  cogs/events.py       sorties : création, boutons d'inscription, annulation (partagé avec le site)
  cogs/characters.py   persos (/ajouter perso, /supprimer perso)
  cogs/players.py      BattleTag
  cogs/orders.py       atelier : panneau, commandes entre persos, boutons en MP (partagé avec le site)
  cogs/schedule.py     rappels en MP et salons vocaux temporaires
  cogs/armory.py       synchro armurerie : métiers, recettes, équipement, talents
  cogs/statsync.py     lecture des priorités de stats (guide stillsixty)
  cogs/auctions.py     relevé des prix de l'hôtel des ventes (toutes les 20 min), catalogue des objets
  cogs/sync.py         synchro de nuit et /admin sync : tout ce qui vient de l'extérieur, nettoyage des persos
  cogs/webbridge.py    actions du site exécutées par le bot (sorties, persos, atelier, administration)
  ephemeral.py         effacement des anciennes réponses privées du bot

  # Données et règles (sans Discord ni HTML)
  gamedata.py          classes, races, rôles et métiers de WoW Forever
  proficiency.py       armures et armes portables par classe (équipement conseillé)
  gear.py              équipement, caractéristiques, priorités de stats par spé
  statsource.py        lecture du guide des priorités de stats
  roles.py             rôles, compositions par défaut, émotes
  timeparse.py         lecture des dates et heures
  instances.py         liste des instances (wiki), pour /ajouter event
  dungeons.py          donjons et raids de Forever (tranches de niveau), pour le site
  dungeon_guides.py    fiches des donjons : entrée, coordonnées, parcours des boss
  recipes.py           recettes : recherche, regroupement, composants dépliés
  orders.py            règles des commandes de l'atelier (recettes commandables, droits, composants)
  auctions.py          hôtel des ventes : agrégation des annonces, prix, base des objets
  profit.py            rentabilité des métiers et calculatrice (recettes, récolte, prix des marchands)
  armory.py            client de l'API Blizzard (armurerie, hôtel des ventes, catalogue des objets)
  armory_probe.py      script de test de l'armurerie
  embeds.py            rendu du message de sortie sur Discord

  # Site web
  web.py               serveur : connexion avec Discord, contrôle d'accès, routes, feuille de style
  webauth.py           connexion au site avec Discord (OAuth2, cookies signés)
  webui.py             mise en page commune : en-tête, menu du compte, thèmes, scripts partagés
  static/site.css      feuille de style (mise en cache par le navigateur)
  webpages.py          Guilde, fiche d'un perso, Métiers, Donjons (consultation)
  webcharacter.py      blocs de la fiche perso : équipement, stats, talents, équipement fabricable
  webrecipes.py        cartes de recettes (Métiers, fiche perso, atelier)
  webmember.py         Sorties, Mes persos, Atelier, Administration (formulaires des membres)
  webauction.py        Hôtel des ventes (liste, favoris, fiche avec courbe des prix)
  webprofit.py         Rentabilité de mes métiers, Calculatrice HdV
  webhelp.py           page d'aide (chapitres, captures annotées, recherche)
  static/aide/         captures de la page d'aide (+ shots.json : tailles et repères)
tools/aide/            base et site de démonstration, prise des captures de l'aide (Playwright)
tests/test_core.py
```
