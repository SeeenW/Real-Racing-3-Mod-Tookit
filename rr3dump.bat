@echo off
setlocal enabledelayedexpansion
title rr3dump - Real Racing 3 asset dump
cd /d "%~dp0"

rem ---------------------------------------------------------------------------
rem  Drag .m3g / .points / .banim / .dashplanes files - or a folder - onto this
rem  file.  The readable reports land in dump\ next to this script.
rem  Text reports (.txt).  For JSON use rr3dump_json.bat.
rem ---------------------------------------------------------------------------

set "HERE=%~dp0"
set "OUT=%HERE%dump"

rem --- find a Python 3 interpreter -------------------------------------------
set "PYEXE="
set "PYARGS="
where py >nul 2>nul && (
    set "PYEXE=py"
    set "PYARGS=-3"
)
if not defined PYEXE (
    where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYEXE=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYEXE if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PYEXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYEXE if exist "%ProgramFiles%\Python312\python.exe" set "PYEXE=%ProgramFiles%\Python312\python.exe"
if not defined PYEXE if exist "%ProgramFiles%\Python311\python.exe" set "PYEXE=%ProgramFiles%\Python311\python.exe"

if not defined PYEXE (
    echo.
    echo   Python 3 was not found on this machine.
    echo   Install it from https://www.python.org/downloads/ and tick
    echo   "Add python.exe to PATH", then drag the files here again.
    echo.
    pause
    exit /b 1
)

if "%~1"=="" goto :menu

rem --- files were dropped -----------------------------------------------------
if not exist "%OUT%" mkdir "%OUT%"
echo.
echo   rr3dump - writing text reports to %OUT%
echo.
"%PYEXE%" %PYARGS% "%HERE%rr3dump.py" -o "%OUT%" --format txt %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo   Done.
) else (
    echo   Finished with errors ^(exit code %RC%^).  The messages are above.
)
echo.
echo   ---------- newest output files ----------
for /f "tokens=1,* delims=:" %%A in ('dir /b /o-d "%OUT%\*.txt" 2^>nul ^| findstr /n "^"') do (
    if %%A LEQ 12 for %%S in ("%OUT%\%%B") do echo   %%~nS  %%~zS bytes
)
echo   -----------------------------------------
echo.
pause
exit /b %RC%

:menu
cls
echo ==============================================================================
echo   rr3dump - Real Racing 3 asset dump  (text reports)
echo ==============================================================================
echo.
echo   Drag any of these onto this .bat file:
echo.
echo     .banim        animation curves  ^(driver.banim, CAR_wing.banim ...^)
echo     .points       anchors and hinges  ^(CAR.points, CAR_int.points ...^)
echo     .m3g          geometry, materials, meshes
echo     .dashplanes   dashboard LCD quads
echo.
echo   You can drop any number of files at once, or a whole folder.
echo.
echo   What you get in dump\ :
echo.
echo     NAME.txt               one report per dropped file
echo.
echo   Drop a FOLDER ^(e.g. the folder of one car^) and you also get:
echo.
echo     FOLDER_report.txt      first and last frame per part, every anchor,
echo                            and every frame of every banim
echo     FOLDER_frames.csv      one row per part per frame
echo                            ^(file, part, t_ms, x, y, z, rx, ry, rz^)
echo     FOLDER_assembly.txt    wheel mounts, tyre radius, active aero
echo                            pivots and the motion rules
echo.
echo     Also written: NAME_frames.csv - every frame of every part,
echo     one row per line, for Excel filtering and sorting.
echo     and NAME_assembly.txt = wheels and active aero pivots.
echo.
echo   Command line equivalent:
echo.
echo     python rr3dump.py -o D:\out --format both --max-keys 0 "path\to\file.banim"
echo.
echo     --max-keys N   print only N keys per curve in the .banim report
echo     --frames N     decode only the first N animation frames
echo     --no-anim      raw curves only, no per-frame decode
echo.
echo   For JSON output use rr3dump_json.bat.
echo.
echo ==============================================================================
echo.
pause
exit /b 0
