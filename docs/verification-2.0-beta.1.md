# Vérification Narrator Studio 2.0.0-beta.1 — 21 octobre 2026

## Résultats

- Python : 23 tests réussis, dont conservation des données, historique absent/corrompu, chemins, protocole, verrou, arrêt pendant un travail, changement de configuration, isolation des DLL du bridge, arrêt de l’arbre de processus Windows et distribution.
- Interface : 10 tests réussis ; typage strict et construction Vite réussis. Brouillon conservé après navigation, ancien événement ignoré, sortie audio restaurée, historique manquant affiché, transfert de taille inconnue sans pourcentage fictif, réglages Whisper disponibles.
- `SELF_TEST.py` : réussi. Ses avertissements dans le worktree sans configuration ne sont pas des échecs des installations réelles.
- Contrats Rust vérifiés sur Windows GitHub Actions : manifeste et empreintes, chemins audio, transfert HTTP contrôlé, reprise Range, serveur ignorant Range, refus d’une partie complète corrompue, manque d’espace, pause et promotion d’une partie complète valide, une seule tâche active.
- Génération réelle OmniVoice : audio de 4,105 s, deux passages, aucune nouvelle tentative, contrôle Whisper 1,0.
- Clonage réel Qwen depuis cette référence **synthétique**, puis génération réelle avec le nouveau profil : audio de 2,915 s, deux passages, aucune nouvelle tentative, contrôle Whisper 1,0.
- Empreintes SHA256 de `config.json` et `history.json` de l’installation originale inchangées après les essais. Les tests vocaux ont utilisé une bibliothèque séparée et les modèles existants.
- Bridge Windows empaqueté exécuté : bootstrap, historique vide, voix et fermeture via protocole réussis.
- Générations depuis un bridge empaqueté avec une version de Python distincte des moteurs IA : OmniVoice puis Qwen réussis, contrôle Whisper 1,0 et fermeture propre. Les scripts des moteurs sont séparés des extensions Python du bridge ; la recherche de DLL est réinitialisée avant leur lancement. Un contrôle de compatibilité entre deux versions de Python est aussi exécuté dans la CI Windows.
- Exécutable Tauri Windows lancé : fenêtre « Narrator Studio » présente et répondant ; utilisateur a confirmé l’affichage des quatre écrans.
- Un crash du téléchargement a été observé dans la première compilation. La commande native synchrone a été remplacée par une commande asynchrone ; l’utilisateur a confirmé **« ça marche »** après remplacement du binaire effectivement lancé. Les anciens fichiers de livraison ont aussi été remplacés pour éviter une confusion entre les deux compilations.
- Nouvelle identité intégrée à la demande utilisateur : symbole original de ruban sonore violet/cyan, PNG transparent et icônes Windows régénérées. Contrôle visuel du frontend en français/anglais et aux dimensions 1366×850, 1024×768 et 780×650.

## Revue et corrections

Revue indépendante de l’ensemble de la branche, puis corrections : commande de téléchargement sur le contexte asynchrone, verrou conservé jusqu’à la fin du travail, interdiction d’un démarrage tardif de worker après annulation, arrêt des workers avant changement de modèle, reprise d’une partie complète, restauration de la sortie du Studio, configuration Whisper et état de téléchargement distinct pour chaque bibliothèque. Les régressions de cycle de vie et d’interface sont couvertes par des tests.

## Portée des essais

Les dialogues Windows d’export et de choix de bibliothèque et le parcours complet d’installation/désinstallation NSIS n’ont pas tous été automatisés. Le modèle complet n’a pas été retéléchargé pour les tests : le manifeste officiel, un petit fichier réel et des transferts HTTP contrôlés ont été utilisés. Les essais des moteurs réutilisent les poids déjà installés.

Les captures fournies montrent le frontend réel en aperçu web, explicitement identifié comme tel. La confirmation des quatre écrans Windows et du bouton de téléchargement provient du contrôle utilisateur de l’exécutable.

Le paquet reste une **bêta non signée**, avec environnements IA externes. L’ancien lanceur est conservé. L’historique propose consultation/export ; sa suppression n’est pas exposée dans cette bêta.
