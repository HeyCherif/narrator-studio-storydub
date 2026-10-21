# Narrator Studio 2.0 beta — Windows

Windows 10/11 x64 avec Microsoft WebView2. Le paquet n’est pas signé numériquement.

L’installateur contient l’interface Tauri/Rust et un bridge Python léger. Les environnements Python IA, CUDA, modèles et profils vocaux restent externes. Ils ne sont pas inclus dans le téléchargement.

Au premier lancement, ouvrir **Modèles → Reprendre mon installation**, puis choisir le dossier Narrator Studio existant. Confirmer le choix : les petits index sont sauvegardés dans `.narrator-backups`, les modèles et audios restent sur place. Fermer l’ancien Narrator avant d’utiliser cette bibliothèque ; un verrou empêche deux écritures simultanées.

Dans **Configuration avancée**, sélectionner les interpréteurs Python et les dossiers de modèles OmniVoice, Qwen et Whisper si la détection ne les retrouve pas. Qwen nécessite son snapshot Base natif ; un GGUF seul ne suffit pas. Whisper est requis pour transcrire les références lors du clonage.

Le gestionnaire télécharge uniquement `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, depuis Hugging Face. Une révision et les empreintes sont fixées avant le transfert. Pause, reprise, annulation et nouvelle tentative conservent les parties réutilisables. Le bouton de reprise ne supprime aucun modèle existant.

**Studio** : écrire, choisir moteur/voix/langue, générer. Le brouillon persiste dans l’application. **Voix** : importer une référence audio pour créer un profil Qwen. **Historique** : écouter et exporter avec le sélecteur Windows. Les entrées dont l’audio manque restent visibles.

Les préférences de l’application sont sous `%APPDATA%/com.heycherif.narratorstudio`. La bibliothèque sélectionnée est distincte des fichiers d’installation. Désinstaller l’interface ne nécessite pas de supprimer cette bibliothèque.

Le lanceur Python/PyWebView historique reste disponible dans le dépôt pour revenir à l’ancienne interface. Ne pas utiliser les deux interfaces simultanément sur la même bibliothèque.

## Construire

Node.js 24, Python 3.12 avec PyInstaller 6.16, Rust stable et Microsoft C++ Build Tools sont requis. La compilation Windows GitHub Actions est aussi disponible.

```powershell
npm ci --prefix desktop
python -m unittest discover -s tests -v
npm test --prefix desktop
npm run build --prefix desktop
python scripts/build_bridge.py
python scripts/collect_notices.py
desktop/node_modules/.bin/tauri build --features desktop --bundles nsis
```

Les versions npm et Rust sont verrouillées. Les commandes de construction prennent leurs données uniquement dans le code source explicitement empaqueté, jamais dans la bibliothèque utilisateur.
