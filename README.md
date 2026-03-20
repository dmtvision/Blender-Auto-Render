# Blender Render Manager — Anti-crash

Un outil simple pour lancer des rendus Blender qui **reprennent automatiquement** après un crash ou un redémarrage du PC.

## Comment ça marche

Le système est composé de **deux scripts** :

1. **`render_manager.py`** (wrapper externe) — Lance Blender et surveille les crashes
2. **`blender_render_script.py`** (script interne) — Tourne dans Blender, rend frame par frame via `bpy.ops.render`

### Principe

- Blender est lancé **une seule fois** et rend toutes les frames en séquence (pas de rechargement de scène entre les frames)
- Après **chaque frame** terminée, la progression est sauvegardée dans `render_progress.json`
- Si Blender crash → le wrapper **relance automatiquement** Blender depuis la dernière frame sauvegardée (- 1 frame par sécurité)
- Si le PC redémarre → relancer le `.bat` et le rendu reprend automatiquement
- Si Blender crash 5 fois de suite sans progresser → le script s'arrête (problème avec la scène)

## Interface graphique (GUI)

Pour tout gérer depuis une seule fenêtre, lancer :

```bash
python render_gui.py
```

L'interface permet de :
- **Parcourir** ou **coller** le chemin d'un fichier `.blend`
- **Sélectionner** la version de Blender (auto-détecté depuis `B:\install`)
- **Configurer** chaque job : plage de frames, moteur de rendu, dossier de sortie
- **Activer/désactiver** chaque job avec une checkbox
- **Ajouter** plusieurs jobs de rendu
- **Générer** un fichier `.bat` prêt à lancer
- **Lancer** le rendu directement avec suivi live dans la console intégrée
- **Sauvegarder** les jobs pour les retrouver au prochain lancement

## Installation

### Pour la GUI :
- **Python 3.10+** installé (et dans le PATH)
- **customtkinter** : `pip install customtkinter`
- **Blender** installé

### Pour le mode ligne de commande / .bat :
- **Python 3.10+** installé (et dans le PATH)
- **Blender** installé

Les fichiers suivants doivent être dans le **même dossier** :
- `render_manager.py`
- `blender_render_script.py`
- `render.bat` (ou vos propres `.bat`)

## Utilisation

### Méthode 1 : Fichier .bat (recommandé)

1. Dupliquer `render.bat`
2. Modifier les variables en haut du fichier :
   ```bat
   SET BLENDER_EXE="C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"
   SET BLEND_FILE="E:\projects\ma_scene.blend"
   SET OUTPUT_DIR="E:\projects\render_output"
   SET FRAME_START=1
   SET FRAME_END=250
   ```
3. Double-cliquer sur le `.bat` pour lancer

### Méthode 2 : Ligne de commande

```bash
python render_manager.py scene.blend -o ./render -s 1 -e 250
```

Avec un chemin Blender personnalisé :
```bash
python render_manager.py scene.blend -o ./render -s 1 -e 250 --blender "C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"
```

## Arguments

| Argument | Description |
|---|---|
| `blend_file` | Chemin vers le fichier `.blend` |
| `-o`, `--output` | Dossier de sortie des frames rendues |
| `-s`, `--start` | Première frame à rendre |
| `-e`, `--end` | Dernière frame à rendre |
| `--blender` | Chemin vers l'exécutable Blender (défaut : `blender`) |

## Fichier de progression

Le fichier `render_progress.json` est créé dans le dossier de sortie. Il contient :
- La liste des frames terminées
- La dernière frame rendue
- Le statut (en cours / terminé)

**Pour re-rendre un projet déjà terminé** : supprimer `render_progress.json` du dossier de sortie.

## Scénarios

| Situation | Comportement |
|---|---|
| Premier lancement | Rend toutes les frames de start à end |
| Blender crash | Relance automatiquement, reprend 1 frame avant le crash |
| PC redémarre | Relancer le `.bat`, reprend automatiquement |
| Rendu déjà terminé | Affiche un message, ne fait rien |
| 5 crashes consécutifs sans progrès | S'arrête (problème probable avec la scène) |

## En cas de problème

- **"Blender executable not found"** → Vérifier le chemin dans `BLENDER_EXE` du `.bat`
- **"Blend file not found"** → Vérifier le chemin dans `BLEND_FILE`
- **Crashes répétés** → Vérifier que la scène se rend correctement en ouvrant Blender manuellement
