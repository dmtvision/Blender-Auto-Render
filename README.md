# Blender Render Manager — Anti-crash

A simple tool to launch Blender renders that **automatically resume** after a crash or a PC restart.

## How it works

The system consists of **two scripts**:

1. **`render_manager.py`** (External wrapper) — Launches Blender and monitors crashes.
2. **`blender_render_script.py`** (Internal script) — Runs inside Blender, rendering frame by frame via `bpy.ops.render`.

### Concept

- Blender is launched **only once** and renders all frames in sequence (no scene reloading between frames).
- After **each completed frame**, the progress is saved to `render_progress.json`.
- If Blender crashes → the wrapper **automatically restarts** Blender from the last saved frame (- 1 frame for safety).
- If the PC restarts → just re-run the `.bat` file and the render will automatically resume.
- If Blender crashes 5 consecutive times without progressing → the script stops (likely an issue with the scene itself).

## Graphical User Interface (GUI)

To manage everything from a single window, run:

```bash
python render_gui.py
```

The interface allows you to:
- **Browse** or **paste** the path to a `.blend` file.
- **Select** the Blender version (auto-detected from your default or custom installation path).
- **Configure** each job: frame range, render engine, output folder.
- **Enable/disable** each job with a checkbox.
- **Add** multiple render jobs.
- **Run** the render directly with a live console tracker.
- **Save** jobs so they persist on the next launch.
- **Toggle** advanced features like missing-frame detection, EXR/PNG to MP4 FFmpeg assembly, external data packing, and Factory Startup isolation.

## Installation

### For the GUI:
- **Python 3.10+** installed (and added to PATH)
- **customtkinter**: `pip install customtkinter`
- **Blender** installed

### For command line / .bat mode:
- **Python 3.10+** installed (and added to PATH)
- **Blender** installed

The following files must be in the **same directory**:
- `render_manager.py`
- `blender_render_script.py`
- `render.bat` (or your own `.bat` files)

## Usage

### Method 1: .bat File (Recommended)

1. Duplicate `render.bat`.
2. Edit the variables at the top of the file:
   ```bat
   SET BLENDER_EXE="C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"
   SET BLEND_FILE="E:\projects\my_scene.blend"
   SET OUTPUT_DIR="E:\projects\render_output"
   SET FRAME_START=1
   SET FRAME_END=250
   ```
3. Double-click the `.bat` file to launch.

### Method 2: Command Line

```bash
python render_manager.py scene.blend -o ./render -s 1 -e 250
```

With a custom Blender path:
```bash
python render_manager.py scene.blend -o ./render -s 1 -e 250 --blender "C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"
```

## Arguments

| Argument | Description |
|---|---|
| `blend_file` | Path to the `.blend` file |
| `-o`, `--output` | Output folder for rendered frames |
| `-s`, `--start` | First frame to render |
| `-e`, `--end` | Last frame to render |
| `--blender` | Path to the Blender executable (default: `blender`) |
| `--factory-startup` | Starts Blender without user preferences or custom addons |
| `--pack-external` | Automatically packs textures directly into a temporary blend copy before rendering |
| `--assemble-mp4` | Runs FFmpeg to stitch rendered frames (PNG/EXR) into a video |
| `--ffmpeg-fps` | Set the output video FPS (default: 24) |
| `--ffmpeg-crf` | Set video compression quality (default: 18) |

## Progress File

The `render_progress.json` file is created inside the output folder. It contains:
- The list of completed frames
- The last rendered frame
- The current status (in_progress / completed)

**To re-render an already completed project**: simply delete `render_progress.json` from the output folder, or use the "Resume Incomplete" check in the GUI which actively assesses the physical hard-drive frame presence!

## Scenarios

| Situation | Behavior |
|---|---|
| First launch | Renders all frames from start to end |
| Blender crashes | Restarts automatically, resumes 1 frame before the crash |
| PC restarts | Relaunch the `.bat`, resumes automatically |
| Render already complete | Displays a message, triggers FFmpeg if checked, does nothing else |
| 5 consecutive crashes without progress | Stops entirely (probable issue with the scene) |

## Troubleshooting

- **"Blender executable not found"** → Check the `BLENDER_EXE` path in the `.bat` or GUI path settings.
- **"Blend file not found"** → Check the `BLEND_FILE` path.
- **Repeated crashes** → Ensure the scene renders correctly by manually opening it in Blender. Enable `--factory-startup` to rule out incompatible Addon interruptions (e.g., `bgl` deprecation exceptions).
