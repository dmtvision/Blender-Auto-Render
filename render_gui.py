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
        self.on_move_up = kwargs.pop("on_move_up", None)
        self.on_move_down = kwargs.pop("on_move_down", None)
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        
        # --- HEADER ---
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(4, 2))
        header_frame.grid_columnconfigure(2, weight=1)

        # Drag Handle (Visual only for now, buttons do the work)
        self.drag_handle = ctk.CTkLabel(header_frame, text="⠿", font=("", 18), text_color=TEXT_DIM, cursor="fleur")
        self.drag_handle.grid(row=0, column=0, padx=(0, 5))
        
        # Drag bindings
        self.drag_handle.bind("<Button-1>", self._on_drag_start)
        self.drag_handle.bind("<B1-Motion>", self._on_drag_motion)

        self.enabled_var = ctk.BooleanVar(value=True)
        self.enabled_cb = ctk.CTkCheckBox(header_frame, text="", variable=self.enabled_var, width=20, checkbox_width=18, checkbox_height=18)
        self.enabled_cb.grid(row=0, column=1, padx=(0, 5))

        self.job_label = ctk.CTkLabel(header_frame, text=f"Job #{self.job_id}", font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_PRIMARY)
        self.job_label.grid(row=0, column=2, sticky="w")

        # Reorder Buttons
        self.up_btn = ctk.CTkButton(header_frame, text="▲", width=26, height=24, fg_color=BG_INPUT, command=lambda: self.on_move_up(self) if self.on_move_up else None)
        self.up_btn.grid(row=0, column=3, padx=2)
        self.down_btn = ctk.CTkButton(header_frame, text="▼", width=26, height=24, fg_color=BG_INPUT, command=lambda: self.on_move_down(self) if self.on_move_down else None)
        self.down_btn.grid(row=0, column=4, padx=2)

        self.delete_btn = ctk.CTkButton(header_frame, text="✕", width=26, height=24, fg_color="transparent", hover_color="#e94560", command=self._on_delete)
        self.delete_btn.grid(row=0, column=5, padx=(5, 0))

        # --- BODY (TWO COLUMNS) ---
        body_frame = ctk.CTkFrame(self, fg_color="transparent")
        body_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=2)
        body_frame.grid_columnconfigure(0, weight=6) 
        body_frame.grid_columnconfigure(1, weight=4)

        # LEFT COLUMN (Paths & Range)
        left_col = ctk.CTkFrame(body_frame, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left_col.grid_columnconfigure(1, weight=1)

        # .blend
        ctk.CTkLabel(left_col, text="File", text_color=TEXT_DIM, font=("", 11)).grid(row=0, column=0, sticky="w", padx=2)
        f_frame = ctk.CTkFrame(left_col, fg_color="transparent")
        f_frame.grid(row=0, column=1, sticky="ew")
        f_frame.grid_columnconfigure(0, weight=1)
        self.blend_path_var = ctk.StringVar()
        self.blend_entry = ctk.CTkEntry(f_frame, textvariable=self.blend_path_var, height=28, font=("", 11), fg_color=BG_INPUT)
        self.blend_entry.grid(row=0, column=0, sticky="ew", padx=(2, 2))
        ctk.CTkButton(f_frame, text="📂", width=32, height=28, fg_color=BG_INPUT, command=self._browse_blend).grid(row=0, column=1)

        # Output
        ctk.CTkLabel(left_col, text="Out", text_color=TEXT_DIM, font=("", 11)).grid(row=1, column=0, sticky="w", padx=2)
        o_frame = ctk.CTkFrame(left_col, fg_color="transparent")
        o_frame.grid(row=1, column=1, sticky="ew")
        o_frame.grid_columnconfigure(0, weight=1)
        self.output_var = ctk.StringVar()
        self.output_entry = ctk.CTkEntry(o_frame, textvariable=self.output_var, height=28, font=("", 11), fg_color=BG_INPUT)
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(2, 2))
        self.browse_out_btn = ctk.CTkButton(o_frame, text="📂", width=32, height=28, fg_color=BG_INPUT, command=self._browse_output)
        self.browse_out_btn.grid(row=0, column=1)
        self.auto_out_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(o_frame, text="Auto", variable=self.auto_out_var, font=("", 10), width=50, checkbox_width=16, checkbox_height=16, command=self._on_auto_toggle).grid(row=0, column=2, padx=4)

        # Version & Frames
        bf_row = ctk.CTkFrame(left_col, fg_color="transparent")
        bf_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        v_labels = [v["label"] for v in self.blender_versions]
        self.version_var = ctk.StringVar(value=v_labels[0] if v_labels else "None")
        self.version_menu = ctk.CTkOptionMenu(bf_row, variable=self.version_var, values=v_labels or ["None"], height=26, font=("", 11), width=140)
        self.version_menu.pack(side="left", padx=2)

        ctk.CTkLabel(bf_row, text="Frames", text_color=TEXT_DIM, font=("", 11)).pack(side="left", padx=(10, 2))
        self.start_var = ctk.StringVar(value="1"); self.end_var = ctk.StringVar(value="250"); self.step_var = ctk.StringVar(value="1")
        self.start_entry = ctk.CTkEntry(bf_row, textvariable=self.start_var, width=50, height=26, font=("", 11))
        self.start_entry.pack(side="left", padx=1)
        ctk.CTkLabel(bf_row, text="→").pack(side="left")
        self.end_entry = ctk.CTkEntry(bf_row, textvariable=self.end_var, width=50, height=26, font=("", 11))
        self.end_entry.pack(side="left", padx=1)
        ctk.CTkLabel(bf_row, text="Step", text_color=TEXT_DIM, font=("", 11)).pack(side="left", padx=(10, 2))
        self.step_entry = ctk.CTkEntry(bf_row, textvariable=self.step_var, width=35, height=26, font=("", 11))
        self.step_entry.pack(side="left", padx=1)
        self.auto_range_var = ctk.BooleanVar(value=True)
        self.auto_range_cb = ctk.CTkCheckBox(bf_row, text="Auto", variable=self.auto_range_var, font=("", 10), width=50, checkbox_width=16, checkbox_height=16, command=self._on_auto_toggle)
        self.auto_range_cb.pack(side="left", padx=5)

        # RIGHT COLUMN (Settings)
        right_col = ctk.CTkFrame(body_frame, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="nsew")
        
        # Row 0: Engine & Scale
        r0 = ctk.CTkFrame(right_col, fg_color="transparent")
        r0.pack(fill="x", pady=1)
        self.engine_var = ctk.StringVar(value="CYCLES")
        self.engine_menu = ctk.CTkOptionMenu(r0, variable=self.engine_var, values=["CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"], height=26, font=("", 11), width=100)
        self.engine_menu.pack(side="left", padx=1)
        self.auto_engine_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(r0, text="Auto", variable=self.auto_engine_var, font=("", 10), width=50, checkbox_width=16, checkbox_height=16, command=self._on_auto_toggle).pack(side="left", padx=4)
        ctk.CTkLabel(r0, text="Scale", text_color=TEXT_DIM, font=("", 11)).pack(side="left", padx=(5, 2))
        self.scale_var = ctk.StringVar(value="100%")
        ctk.CTkOptionMenu(r0, variable=self.scale_var, values=["200%", "150%", "125%", "100%", "75%", "50%", "25%"], height=26, font=("", 11), width=75).pack(side="left", padx=1)

        # Row 1: Preset & Time Limit
        r1 = ctk.CTkFrame(right_col, fg_color="transparent")
        r1.pack(fill="x", pady=1)
        self.preset_var = ctk.StringVar(value="Default")
        ctk.CTkOptionMenu(r1, variable=self.preset_var, values=["Default", "Fast (128)", "Draft (32+Simp)"], height=26, font=("", 11), width=100).pack(side="left", padx=1)
        ctk.CTkLabel(r1, text="Limit", text_color=TEXT_DIM, font=("", 11)).pack(side="left", padx=(5, 2))
        self.time_limit_var = ctk.StringVar(value="0")
        ctk.CTkEntry(r1, textvariable=self.time_limit_var, width=50, height=26, font=("", 11)).pack(side="left", padx=1)
        ctk.CTkButton(r1, text="🔍 Auto-Detect", width=85, height=26, font=("", 10), fg_color=BG_INPUT, command=self._detect_settings).pack(side="right", padx=1)

        # Row 2: Flags & Options
        r2 = ctk.CTkFrame(right_col, fg_color="transparent")
        r2.pack(fill="x", pady=2)
        self.factory_startup_var = ctk.BooleanVar(value=False); self.pack_var = ctk.BooleanVar(value=False); self.assemble_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(r2, text="Safe", variable=self.factory_startup_var, font=("", 10), checkbox_width=14, checkbox_height=14).pack(side="left", padx=2)
        ctk.CTkCheckBox(r2, text="Pack", variable=self.pack_var, font=("", 10), checkbox_width=14, checkbox_height=14).pack(side="left", padx=2)
        ctk.CTkCheckBox(r2, text="Video", variable=self.assemble_var, font=("", 10), checkbox_width=14, checkbox_height=14).pack(side="left", padx=2)

        # Video Settings (Row 3 in new layout)
        r3 = ctk.CTkFrame(right_col, fg_color="transparent")
        r3.pack(fill="x", pady=1)
        ctk.CTkLabel(r3, text="FPS:", text_color=TEXT_DIM, font=("", 11)).pack(side="left", padx=(2, 2))
        self.fps_var = ctk.StringVar(value="24")
        ctk.CTkEntry(r3, textvariable=self.fps_var, width=40, height=26, font=("", 11)).pack(side="left", padx=1)
        ctk.CTkLabel(r3, text="Quality:", text_color=TEXT_DIM, font=("", 11)).pack(side="left", padx=(10, 2))
        self.quality_var = ctk.StringVar(value="CRF 18 (High)")
        ctk.CTkOptionMenu(r3, variable=self.quality_var, values=["CRF 18 (High)", "CRF 23 (Medium)", "CRF 28 (Low)"], height=26, font=("", 11), width=120).pack(side="left", padx=1)

        # Progress
        self.progress_bar = ctk.CTkProgressBar(self, height=4, fg_color=BG_DARK, progress_color=SUCCESS)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 6))
        self.progress_bar.set(0)

        self._on_auto_toggle()

    def _on_drag_start(self, event):
        self._drag_start_y = event.y_root

    def _on_drag_motion(self, event):
        delta = event.y_root - self._drag_start_y
        threshold = 40 # px to trigger swap
        if delta > threshold:
            if self.on_move_down: 
                self.on_move_down(self)
                self._drag_start_y = event.y_root
        elif delta < -threshold:
            if self.on_move_up: 
                self.on_move_up(self)
                self._drag_start_y = event.y_root

    def _on_auto_toggle(self):
        st_out = "disabled" if self.auto_out_var.get() else "normal"
        self.output_entry.configure(state=st_out)
        if hasattr(self, "browse_out_btn"): self.browse_out_btn.configure(state=st_out)
        
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
            "resolution_scale": self.scale_var.get(),
            "time_limit": self.time_limit_var.get(),
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
        self.scale_var.set(config.get("resolution_scale", "100%"))
        self.time_limit_var.set(config.get("time_limit", "0"))
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
        row = RenderJobRow(self.jobs_scroll, self.blender_versions, 
                           on_delete=self._remove_job_row,
                           on_move_up=self._move_job_up,
                           on_move_down=self._move_job_down)
        row.pack(fill="x", pady=4) 
        if config: row.set_config(config)
        self.job_rows.append(row); return row

    def _remove_job_row(self, row):
        row.destroy(); self.job_rows.remove(row)
        self._update_job_indices()

    def _move_job_up(self, row):
        idx = self.job_rows.index(row)
        if idx > 0:
            self.job_rows[idx], self.job_rows[idx-1] = self.job_rows[idx-1], self.job_rows[idx]
            self._reorder_rows_ui()

    def _move_job_down(self, row):
        idx = self.job_rows.index(row)
        if idx < len(self.job_rows) - 1:
            self.job_rows[idx], self.job_rows[idx+1] = self.job_rows[idx+1], self.job_rows[idx]
            self._reorder_rows_ui()

    def _reorder_rows_ui(self):
        for row in self.job_rows:
            row.pack_forget()
        for row in self.job_rows:
            row.pack(fill="x", pady=4)
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
        
        # Capture all configs in main thread (critical for Tkinter safety)
        configs = []
        for r in jobs:
            configs.append((r, r.get_config(), r.get_blender_exe()))
        
        self._save_jobs()
        self._update_time_elapsed()
        
        workers = str(self.workers_var.get() or 1)
        threading.Thread(target=self._run_all, args=(configs, workers), daemon=True).start()

    def _run_all(self, job_data, workers):
        self._log_safe("   [v] Initiating render thread...")
        try:
            self._log_safe(f"   [v] Workers: {workers} | Jobs: {len(job_data)}")
            for i, (row, cfg, blender_exe) in enumerate(job_data, 1):
                if not self.is_running: break
                self.current_job = row
                self.after(0, lambda r=row: r.set_active(True))
                
                msg = f"\n▶ [{i}/{len(job_data)}] JOB: {os.path.basename(cfg['blend_file'])}"
                self._log_safe(msg)
                self.after(0, lambda m=msg: self.status_bar.configure(text=m.strip()))
                
                if not blender_exe:
                    self._log_safe(f"❌ Error: Blender executable not found for Job #{row.job_id}")
                    continue

                if not os.path.exists(RENDER_MANAGER_SCRIPT):
                    self._log_safe(f"❌ Error: Manager script not found at {RENDER_MANAGER_SCRIPT}")
                    continue

                cmd = [sys.executable, "-u", str(RENDER_MANAGER_SCRIPT), str(cfg["blend_file"])]
                cmd += ["-o", "auto" if cfg["auto_out"] else str(cfg["output_dir"])]
                cmd += ["-s", "auto" if cfg["auto_range"] else str(cfg["frame_start"])]
                cmd += ["-e", "auto" if cfg["auto_range"] else str(cfg["frame_end"])]
                cmd += ["-st", str(cfg["frame_step"]), "--blender", str(blender_exe)]
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
                
                if cfg.get("resolution_scale"):
                    cmd += ["--resolution-scale", str(cfg["resolution_scale"])]
                
                if cfg.get("time_limit") and str(cfg["time_limit"]) != "0":
                    cmd += ["--time-limit", str(cfg["time_limit"])]
                
                p = cfg.get("preset", "Default")
                if "Fast" in p: cmd += ["--samples", "128"]
                elif "Draft" in p: cmd += ["--samples", "32", "--simplify", "1", "--volumes", "0"]
 
                self._log_safe(f"   Launch command: {' '.join(cmd)}")
                
                cflags = 0x08000000 if os.name == 'nt' else 0
                try:
                    self.running_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                                            text=True, bufsize=1, encoding='utf-8', errors='replace',
                                                            creationflags=cflags)
                except Exception as e:
                    self._log_safe(f"❌ Error: Could not start process: {e}")
                    self.after(0, lambda r=row: r.set_active(False))
                    continue

                for line in iter(self.running_process.stdout.readline, ""):
                    if not self.is_running: break
                    self._log_safe(line.strip())
                
                self.running_process.wait()
                self.after(0, lambda r=row: r.set_active(False))
            self._log_safe("\n🏁 " + ("FINISHED" if self.is_running else "STOPPED"))
        except Exception as e:
            import traceback
            error_msg = f"Fatal Error in render thread:\n{e}\n{traceback.format_exc()}"
            print(error_msg)
            self._log_safe(f"\n❌ FATAL THREAD ERROR: {e}")
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
