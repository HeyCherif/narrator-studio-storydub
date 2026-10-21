# Narrator Studio · StoryDub

Application locale de narration longue avec génération TTS et contrôle qualité automatique. La version 2.0 bêta propose une interface Windows Tauri/Rust, avec Tabler sombre violet/cyan, en français et anglais. L’interface PyWebView historique est conservée comme solution de retour.

## Version 2.0 bêta

Studio, bibliothèque de voix, gestion des modèles et historique. Téléchargement Qwen officiel avec reprise et vérification ; réutilisation des moteurs Python, modèles et voix existants.

- [Installation et reprise d’une bibliothèque](docs/installation.md)
- [Notes de version et limites](docs/release.md)
- [Vérifications effectuées](docs/verification-2.0-beta.1.md)

Les environnements IA et modèles restent externes. Le paquet Windows ne contient aucune configuration, voix ni donnée personnelle. Fermer l’ancienne interface avant de réutiliser sa bibliothèque.

## Fonctionnalités

- découpage du texte en segments courts ;
- génération avec les runtimes vocaux locaux ;
- contrôle acoustique des fichiers WAV ;
- retranscription de validation avec Faster-Whisper ;
- comparaison entre texte attendu et texte entendu ;
- nouvelles tentatives et découpage de secours en cas d'échec ;
- assemblage final des segments validés.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Sous Windows, utilisez `LANCER_NARRATOR_STUDIO.bat`. `SELF_TEST.py` fournit un test de régression du pipeline.

## Structure

- `app.py` : application et API locale ;
- `web` : interface utilisateur ;
- `tts_worker.py` et `qwen_tts_worker.py` : génération vocale ;
- `qc_worker.py` et `quality_utils.py` : contrôle qualité.

## Modèles et données privées

Les voix clonées, tenseurs `.pt`, modèles IA, historiques, configuration locale et sorties audio ne sont pas inclus dans le dépôt.
