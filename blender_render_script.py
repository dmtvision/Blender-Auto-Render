"""
Blender Internal Render Script - PERFORMANCE OPTIMIZED
======================================================
This script runs INSIDE Blender (via -P flag).
Compatible with Blender 4.x and 5.x.
"""

import bpy
import sys
import json
import os
import time

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
                if time.time() - start > 10:
                    try: os.rmdir(self.lock_dir)
                    except: pass
                time.sleep(0.1)
    def __exit__(self, *args):
        try: os.rmdir(self.lock_dir)
        except: pass

def get_blender_version():
    """Returns (major, minor, patch) tuple."""
    return bpy.app.version  # e.g. (5, 1, 0)

def setup_performance_gpu(engine):
    """Initializes GPU with maximum performance settings.
    Compatible with Blender 4.x and 5.x."""
    scene = bpy.context.scene
    
    # 1. Threading
    try:
        bpy.context.preferences.system.thread_mode = 'AUTO'
    except: pass

    if engine == 'CYCLES':
        try:
            # Enable Cycles addon — different API in 5.x vs 4.x
            try:
                if "cycles" not in bpy.context.preferences.addons:
                    bpy.ops.preferences.addon_enable(module="cycles")
            except Exception:
                # Blender 5.x: Cycles is built-in, no need to enable it as addon
                pass
            
            cprefs = bpy.context.preferences.addons['cycles'].preferences
            
            # refresh_devices() triggers HIPEW warning on Windows/NVIDIA — harmless
            cprefs.refresh_devices()
            
            print(f"  [i] Scanning GPU devices...", flush=True)
            
            best_type = None
            found_types = []
            
            for dev_type in ('OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI'):
                try:
                    type_devices = cprefs.get_devices_for_type(dev_type)
                    if type_devices:
                        found_types.append(dev_type)
                        if not best_type:
                            best_type = dev_type
                except Exception:
                    continue
            
            if best_type:
                cprefs.compute_device_type = best_type
                # ENABLE ONLY THE GPU FOR MAXIMUM SPEED (avoiding CPU bottleneck)
                active_count = 0
                for device in cprefs.devices:
                    if device.type == best_type:
                        device.use = True
                        active_count += 1
                        print(f"  [GPU] ACTIVE: {device.name} ({best_type})", flush=True)
                    else:
                        device.use = False 
                
                scene.cycles.device = 'GPU'
                print(f"  [GPU] {active_count} device(s) enabled via {best_type}", flush=True)
                
                # Performance settings
                scene.render.use_persistent_data = True
                try:
                    scene.cycles.use_spatial_splits = True
                except Exception:
                    pass  # May not exist in all Blender versions
            else:
                scene.cycles.device = 'CPU'
                available = ", ".join(found_types) if found_types else "None"
                print(f"  [!] WARNING: No GPU found (checked: {available}). Using CPU.", flush=True)
        except Exception as e:
            print(f"  [!] GPU setup error: {e}", flush=True)
            scene.cycles.device = 'CPU'

def parse_args():
    argv = sys.argv
    if "--" not in argv: sys.exit(1)
    custom_args = argv[argv.index("--") + 1:]
    args = {}
    i = 0
    while i < len(custom_args):
        key = custom_args[i].lstrip("-")
        if i + 1 < len(custom_args) and not custom_args[i + 1].startswith("--"):
            args[key] = custom_args[i + 1]; i += 2
        else: args[key] = True; i += 1
    return args

def load_progress(path):
    if not os.path.exists(path): return None
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return None

def save_progress(path, data):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    try: os.replace(tmp_path, path)
    except:
        if os.path.exists(path): os.unlink(path)
        os.rename(tmp_path, path)

def is_frame_done(base_path, frame):
    prefix = f"{base_path}{frame:04d}"
    for ext in (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff"):
        if os.path.exists(prefix + ext): return True
    return False

def set_engine(scene, engine_override):
    """Set render engine with Blender 4.x / 5.x compatibility."""
    if engine_override == "auto":
        return  # Keep whatever is in the .blend file
    
    # Handle EEVEE naming changes across versions
    if engine_override in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            items = bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items
            available = [item.identifier for item in items]
            if "BLENDER_EEVEE_NEXT" in available:
                scene.render.engine = "BLENDER_EEVEE_NEXT"
            elif "BLENDER_EEVEE" in available:
                scene.render.engine = "BLENDER_EEVEE"
            else:
                print(f"  [!] EEVEE not available, keeping: {scene.render.engine}", flush=True)
        except Exception as e:
            print(f"  [!] Engine set error: {e}", flush=True)
    else:
        try:
            scene.render.engine = engine_override
        except Exception as e:
            print(f"  [!] Cannot set engine '{engine_override}': {e}", flush=True)

def main():
    version = get_blender_version()
    print(f"\n  [i] Blender {version[0]}.{version[1]}.{version[2]}", flush=True)
    
    args = parse_args()
    worker_id = args.get("worker-id", "0")
    frame_start, frame_end = int(args.get("start", 1)), int(args.get("end", 250))
    frame_step = int(args.get("step", 1))
    output_path = args.get("output", "//render/")
    progress_path = args.get("progress-file", "render_progress.json")
    
    scene = bpy.context.scene
    
    # Set engine with compatibility
    engine_override = args.get("engine", "auto")
    set_engine(scene, engine_override)
    print(f"  [i] Engine: {scene.render.engine}", flush=True)
    
    # ──────────────────────────────────────────────
    # PERFORMANCE / GPU SETUP
    # ──────────────────────────────────────────────
    setup_performance_gpu(scene.render.engine)
    # ──────────────────────────────────────────────

    # Overrides: samples
    samples = args.get("samples")
    if samples:
        val = int(samples)
        if scene.render.engine == 'CYCLES':
            scene.cycles.samples = val
        elif scene.render.engine in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'):
            if hasattr(scene, "eevee"):
                if hasattr(scene.eevee, "render_samples"): scene.eevee.render_samples = val
                elif hasattr(scene.eevee, "taa_render_samples"): scene.eevee.taa_render_samples = val
        print(f"  [i] Samples override: {val}", flush=True)

    # Overrides: simplify
    simplify = args.get("simplify")
    if simplify:
        scene.render.use_simplify = True
        scene.render.simplify_subdivision = int(simplify)
        print(f"  [i] Simplify: level {simplify}", flush=True)

    # Overrides: volumes
    if args.get("volumes") == "0":
        if hasattr(scene, "cycles"): 
            try: scene.cycles.use_volume = False
            except: pass
        if hasattr(scene, "eevee"):
            if hasattr(scene.eevee, "use_volumes"): scene.eevee.use_volumes = False 
            if hasattr(scene.eevee, "use_volumetric"): scene.eevee.use_volumetric = False 
        print(f"  [i] Volumes: disabled", flush=True)

    # Build output path
    if os.path.isdir(bpy.path.abspath(output_path)):
        base_path = bpy.path.abspath(os.path.join(output_path, "frame_"))
    else:
        base_path = bpy.path.abspath(output_path)
    
    render_range = list(range(frame_start, frame_end + 1, frame_step))
    total_to_render = len(render_range)

    print(f"  [i] Output base: {base_path}", flush=True)
    print(f"  [i] Frames: {frame_start}-{frame_end} (step {frame_step}), total: {total_to_render}", flush=True)
    print(f"\n[Worker {worker_id}] Starting render loop...", flush=True)

    rendered_count = 0

    while True:
        frame = None
        with SimpleFileLock(progress_path):
            progress = load_progress(progress_path) or {"completed_frames": [], "total_time_spent": 0.0}
            completed_set = set(progress.get("completed_frames", []))
            claimed = progress.get("claimed_frames", {})
            locally_completed = []
            for f in render_range:
                if f not in completed_set:
                    if is_frame_done(base_path, f):
                        completed_set.add(f); locally_completed.append(f); continue
                    is_claimed = False
                    for wid, frames in claimed.items():
                        if f in frames: is_claimed = True; break
                    if not is_claimed: frame = f; break
            if locally_completed: progress["completed_frames"] = sorted(list(completed_set))
            if frame is not None:
                if worker_id not in claimed: claimed[worker_id] = []
                claimed[worker_id].append(frame)
                progress["claimed_frames"] = claimed
                save_progress(progress_path, progress)
            elif locally_completed: save_progress(progress_path, progress)

        if frame is None: break 

        # Render
        print(f"  [Worker {worker_id}] Rendering frame {frame}...", end=" ", flush=True)
        t0 = time.time()
        scene.frame_set(frame)
        scene.render.filepath = f"{base_path}{frame:04d}"
        
        try:
            bpy.ops.render.render(write_still=True)
        except Exception as e:
            print(f"FAILED: {e}", flush=True)
            continue
        
        dur = time.time() - t0
        rendered_count += 1
        
        # Save Progress
        with SimpleFileLock(progress_path):
            progress = load_progress(progress_path)
            if progress is None:
                progress = {"completed_frames": [], "total_time_spent": 0.0, "claimed_frames": {}}
            completed_set = set(progress.get("completed_frames", []))
            completed_set.add(frame)
            progress["completed_frames"] = sorted(completed_set)
            progress["total_time_spent"] = progress.get("total_time_spent", 0.0) + dur
            claimed = progress.get("claimed_frames", {})
            if worker_id in claimed and frame in claimed[worker_id]: claimed[worker_id].remove(frame)
            progress["claimed_frames"] = claimed
            if set(render_range).issubset(completed_set): progress["status"] = "completed"
            save_progress(progress_path, progress)

        # Global Stats
        total_ts = progress["total_time_spent"]
        count = len(completed_set)
        avg = total_ts / count if count > 0 else 0
        rem_count = total_to_render - count
        eta, total_est = avg * rem_count, avg * total_to_render
        def fmt(s): return time.strftime('%H:%M:%S', time.gmtime(s))
        print(f"OK ({dur:.1f}s) | {count}/{total_to_render} done | ETA: {fmt(eta)} | Total: {fmt(total_est)}", flush=True)

    print(f"\n[Worker {worker_id}] Finished. Rendered {rendered_count} frames this session.", flush=True)

if __name__ == "__main__":
    main()
