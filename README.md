# Centre d'aide SmartCampus (site web)

Site d'aide interactif construit à partir de la documentation du projet (`istc-projects/docs/`).

## Consulter le site

- Sur ce poste : double-cliquez sur `site/index.html` (aucun serveur nécessaire).
- En ligne : copiez **le contenu du dossier `site/`** sur n'importe quel hébergement de fichiers statiques. Par exemple :
  - un bloc Nginx `root /var/www/aide;` ;
  - GitHub Pages ;
  - Netlify (glisser-déposer du dossier).

  `404.html` sert de page « introuvable ».

## Fonctions

- Recherche instantanée dans toute la documentation : touche `/` ou `Ctrl+K` / `Cmd+K`, filtre par rubrique, surlignage sur la page d'arrivée.
- **Je suis…** : dix parcours de lecture par profil (secrétariat, comptabilité, formateur, étudiant…), avec progression mémorisée et bandeau « étape suivante » sur les pages.
- « Comment faire pour… » : accès direct aux procédures fréquentes.
- Captures d'écran agrandissables (visionneuse, flèches ← →, taille réelle).
- Définitions du glossaire au survol des termes, glossaire filtrable.
- Listes à cocher mémorisées (ex. « Démarrer une nouvelle année »).
- Bouton « Copier » sur les blocs de commandes.
- Sommaire de page qui suit la lecture, pages précédente / suivante, pages déjà consultées marquées.
- Affichage :
  - mode clair / sombre ;
  - adapté au téléphone ;
  - impression propre ;
  - téléchargement de la version Word (désactivé : le Word contient aussi les rubriques techniques).

La progression, les cases cochées et le thème sont enregistrés dans le navigateur de chaque visiteur (rien n'est envoyé à un serveur).

## Mettre à jour le site après une modification de la documentation

1. Modifiez les fichiers Markdown dans `istc-projects/docs/` (et la navigation dans `istc-projects/mkdocs.yml`).
2. Reconstruisez :

   ```bash
   cd smartcampus-aide
   pip3 install markdown pymdown-extensions pyyaml pygments pillow   # une seule fois
   python3 construire_site.py
   ```

   Si la documentation est ailleurs : `python3 construire_site.py --docs /chemin/vers/docs`.
3. Republiez le dossier `site/`.

Les diagrammes déjà dessinés sont réutilisés depuis `diagrammes/`. Pour un diagramme **nouveau ou modifié**, installez mermaid-cli (`npm install -g @mermaid-js/mermaid-cli`). Sans lui, le diagramme s'affiche sous forme de texte et un avertissement est donné.

## Personnaliser

| Quoi | Où |
|---|---|
| Titre, recherches suggérées, profils « Je suis… », articles populaires (`taches`) | `config_site.json` |
| Rubriques thématiques (icône, couleur, pages) et coordonnées du support (`contact`) | `config_site.json` |
| Logo | `modele/logo.png` |
| Rubriques de la documentation non publiées (Installation, Développeurs : le centre d'aide est réservé aux utilisateurs) | `sections_exclues` dans `config_site.json` |
| Couleurs, typographie, mise en page (charte : dossier `charte graphique/`) | `modele/style.css` (variables en haut du fichier) |
| Comportements interactifs | `modele/app.js` |
| Couleurs des diagrammes | `mermaid-clair.json`, `mermaid-sombre.json` |

Un profil ou une tâche qui pointe vers une page ou une section disparue est signalé par un avertissement pendant la construction.

## Contenu du dossier

```
construire_site.py   générateur (Markdown → HTML)
config_site.json     réglages de la page d'accueil et des parcours
modele/              CSS, JavaScript et icône copiés dans site/assets
diagrammes/          diagrammes déjà dessinés (clair / sombre)
site/                le site prêt à publier (régénéré à chaque construction)
```
