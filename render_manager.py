#!/usr/bin/env python3
"""
Blender Crash-Resistant Render Manager (External Wrapper)
==========================================================
Launches Blender with an internal render script that renders frame by frame.
Handles real-time global estimation and console output.
Compatible with Blender 4.x and 5.x.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import tempfile
import threading
import re
from pathlib import Path

def get_file_prefix(blend_file: str) -> str:
    blend_filename = os.path.basename(blend_file)
    if not blend_filename:
        return "FRM_"
        
    base = os.path.splitext(blend_filename)[0]
    version = ""
    # find version pattern at the end: _v2, v03, -v4, etc.
    v_match = re.search(r'[-_]*[vV](\d+)$', base)
    if not v_match:
        # just numbers after dash/underscore
        v_match = re.search(r'[-_]+(\d+)$', base)
        
    if v_match:
        version = "v" + v_match.group(1)
        base = base[:v_match.start()]
        
    # extract words based on non-alphanumeric, or CamelCase
    clean = re.sub(r'[^a-zA-Z0-9]', ' ', base)
    clean = re.sub(r'([a-z])([A-Z])', r'\1 \2', clean)
    words = clean.split()
    
    if len(words) > 1:
        abbr = "".join(w[0].upper() for w in words if w)
    elif len(words) == 1:
        abbr = words[0][:4].upper()
    else:
        abbr = "FRM"
        
    if version:
        return f"{abbr}_{version}_"
    else:
        return f"{abbr}_"

# Force UTF-8 for stdout/stderr to avoid charmap errors
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass

# ──────────────────────────────────────────────
# File Locking
# ──────────────────────────────────────────────

class SimpleFileLock:
    def __init__(self, path: str):
        self.lock_dir = path + ".lock"
    def __enter__(self):
        start = time.time()
        while True:
            try:
                os.mkdir(self.lock_dir)
                return self
            except FileExistsError:
                if time.time() - start > 10: # Timeout 10s
                    try: os.rmdir(self.lock_dir)
                    except: pass
                time.sleep(0.1)
    def __exit__(self, *args):
        try: os.rmdir(self.lock_dir)
        except: pass

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

PROGRESS_FILENAME = "render_progress.json"
INTERNAL_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_render_script.py")

# Lines from Blender stdout to always suppress
NOISE_PATTERNS = [
    "HIPEW initialization failed",
    "Read prefs:",
    "found bundled python",
    "Warning: region type",
    "Blender quit",
    "ALSA lib",
    "AL lib",
    "Fra:",  # Blender's own frame counter (we have our own)
]

def is_noise(line: str) -> bool:
    """Returns True if a line is known Blender noise to suppress."""
    for pattern in NOISE_PATTERNS:
        if pattern in line:
            return True
    return False

def get_progress_path(output_dir: str) -> str:
    return os.path.join(output_dir, PROGRESS_FILENAME)

def load_progress(output_dir: str) -> dict | None:
    path = get_progress_path(output_dir)
    if not os.path.exists(path): return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return None

def save_progress(output_dir: str, data: dict) -> None:
    path = get_progress_path(output_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    try: os.replace(tmp_path, path)
    except:
        if os.path.exists(path): os.unlink(path)
        os.rename(tmp_path, path)

def init_progress(blend_file: str, output_dir: str, prefix: str, frame_start: int, frame_end: int) -> dict:
    return {
        "blend_file": os.path.abspath(blend_file),
        "output_dir": os.path.abspath(output_dir),
        "prefix": prefix,
        "frame_start": frame_start, "frame_end": frame_end,
        "completed_frames": [], "last_completed_frame": None,
        "status": "in_progress", "total_time_spent": 0.0,
        "claimed_frames": {}
    }

def print_global_status(progress, total_frames):
    if not progress: return
    completed = len(progress.get("completed_frames", []))
    if completed == 0: return
    
    total_ts = progress.get("total_time_spent", 0.0)
    avg = total_ts / completed
    rem_count = total_frames - completed
    eta = avg * rem_count
    total_est = avg * total_frames
    
    perc = (completed / total_frames) * 100
    
    def fmt(s): 
        s = int(s)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}"
    
    status_line = f"\n[PROGRESS] {perc:3.1f}% | {completed}/{total_frames} frames | Remaining: {fmt(eta)} | Total: {fmt(total_est)}\n"
    print(status_line, flush=True)

def launch_blender(blender_exe: str, blend_file: str, output_dir: str, prefix: str,
                   frame_start: int, frame_end: int, frame_step: int, engine: str, 
                   progress_file: str, worker_id: int = 0, samples=None, simplify=None, volumes=None, total_frames=0,
                   use_factory_startup=False, resolution_scale=None, time_limit=None) -> int:
    cmd = [
        blender_exe,
        "-noaudio",
        "-b", blend_file,
    ]
    if use_factory_startup:
        cmd.insert(1, "--factory-startup")
    else:
        # If not using factory settings, ensure scripts are allowed to run (drivers, etc.)
        cmd.insert(1, "-y") # --enable-autoexec

    cmd.extend([
        "-P", INTERNAL_SCRIPT,
        "--",
        "--start", str(frame_start),
        "--end", str(frame_end),
        "--step", str(frame_step),
        "--engine", engine,
        "--output-dir", output_dir,
        "--prefix", prefix,
        "--progress-file", progress_file,
        "--worker-id", str(worker_id)
    ])
    if samples: cmd.extend(["--samples", str(samples)])
    if simplify: cmd.extend(["--simplify", str(simplify)])
    if volumes: cmd.extend(["--volumes", str(volumes)])
    if resolution_scale: cmd.extend(["--resolution-scale", str(resolution_scale)])
    if time_limit and str(time_limit) != "0": cmd.extend(["--time-limit", str(time_limit)])

    print(f"  [Worker {worker_id}] CMD: {' '.join(cmd[:6])}... (truncated)", flush=True)

    try:
        # Use Popen to pipe stdout in real-time
        # creationflags=0x08000000 (CREATE_NO_WINDOW) hides the console on Windows
        cflags = 0x08000000 if os.name == 'nt' else 0
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                text=True, bufsize=1, encoding='utf-8', errors='replace',
                                creationflags=cflags)
        
        for line in iter(proc.stdout.readline, ""):
            line = line.strip()
            if not line: continue
            
            # Skip known noise
            if is_noise(line):
                continue
            
            # Show frame completion lines (our script prints "OK (")
            if "OK (" in line:
                print(f"  [Worker {worker_id}] {line}", flush=True)
                # After each frame, print the global status
                try:
                    p = load_progress(os.path.dirname(progress_file))
                    print_global_status(p, total_frames)
                except Exception:
                    pass
            elif "[Worker" in line or "[GPU]" in line or "[i]" in line:
                # Our own script's info lines — pass through
                print(f"  {line}", flush=True)
            elif "Rendering frame" in line:
                print(f"  {line}", flush=True)
            elif "Finished" in line and "frames" in line:
                print(f"  {line}", flush=True)
            elif "Error" in line or "Exception" in line or "FAILED" in line:
                print(f"  [Worker {worker_id}] ⚠ {line}", flush=True)
            elif "Warning" in line or "Python" in line:
                print(f"  [Worker {worker_id}] i {line}", flush=True)
            else:
                # Less aggressive skipping: print it anyway to help debug if it's not noise
                print(f"  [Blender] {line}", flush=True)

        proc.stdout.close()
        return proc.wait()
    except Exception as e:
        print(f"  [Worker {worker_id}] ERROR in wrapper: {e}", flush=True)
        return 1

def get_blend_info(blender_exe: str, blend_file: str) -> dict:
    script = """
import bpy, json, sys, os
scene = bpy.context.scene
fps = getattr(scene.render, 'fps', 24) / getattr(scene.render, 'fps_base', 1.0)
info = {'start': scene.frame_start, 'end': scene.frame_end, 'step': scene.frame_step, 'output': bpy.path.abspath(scene.render.filepath), 'engine': scene.render.engine, 'fps': fps}
with open(sys.argv[-1], 'w') as f: json.dump(info, f)
"""
    fd, tmp_path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    script_fd, script_path = tempfile.mkstemp(suffix=".py")
    with open(script_fd, "w", encoding="utf-8") as f: f.write(script)
    
    try:
        subprocess.run([blender_exe, "--factory-startup", "-noaudio", "-b", blend_file, "-P", script_path, "--", tmp_path], 
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180, creationflags=0x08000000)
    except subprocess.TimeoutExpired:
        print("  [!] Blend info detection timed out (180s). File may be too heavy.", flush=True)
    
    try:
        with open(tmp_path, "r") as f: info = json.load(f)
    except: info = {}
    try: os.unlink(tmp_path); os.unlink(script_path)
    except: pass
    return info

def pack_blend_file(blender_exe: str, blend_file: str) -> str | None:
    packed_blend = tempfile.mktemp(suffix=".blend", prefix="packed_")
    script = f"""
import bpy
try:
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=r'{packed_blend}')
except Exception as e:
    print('PACK_FAILED:', e)
"""
    fd, script_path = tempfile.mkstemp(suffix=".py"); os.close(fd)
    with open(script_path, "w", encoding="utf-8") as f: f.write(script)
    
    print(f"  [i] Packing external data into temporary file...", flush=True)
    subprocess.run([blender_exe, "--factory-startup", "-noaudio", "-b", blend_file, "-P", script_path], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
    try: os.unlink(script_path)
    except: pass
    
    if os.path.exists(packed_blend):
        return packed_blend
    return None

def assemble_video(blender_exe: str, output_dir: str, prefix: str, fps: str):
    import glob
    import tempfile
    import re
    
    all_files = []
    found_ext = None
    for ext in (".png", ".exr", ".jpg", ".jpeg", ".tif", ".tiff"):
        matched = glob.glob(os.path.join(output_dir, f"{prefix}*{ext}"))
        if matched:
            all_files = sorted(matched)
            found_ext = ext
            break
            
    if not all_files:
        print(f"  [!] No sequence matching {prefix} found in {output_dir} to assemble.", flush=True)
        return

    print(f"  [i] Assembling {found_ext} video using Blender Compositor at {fps} FPS...", flush=True)
    out_name = f"render_output_{prefix.strip('_')}.mp4" if prefix.strip('_') else "render_output.mp4"
    out_mp4 = os.path.join(output_dir, out_name)
    
    if os.path.exists(out_mp4):
        try: os.unlink(out_mp4)
        except: pass

    quarantine_dir = os.path.join(output_dir, "_blender_quarantine")
    os.makedirs(quarantine_dir, exist_ok=True)

    clean_env = os.environ.copy()
    if 'OCIO' in clean_env:
        del clean_env['OCIO']
    clean_env['BLENDER_USER_SCRIPTS'] = quarantine_dir
    clean_env['BLENDER_USER_CONFIG'] = quarantine_dir

    fd, script_path = tempfile.mkstemp(suffix=".py", prefix="assemble_")
    os.close(fd)
    
    first_file = os.path.basename(all_files[0])
    match = re.search(r'(\d+)' + re.escape(found_ext) + '$', first_file)
    first_frame_num = int(match.group(1)) if match else 1
    duration = len(all_files)
    
    script = f"""
import bpy
import os
import sys

out_mp4 = r"{out_mp4}"

print("--- INITIALIZING VIDEO ASSEMBLY ---")
try:
    bpy.context.scene.display_settings.display_device = 'sRGB'
    bpy.context.scene.view_settings.view_transform = 'AgX'
    bpy.context.scene.view_settings.look = 'None'
    bpy.context.scene.view_settings.exposure = 0.0
    bpy.context.scene.view_settings.gamma = 1.0
    bpy.context.scene.sequencer_colorspace_settings.name = 'sRGB'
except Exception as e:
    pass

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = {duration}
scene.render.fps = int(float({fps}))
if str({fps}) in ("23.98", "23.976"):
    scene.render.fps = 24
    scene.render.fps_base = 1.001

scene.use_nodes = True
tree = scene.node_tree
tree.nodes.clear()

img = bpy.data.images.load(r"{os.path.abspath(all_files[0])}")
# Force image loading to get correct dimensions
try:
    img.update()
    if img.size[0] == 0:
        # Accessing pixels forces a hard load of the file
        _ = img.pixels[0]
except:
    pass

width, height = img.size[0], img.size[1]
if width == 0 or height == 0:
    # Fallback to a standard resolution if detection fails
    width, height = 1920, 1080

scene.render.resolution_x = width if width % 2 == 0 else width - 1
scene.render.resolution_y = height if height % 2 == 0 else height - 1
if scene.render.resolution_x < 2: scene.render.resolution_x = 2
if scene.render.resolution_y < 2: scene.render.resolution_y = 2
scene.render.resolution_percentage = 100

img.source = 'SEQUENCE'
try:
    if "{found_ext.lower()}" == ".exr":
        img.colorspace_settings.name = 'Linear Rec.709'
except:
    pass

node_image = tree.nodes.new(type="CompositorNodeImage")
node_image.image = img
node_image.frame_duration = {duration}
node_image.frame_start = 1
node_image.frame_offset = {first_frame_num} - 1
node_image.use_auto_refresh = True

node_composite = tree.nodes.new(type="CompositorNodeComposite")
tree.links.new(node_image.outputs['Image'], node_composite.inputs['Image'])

scene.render.use_file_extension = True
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.ffmpeg.constant_rate_factor = 'HIGH'
scene.render.filepath = r"{os.path.join(output_dir, 'vid_temp_')}"

if not scene.camera:
    cam_data = bpy.data.cameras.new(name='DummyCam')
    cam_obj = bpy.data.objects.new('DummyCam', cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj

try:
    bpy.ops.render.render(animation=True)
except Exception as e:
    sys.exit(1)
"""
    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
            
        files_before = set(os.listdir(output_dir))
        
        cmd = [blender_exe, "-b", "--factory-startup", "--disable-autoexec", "-P", script_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                text=True, encoding='utf-8', errors='replace', creationflags=0x08000000, env=clean_env)
        
        files_after = set(os.listdir(output_dir))
        new_files = [f for f in files_after - files_before if f.startswith("vid_temp_") and f.endswith(".mp4")]
        
        if result.returncode == 0 and new_files:
            if os.path.exists(out_mp4):
                try: os.unlink(out_mp4)
                except: pass
            os.rename(os.path.join(output_dir, new_files[0]), out_mp4)
            print(f"  [✓] Video successfully created: {out_mp4}", flush=True)
        else:
            print(f"  [!] Video creation failed. Blender output:", flush=True)
            if result.stderr:
                for line in result.stderr.splitlines()[-5:]: print(f"      {line.strip()}", flush=True)
    except Exception as e:
        print(f"  [!] Assembly execution error: {e}", flush=True)
    finally:
        if os.path.exists(script_path):
            try: os.unlink(script_path)
            except: pass
        if os.path.exists(quarantine_dir) and not os.listdir(quarantine_dir):
            try: os.rmdir(quarantine_dir)
            except: pass

def generate_render_report(output_dir: str, args: argparse.Namespace, progress: dict, total_frames: int):
    """Generates a summary report of the render session."""
    report_path = os.path.join(output_dir, "render_report.txt")
    try:
        times = [float(v) for v in progress.get("frame_times", {}).values()]
        if not times: return
        
        total_time = sum(times)
        avg = total_time / len(times)
        min_t = min(times)
        max_t = max(times)
        
        def fmt(s): 
            s = int(s)
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:02d}"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("========================================\n")
            f.write("        BLENDER RENDER REPORT\n")
            f.write("========================================\n\n")
            f.write(f"Date:        {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Blend file:  {os.path.basename(args.blend_file)}\n")
            f.write(f"Blender:     {args.blender}\n")
            f.write(f"Engine:      {getattr(args, 'engine', 'auto')}\n")
            f.write(f"Scale:       {getattr(args, 'resolution_scale', '100%')}\n")
            f.write(f"Samples:     {getattr(args, 'samples', 'Default')}\n")
            f.write(f"Time Limit:  {getattr(args, 'time_limit', 'None')}s\n")
            f.write(f"Workers:     {getattr(args, 'workers', 1)}\n\n")
            f.write("----------------------------------------\n")
            f.write(f"Total Frames:    {total_frames}\n")
            f.write(f"Completed:       {len(times)}\n")
            f.write(f"Total Time:      {fmt(total_time)} ({round(total_time, 2)}s)\n")
            f.write(f"Average Frame:   {round(avg, 2)}s\n")
            f.write(f"Shortest Frame:  {round(min_t, 2)}s\n")
            f.write(f"Longest Frame:   {round(max_t, 2)}s\n")
            f.write("----------------------------------------\n")
            f.write("\nRendered with Blender Auto-Render Manager\n")
            
        print(f"  [✓] Render report saved to: {report_path}", flush=True)
    except Exception as e:
        print(f"  [!] Failed to generate report: {e}", flush=True)

def run(args: argparse.Namespace) -> None:
    blend_file = os.path.abspath(args.blend_file)
    blender_exe = args.blender
    if not os.path.isfile(blend_file):
        print(f"  [!] Blend file not found: {blend_file}", flush=True)
        sys.exit(1)
    
    if not os.path.isfile(blender_exe):
        print(f"  [!] Blender executable not found: {blender_exe}", flush=True)
        sys.exit(1)
    
    print(f"  [i] Blend: {blend_file}", flush=True)
    print(f"  [i] Blender: {blender_exe}", flush=True)
    
    if getattr(args, 'pack_external', False):
        new_blend = pack_blend_file(blender_exe, blend_file)
        if new_blend:
            blend_file = new_blend
            print(f"  [i] Successfully packed to: {blend_file}", flush=True)
        else:
            print(f"  [!] Failed to pack data, using original blend.", flush=True)
    
    needs_auto = (args.start == 'auto' or args.end == 'auto' or args.output == 'auto')
    if needs_auto:
        print(f"  [i] Auto-detecting scene settings...", flush=True)
        info = get_blend_info(blender_exe, blend_file)
        if not info:
            print(f"  [!] Failed to detect scene info.", flush=True)
            sys.exit(1)
        frame_start = info['start'] if args.start == 'auto' else int(args.start)
        frame_end = info['end'] if args.end == 'auto' else int(args.end)
        step = info.get('step', 1) if args.step == 'auto' else int(args.step)
        output_dir = info['output'] if args.output == 'auto' else args.output
        
        # Only strip filename if we are in auto-mode and it looks like a file path
        if args.output == 'auto' and not output_dir.endswith(('/', '\\')):
            output_dir = os.path.dirname(output_dir) or os.path.dirname(blend_file)
        print(f"  [i] Detected: frames {frame_start}-{frame_end}, output: {output_dir}", flush=True)
    else:
        frame_start, frame_end = int(args.start), int(args.end)
        step = int(args.step) if args.step != 'auto' else 1 # Fallback for safety
        output_dir = args.output

    if not output_dir or output_dir.strip() == "":
        output_dir = os.path.dirname(os.path.abspath(blend_file))

    os.makedirs(output_dir, exist_ok=True)
    progress_file = get_progress_path(output_dir)
    
    # Ensure step is at least 1
    if step < 1: step = 1
    total_frames = len(range(frame_start, frame_end + 1, step))

    progress = load_progress(output_dir)
    if progress and (progress.get("blend_file") != os.path.abspath(blend_file)):
        progress = None
    
    if progress:
        prefix = progress.get("prefix", get_file_prefix(blend_file))
    else:
        prefix = get_file_prefix(blend_file)
    
    if progress and progress.get("status") == "completed":
        print("  [✓] All frames already completed.", flush=True)
        if getattr(args, 'assemble_mp4', False):
            assemble_video(blender_exe, output_dir, prefix, getattr(args, 'ffmpeg_fps', "24"))
        return

    if progress is None:
        progress = init_progress(blend_file, output_dir, prefix, frame_start, frame_end)
        with SimpleFileLock(progress_file): save_progress(output_dir, progress)
    else:
        completed = len(progress.get("completed_frames", []))
        print(f"  [i] Resuming: {completed}/{total_frames} already done.", flush=True)
        with SimpleFileLock(progress_file):
            progress["claimed_frames"] = {}
            save_progress(output_dir, progress)

    num_workers = int(getattr(args, 'workers', 1))
    print(f"  [i] Starting {num_workers} worker(s) | Total frames: {total_frames}", flush=True)

    def worker_thread(worker_id):
        nonlocal progress
        crashes = 0
        while crashes < 5:
            with SimpleFileLock(progress_file):
                progress = load_progress(output_dir) or progress
            
            completed = set(progress.get("completed_frames", []))
            claimed = progress.get("claimed_frames", {})
            
            # Find frames that are NOT completed
            missing_frames = [f for f in range(frame_start, frame_end + 1, step) if f not in completed]
            
            if not missing_frames:
                break # All done!

            # Check if any missing frames are NOT claimed by others
            unclaimed_missing = []
            for f in missing_frames:
                is_claimed_by_other = False
                for wid, frames in claimed.items():
                    if str(wid) != str(worker_id) and f in frames:
                        is_claimed_by_other = True
                        break
                if not is_claimed_by_other:
                    unclaimed_missing.append(f)
            
            if not unclaimed_missing:
                # All remaining work is being handled by other workers.
                # We can safely exit this worker thread.
                break

            exit_code = launch_blender(
                blender_exe, blend_file, output_dir, prefix, frame_start, frame_end, step, 
                getattr(args, 'engine', 'auto'), progress_file, worker_id,
                getattr(args, 'samples', None), getattr(args, 'simplify', None), 
                getattr(args, 'volumes', None), total_frames, getattr(args, 'factory_startup', False),
                getattr(args, 'resolution_scale', None), getattr(args, 'time_limit', None)
            )
            
            if exit_code == 0:
                crashes = 0
                # Short sleep to prevent tight CPU loop if Blender exits too fast
                time.sleep(1)
            else:
                crashes += 1
                if crashes < 5:
                    print(f"  [Worker {worker_id}] ⚠ CRASH #{crashes}/5 — retrying in 3s...", flush=True)
                    time.sleep(3)
                else:
                    print(f"  [Worker {worker_id}] ❌ CRASH LIMIT REACHED. Stopping worker.", flush=True)

    threads = []
    for i in range(num_workers):
        t = threading.Thread(target=worker_thread, args=(i,), daemon=True)
        t.start(); threads.append(t); time.sleep(2)
    for t in threads: t.join()

    # Final status
    final = load_progress(output_dir)
    if final:
        done = len(final.get("completed_frames", []))
        print(f"\n  SESSION ENDED — {done}/{total_frames} frames completed.", flush=True)
        
        # Reports
        generate_render_report(output_dir, args, final, total_frames)
        
        if done >= total_frames and getattr(args, 'assemble_mp4', False):
            assemble_video(blender_exe, output_dir, prefix, getattr(args, 'ffmpeg_fps', "24"))
    else:
        print("\n  SESSION ENDED", flush=True)
        
    # Cleanup packed blend if used
    if getattr(args, 'pack_external', False) and "packed_" in blend_file:
        try: os.unlink(blend_file)
        except: pass

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("blend_file")
    parser.add_argument("-o", "--output", default="auto")
    parser.add_argument("-s", "--start", default="auto")
    parser.add_argument("-e", "--end", default="auto")
    parser.add_argument("-st", "--step", default="1")
    parser.add_argument("--engine", default="auto")
    parser.add_argument("--samples")
    parser.add_argument("--simplify")
    parser.add_argument("--volumes")
    parser.add_argument("--resolution-scale")
    parser.add_argument("--time-limit")
    parser.add_argument("--factory-startup", action="store_true")
    parser.add_argument("--pack-external", action="store_true")
    parser.add_argument("--assemble-mp4", action="store_true")
    parser.add_argument("--ffmpeg-fps", default="24")
    parser.add_argument("--ffmpeg-crf", default="18")
    parser.add_argument("-w", "--workers", type=int, default=1)
    parser.add_argument("--blender", default="blender")
    run(parser.parse_args())

if __name__ == "__main__": main()
