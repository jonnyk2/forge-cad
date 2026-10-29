@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Run INSTALL_AND_TEST.bat first.
  pause & exit /b 1
)
call .venv\Scripts\activate.bat
if not exist "%USERPROFILE%\ForgeProjects" mkdir "%USERPROFILE%\ForgeProjects"
echo Forge web app starting at http://127.0.0.1:8765  (close this window to stop)
echo Your projects live in %USERPROFILE%\ForgeProjects
forge serve "%USERPROFILE%\ForgeProjects"
