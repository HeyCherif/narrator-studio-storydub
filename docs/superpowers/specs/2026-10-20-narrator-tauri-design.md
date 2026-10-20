# Narrator Studio — conception de la version Tauri

Date : 20 octobre 2026
Statut : conception proposée, à relire avant plan d’implémentation.

## 1. Résultat attendu

Faire de Narrator Studio une application Windows de narration agréable à utiliser : une interface Tabler sombre violet/cyan, une identité visuelle originale, des téléchargements compréhensibles et une installation de bureau Tauri. Conserver la génération OmniVoice/Qwen et le contrôle qualité Python existants, ainsi que les modèles, voix clonées, historiques et fichiers audio du propriétaire.

Direction validée par l’utilisateur : Tauri + Rust pour l’application et les téléchargements, moteurs Python conservés, quatre espaces Studio / Voix / Modèles / Historique, nouveau logo.

La première version cible Windows x64. Une distribution macOS/Linux et une réécriture des moteurs TTS en Rust sont hors périmètre de cette version.

## 2. Constat sur l’application actuelle

- `app.py` regroupe API, fenêtre PyWebView, serveur HTTP local, configuration, historique et orchestration des moteurs.
- `tts_worker.py`, `qwen_tts_worker.py`, `qc_worker.py` et `quality_utils.py` fournissent les fonctions vocales et de contrôle qualité à préserver.
- `web/index.html`, `web/app.js` et `web/styles.css` portent un éditeur et un panneau de réglages, clonage et historique.
- Le téléchargement Qwen utilise un sous-processus `huggingface_hub.snapshot_download`. Le backend examiné signale essentiellement début et fin ; les champs visuels de progression ne constituent pas encore une mesure fiable du transfert.
- Les données sont actuellement près des sources : `config.json`, `history.json`, `history/`, `qwen_voices/`, `models/`. Plusieurs runtimes et modèles proviennent d’installations partagées sur D:.
- Les outils Rust/Cargo n’ont pas été détectés dans le terminal courant. Leur installation, ainsi que la vérification des outils de compilation Windows, sera une étape de préparation après approbation du plan.

## 3. Choix d’architecture

### Option retenue : Tauri + Rust et moteurs Python séparés

L’interface locale appelle des commandes Tauri explicites. Rust contrôle les téléchargements, les sélecteurs de fichiers, les chemins autorisés et le cycle de vie du processus Python. Python conserve la synthèse, le clonage, la transcription de contrôle, les reprises de génération et l’assemblage WAV.

Les moteurs PyTorch/CUDA ne sont ni chargés ni téléchargés simplement parce que l’utilisateur ouvre l’application. Ils démarrent lorsqu’une opération en a besoin, avec un état visible de préparation.

Tauri documente l’intégration de processus externes, dont des programmes Python empaquetés : [sidecars](https://v2.tauri.app/develop/sidecar/). Les permissions seront limitées à la fenêtre et aux commandes nécessaires : [capabilities](https://v2.tauri.app/security/capabilities/).

### Alternatives examinées

| Option | Intérêt | Conséquence |
| --- | --- | --- |
| Garder PyWebView et refaire l’interface | Transition plus courte | Ne réalise pas le choix Tauri/Rust demandé ; les téléchargements restent à restructurer. |
| Tauri + Rust + moteurs Python | Nouvelle application native tout en réutilisant le pipeline | Nécessite une couche de communication et une préparation de distribution. Option retenue. |
| Tout réécrire en Rust | Un langage principal à terme | Réécriture importante des moteurs vocaux et du contrôle qualité, avec risque de régression et sans bénéfice démontré pour cette version. |

## 4. Interface et identité

Base : Tabler installé et fourni localement avec l’application, sans dépendance à un CDN pour ouvrir les écrans. Frontend TypeScript/Vite, composants simples et modules par écran ; pas de framework supplémentaire nécessaire pour cette première refonte.

Palette : fond bleu nuit proche de `#0b1020`, panneaux `#11182b`, texte clair, violet `#a78bfa` pour la sélection et cyan `#67e8f9` pour les accents. Les états erreur/succès gardent leurs propres couleurs et un libellé lisible. Contrastes, focus clavier, états désactivés et mouvement réduit doivent rester explicites.

Logo : symbole original associant une onde vocale et un N, lisible en petite taille, avec wordmark Narrator Studio. Déclinaisons icône Windows, barre latérale, fond sombre et monochrome. Aucun visage ni reprise du logo d’un fournisseur de modèles.

Navigation latérale : **Studio**, **Voix**, **Modèles**, **Historique**. Un bouton Réglages ouvre un panneau secondaire pour la langue, les dossiers et les diagnostics. L’interface sera français/anglais ; les textes passeront par un dictionnaire partagé.

### Studio

- Éditeur de script central avec nombre de mots/caractères et conservation automatique du brouillon local.
- Choix du moteur et de la voix dans un panneau compact ; réglages compatibles avec le moteur uniquement.
- Action principale « Générer », puis « Annuler » pendant le travail.
- Affichage des étapes réelles : préparation, segment en cours, contrôle qualité, assemblage, terminé/erreur.
- Lecteur du résultat, durée mesurée et action Exporter. Pas d’estimation de durée inventée.
- Une génération à la fois dans cette première version ; changer d’écran ne l’interrompt pas.

### Voix

- Bibliothèque distincte par moteur, avec nom, langue disponible et écoute d’un extrait existant.
- Clonage Qwen : sélectionner l’audio, nommer la voix, vérifier la transcription puis créer le profil compatible avec le pipeline existant.
- Les voix OmniVoice existantes restent utilisables. Aucun nouveau mécanisme de clonage OmniVoice n’est promis dans cette version.
- Échec, référence manquante et profil incompatible sont présentés avec une action de correction.

### Modèles

- Cartes séparant clairement modèle installé, moteur Python disponible et capacité de calcul.
- Réutiliser un dossier existant via le sélecteur natif ; vérifier les fichiers requis avant de le déclarer prêt.
- Premier téléchargement intégré : snapshot officiel **Qwen/Qwen3-TTS-12Hz-0.6B-Base**. Aucun téléchargement de plusieurs gigaoctets sans action explicite.
- OmniVoice et Faster-Whisper : détection/réutilisation des installations actuelles. Leur téléchargement automatique n’entre pas dans cette première livraison tant qu’un catalogue de sources et licences n’est pas établi.
- Les chemins et détails techniques sont dans « Détails » ou « Réglages avancés », pas au milieu du parcours normal.

### Historique

- Recherche et liste des générations existantes : titre/extrait, moteur, voix, date et durée réelle si disponible.
- Écouter, exporter et ouvrir le dossier du résultat.
- Un fichier absent reste signalé comme absent ; il n’est pas remplacé par un résultat fictif.
- La suppression d’une entrée demande confirmation et ne supprime pas implicitement une voix ou un modèle.

### Adaptation et accessibilité

Vérification à 1440×900, 1280×720 et 900×700. Sur les fenêtres étroites, les réglages passent dans un panneau escamotable ; les commandes principales restent visibles. Navigation clavier complète, labels sur les boutons à icône, aucune information transmise uniquement par la couleur et animations courtes désactivables.

## 5. Téléchargements et intégrité

Rust possède une file persistante, limitée à un téléchargement actif pour commencer. Les états sont : en attente, préparation, téléchargement, pause, vérification, prêt, annulé, erreur.

- Manifeste issu du dépôt officiel, fixé à une révision immuable pour chaque installation. Enregistrer dépôt, révision, fichiers et tailles attendues.
- Pour les fichiers LFS, vérifier l’empreinte SHA256 annoncée par les métadonnées. Pour les petits fichiers Git, vérifier l’identifiant de contenu Git attendu ou une empreinte documentée du catalogue. Ne pas annoncer une vérification cryptographique sans référence vérifiable.
- Écriture dans des fichiers temporaires `.part`, puis validation et renommage ; le modèle n’est jamais déclaré prêt avec un fichier partiel.
- Progression à partir des octets effectivement reçus ; taille inconnue = état indéterminé. Débit et temps restant sont calculés, et masqués tant qu’ils ne sont pas fiables.
- Pause/reprise avec HTTP Range lorsque le serveur le permet. Si la révision ou le contenu distant change, invalider la reprise plutôt que concaténer deux fichiers différents.
- Vérifier l’espace disque avant un transfert dont la taille est connue. Montrer un message et permettre de choisir un autre dossier.
- Annuler arrête le transfert et conserve les parties réutilisables par défaut. Nettoyer les parties d’un téléchargement constitue une action séparée.
- Les erreurs réseau, espace disque, permissions et intégrité ont des messages différents et une action Réessayer.
- Valider les noms issus du manifeste, interdire les chemins absolus/traversées et limiter les destinations au dossier choisi. Les redirections HTTPS du fournisseur sont traitées sans y transmettre de secrets arbitraires.
- Les nouveaux fichiers restent sur D: lorsque l’utilisateur choisit cette bibliothèque. Ne pas recopier silencieusement les gros modèles sur C:.

## 6. Contrat entre interface, Rust et Python

L’interface ne reçoit aucun accès général au shell. Elle invoque une liste fermée de commandes : état de l’application, moteurs, génération/annulation, voix, historique, sélection/export de fichiers et file de téléchargement.

Rust lance un seul bridge Python possédé par l’application, avec chemins et arguments validés. Communication JSON par lignes sur stdin/stdout : identifiant de requête, commande autorisée, paramètres validés, réponse et événements d’avancement. Les journaux vont sur stderr pour ne pas corrompre le protocole. Les charges audio restent sur disque et transitent par identifiants/chemins validés, pas par messages JSON volumineux.

Le bridge réutilise la logique métier d’AppAPI après extraction de ses dépendances PyWebView/serveur HTTP. La version Tauri n’expose pas de serveur de contrôle HTTP sans authentification. Le lecteur accède uniquement aux sorties audio approuvées via un protocole de ressources limité ; aucun accès arbitraire au disque depuis le HTML.

Fermeture : demander l’arrêt, attendre un délai borné, puis terminer uniquement les processus lancés par cette instance. Une application ou un runtime partagé démarré ailleurs ne doit pas être arrêté. Une seule opération utilise un même moteur à la fois ; l’état est conservé lors du passage d’un écran à l’autre.

## 7. Conservation des données et transition

- Le dossier actuel et les lanceurs PyWebView sont conservés pour permettre un retour à l’ancienne version.
- Au premier lancement, proposer « Reprendre mon installation existante » avec sélection du dossier de Narrator Studio. Lire et valider la configuration avant confirmation.
- Avant toute adaptation du format, faire une copie versionnée des petits fichiers de configuration/index. Ne pas dupliquer les modèles et WAV volumineux.
- La nouvelle configuration réside dans les données applicatives utilisateur ; elle référence la bibliothèque existante sur D: tant que l’utilisateur ne choisit pas une autre destination.
- Préserver les champs inconnus de l’ancienne configuration, les identifiants d’historique, les profils de voix et les chemins. Aucune conversion destructive automatique des tenseurs de voix.
- Première lecture des historiques existants en mode conservateur. Les nouvelles entrées utilisent un format versionné et des écritures atomiques.
- Si deux versions tentent d’écrire la même bibliothèque, bloquer la seconde écriture et expliquer comment fermer l’autre instance.

## 8. Structure envisagée

```text
desktop/                  interface Vite / TypeScript / Tabler
  src/screens/            Studio, Voix, Modèles, Historique
  src/components/         commandes, lecteur, cartes et états partagés
  src/i18n/               textes français/anglais
  src/assets/             identité et ressources locales
src-tauri/
  src/commands/           commandes explicites de l’interface
  src/downloads/          manifeste, file, reprise et intégrité
  src/runtime/            bridge Python et cycle de vie
  src/storage/            chemins, préférences et transition
  capabilities/           permissions minimales
backend/                  logique Python extraite et bridge JSON
tests/                    tests de régression et contrats
scripts/                  construction et vérification de distribution
```

Les workers actuels restent présents. `app.py` continue d’être un point d’entrée compatible avec l’ancienne interface durant la transition.

## 9. Dépendances et distribution

- Frontend : Vite, TypeScript, Tabler et icônes Tabler ; versions fixées par le verrou de dépendances.
- Desktop : Tauri et plugins strictement nécessaires aux dialogues/ressources.
- Rust : sérialisation JSON, tâches asynchrones, HTTP avec streaming et SHA256. Choisir des versions maintenues au moment de l’implémentation et conserver Cargo.lock.
- Python : réutiliser les environnements TTS/QC déjà installés. Le bridge sera empaqueté comme processus compagnon léger ; aucun modèle, voix clonée ou historique utilisateur dans les installateurs.
- Premier objectif de distribution : installateur Windows x64 avec bridge et ressources d’interface, plus procédure de lancement depuis les sources. Le besoin des runtimes IA externes est annoncé avant la génération.
- Aucun téléchargement/installation silencieux de CUDA, PyTorch ou de pilotes. Un runtime absent donne une étape de configuration claire.
- Icônes et notices de dépendances incluses. Ne pas annoncer une signature numérique si les exécutables restent non signés.

## 10. Vérifications et critères d’acceptation

1. Les contrôles actuels du pipeline et `SELF_TEST.py` passent après extraction du bridge.
2. Une génération réelle réussit avec OmniVoice et une avec Qwen lorsque leur runtime/modèle est disponible ; ouvrir et écouter les sorties. À défaut de moteur disponible, signaler précisément cette limite sans déclarer le moteur validé.
3. Un clonage Qwen réel produit un profil réutilisable. Utiliser une référence de test explicitement autorisée, sans publier l’audio personnel.
4. Téléchargement testé avec un serveur local contrôlé : progression réelle, interruption, reprise, absence de Range, changement de manifeste, annulation, intégrité invalide et destination non autorisée.
5. Une vérification réelle du manifeste officiel et d’un petit fichier valide le trajet réseau. Le modèle déjà installé est réutilisé ; ne pas retélécharger plusieurs gigaoctets uniquement pour le test.
6. La reprise de l’ancienne configuration conserve le nombre d’entrées d’historique, les profils et les empreintes des fichiers utilisateur.
7. Un arrêt pendant un travail ne laisse pas de worker possédé actif. Les processus externes restent intacts.
8. Captures et vérification visuelle sur les trois dimensions prévues, en français et anglais ; clavier, contrastes, erreurs et mouvement réduit.
9. Construire et lancer l’exécutable Tauri réel, vérifier l’icône, le démarrage, les écrans, le bridge et l’accès audio. Une compilation seule ne valide pas la livraison.
10. Scanner le paquet : aucune configuration personnelle, référence vocale, clé, historique ou poids de modèle distribué.

## 11. Découpage proposé

1. Référence fonctionnelle et fixtures de transition ; vérifier les prérequis Windows.
2. Extraire le bridge Python, conserver le lancement PyWebView et verrouiller les régressions.
3. Créer la coque Tauri et les commandes bornées.
4. Intégrer identité et quatre écrans Tabler avec les fonctions réelles.
5. Livrer le gestionnaire Rust de téléchargement Qwen et la détection des installations existantes.
6. Valider les deux moteurs, la transition, l’accessibilité et le paquet Windows ; préparer ensuite la release Narrator.

La release Narrator ne sera pas annoncée comme prête avant ces vérifications. Nexus 2.5.1 et Renkavi 0.3.0-beta.3 ont déjà été publiés séparément et ne dépendent pas de cette refonte.
