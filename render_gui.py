#!/usr/bin/env python3
"""
Blender Render Manager — GUI
=============================
A minimal, single-window desktop app that wraps render_manager.py
with multi-worker support and split console for stats and logs.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import sys
import subprocess
import threading
import json
import re
from pathlib import Path

# Force UTF-8 for Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except: pass
# ──────────────────────────────────────────────
# Config & Settings
# ──────────────────────────────────────────────

BLENDER_INSTALL_DIR_DEFAULT = r"B:\install"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RENDER_MANAGER_SCRIPT = os.path.join(SCRIPT_DIR, "render_manager.py")
JOBS_SAVE_FILE = os.path.join(SCRIPT_DIR, "render_jobs.json")
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "settings.json")

def load_settings():
    if os.path.isfile(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except: pass
    return {"blender_install_dir": BLENDER_INSTALL_DIR_DEFAULT, "global_workers": 1}

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except: pass

GLOBAL_SETTINGS = load_settings()
BLENDER_INSTALL_DIR = GLOBAL_SETTINGS.get("blender_install_dir", BLENDER_INSTALL_DIR_DEFAULT)

# Theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Colors
BG_DARK = "#1a1a2e"
BG_CARD = "#16213e"
BG_INPUT = "#0f3460"
ACCENT = "#e94560"
ACCENT_HOVER = "#ff6b81"
TEXT_PRIMARY = "#eaeaea"
TEXT_DIM = "#8892b0"
SUCCESS = "#00d2d3"
BORDER = "#233554"


def discover_blender_installations(install_dir: str) -> list[dict]:
    """Scan install_dir for folders containing blender.exe."""
    installations = []
    if not os.path.isdir(install_dir):
        return installations

    try:
        entries = sorted(os.listdir(install_dir), reverse=True)
    except:
        return []

    for entry in entries:
        full_path = os.path.join(install_dir, entry)
        exe_path = os.path.join(full_path, "blender.exe")
        if os.path.isdir(full_path) and os.path.isfile(exe_path):
            version_match = re.search(r"(\d+\.\d+)", entry)
            version = version_match.group(1) if version_match else entry
            installations.append({
                "label": f"Blender {version}" if version_match else entry,
                "version": version,
                "exe": exe_path,
                "folder": entry,
            })
    return installations


# ──────────────────────────────────────────────
# Render Job Row Widget
# ──────────────────────────────────────────────

class RenderJobRow(ctk.CTkFrame):
    _row_counter = 0

    def __init__(self, master, blender_versions: list[dict], on_delete=None, **kwargs):
        super().__init__(master, fg_color=BG_CARD, corner_radius=12, border_width=1,
                         border_color=BORDER, **kwargs)
        RenderJobRow._row_counter += 1
        self.job_id = RenderJobRow._row_counter
        self.blender_versions = blender_versions
        self.on_delete = on_delete
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        pad = {"padx": 10, "pady": 6}

        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, columnspan=3, sticky="ew", **pad)
        header_frame.grid_columnconfigure(1, weight=1)

        self.enabled_var = ctk.BooleanVar(value=True)
        self.enabled_cb = ctk.CTkCheckBox(header_frame, text="", variable=self.enabled_var, width=24, checkbox_width=20, checkbox_height=20)
        self.enabled_cb.grid(row=0, column=0, padx=(0, 8))

        self.job_label = ctk.CTkLabel(header_frame, text=f"Job #{self.job_id}", font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT_PRIMARY)
        self.job_label.grid(row=0, column=1, sticky="w")

        self.delete_btn = ctk.CTkButton(header_frame, text="✕", width=30, height=28, fg_color="transparent", hover_color="#e94560", command=self._on_delete)
        self.delete_btn.grid(row=0, column=2, sticky="e")

        # Blend file
        ctk.CTkLabel(self, text=".blend", text_color=TEXT_DIM).grid(row=1, column=0, sticky="w", padx=(12, 4), pady=4)
        file_frame = ctk.CTkFrame(self, fg_color="transparent")
        file_frame.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=4)
        file_frame.grid_columnconfigure(0, weight=1)

        self.blend_path_var = ctk.StringVar()
        self.blend_entry = ctk.CTkEntry(file_frame, textvariable=self.blend_path_var, height=32, fg_color=BG_INPUT, border_color=BORDER)
        self.blend_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.browse_btn = ctk.CTkButton(file_frame, text="📂", width=36, height=32, fg_color=BG_INPUT, command=self._browse_blend)
        self.browse_btn.grid(row=0, column=1)

        # Version
        ctk.CTkLabel(self, text="Version", text_color=TEXT_DIM).grid(row=2, column=0, sticky="w", padx=(12, 4), pady=4)
        v_labels = [v["label"] for v in self.blender_versions]
        default_v = v_labels[0] if v_labels else "Aucune"
        self.version_var = ctk.StringVar(value=default_v)
        self.version_menu = ctk.CTkOptionMenu(self, variable=self.version_var, values=v_labels if v_labels else ["Aucune"], fg_color=BG_INPUT, width=260)
        self.version_menu.grid(row=2, column=1, columnspan=2, sticky="w", padx=(0, 10), pady=4)

        # Output
        ctk.CTkLabel(self, text="Output", text_color=TEXT_DIM).grid(row=3, column=0, sticky="w", padx=(12, 4), pady=4)
        out_frame = ctk.CTkFrame(self, fg_color="transparent")
        out_frame.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=4)
        out_frame.grid_columnconfigure(0, weight=1)
        self.output_var = ctk.StringVar()
        self.output_entry = ctk.CTkEntry(out_frame, textvariable=self.output_var, height=32, fg_color=BG_INPUT)
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.browse_out_btn = ctk.CTkButton(out_frame, text="📂", width=36, height=32, fg_color=BG_INPUT, command=self._browse_output)
        self.browse_out_btn.grid(row=0, column=1, padx=(0, 6))
        self.auto_out_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(out_frame, text="Auto", variable=self.auto_out_var, width=60, command=self._on_auto_toggle).grid(row=0, column=2)

        # Range
        ctk.CTkLabel(self, text="Frames", text_color=TEXT_DIM).grid(row=4, column=0, sticky="w", padx=(12, 4), pady=4)
        range_frame = ctk.CTkFrame(self, fg_color="transparent")
        range_frame.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=4)
        self.start_var = ctk.StringVar(value="1"); self.end_var = ctk.StringVar(value="250"); self.step_var = ctk.StringVar(value="1")
        ctk.CTkEntry(range_frame, textvariable=self.start_var, width=60).grid(row=0, column=0, padx=2)
        ctk.CTkLabel(range_frame, text="→").grid(row=0, column=1)
        ctk.CTkEntry(range_frame, textvariable=self.end_var, width=60).grid(row=0, column=2, padx=2)
        ctk.CTkLabel(range_frame, text="Step:", text_color=TEXT_DIM).grid(row=0, column=3, padx=(10, 2))
        ctk.CTkEntry(range_frame, textvariable=self.step_var, width=40).grid(row=0, column=4, padx=2)
        self.auto_range_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(range_frame, text="Auto", variable=self.auto_range_var, width=60, command=self._on_auto_toggle).grid(row=0, column=5)

        # Settings
        ctk.CTkLabel(self, text="Settings", text_color=TEXT_DIM).grid(row=5, column=0, sticky="w", padx=(12, 4), pady=4)
        conf_frame = ctk.CTkFrame(self, fg_color="transparent")
        conf_frame.grid(row=5, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=4)
        self.engine_var = ctk.StringVar(value="CYCLES")
        ctk.CTkOptionMenu(conf_frame, variable=self.engine_var, values=["CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"], width=150).grid(row=0, column=0, padx=2)
        self.auto_engine_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(conf_frame, text="Auto", variable=self.auto_engine_var, width=60, command=self._on_auto_toggle).grid(row=0, column=1)
        
        ctk.CTkLabel(conf_frame, text="Preset:", text_color=TEXT_DIM).grid(row=0, column=2, padx=(15, 2))
        self.preset_var = ctk.StringVar(value="Default")
        ctk.CTkOptionMenu(conf_frame, variable=self.preset_var, values=["Default", "Fast (128)", "Draft (32+Simp)"], width=130).grid(row=0, column=3, padx=2)
        
        ctk.CTkButton(conf_frame, text="🔍 Detect", width=80, height=30, fg_color=BG_INPUT, command=self._detect_settings).grid(row=0, column=4, padx=(15, 0))

        self._on_auto_toggle()

    def _on_auto_toggle(self):
        st_out = "disabled" if self.auto_out_var.get() else "normal"
        self.output_entry.configure(state=st_out); self.browse_out_btn.configure(state=st_out)

    def _browse_blend(self):
        path = filedialog.askopenfilename(filetypes=[("Blender files", "*.blend")])
        if path: self.blend_path_var.set(path)
    def _browse_output(self):
        path = filedialog.askdirectory()
        if path: self.output_var.set(path)
    def _on_delete(self):
        if self.on_delete: self.on_delete(self)

    def _detect_settings(self):
        blend = self.blend_path_var.get().strip()
        exe = self.get_blender_exe()
        if not (blend and exe): return
        import render_manager
        info = render_manager.get_blend_info(exe, blend)
        if info:
            if self.auto_range_var.get():
                self.start_var.set(str(info.get('start', 1))); self.end_var.set(str(info.get('end', 250)))
            if self.auto_out_var.get():
                out = info.get('output', ""); self.output_var.set(os.path.dirname(out) if out and not out.endswith(('/', '\\')) else out)
            if self.auto_engine_var.get():
                self.engine_var.set(info.get('engine', 'CYCLES'))

    def get_blender_exe(self) -> str | None:
        label = self.version_var.get()
        for v in self.blender_versions:
            if v["label"] == label: return v["exe"]
        return None

    def get_config(self) -> dict:
        return {
            "enabled": self.enabled_var.get(), "auto_out": self.auto_out_var.get(),
            "auto_range": self.auto_range_var.get(), "auto_engine": self.auto_engine_var.get(),
            "blend_file": self.blend_path_var.get(), "blender_version": self.version_var.get(),
            "output_dir": self.output_var.get(), "frame_start": self.start_var.get(),
            "frame_end": self.end_var.get(), "frame_step": self.step_var.get(),
            "engine": self.engine_var.get(), "preset": self.preset_var.get()
        }

    def set_config(self, config: dict):
        self.enabled_var.set(config.get("enabled", True))
        self.auto_out_var.set(config.get("auto_out", True))
        self.auto_range_var.set(config.get("auto_range", True))
        self.auto_engine_var.set(config.get("auto_engine", True))
        self.blend_path_var.set(config.get("blend_file", ""))
        self.version_var.set(config.get("blender_version", self.version_var.get()))
        self.output_var.set(config.get("output_dir", ""))
        self.start_var.set(str(config.get("frame_start", "1")))
        self.end_var.set(str(config.get("frame_end", "250")))
        self.step_var.set(str(config.get("frame_step", "1")))
        self.engine_var.set(config.get("engine", "CYCLES"))
        self.preset_var.set(config.get("preset", "Default"))
        self._on_auto_toggle()

    def validate(self):
        b = self.blend_path_var.get().strip()
        if not (b and os.path.isfile(b)): return f"Job #{self.job_id}: Fichier .blend invalide"
        if not self.get_blender_exe(): return f"Job #{self.job_id}: Blender non trouvé"
        return None


# ──────────────────────────────────────────────
# Main Application
# ──────────────────────────────────────────────

class BlenderRenderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Blender Render Manager")
        self.geometry("1100x900")
        self.configure(fg_color=BG_DARK)

        self.blender_versions = discover_blender_installations(BLENDER_INSTALL_DIR)
        self.job_rows = []
        self.running_process = None
        self.is_running = False

        self._build_ui()
        self._load_saved_jobs()

    def _build_ui(self):
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(top_frame, text="⬡  Blender Auto-Render", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        
        settings_bar = ctk.CTkFrame(self, fg_color=BG_CARD)
        settings_bar.pack(fill="x", padx=20, pady=5)
        
        ctk.CTkLabel(settings_bar, text="Workers (Parallel) :", text_color=TEXT_DIM).pack(side="left", padx=(15, 5))
        self.workers_var = ctk.StringVar(value=str(GLOBAL_SETTINGS.get("global_workers", 1)))
        ctk.CTkEntry(settings_bar, textvariable=self.workers_var, width=50).pack(side="left", padx=5)
        
        ctk.CTkButton(settings_bar, text="⚙ Path Settings", width=120, fg_color=BG_INPUT, command=self._show_settings).pack(side="right", padx=10)
        ctk.CTkButton(settings_bar, text="↻ Resume Incomplete", width=160, fg_color=SUCCESS, text_color="#000", font=ctk.CTkFont(weight="bold"), command=self._resume_unfinished).pack(side="right", padx=5)

        self.jobs_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.jobs_scroll.pack(fill="both", expand=True, padx=16, pady=5)
        self.jobs_scroll.grid_columnconfigure(0, weight=1)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkButton(btn_frame, text="＋ Add Job", fg_color=BG_CARD, command=self._add_job_row).pack(side="left", padx=5)
        self.run_btn = ctk.CTkButton(btn_frame, text="▶ START ALL", fg_color=ACCENT, font=ctk.CTkFont(weight="bold"), height=40, command=self._start_render)
        self.run_btn.pack(side="right", padx=5)
        self.stop_btn = ctk.CTkButton(btn_frame, text="⏹ STOP RENDERS", fg_color="#c0392b", height=40, command=self._stop_render)

        # SPLIT CONSOLE
        console_container = ctk.CTkFrame(self, fg_color="transparent")
        console_container.pack(fill="x", padx=20, pady=(0, 20))

        # Stats Section (Global)
        self.stats_text = ctk.CTkTextbox(console_container, height=100, fg_color=BG_CARD, text_color=SUCCESS, font=("Consolas", 12, "bold"))
        self.stats_text.pack(fill="x", pady=(0, 10))
        self.stats_text.insert("0.0", ">>> Global Render Stats Wait Area <<<\n")
        self.stats_text.configure(state="disabled")

        # Logs Section (Per Frame)
        self.logs_text = ctk.CTkTextbox(console_container, height=180, fg_color=BG_CARD, text_color=TEXT_PRIMARY, font=("Consolas", 11))
        self.logs_text.pack(fill="x")
        self.logs_text.configure(state="disabled")

    def _show_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("500x250")
        ctk.CTkLabel(dialog, text="Blender Installations Root Folder (ex: B:\\install) :").pack(pady=(20, 5))
        path_var = ctk.StringVar(value=BLENDER_INSTALL_DIR)
        ctk.CTkEntry(dialog, textvariable=path_var, width=400).pack(pady=5)
        
        def save():
            GLOBAL_SETTINGS["blender_install_dir"] = path_var.get()
            GLOBAL_SETTINGS["global_workers"] = int(self.workers_var.get() or 1)
            save_settings(GLOBAL_SETTINGS)
            messagebox.showinfo("Saved", "Settings saved. Please restart the app.")
            dialog.destroy()
        ctk.CTkButton(dialog, text="Save & Close", command=save).pack(pady=20)

    def _add_job_row(self, config=None):
        row = RenderJobRow(self.jobs_scroll, self.blender_versions, on_delete=self._remove_job_row)
        row.pack(fill="x", pady=6)
        if config: row.set_config(config)
        self.job_rows.append(row); return row

    def _remove_job_row(self, row):
        row.destroy(); self.job_rows.remove(row)

    def _save_jobs(self):
        configs = [row.get_config() for row in self.job_rows]
        with open(JOBS_SAVE_FILE, "w", encoding="utf-8") as f: json.dump(configs, f, indent=2)
        try: GLOBAL_SETTINGS["global_workers"] = int(self.workers_var.get())
        except: GLOBAL_SETTINGS["global_workers"] = 1
        save_settings(GLOBAL_SETTINGS)

    def _load_saved_jobs(self):
        if os.path.isfile(JOBS_SAVE_FILE):
            try:
                with open(JOBS_SAVE_FILE, "r", encoding="utf-8") as f:
                    configs = json.load(f)
                    for c in configs: self._add_job_row(c)
                return
            except: pass
        self._add_job_row()

    def _resume_unfinished(self):
        self._log("🔍 Checking for incomplete renders...")
        count = 0
        for row in self.job_rows:
            cfg = row.get_config()
            out = cfg["output_dir"]
            if not out or cfg.get("auto_out"): continue
            prog_file = os.path.join(out, "render_progress.json")
            if os.path.exists(prog_file):
                try:
                    with open(prog_file, "r") as f: data = json.load(f)
                    if data.get("status") != "completed":
                        self._log(f"   Incomplete: {os.path.basename(cfg['blend_file'])}")
                        row.enabled_var.set(True); count += 1
                    else: row.enabled_var.set(False)
                except: pass
        if count > 0: self._log(f"✅ {count} job(s) ready.")
        else: self._log("ℹ No incomplete renders found.")

    def _start_render(self):
        if self.is_running: return
        jobs = [r for r in self.job_rows if r.enabled_var.get()]
        if not jobs: return
        for r in jobs:
            err = r.validate()
            if err: messagebox.showerror("Error", err); return
        self.is_running = True
        self.run_btn.pack_forget(); self.stop_btn.pack(side="right", padx=5)
        self._save_jobs()
        threading.Thread(target=self._run_all, args=(jobs,), daemon=True).start()

    def _run_all(self, jobs):
        try:
            workers = str(self.workers_var.get() or 1)
            for i, row in enumerate(jobs, 1):
                if not self.is_running: break
                cfg = row.get_config()
                self._log_safe(f"\n▶ [{i}/{len(jobs)}] JOB: {os.path.basename(cfg['blend_file'])}")
                
                cmd = [sys.executable, "-u", RENDER_MANAGER_SCRIPT, cfg["blend_file"]]
                cmd += ["-o", "auto" if cfg["auto_out"] else str(cfg["output_dir"])]
                cmd += ["-s", "auto" if cfg["auto_range"] else str(cfg["frame_start"])]
                cmd += ["-e", "auto" if cfg["auto_range"] else str(cfg["frame_end"])]
                cmd += ["-st", str(cfg["frame_step"]), "--blender", str(row.get_blender_exe())]
                cmd += ["--engine", "auto" if cfg["auto_engine"] else str(cfg["engine"])]
                cmd += ["--workers", workers]
                
                p = cfg.get("preset", "Default")
                if "Fast" in p: cmd += ["--samples", "128"]
                elif "Draft" in p: cmd += ["--samples", "32", "--simplify", "1", "--volumes", "0"]

                self.running_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                                        text=True, bufsize=1, encoding='utf-8', errors='replace',
                                                        creationflags=0x08000000)
                for line in iter(self.running_process.stdout.readline, ""):
                    if not self.is_running: break
                    self._log_safe(line.strip())
                self.running_process.wait()
            self._log_safe("\n🏁 " + ("FINISHED" if self.is_running else "STOPPED"))
        finally:
            self.is_running = False; self.running_process = None
            self.after(0, lambda: (self.stop_btn.pack_forget(), self.run_btn.pack(side="right", padx=5)))

    def _stop_render(self):
        self.is_running = False
        if self.running_process: self.running_process.terminate()

    def _log(self, msg):
        target = self.logs_text
        if "[PROGRESS]" in msg:
            target = self.stats_text
            self.stats_text.configure(state="normal")
            self.stats_text.delete("1.0", "end")
            self.stats_text.insert("end", msg.strip() + "\n")
            self.stats_text.configure(state="disabled")
            return
        
        target.configure(state="normal")
        target.insert("end", msg + "\n")
        target.see("end")
        target.configure(state="disabled")

    def _log_safe(self, msg): self.after(0, lambda: self._log(msg))

if __name__ == "__main__":
    BlenderRenderApp().mainloop()
