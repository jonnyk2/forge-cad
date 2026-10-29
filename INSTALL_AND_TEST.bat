@echo off
setlocal
cd /d "%~dp0"
echo ============================================================ > test_results.txt
echo Forge install + test  %date% %time% >> test_results.txt
echo ============================================================ >> test_results.txt

where py >nul 2>&1 && set PY=py -3 || set PY=python
%PY% --version >> test_results.txt 2>&1 || (
  echo Python 3 not found. Install it from https://www.python.org/downloads/ and tick "Add to PATH". >> test_results.txt
  echo Python 3 not found. Install it from https://www.python.org/downloads/ and tick "Add to PATH".
  pause & exit /b 1
)

echo [1/4] creating virtual environment...
if not exist .venv ( %PY% -m venv .venv >> test_results.txt 2>&1 )
call .venv\Scripts\activate.bat

echo [2/4] installing forge + CAD kernel (first time ~200 MB, a few minutes)...
python -m pip install --upgrade pip >> test_results.txt 2>&1
python -m pip install -e . pytest >> test_results.txt 2>&1 || (
  echo pip install FAILED - see test_results.txt
  type test_results.txt | more
  pause & exit /b 1
)

echo [3/4] running kernel tests...
echo. >> test_results.txt
echo ---------------- pytest -m kernel -v ---------------- >> test_results.txt
python -m pytest -m kernel -v --tb=short -rf --durations=6 -p no:cacheprovider --basetemp=.pytest_tmp >> test_results.txt 2>&1
echo pytest exit code: %errorlevel% >> test_results.txt

echo [4/4] building the phone stand starter...
echo. >> test_results.txt
echo ---------------- forge build phone_stand ---------------- >> test_results.txt
cd starters
forge build phone_stand.py --render --export 3mf,step >> ..\test_results.txt 2>&1
cd ..

echo.
echo Done. Results are in test_results.txt (showing the tail):
echo ------------------------------------------------------------
powershell -command "Get-Content test_results.txt -Tail 40"
echo ------------------------------------------------------------
echo Next: double-click RUN_APP.bat to open the web app.
pause
