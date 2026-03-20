@echo off
REM ============================================================
REM  BLENDER RENDER MANAGER - Example Batch File
REM ============================================================
REM  Duplicate this file for each project/scene.
REM  Edit the variables below, then double-click to launch.
REM  If Blender crashes or the PC reboots, just re-run this .bat
REM  and the render will resume automatically.
REM ============================================================

REM -- Path to Blender executable --
SET BLENDER_EXE="C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"

REM -- Path to your .blend file --
SET BLEND_FILE="E:\projects\my_scene.blend"

REM -- Output directory for rendered frames --
SET OUTPUT_DIR="E:\projects\render_output"

REM -- Frame range --
SET FRAME_START=1
SET FRAME_END=250

REM ============================================================
REM  DO NOT EDIT BELOW THIS LINE
REM ============================================================

echo.
echo  ========================================
echo   Blender Render Manager
echo  ========================================
echo   Blend : %BLEND_FILE%
echo   Output: %OUTPUT_DIR%
echo   Frames: %FRAME_START% - %FRAME_END%
echo  ========================================
echo.

python "%~dp0render_manager.py" %BLEND_FILE% -o %OUTPUT_DIR% -s %FRAME_START% -e %FRAME_END% --blender %BLENDER_EXE%

echo.
echo  Render session finished. Press any key to close.
pause >nul
