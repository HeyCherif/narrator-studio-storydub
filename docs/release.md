# Narrator Studio 2.0.0-beta.1

Interface Tauri 2 / Rust, avec Tabler sombre violet/cyan et logo original. Studio, Voix, Modèles et Historique, en français et anglais.

Le bridge conserve les moteurs Python existants OmniVoice, Qwen3-TTS et le contrôle Faster-Whisper. Il reste léger : aucun environnement IA, modèle ni voix personnelle dans le paquet.

Les téléchargements Qwen sont pilotés en Rust : manifeste officiel à révision fixe, SHA256/Git blob SHA1, parties réutilisables, pause/reprise, contrôle d’espace disque, une tâche active et validation avant promotion. L’état est propre à chaque bibliothèque.

La reprise d’installation sauvegarde les petits index et conserve les fichiers à leur emplacement. Les références d’historique manquantes restent visibles ; les exports passent par un choix natif. Le verrou de bibliothèque protège l’accès concurrent entre les nouveaux lanceurs.

## Vérification

- Tests Python de bibliothèque, protocole, arrêt et distribution ; tests frontend de navigation/brouillon, état, historique et configuration.
- Tests Rust de manifeste, chemins, intégrité, transfert HTTP contrôlé et reprise.
- Compilation et empaquetage Windows x64 via GitHub Actions.
- Génération réelle OmniVoice et Qwen, création d’un profil Qwen depuis une référence synthétique, contrôle Whisper avec score 1.0 ; empreintes des index originaux inchangées.

Les commandes de vérification et les résultats exacts du livrable sont consignés dans le rapport joint. La vérification des sources et des moteurs ne remplace pas un essai de chaque dialogue natif sur chaque version de Windows.

## Limites de cette bêta

- Application non signée ; environnements Python IA externes à configurer/réutiliser.
- OmniVoice et Whisper : réutilisation d’une installation existante uniquement.
- Le gestionnaire automatique prend en charge le modèle Qwen Base 0.6B natif, pas les packs GGUF.
- L’interface d’historique est volontairement conservatrice : consultation/export ; aucune suppression n’est exposée dans cette bêta.
- Les préférences FR/EN traduisent l’interface ; les diagnostics des moteurs restent dans leur langue d’origine.

L’ancien lanceur PyWebView est conservé. Fermer toute ancienne version avant de sélectionner sa bibliothèque dans l’application 2.0.
