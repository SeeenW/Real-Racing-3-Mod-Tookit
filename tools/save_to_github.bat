@echo off
rem ---------------------------------------------------------------------------
rem  Save the work to GitHub.
rem
rem  Double-click it, or run it from a terminal:
rem      tools\save_to_github.bat "what I changed"
rem
rem  It stages everything that is not ignored, shows you the list, asks for a
rem  message if you did not give one, then commits and pushes.  Nothing is
rem  deleted and nothing is forced: if git refuses, it says why and stops.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "MSG=%~1"

echo === what changed ===
git status --short
echo.

git add -A

rem Nothing staged? Then there is nothing to save.
git diff --cached --quiet
if not errorlevel 1 (
    echo Nothing to save - the working copy already matches the last commit.
    echo.
    pause
    exit /b 0
)

if "%MSG%"=="" (
    set /p "MSG=Message for this save: "
)
if "%MSG%"=="" set "MSG=Update"

echo.
echo === saving: %MSG% ===
git commit -m "%MSG%"
if errorlevel 1 (
    echo.
    echo The commit failed - read the message above.  Nothing was pushed.
    pause
    exit /b 1
)

echo.
echo === uploading to GitHub ===
git push
if errorlevel 1 (
    echo.
    echo The push failed.  The commit is safe on this machine; run this again
    echo once the problem above is fixed.
    pause
    exit /b 1
)

echo.
echo Done - https://github.com/SeeenW/Real-Racing-3-Mod-Tookit
pause
