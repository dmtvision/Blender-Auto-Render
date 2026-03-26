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
import time
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

# Colors (Blender Minimalist Style)
BG_DARK = "#1d1d1d"        # Main background
BG_CARD = "#2b2b2b"        # Card / panel background
BG_INPUT = "#3a3a3a"       # Inputs / elements
ACCENT = "#4772b3"         # Blender blue selection
ACCENT_HOVER = "#5c85c7"
TEXT_PRIMARY = "#e6e6e6"
TEXT_DIM = "#9c9c9c"
SUCCESS = "#56804b"        # Soft green
BORDER = "#141414"


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
        self.is_active = False
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
        default_v = v_labels[0] if v_labels else "None"
        self.version_var = ctk.StringVar(value=default_v)
        self.version_menu = ctk.CTkOptionMenu(self, variable=self.version_var, values=v_labels if v_labels else ["None"], fg_color=BG_INPUT, width=260)
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
        self.start_entry = ctk.CTkEntry(range_frame, textvariable=self.start_var, width=60)
        self.start_entry.grid(row=0, column=0, padx=2)
        ctk.CTkLabel(range_frame, text="→").grid(row=0, column=1)
        self.end_entry = ctk.CTkEntry(range_frame, textvariable=self.end_var, width=60)
        self.end_entry.grid(row=0, column=2, padx=2)
        ctk.CTkLabel(range_frame, text="Step:", text_color=TEXT_DIM).grid(row=0, column=3, padx=(10, 2))
        ctk.CTkEntry(range_frame, textvariable=self.step_var, width=40).grid(row=0, column=4, padx=2)
        self.auto_range_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(range_frame, text="Auto", variable=self.auto_range_var, width=60, command=self._on_auto_toggle).grid(row=0, column=5)

        # Settings
        ctk.CTkLabel(self, text="Settings", text_color=TEXT_DIM).grid(row=5, column=0, sticky="nw", padx=(12, 4), pady=(8, 4))
        conf_frame = ctk.CTkFrame(self, fg_color="transparent")
        conf_frame.grid(row=5, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=4)
        
        self.engine_var = ctk.StringVar(value="CYCLES")
        self.engine_menu = ctk.CTkOptionMenu(conf_frame, variable=self.engine_var, values=["CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"], width=150)
        self.engine_menu.grid(row=0, column=0, padx=2, pady=2)
        
        self.auto_engine_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(conf_frame, text="Auto", variable=self.auto_engine_var, width=60, command=self._on_auto_toggle).grid(row=0, column=1, pady=2)
        
        ctk.CTkLabel(conf_frame, text="Preset:", text_color=TEXT_DIM).grid(row=0, column=2, padx=(15, 2), pady=2)
        self.preset_var = ctk.StringVar(value="Default")
        ctk.CTkOptionMenu(conf_frame, variable=self.preset_var, values=["Default", "Fast (128)", "Draft (32+Simp)"], width=130).grid(row=0, column=3, padx=2, pady=2)
        
        # Factory Startup & Detect Button (Row 1)
        self.factory_startup_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(conf_frame, text="Factory Startup (Ignore Addons / Safe Mode)", variable=self.factory_startup_var).grid(row=1, column=0, columnspan=2, sticky="w", padx=2, pady=(10, 2))
        
        ctk.CTkButton(conf_frame, text="🔍 Auto-Detect", width=100, height=28, fg_color=BG_INPUT, hover_color=ACCENT_HOVER, command=self._detect_settings).grid(row=1, column=3, sticky="e", padx=2, pady=(10, 2))
        
        # Packing & FFmpeg (Row 2)
        self.pack_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(conf_frame, text="Pack External Data", variable=self.pack_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=2, pady=4)
        
        self.assemble_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(conf_frame, text="Assemble MP4 Video", variable=self.assemble_var).grid(row=2, column=2, columnspan=2, sticky="w", padx=2, pady=4)

        # Video Settings (Row 3)
        vid_frame = ctk.CTkFrame(conf_frame, fg_color="transparent")
        vid_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(0, 2))
        
        ctk.CTkLabel(vid_frame, text="Video FPS:", text_color=TEXT_DIM).pack(side="left", padx=(2, 2))
        self.fps_var = ctk.StringVar(value="24")
        ctk.CTkEntry(vid_frame, textvariable=self.fps_var, width=50).pack(side="left", padx=2)
        
        ctk.CTkLabel(vid_frame, text="Compression:", text_color=TEXT_DIM).pack(side="left", padx=(15, 2))
        self.quality_var = ctk.StringVar(value="CRF 18 (High)")
        ctk.CTkOptionMenu(vid_frame, variable=self.quality_var, values=["CRF 18 (High)", "CRF 23 (Medium)", "CRF 28 (Low)"], width=130).pack(side="left", padx=2)

        # Progress Bar
        self.progress_bar = ctk.CTkProgressBar(self, height=6, fg_color=BG_DARK, progress_color=SUCCESS)
        self.progress_bar.grid(row=6, column=0, columnspan=3, sticky="ew", padx=10, pady=(4, 10))
        self.progress_bar.set(0)

        self._on_auto_toggle()

    def _on_auto_toggle(self):
        st_out = "disabled" if self.auto_out_var.get() else "normal"
        self.output_entry.configure(state=st_out); self.browse_out_btn.configure(state=st_out)
        
        st_range = "disabled" if self.auto_range_var.get() else "normal"
        self.start_entry.configure(state=st_range); self.end_entry.configure(state=st_range)
        
        st_engine = "disabled" if self.auto_engine_var.get() else "normal"
        self.engine_menu.configure(state=st_engine)

    def set_progress(self, percentage):
        self.progress_bar.set(percentage)

    def set_active(self, active=True):
        self.is_active = active
        if active:
            self.configure(border_color=ACCENT, border_width=2)
            self.job_label.configure(text_color=ACCENT)
        else:
            self.configure(border_color=BORDER, border_width=1)
            self.job_label.configure(text_color=TEXT_PRIMARY)

    def update_id(self, new_id):
        self.job_id = new_id
        self.job_label.configure(text=f"Job #{self.job_id}")

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
            self.fps_var.set(str(round(info.get('fps', 24.0), 2)))

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
            "engine": self.engine_var.get(), "preset": self.preset_var.get(),
            "factory_startup": self.factory_startup_var.get(),
            "pack_external": self.pack_var.get(),
            "assemble_mp4": self.assemble_var.get(),
            "fps": self.fps_var.get(),
            "quality": self.quality_var.get()
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
        self.factory_startup_var.set(config.get("factory_startup", False))
        self.pack_var.set(config.get("pack_external", False))
        self.assemble_var.set(config.get("assemble_mp4", False))
        self.fps_var.set(config.get("fps", "24"))
        self.quality_var.set(config.get("quality", "CRF 18 (High)"))
        self._on_auto_toggle()

    def validate(self):
        b = self.blend_path_var.get().strip()
        if not (b and os.path.isfile(b)): return f"Job #{self.job_id}: Invalid .blend file"
        if not self.get_blender_exe(): return f"Job #{self.job_id}: Blender executable not found"
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
        self.start_render_time = None

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

        # Global Status Info
        self.status_bar = ctk.CTkLabel(self, text="Ready", text_color=TEXT_DIM)
        self.status_bar.pack(side="bottom", anchor="w", padx=20, pady=(0, 10))

    def _show_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("550x300")
        dialog.attributes('-topmost', True)
        dialog.grab_set()
        
        ctk.CTkLabel(dialog, text="Blender Installations Root Folder :", font=("", 14, "bold")).pack(pady=(20, 5))
        
        path_var = ctk.StringVar(value=BLENDER_INSTALL_DIR)
        default_path = r"C:\Program Files\Blender Foundation"
        
        radio_var = ctk.StringVar(value="custom" if path_var.get() != default_path else "default")
        
        def on_radio_change():
            if radio_var.get() == "default":
                path_var.set(default_path)
                entry.configure(state="disabled")
            else:
                entry.configure(state="normal")
                
        ctk.CTkRadioButton(dialog, text=f"Default Windows Install ({default_path})", variable=radio_var, value="default", command=on_radio_change).pack(anchor="w", padx=50, pady=(10, 5))
        
        custom_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        custom_frame.pack(fill="x", padx=50, pady=5)
        ctk.CTkRadioButton(custom_frame, text="Custom Path:", variable=radio_var, value="custom", command=on_radio_change).pack(side="left", padx=(0, 10))
        entry = ctk.CTkEntry(custom_frame, textvariable=path_var, width=220)
        entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(custom_frame, text="📂", width=30, fg_color=BG_INPUT, command=lambda: path_var.set(filedialog.askdirectory())).pack(side="left", padx=(5, 0))
        
        on_radio_change()
        
        def save():
            GLOBAL_SETTINGS["blender_install_dir"] = path_var.get()
            GLOBAL_SETTINGS["global_workers"] = int(self.workers_var.get() or 1)
            save_settings(GLOBAL_SETTINGS)
            messagebox.showinfo("Saved", "Settings saved. Please restart the app.", parent=dialog)
            dialog.destroy()
        ctk.CTkButton(dialog, text="Save & Restart App", fg_color=ACCENT, command=save).pack(pady=20)

    def _add_job_row(self, config=None):
        row = RenderJobRow(self.jobs_scroll, self.blender_versions, on_delete=self._remove_job_row)
        row.pack(fill="x", pady=6)
        if config: row.set_config(config)
        self.job_rows.append(row); return row

    def _remove_job_row(self, row):
        row.destroy(); self.job_rows.remove(row)
        self._update_job_indices()

    def _update_job_indices(self):
        for i, row in enumerate(self.job_rows, 1):
            row.update_id(i)
        RenderJobRow._row_counter = len(self.job_rows)

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
        self._log("🔍 Checking for incomplete renders (physical files check)...")
        count = 0
        for row in self.job_rows:
            cfg = row.get_config()
            out = cfg["output_dir"]
            if not out or cfg.get("auto_out"): continue
            prog_file = os.path.join(out, "render_progress.json")
            if os.path.exists(prog_file):
                try:
                    with open(prog_file, "r") as f: data = json.load(f)
                    
                    frame_start = data.get("frame_start", 1)
                    frame_end = data.get("frame_end", 250)
                    step = data.get("frame_step", 1)
                    
                    # Verifying physical presence of files
                    missing = False
                    total = 0
                    found_count = 0
                    for f in range(frame_start, frame_end + 1, step):
                        total += 1
                        found = False
                        for ext in (".png", ".jpg", ".jpeg", ".exr"):
                            if os.path.exists(os.path.join(out, f"frame_{f:04d}{ext}")):
                                found = True
                                break
                        if found: found_count += 1
                        else: missing = True
                    
                    if missing or found_count < total:
                        # Reset progress status to let manager render again
                        data["status"] = "in_progress"
                        try:
                            with open(prog_file, "w") as fw: json.dump(data, fw)
                        except: pass
                        self._log(f"   Incomplete ({found_count}/{total} frames): {os.path.basename(cfg['blend_file'])}")
                        row.enabled_var.set(True); count += 1
                        if total > 0: row.set_progress(found_count / total)
                    else: 
                        row.enabled_var.set(False)
                        row.set_progress(1.0)
                except Exception as e:
                    self._log(f"   Error parsing progress for {os.path.basename(cfg['blend_file'])}")
                    
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
        self.start_render_time = time.time()
        self.run_btn.pack_forget(); self.stop_btn.pack(side="right", padx=5)
        self._save_jobs()
        self._update_time_elapsed()
        threading.Thread(target=self._run_all, args=(jobs,), daemon=True).start()

    def _run_all(self, jobs):
        try:
            workers = str(self.workers_var.get() or 1)
            for i, row in enumerate(jobs, 1):
                if not self.is_running: break
                self.current_job = row
                self.after(0, lambda r=row: r.set_active(True))
                cfg = row.get_config()
                msg = f"\n▶ [{i}/{len(jobs)}] JOB: {os.path.basename(cfg['blend_file'])}"
                self._log_safe(msg)
                self.after(0, lambda m=msg: self.status_bar.configure(text=m.strip()))
                
                cmd = [sys.executable, "-u", RENDER_MANAGER_SCRIPT, cfg["blend_file"]]
                cmd += ["-o", "auto" if cfg["auto_out"] else str(cfg["output_dir"])]
                cmd += ["-s", "auto" if cfg["auto_range"] else str(cfg["frame_start"])]
                cmd += ["-e", "auto" if cfg["auto_range"] else str(cfg["frame_end"])]
                cmd += ["-st", str(cfg["frame_step"]), "--blender", str(row.get_blender_exe())]
                cmd += ["--engine", "auto" if cfg["auto_engine"] else str(cfg["engine"])]
                cmd += ["--workers", workers]
                if cfg.get("factory_startup"):
                    cmd += ["--factory-startup"]
                if cfg.get("pack_external"):
                    cmd += ["--pack-external"]
                if cfg.get("assemble_mp4"):
                    cmd += ["--assemble-mp4"]
                    # Extract numeric CRF (e.g. 18 from "CRF 18 (High)")
                    try: crf = cfg["quality"].split(" ")[1]
                    except: crf = "18"
                    cmd += ["--ffmpeg-fps", str(cfg["fps"]), "--ffmpeg-crf", crf]
                
                p = cfg.get("preset", "Default")
                if "Fast" in p: cmd += ["--samples", "128"]
                elif "Draft" in p: cmd += ["--samples", "32", "--simplify", "1", "--volumes", "0"]

                self.running_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                                        text=True, bufsize=1, encoding='utf-8', errors='replace')
                for line in iter(self.running_process.stdout.readline, ""):
                    if not self.is_running: break
                    self._log_safe(line.strip())
                
                self.running_process.wait()
                self.after(0, lambda r=row: r.set_active(False))
            self._log_safe("\n🏁 " + ("FINISHED" if self.is_running else "STOPPED"))
        finally:
            self.is_running = False; self.running_process = None
            self.start_render_time = None
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
            
            # Update Progress Bar for Current Job
            try:
                import re
                match = re.search(r"([0-9.]+)\%", msg)
                if match and hasattr(self, "current_job"):
                    perc = float(match.group(1)) / 100.0
                    self.current_job.set_progress(perc)
            except: pass
            return
        
        target.configure(state="normal")
        target.insert("end", msg + "\n")
        target.see("end")
        target.configure(state="disabled")

    def _log_safe(self, msg): self.after(0, lambda: self._log(msg))

    def _update_time_elapsed(self):
        if not self.is_running or self.start_render_time is None:
            return
        
        elapsed = time.time() - self.start_render_time
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        s = int(elapsed % 60)
        time_str = f"Elapsed: {h:02d}:{m:02d}:{s:02d}"
        
        current_status = self.status_bar.cget("text")
        if " | " in current_status:
            current_status = current_status.split(" | ")[0]
        
        self.status_bar.configure(text=f"{current_status} | {time_str}")
        self.after(1000, self._update_time_elapsed)

if __name__ == "__main__":
    BlenderRenderApp().mainloop()
