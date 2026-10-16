@echo off
cd /d "%~dp0"
python -c "import numpy, scipy, shapely, networkx" >nul 2>&1
if errorlevel 1 (
  echo SutraYana needs its Python dependencies. Installing from requirements.txt...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Setup failed. Install Python 3.10 or later, then try again.
    pause
    exit /b 1
  )
)
python launch_studio.py
if errorlevel 1 pause
