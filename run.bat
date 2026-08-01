@echo off
rem Lanza el simulador. Requiere Python 3.10+ y las dependencias instaladas:
rem     pip install -r requirements.txt
cd /d "%~dp0"
python -m simulator.main
if errorlevel 1 pause
