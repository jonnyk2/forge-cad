@echo off
cd /d "%~dp0"
echo Pulling latest Forge...
git pull --ff-only || (echo git pull failed - see above & pause & exit /b 1)
if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
  python -m pip install -q -e . 2>nul
)
echo Up to date. Run RUN_APP.bat (or just refresh the browser if it's already running).
pause
