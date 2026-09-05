@echo off
rem Lanza el simulador. Requiere Python 3.10+ y las dependencias instaladas:
rem     pip install -r requirements.txt
rem
rem El render por GPU (moderngl) no tiene ruedas para Python 3.14 todavia.
rem Si hay un Python 3.13 instalado junto al 3.14 (los instaladores de
rem python.org conviven sin problema), se usa ese; si no, el "python" que
rem haya en el PATH (el juego funciona igual, con el render por SDL).
cd /d "%~dp0"
py -3.13 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.13 -m simulator.main
) else (
    python -m simulator.main
)
if errorlevel 1 pause
