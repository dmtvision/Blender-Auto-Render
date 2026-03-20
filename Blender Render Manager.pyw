"""
Blender Render Manager — Double-click launcher (no console window).
"""
import os
import sys
import traceback

# Redirect stdout and stderr to prevent crashes in pythonw (where they are None)
# and capture any errors in a log file.
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash_log.txt")
try:
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from render_gui import BlenderRenderApp

    if __name__ == "__main__":
        app = BlenderRenderApp()
        app.mainloop()
except Exception as e:
    with open(log_path, "a", encoding="utf-8") as f:
        traceback.print_exc(file=f)
