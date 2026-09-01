#!/usr/bin/env python3
"""Diagnostico del force feedback SIN SDL: solo lo que dice el nucleo.

Para que sirve
--------------
El diagnostico de dentro del juego (``--ffb``) necesita el entorno virtual
con PySDL2. Este NO: usa solo la biblioteca estandar de Python, asi que
arranca con el ``python3`` del sistema aunque no haya venv, ni pip, ni nada
instalado. En una Steam Deck eso importa: el sistema de archivos es de solo
lectura y el Python del sistema viene sin pip.

Y para la pregunta que de verdad interesa —¿el nucleo publica el force
feedback del volante?— SDL sobra: la respuesta esta en ``/sys``, en
``/dev/input`` y en ``/dev/hidraw``, y se lee sin abrir nada.

    python3 tools/ffb_info.py            # inventario completo y veredicto
    python3 tools/ffb_info.py --probar   # ademas EMPUJA el volante

``--probar`` es la prueba definitiva: si el volante tira hacia un lado y
luego hacia el otro, el force feedback funciona y el juego lo va a usar.

El informe se guarda ademas en ``diagnostico_ffb_nucleo.txt``, para poder
subirlo con git en vez de copiarlo a mano.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".."))

from simulator import config as cfg          # noqa: E402  (sin dependencias)
from simulator import ffb_evdev as ff        # noqa: E402  (solo stdlib)

RAIZ = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
INFORME = os.path.join(RAIZ, "diagnostico_ffb_nucleo.txt")

_lineas = []


def di(t=""):
    print(t)
    _lineas.append(t)


def _permisos(d):
    if d["escritura"]:
        return "rw"
    return "SOLO LECTURA" if d["lectura"] else "sin permiso"


def _fila(d):
    ids = f"{d['vid']}:{d['pid']}" if d["vid"] else "-"
    di(f"  {d['ruta']:<18} {_permisos(d):<12} {ids:<10} "
       f"{d['driver'] or '-':<16} {d['nombre'] or '?'}")


def inventario():
    di("\nLO QUE DICE EL NUCLEO SOBRE EL FORCE FEEDBACK")
    evs = ff.listar()
    if not evs:
        di("\n  No hay /dev/input/event*: esto solo funciona en Linux.")
        return None

    # TODOS los nodos, no solo los que tienen fuerza: si el volante no
    # aparece en esta lista es que no estaba conectado, y entonces el resto
    # del diagnostico no vale nada.
    di(f"\n  /dev/input/event*: {len(evs)} dispositivos\n")
    for d in evs:
        _fila(d)
        for e in ff.efectos_de(d["ff"]):
            di(f"        FF: {e}")

    # /dev/hidraw*: la otra puerta al volante, la que usan los drivers de
    # Thrustmaster para mandar la fuerza como informes HID de salida.
    hr = ff.hidraws()
    di(f"\n  /dev/hidraw*: {len(hr)} dispositivos\n")
    for d in hr:
        _fila(d)

    return ff.buscar_volante(cfg.WHEEL_NAME_HINTS)


def sistema():
    di("\n  Sistema:")
    di(f"    kernel: {os.uname().release}")
    try:
        with open("/proc/modules") as f:
            mods = f.read()
    except OSError:
        di("    (no se pudo leer /proc/modules)")
        return
    for m in ("hid_tmff2", "hid_thrustmaster", "hid_generic", "ff_memless",
              "usbhid"):
        di(f"    modulo {m}: "
           f"{'CARGADO' if m in mods else 'no cargado'}")


def _volante_hidraw():
    """El /dev/hidraw del volante, si lo hay."""
    for d in ff.hidraws():
        if any(p in d["nombre"].lower() for p in cfg.WHEEL_NAME_HINTS):
            return d
    return None


def veredicto(cand):
    di()
    if cand is None:
        di("  El volante NO expone force feedback por evdev.")
        hr = _volante_hidraw()
        if hr is None:
            di("  Ademas, no aparece ningun /dev/hidraw suyo. Comprueba que el")
            di("  volante este encendido y conectado, y repitelo SIN Steam")
            di("  abierto por si tiene tomado el dispositivo.")
        else:
            di(f"  Pero SI tiene {hr['ruta']} ({hr['vid']}:{hr['pid']}, driver "
               f"{hr['driver'] or '?'}), "
               f"{'CON' if hr['escritura'] else 'SIN'} permiso de escritura.")
            di("  Esa es la otra puerta: los drivers de Thrustmaster mandan la")
            di("  fuerza como informes HID de salida por ese mismo canal, y eso")
            di("  se puede hacer desde espacio de usuario.")
        return 1
    if not cand["escritura"]:
        di(f"  El volante SI tiene force feedback en {cand['ruta']}, pero falta")
        di("  PERMISO DE ESCRITURA. Anade tu usuario al grupo 'input' y")
        di("  reinicia la sesion:")
        di("     sudo usermod -aG input $USER")
        return 1
    di(f"  HAY FORCE FEEDBACK en {cand['ruta']} ({cand['nombre']}).")
    di("  El juego lo usara por la via directa de evdev, la misma que usan los")
    di("  juegos de Steam a traves de Proton.")
    di("  Compruebalo con:  python3 tools/ffb_info.py --probar")
    return 0


def probar(cand):
    """Empuja el volante a un lado y a otro. Si se mueve, funciona."""
    if cand is None or not cand["escritura"]:
        return veredicto(cand)
    v = ff.VolanteEvdev(cand["ruta"], cand["ff"])
    if not v.ok:
        di(f"\n  No se pudo preparar el efecto: {v.motivo}")
        v.close()
        return 1
    di(f"\n  PRUEBA DE FUERZA en {v.ruta} ({v.nombre})")
    di("  SUJETA EL VOLANTE. Va a empujar a un lado y al otro.\n")
    v.autocentrado(0.0)
    v.ganancia(1.0)
    try:
        for nivel, texto in ((0.35, "derecha, suave"),
                             (0.60, "derecha, fuerte"),
                             (-0.35, "izquierda, suave"),
                             (-0.60, "izquierda, fuerte")):
            di(f"    {texto} ...")
            v.constante(nivel)
            time.sleep(1.5)
            v.constante(0.0)
            time.sleep(0.5)
        if v.soporta(ff.FF_PERIODIC):
            di("    vibracion (textura del asfalto) ...")
            v.textura(0.6, 30)
            time.sleep(1.5)
            v.textura(0.0, 50)
    except KeyboardInterrupt:
        pass
    finally:
        v.close()
    di("\n  Si el volante se ha movido, el force feedback funciona.")
    di("  Si no se ha movido nada, sube este informe.")
    return 0


def guardar():
    try:
        with open(INFORME, "w", encoding="utf-8") as f:
            f.write("\n".join(_lineas) + "\n")
    except OSError as e:
        print(f"\n  (no se pudo guardar el informe: {e})")
        return
    print(f"\n  Informe guardado en: {INFORME}")
    print("  Para mandarlo sin copiarlo a mano:")
    print("    git add diagnostico_ffb_nucleo.txt && "
          "git commit -m 'diagnostico ffb' && git push")


def main(argv):
    cand = inventario()
    sistema()
    salida = probar(cand) if "--probar" in argv else veredicto(cand)
    guardar()
    return salida


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
