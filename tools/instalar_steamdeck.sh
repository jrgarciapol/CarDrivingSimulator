#!/usr/bin/env bash
#
# Instalador para Steam Deck (SteamOS) y para cualquier Linux donde falte
# pip o el Python del sistema este "gestionado externamente".
#
# EL PROBLEMA. SteamOS trae Python 3, pero:
#   - su sistema de archivos raiz es de SOLO LECTURA, y
#   - su Python esta marcado como "externally-managed" (PEP 668).
# Por eso "pip install ..." responde "command not found", y cualquier
# intento de instalar pip o paquetes en el Python DEL SISTEMA es rechazado
# con "error: externally-managed-environment".
#
# LA SOLUCION. No se toca el Python del sistema PARA NADA. Se crea un
# entorno virtual (.venv) dentro del proyecto y se instala todo ahi: un
# venv NO esta gestionado externamente, asi que pip funciona sin trabas.
# Ademas es lo mas limpio en un sistema inmutable: no ensucia el sistema,
# se borra con "rm -rf .venv" y se rehace si SteamOS actualiza Python.
#
# Si el propio venv no trae pip (SteamOS a veces quita ensurepip, porque
# escribir pip en /usr es imposible al ser de solo lectura), se le inyecta
# con el get-pip.py oficial: dentro del venv si se puede escribir.
#
# LO QUE NO HACE, a proposito: "sudo steamos-readonly disable" + pacman.
# Funciona, pero cada actualizacion de SteamOS reemplaza la particion del
# sistema y se pierde, ademas de dejar el equipo en un estado no soportado.
#
#   Uso:  bash tools/instalar_steamdeck.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."
RAIZ="$PWD"
VENV="$RAIZ/.venv"

echo "== Instalador de Car Driving Simulator para Steam Deck =="
echo

# --- 1. Python -------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: no hay python3. En una Steam Deck deberia venir de serie."
    exit 1
fi
PY=$(command -v python3)
echo "Python: $PY  ($($PY -V 2>&1))"

descargar_getpip() {  # $1 = destino
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q https://bootstrap.pypa.io/get-pip.py -O "$1"
    else
        echo "ERROR: no hay ni curl ni wget para descargar get-pip.py"
        return 1
    fi
}

venv_tiene_pip() { "$VENV/bin/python" -m pip --version >/dev/null 2>&1; }

# --- 2. entorno virtual, con pip garantizado -------------------------------
# NO se intenta instalar pip en el Python del sistema: en SteamOS esta
# gestionado externamente (PEP 668) y lo rechaza. Todo va dentro del venv.
if venv_tiene_pip; then
    echo "Entorno virtual .venv: ya existe y tiene pip"
else
    echo "Creando entorno virtual en .venv ..."
    # Se crea SIN pip (no depende de que el sistema tenga ensurepip, que en
    # SteamOS suele faltar porque no puede escribir en /usr) y se le mete
    # pip a mano con get-pip.py, que dentro del venv si funciona.
    rm -rf "$VENV"
    "$PY" -m venv --without-pip "$VENV"
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT
    echo "Descargando get-pip.py (pip no viene con SteamOS)..."
    descargar_getpip "$TMP/get-pip.py"
    echo "Instalando pip DENTRO del entorno virtual..."
    "$VENV/bin/python" "$TMP/get-pip.py" >/dev/null
    if ! venv_tiene_pip; then
        echo "ERROR: no se ha podido preparar pip en el entorno virtual."
        echo "Alternativa: usar distrobox (ver README, seccion Steam Deck)."
        exit 1
    fi
    echo "pip: listo en el entorno virtual"
fi

# --- 3. dependencias -------------------------------------------------------
# SOLO las del juego. matplotlib esta en requirements.txt pero unicamente lo
# usan los editores de trazado (tools/), que no se manejan con un mando: son
# ~70 MB de descarga que en la Deck no pintan nada.
echo
echo "Instalando dependencias del juego (pysdl2, pysdl2-dll, numpy)..."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet \
    "pysdl2>=0.9.16" "pysdl2-dll>=2.28.0" "numpy>=1.24"

# moderngl (escena 3D en la GPU) es OPCIONAL: si no hubiera rueda para este
# Python el juego sigue con el render de SDL, asi que su fallo no debe tumbar
# la instalacion entera
echo "Instalando moderngl (escena en la GPU; opcional)..."
if ! "$VENV/bin/python" -m pip install --quiet "moderngl>=5.10"; then
    echo "  (sin moderngl: el juego usara el renderizador de SDL)"
fi

# --- 4. comprobacion -------------------------------------------------------
echo
echo "Comprobando la instalacion..."
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy "$VENV/bin/python" - <<'PYEOF'
import sdl2, numpy
print(f"  numpy {numpy.__version__}")
if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO) != 0:
    raise SystemExit("  ERROR al iniciar SDL: " + sdl2.SDL_GetError().decode())
print("  SDL2 arranca correctamente")
sdl2.SDL_Quit()
PYEOF

# --- 5. lanzador -----------------------------------------------------------
cat > "$RAIZ/jugar.sh" <<EOF
#!/usr/bin/env bash
# Lanzador del simulador. Anadelo a Steam como juego externo:
#   Steam > Anadir un juego > Anadir un juego que no sea de Steam
# Es una aplicacion NATIVA de Linux: NO hay que forzar ninguna herramienta
# de compatibilidad (Proton).
cd "\$(dirname "\$0")"
exec .venv/bin/python -m simulator.main --rendimiento "\$@"
EOF
chmod +x "$RAIZ/jugar.sh"

echo
echo "== Listo =="
echo "Para jugar:                 ./jugar.sh"
echo "Sin preset de rendimiento:  .venv/bin/python -m simulator.main"
echo "Con el volante conectado, se detecta solo y tiene prioridad sobre el mando."
