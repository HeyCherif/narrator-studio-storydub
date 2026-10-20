# Narrator Studio Tauri Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer Narrator Studio Windows x64 avec Tauri, une interface Tabler sombre violet/cyan, des téléchargements Qwen fiables et les données vocales existantes conservées.

**Architecture:** Le frontend TypeScript appelle des commandes Tauri bornées. Rust gère la bibliothèque, les téléchargements et un bridge Python par stdin/stdout. Les workers Python existants restent responsables de la synthèse, du clonage et du contrôle qualité.

**Tech Stack:** Tauri 2, Rust, Tokio, Reqwest avec streaming TLS, Serde, SHA256/SHA1 de contenu Git, Vite, TypeScript, Tabler, Vitest, Python et unittest. Environnements PyTorch/CUDA existants réutilisés ; bridge léger empaqueté avec PyInstaller.

**Spec:** `docs/superpowers/specs/2026-10-20-narrator-tauri-design.md` — approuvée le 20 octobre 2026.

## Global Constraints

- Première cible : Windows x64 ; l’ancien lanceur PyWebView reste disponible.
- Palette : fond `#0b1020`, panneaux `#11182b`, violet `#a78bfa`, cyan `#67e8f9`.
- Quatre espaces : Studio, Voix, Modèles, Historique ; réglages secondaires et français/anglais.
- Vérifier 1440×900, 1280×720 et 900×700, clavier et mouvement réduit.
- Un téléchargement actif et une génération active au maximum ; aucun chargement de modèle au simple démarrage.
- Téléchargement intégré initial : `Qwen/Qwen3-TTS-12Hz-0.6B-Base`. OmniVoice/Whisper : détection et réutilisation.
- Conserver voix, modèles, historiques, WAV et champs inconnus de configuration. Ne pas déplacer de gros fichiers implicitement.
- Aucun poids, voix personnelle, historique ou configuration personnelle dans la distribution.
- Aucune installation silencieuse de CUDA, PyTorch ou pilotes ; aucune commande shell arbitraire exposée au frontend.
- Une génération ou un clonage non vérifié avec un moteur réel reste déclaré non vérifié.

## Review Focus

1. Installation sur D: avec espaces, accents et chemins externes : reprise sans duplication ni écriture hors bibliothèque choisie — tâche 1.
2. Historique malformé ou audio absent : conserver les données et montrer un état récupérable — tâches 1 et 7.
3. Réponse worker tardive après annulation/redémarrage : ne pas ressusciter une génération terminée — tâches 2 et 3.
4. Serveur ignorant Range ou révision modifiée : recommencer proprement, sans concaténation de contenus différents — tâche 5.
5. Fermeture pendant génération/transfert : vider les écritures possédées, conserver les fichiers utilisateur, arrêter uniquement les processus de cette instance — tâches 3, 5 et 8.

## Préparation d’exécution

- Lire la spécification et les éventuels nouveaux AGENTS.md. Utiliser `superpowers:using-git-worktrees` au début de l’exécution pour isoler le travail du dossier contenant les données réelles ; ne pas recopier les modèles.
- Inventorier les runtimes Python existants, le cache de modèles et les outils Windows. Installer les prérequis Rust/MSVC officiels nécessaires dans le cadre de l’exécution approuvée, sans modifier les installations IA existantes.
- Résoudre les versions compatibles au démarrage, enregistrer package-lock.json/Cargo.lock et les notices. Aucune dépendance frontend à un CDN.
- Créer les fixtures de tests sous des dossiers temporaires ; ne jamais appeler une suppression ou une migration contre la bibliothèque réelle pour un test automatisé.

## Cartographie des fichiers

| Ensemble | Fichiers et responsabilité |
| --- | --- |
| Données Python | `backend/library.py` : chemins injectés, lecture conservatrice et sauvegarde des petits index. |
| Pipeline Python | `backend/runtime.py` : workers et génération extraits ; `backend/bridge.py` : protocole JSON fermé. |
| Compatibilité | `app.py` : adaptateur PyWebView conservé ; `SELF_TEST.py` : vérification des deux points d’entrée. |
| Application Rust | `src-tauri/src/lib.rs`, `runtime/{bridge,lifecycle}.rs`, `storage/{library,settings}.rs`, `commands/{mod,studio,voices,history,models}.rs`. |
| Téléchargements | `src-tauri/src/downloads/{mod,catalog,manifest,queue,transfer,integrity}.rs`. |
| Frontend | `desktop/src/{main,api,types}.ts`, `screens/{studio,voices,models,history}.ts`, `components/{shell,player,status,dialogs}.ts`, `i18n/{index,fr,en}.ts`, `styles/{tokens,app}.css`. |
| Identité | `desktop/src/assets/brand/`, `src-tauri/icons/`, notices d’utilisation des ressources. |
| Livraison | `scripts/build_desktop.py`, `scripts/verify_distribution.py`, `.github/workflows/windows-release.yml`, documentation installation et release. |

### Task 1: Isoler la bibliothèque et sécuriser la reprise

**Files:** Create `backend/__init__.py`, `backend/library.py`, `tests/test_library.py`, `tests/fixtures/legacy_library/`. Modify les accès aux constantes de chemins dans `app.py`.

**Interfaces:** Produces `LibraryPaths(root: Path)`, `inspect_legacy(root: Path) -> LegacyInspection`, `adopt_legacy(root: Path, settings_path: Path) -> AdoptionResult`, `read_history(paths: LibraryPaths) -> list[dict]`. `LegacyInspection` expose nombres d’entrées, profils, erreurs et empreintes des petits index ; `AdoptionResult` expose racine et sauvegardes d’index.

- [ ] **Step 1:** Écrire `test_inspection_is_read_only`, `test_unknown_config_fields_survive`, `test_missing_audio_remains_visible`, `test_corrupt_history_is_not_overwritten`, `test_unicode_external_paths_are_preserved`. Assertions : empreintes avant/après identiques à l’inspection ; l’entrée absente garde son identifiant et `available=False` ; sauvegarde précède toute adaptation.
- [ ] **Step 2:** Exécuter `python -m unittest discover -s tests -p test_library.py -v` ; constater l’échec des nouvelles interfaces absentes.
- [ ] **Step 3:** Implémenter les interfaces, écrire atomiquement les petits index et injecter `LibraryPaths` ; rendre l’import de module sans création de dossiers utilisateur. Le frontend n’obtient jamais les secrets/paramètres inutiles.
- [ ] **Step 4:** Relancer les tests ; vérifier l’absence de copie des WAV/modèles et l’usage exclusif des fixtures temporaires.
- [ ] **Step 5:** Commit `refactor: isolate narrator library and preserve legacy data` avec les fichiers de cette tâche.

### Task 2: Extraire le pipeline et fournir le bridge Python

**Files:** Create `backend/runtime.py`, `backend/bridge.py`, `tests/test_bridge.py`, `tests/test_runtime.py`. Modify `app.py`, `SELF_TEST.py`. Conserver `tts_worker.py`, `qwen_tts_worker.py`, `qc_worker.py`, `quality_utils.py` et leurs comportements vocaux.

**Interfaces:** Consumes Task 1. Produces `NarratorRuntime(paths: LibraryPaths, emit: Callable[[dict], None], lazy: bool=True)`, `dispatch(command: str, payload: dict) -> dict`, `shutdown(timeout_seconds: float=5) -> None` et `python -m backend.bridge --library <root>`.

Protocole version 1 : requête `{id, command, payload}` ; réponse `{id, ok, result, error}` ; événement `{event, job_id, payload}`. Commandes permises : `bootstrap`, `set_engine`, `generate`, `cancel_generate`, `voices`, `clone_voice`, `history`, `shutdown`. JSON sur stdout, diagnostics sur stderr ; pas d’appel de méthode par introspection.

- [ ] **Step 1:** Écrire les tests `test_unknown_command_is_rejected`, `test_bootstrap_does_not_load_models`, `test_stdout_contains_only_protocol_lines`, `test_cancel_ignores_late_job_events`, `test_shutdown_drains_owned_workers`. Assertions : compteur de chargement zéro au bootstrap ; commande inconnue = `unknown-command` ; événement d’un ancien `job_id` ignoré.
- [ ] **Step 2:** Exécuter `python -m unittest discover -s tests -p test_bridge.py -v` et constater l’échec attendu.
- [ ] **Step 3:** Extraire la logique métier d’AppAPI vers `NarratorRuntime`, garder un adaptateur PyWebView dans `app.py` et démarrer les workers à la demande. Ne pas embarquer PyWebView dans le bridge léger.
- [ ] **Step 4:** Relancer `test_bridge.py`, `test_runtime.py`, puis `python SELF_TEST.py` avec le runtime IA existant ; séparer les tests de protocole simulés des essais vocaux réels.
- [ ] **Step 5:** Commit `refactor: expose narrator runtime through a bounded Python bridge`.

### Task 3: Créer Tauri et contrôler le cycle de vie

**Files:** Create `src-tauri/{Cargo.toml,build.rs,tauri.conf.json}`, `src-tauri/src/{main,lib}.rs`, `src-tauri/src/runtime/{mod,bridge,lifecycle}.rs`, `src-tauri/src/storage/{mod,library,settings}.rs`, `src-tauri/src/commands/mod.rs`, `src-tauri/capabilities/main.json`, `src-tauri/tests/runtime_contract.rs`. Create frontend `desktop/{package.json,tsconfig.json,vite.config.ts,index.html}` et ses fichiers verrouillés.

**Interfaces:** Consumes Tasks 1–2. Produces Rust `Bridge::request(command: RuntimeCommand, payload: Value) -> Result<Value, BridgeError>` et `Bridge::shutdown(deadline: Duration)`. Événements Tauri : `runtime:event`, `runtime:state`. Configuration utilisateur versionnée avec `library_root`, `locale`, `model_root` et références de runtimes ; chemins choisis via dialogue natif.

- [ ] **Step 1:** Écrire `rejects_unknown_commands`, `rejects_foreign_output_paths`, `late_response_does_not_resolve_new_request`, `shutdown_does_not_kill_external_process`, `second_writer_is_rejected` dans `runtime_contract.rs`, avec un faux sidecar exécutable de test.
- [ ] **Step 2:** Exécuter `cargo test --manifest-path src-tauri/Cargo.toml --test runtime_contract` et constater l’échec initial.
- [ ] **Step 3:** Implémenter bridge, limites de messages/délais, verrou de bibliothèque et arrêt borné ; ne pas bloquer le thread de lecture pendant une requête. Lancer uniquement le bridge configuré, sans droits shell génériques côté frontend. Appliquer une CSP locale et un scope audio limité aux fichiers validés.
- [ ] **Step 4:** Relancer les tests, `cargo check --manifest-path src-tauri/Cargo.toml` et ouvrir la coque réelle : bootstrap sans serveur HTTP de contrôle ni chargement GPU.
- [ ] **Step 5:** Commit `feat: add Tauri shell and managed narrator bridge`.

### Task 4: Définir les manifestes et l’intégrité des modèles

**Files:** Create `src-tauri/src/downloads/{mod,catalog,manifest,integrity}.rs`, `src-tauri/tests/model_manifest.rs`, fixtures de réponses Hugging Face.

**Interfaces:** Produces `ModelId::Qwen06Base`, `ModelManifest { repo, revision, files }`, `ModelFile { relative_path, bytes: Option<u64>, integrity: Integrity }`, `Integrity::Sha256(String)` / `Integrity::GitBlobSha1(String)`, `resolve_manifest(model: ModelId) -> Result<ModelManifest>` et `verify_file(path: &Path, file: &ModelFile) -> Result<()>`.

- [ ] **Step 1:** Écrire `pins_revision`, `rejects_traversal_and_absolute_paths`, `verifies_lfs_sha256`, `verifies_git_blob_header_hash`, `rejects_manifest_without_integrity`. Pour Git : empreinte de `blob <taille>\0<contenu>`, pas du contenu seul.
- [ ] **Step 2:** Exécuter `cargo test --manifest-path src-tauri/Cargo.toml --test model_manifest` ; confirmer le rouge initial.
- [ ] **Step 3:** Implémenter le catalogue fermé au dépôt Qwen approuvé, résoudre une révision immuable, les métadonnées LFS/Git et les noms autorisés. Sources et licences restent affichables ; aucun dépôt arbitraire saisi dans l’interface de cette version.
- [ ] **Step 4:** Vérifier les tests, puis un manifeste officiel et un petit fichier réel ; ne pas télécharger le modèle complet si déjà présent. Pour une bibliothèque existante, distinguer « fichiers requis présents » de « contenu vérifié ».
- [ ] **Step 5:** Commit `feat: validate official Qwen manifests and model integrity`.

### Task 5: Ajouter la file de téléchargement Rust

**Files:** Create `src-tauri/src/downloads/{queue,transfer}.rs`, `src-tauri/src/commands/models.rs`, `src-tauri/tests/download_transfer.rs` et serveur HTTP local de test.

**Interfaces:** Consumes Task 4. Produces `DownloadManager::{enqueue(ModelId), pause(id), resume(id), cancel(id), retry(id), snapshot()}`. `DownloadSnapshot { id, model, state, bytes_done, total_bytes: Option<u64>, speed_bps: Option<f64>, eta_seconds: Option<u64>, error }`. États exacts : `queued`, `preparing`, `downloading`, `paused`, `verifying`, `ready`, `cancelled`, `error`. Événement Tauri `downloads:changed`.

- [ ] **Step 1:** Écrire `progress_uses_received_bytes`, `unknown_length_is_indeterminate`, `pause_resume_uses_range`, `range_ignored_restarts_without_append`, `changed_revision_invalidates_partial`, `checksum_failure_never_marks_ready`, `one_active_download`, `insufficient_space_prevents_transfer`, `cancel_preserves_reusable_part`, `shutdown_flushes_partial`.
- [ ] **Step 2:** Exécuter `cargo test --manifest-path src-tauri/Cargo.toml --test download_transfer` ; vérifier que les nouveaux cas échouent avant implémentation.
- [ ] **Step 3:** Implémenter streaming vers `.part`, métadonnées atomiques, gestion Range/ETag/révision, limites de redirection HTTPS et validation avant renommage. Réserver une seule tâche active ; recalculer les mesures à la reprise et masquer une estimation insuffisante. Persister la file hors des dossiers du modèle.
- [ ] **Step 4:** Relancer les tests avec contenu local contrôlé et fichiers de petite taille. Aucune suppression hors fichiers partiels créés par la file ; le nettoyage des parties reste une action explicite séparée.
- [ ] **Step 5:** Commit `feat: add resumable model downloads with measured progress`.

### Task 6: Construire l’identité et le Studio Tabler

**Files:** Create `desktop/src/{main,api,types}.ts`, `components/{shell,player,status,dialogs}.ts`, `screens/studio.ts`, `styles/{tokens,app}.css`, `i18n/{index,fr,en}.ts`, `assets/brand/`, `desktop/tests/{studio,navigation,i18n}.test.ts`.

**Interfaces:** Consumes Task 3. Produces `NarratorClient::{bootstrap,generate,cancelGenerate,subscribeRuntime}` et `mountStudio(container: HTMLElement, client: NarratorClient)`. `GenerateRequest { text, engine: 'omnivoice'|'qwen', voice_id, language, options }` ; types d’événement alignés avec le protocole Task 2. `t(key, params?)` et `setLocale('fr'|'en')` sont partagés par tous les écrans.

- [ ] **Step 1:** Écrire les tests : moteur absent désactive Générer avec action de configuration ; navigation ne perd pas le brouillon ; double clic ne démarre pas deux travaux ; annulation ignore un événement tardif ; réglage OmniVoice caché pour Qwen ; textes FR/EN et nom accessible sur chaque commande à icône.
- [ ] **Step 2:** Exécuter `npm test --prefix desktop -- --run` ; confirmer les échecs des comportements absents.
- [ ] **Step 3:** Installer Tabler localement, appliquer les quatre couleurs exactes et créer le logo original onde/N avec déclinaisons. Monter la navigation, le Studio, le lecteur et les dialogues. Donner priorité au texte, à la voix et à Générer ; placer diagnostics/chemins en détails. Respecter `prefers-reduced-motion`.
- [ ] **Step 4:** Tests, `npm run typecheck --prefix desktop`, `npm run build --prefix desktop`, puis captures des trois dimensions. Inspecter les images ; corriger collisions, contrastes et focus. Produire un logo net en petite taille, sans reprendre l’identité d’un fournisseur.
- [ ] **Step 5:** Commit `feat: add dark Tabler narrator studio and visual identity`.

### Task 7: Relier Voix, Modèles et Historique

**Files:** Create `desktop/src/screens/{voices,models,history}.ts`, `src-tauri/src/commands/{studio,voices,history}.rs`, `desktop/tests/{voices,models,history}.test.ts`, `src-tauri/tests/file_commands.rs`. Compléter `desktop/src/api.ts` et `types.ts`.

**Interfaces:** Consumes Tasks 1–6. Adds client `voices()`, `cloneVoice(CloneRequest)`, `history()`, `exportAudio(id)`, `openHistoryFolder()`, `adoptLegacyLibrary()`, `detectModels()`, `downloadAction(action, id)`. `HistoryEntry { id, filename, engine, voice, created_at, duration_seconds: number|null, available }`. `ModelStatus` distingue `files_present`, `integrity_verified` et `runtime_available`.

- [ ] **Step 1:** Tester historique absent/malformé sans effacement, audio manquant visible, export via choix natif, chemin forgé refusé, profil incompatible expliqué, confirmation avant suppression d’une entrée et progression indéterminée sans pourcentage inventé.
- [ ] **Step 2:** Exécuter tests frontend et `cargo test --manifest-path src-tauri/Cargo.toml --test file_commands` ; constater l’échec initial.
- [ ] **Step 3:** Relier les cartes et commandes réelles, le clonage Qwen et sa transcription, la reprise de bibliothèque avec sauvegarde des petits index et les détails de téléchargement. OmniVoice/Whisper ne proposent que la réutilisation ; aucun bouton de téléchargement fictif. La suppression d’historique exige confirmation et reste limitée à l’entrée/fichier explicitement désigné.
- [ ] **Step 4:** Tests, vérification visuelle FR/EN, navigation clavier et conservation d’un travail en changeant d’écran. Tester avec une fixture existante et comparer les empreintes avant/après la reprise.
- [ ] **Step 5:** Commit `feat: connect voice library, model manager and narration history`.

### Task 8: Construire et vérifier la distribution Windows

**Files:** Create `scripts/build_desktop.py`, `scripts/verify_distribution.py`, tests de distribution, `.github/workflows/windows-release.yml`, `docs/{installation,release}.md`. Modify `README.md`, `.gitignore`, configuration de bundle et icônes Tauri.

**Interfaces:** Produces `python scripts/build_desktop.py --version <semver> --output <dir>` et `python scripts/verify_distribution.py <dir>`. Le premier empaquette un bridge léger, construit Tauri et produit les empreintes ; le second vérifie la version, les binaires attendus et l’absence de données/poids interdits au niveau de la bibliothèque applicative.

- [ ] **Step 1:** Écrire les tests de manifeste de distribution : interdire configuration/historique/voix/modèles personnels, accepter les répertoires `data` internes légitimes d’une dépendance, exiger icône, notices, bridge et version cohérente. Tester fermeture pendant un travail sur fixture sans toucher à un processus externe.
- [ ] **Step 2:** Exécuter la suite de distribution ; constater les échecs avant la construction du livrable.
- [ ] **Step 3:** Construire le sidecar et le bundle Tauri Windows x64, gérer les ressources depuis les chemins du bundle et les données depuis la configuration utilisateur. Documenter WebView2, runtimes IA externes, erreurs de préparation et retour au lanceur existant. Ne pas annoncer de signature numérique inexistante.
- [ ] **Step 4:** Exécuter unittest, SELF_TEST, tests Rust, typage/tests/build frontend, puis lancer l’exécutable réel avec bibliothèque temporaire. Vérifier les quatre écrans, le bridge, le lecteur et le trajet de téléchargement ; capturer le résultat. Exécuter une vraie génération par moteur disponible et un clonage Qwen avec référence autorisée ; noter chaque contrôle non réalisable. Vérifier les empreintes des données existantes et l’absence de worker possédé après fermeture.
- [ ] **Step 5:** Commit `build: package and verify Narrator Studio for Windows`. Ne publier la release Narrator qu’après les critères d’acceptation de la spécification et une vérification finale de la branche ; garder les fichiers utilisateur hors Git.

## Contrôle de couverture du plan

- Identité et quatre écrans : tâches 6–7 ; catalogue et téléchargements : tâches 4–5.
- Compatibilité, moteurs, protocole et cycle de vie : tâches 1–3.
- Données existantes, chemins D:, sauvegarde des petits index, fichiers absents et verrou d’écriture : tâches 1, 3 et 7.
- FR/EN, trois dimensions, clavier et mouvement réduit : tâches 6–8.
- Distribution réelle, essais vocaux, confidentialité et notices : tâche 8.
- Dépendances et outils Windows : préparation, avec versions verrouillées dans les tâches qui les utilisent.

## Choix d’exécution à confirmer

Recommandation : exécution directe dans cette conversation, tâche par tâche. Les interfaces entre bibliothèque, bridge, fenêtre et téléchargements dépendent fortement les unes des autres ; conserver le contexte simplifie leur intégration. Une revue indépendante de la branche intervient à la fin.

Alternative : un agent d’implémentation et un agent de revue distincts par tâche, puis revue globale ; plus de contrôles intermédiaires, davantage de consommation. Aucune implémentation ne commence avant relecture de ce plan et choix de la méthode.
