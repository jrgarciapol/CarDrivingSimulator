#!/usr/bin/env bash
#
# Instalador para Steam Deck (SteamOS) y para cualquier Linux donde falte
# pip.
#
# EL PROBLEMA. SteamOS trae Python 3, pero su sistema de archivos raíz es de
# SOLO LECTURA y la imagen viene SIN pip: por eso "pip install ..." responde
# "pip: command not found", y a menudo "python3 -m pip" tampoco existe.
#
# LA SOLUCION que aplica este script, en orden y parando en cuanto una
# funciona:
#   1. usar pip si ya está;
#   2. si no, activarlo con ensurepip (viene en algunas versiones);
#   3. si tampoco, descargar get-pip.py del sitio oficial de Python.
# Después crea un ENTORNO VIRTUAL dentro del propio proyecto (.venv), que
# es lo más limpio en un sistema inmutable: no toca nada del sistema, se
# borra con un rm -rf y se puede rehacer si SteamOS actualiza Python.
#
# LO QUE NO HACE, a propósito: desactivar el modo de solo lectura con
# "sudo steamos-readonly disable" e instalar con pacman. Funciona, pero
# cada actualización de SteamOS reemplaza la partición del sistema y se
# pierde, además de dejar el sistema en un estado que Valve no soporta.
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

# --- 2. conseguir pip ------------------------------------------------------
tiene_pip() { "$1" -m pip --version >/dev/null 2>&1; }

if tiene_pip "$PY"; then
    echo "pip: ya disponible"
else
    echo "pip: no esta (normal en SteamOS). Intentando activarlo..."
    if "$PY" -m ensurepip --upgrade >/dev/null 2>&1 && tiene_pip "$PY"; then
        echo "pip: activado con ensurepip"
    else
        echo "pip: ensurepip no disponible; descargando get-pip.py..."
        TMP=$(mktemp -d)
        trap 'rm -rf "$TMP"' EXIT
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$TMP/get-pip.py"
        elif command -v wget >/dev/null 2>&1; then
            wget -q https://bootstrap.pypa.io/get-pip.py -O "$TMP/get-pip.py"
        else
            echo "ERROR: no hay ni curl ni wget para descargar get-pip.py"
            exit 1
        fi
        "$PY" "$TMP/get-pip.py" --user >/dev/null
        export PATH="$HOME/.local/bin:$PATH"
        if ! tiene_pip "$PY"; then
            echo "ERROR: no se ha podido instalar pip."
            echo "Alternativa: usar distrobox (ver README, seccion Steam Deck)."
            exit 1
        fi
        echo "pip: instalado en tu usuario (~/.local)"
    fi
fi

# --- 3. entorno virtual ----------------------------------------------------
# Aislar del sistema es lo correcto aqui: la raiz es de solo lectura y una
# actualizacion de SteamOS puede cambiar la version de Python, dejando los
# paquetes instalados "a pelo" en un directorio que ya no se busca.
if [ ! -d "$VENV" ]; then
    echo "Creando entorno virtual en .venv ..."
    if ! "$PY" -m venv "$VENV" 2>/dev/null; then
        # venv sin ensurepip: se crea vacio y se le mete pip a mano
        echo "  (sin ensurepip: creando el entorno sin pip y anadiendoselo)"
        "$PY" -m venv --without-pip "$VENV"
        TMP2=$(mktemp -d)
        trap 'rm -rf "$TMP2"' EXIT
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$TMP2/get-pip.py"
        else
            wget -q https://bootstrap.pypa.io/get-pip.py -O "$TMP2/get-pip.py"
        fi
        "$VENV/bin/python" "$TMP2/get-pip.py" >/dev/null
    fi
else
    echo "Entorno virtual .venv: ya existe"
fi

# --- 4. dependencias -------------------------------------------------------
# SOLO las del juego. matplotlib esta en requirements.txt pero unicamente lo
# usan los editores de trazado (tools/), que no se manejan con un mando: son
# ~70 MB de descarga que en la Deck no pintan nada.
echo
echo "Instalando dependencias del juego (pysdl2, pysdl2-dll, numpy)..."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet "pysdl2>=0.9.16" "pysdl2-dll>=2.28.0" "numpy>=1.24"

# --- 5. comprobacion -------------------------------------------------------
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

# --- 6. lanzador -----------------------------------------------------------
cat > "$RAIZ/jugar.sh" <<EOF
#!/usr/bin/env bash
# Lanzador del simulador. Anadelo a Steam como juego externo:
#   Steam > Anadir un juego > Anadir un juego que no sea de Steam
# y luego, en Propiedades, marca "Forzar el uso de una herramienta de
# compatibilidad" NO (es una aplicacion nativa de Linux).
cd "\$(dirname "\$0")"
exec .venv/bin/python -m simulator.main --rendimiento "\$@"
EOF
chmod +x "$RAIZ/jugar.sh"

echo
echo "== Listo =="
echo "Para jugar:            ./jugar.sh"
echo "Sin preset de rendimiento:  .venv/bin/python -m simulator.main"
echo "Con el volante conectado, se detecta solo y tiene prioridad sobre el mando."
