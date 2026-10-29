@echo off
cd /d "%~dp0"
echo Pulling latest Forge...
git pull --ff-only || (echo git pull failed - see above & pause & exit /b 1)
if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
  python -m pip install -q -e . 2>nul
)
echo Up to date. If the app is running, close its window and run RUN_APP.bat again.
pause
