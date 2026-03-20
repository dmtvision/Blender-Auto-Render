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
from pathlib import Path

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

def init_progress(blend_file: str, output_dir: str, frame_start: int, frame_end: int) -> dict:
    return {
        "blend_file": os.path.abspath(blend_file),
        "output_dir": os.path.abspath(output_dir),
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
    
    def fmt(s): return time.strftime('%H:%M:%S', time.gmtime(s))
    
    status_line = f"\n[PROGRESS] {perc:3.1f}% | {completed}/{total_frames} frames | Restant: {fmt(eta)} | Total: {fmt(total_est)}\n"
    print(status_line, flush=True)

def launch_blender(blender_exe: str, blend_file: str, output_path: str,
                   frame_start: int, frame_end: int, frame_step: int, engine: str, 
                   progress_file: str, worker_id: int = 0, samples=None, simplify=None, volumes=None, total_frames=0) -> int:
    cmd = [
        blender_exe,
        "--factory-startup",
        "-noaudio",
        "-b", blend_file,
        "-P", INTERNAL_SCRIPT,
        "--",
        "--start", str(frame_start),
        "--end", str(frame_end),
        "--step", str(frame_step),
        "--engine", engine,
        "--output", output_path,
        "--progress-file", progress_file,
        "--worker-id", str(worker_id)
    ]
    if samples: cmd.extend(["--samples", str(samples)])
    if simplify: cmd.extend(["--simplify", str(simplify)])
    if volumes: cmd.extend(["--volumes", str(volumes)])

    print(f"  [Worker {worker_id}] CMD: {' '.join(cmd[:6])}... (truncated)", flush=True)

    try:
        # Use Popen to pipe stdout in real-time
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                text=True, bufsize=1, encoding='utf-8', errors='replace')
        
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
            # else: silently skip (Blender verbose output)

        proc.stdout.close()
        return proc.wait()
    except Exception as e:
        print(f"  [Worker {worker_id}] ERROR in wrapper: {e}", flush=True)
        return 1

def get_blend_info(blender_exe: str, blend_file: str) -> dict:
    script = """
import bpy, json, sys, os
scene = bpy.context.scene
info = {'start': scene.frame_start, 'end': scene.frame_end, 'output': bpy.path.abspath(scene.render.filepath), 'engine': scene.render.engine}
with open(sys.argv[-1], 'w') as f: json.dump(info, f)
"""
    fd, tmp_path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    script_fd, script_path = tempfile.mkstemp(suffix=".py")
    with open(script_fd, "w", encoding="utf-8") as f: f.write(script)
    
    try:
        subprocess.run([blender_exe, "--factory-startup", "-noaudio", "-b", blend_file, "-P", script_path, "--", tmp_path], 
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    except subprocess.TimeoutExpired:
        print("  [!] Blend info detection timed out", flush=True)
    
    try:
        with open(tmp_path, "r") as f: info = json.load(f)
    except: info = {}
    try: os.unlink(tmp_path); os.unlink(script_path)
    except: pass
    return info

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
    
    needs_auto = (args.start == 'auto' or args.end == 'auto' or args.output == 'auto')
    if needs_auto:
        print(f"  [i] Auto-detecting scene settings...", flush=True)
        info = get_blend_info(blender_exe, blend_file)
        if not info:
            print(f"  [!] Failed to detect scene info.", flush=True)
            sys.exit(1)
        frame_start = info['start'] if args.start == 'auto' else int(args.start)
        frame_end = info['end'] if args.end == 'auto' else int(args.end)
        output_dir = info['output'] if args.output == 'auto' else args.output
        if not output_dir.endswith(('/', '\\')):
            output_dir = os.path.dirname(output_dir) or os.path.dirname(blend_file)
        print(f"  [i] Detected: frames {frame_start}-{frame_end}, output: {output_dir}", flush=True)
    else:
        frame_start, frame_end, output_dir = int(args.start), int(args.end), args.output

    os.makedirs(output_dir, exist_ok=True)
    progress_file = get_progress_path(output_dir)
    
    step = int(getattr(args, 'step', 1))
    total_frames = len(range(frame_start, frame_end + 1, step))

    progress = load_progress(output_dir)
    if progress and (progress.get("blend_file") != os.path.abspath(blend_file)):
        progress = None
    
    if progress and progress.get("status") == "completed":
        print("  [✓] All frames already completed.", flush=True); return

    if progress is None:
        progress = init_progress(blend_file, output_dir, frame_start, frame_end)
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
            if all(f in completed for f in range(frame_start, frame_end + 1, step)): break

            exit_code = launch_blender(blender_exe, blend_file, output_dir, frame_start, frame_end, step, getattr(args, 'engine', 'auto'), progress_file, worker_id, getattr(args, 'samples', None), getattr(args, 'simplify', None), getattr(args, 'volumes', None), total_frames)
            
            if exit_code == 0: crashes = 0
            else:
                crashes += 1
                print(f"  [Worker {worker_id}] ⚠ CRASH #{crashes}/5 — retrying in 3s...", flush=True)
                time.sleep(3)

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
    else:
        print("\n  SESSION ENDED", flush=True)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("blend_file")
    parser.add_argument("-o", "--output", default="auto")
    parser.add_argument("-s", "--start", default="auto")
    parser.add_argument("-e", "--end", default="auto")
    parser.add_argument("-st", "--step", type=int, default=1)
    parser.add_argument("--engine", default="auto")
    parser.add_argument("--samples")
    parser.add_argument("--simplify")
    parser.add_argument("--volumes")
    parser.add_argument("-w", "--workers", type=int, default=1)
    parser.add_argument("--blender", default="blender")
    run(parser.parse_args())

if __name__ == "__main__": main()
