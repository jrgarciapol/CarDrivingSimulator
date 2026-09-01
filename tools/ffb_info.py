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
feedback del volante?— SDL sobra: la respuesta esta en ``/sys`` y en
``/dev/input``, y se lee sin abrir nada.

    python3 tools/ffb_info.py            # inventario y veredicto
    python3 tools/ffb_info.py --probar   # ademas EMPUJA el volante 3 s

``--probar`` es la prueba definitiva: si el volante tira hacia un lado y
luego hacia el otro, el force feedback funciona y el juego lo va a usar.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".."))

from simulator import config as cfg          # noqa: E402  (sin dependencias)
from simulator import ffb_evdev as ff        # noqa: E402  (solo stdlib)


def inventario():
    print("\nLO QUE DICE EL NUCLEO SOBRE EL FORCE FEEDBACK\n")
    evs = ff.listar()
    if not evs:
        print("  No hay /dev/input/event*: esto solo funciona en Linux.")
        return None
    rw = sum(1 for d in evs if d["lectura"] and d["escritura"])
    print(f"  /dev/input/event*: {len(evs)} dispositivos, "
          f"{rw} con permiso de lectura+escritura")
    con_ff = [d for d in evs if d["ff"]]
    if not con_ff:
        print("  NINGUN dispositivo anuncia force feedback.")
    for d in con_ff:
        permisos = ("lectura+escritura" if d["escritura"]
                    else "SOLO LECTURA (no sirve para el FFB)")
        print(f"\n  {d['ruta']}  {d['nombre'] or '?'}   [{permisos}]")
        for e in ff.efectos_de(d["ff"]):
            print(f"      SI  {e}")
    return ff.buscar_volante(cfg.WHEEL_NAME_HINTS)


def veredicto(cand):
    print()
    if cand is None:
        print("  El volante NO expone force feedback al sistema.")
        print("  Pruebalo con el volante encendido y SIN Steam abierto: si")
        print("  Steam tiene tomado el dispositivo, aqui no aparece.")
        return 1
    if not cand["escritura"]:
        print(f"  El volante SI tiene force feedback en {cand['ruta']}, pero")
        print("  falta PERMISO DE ESCRITURA. Anade tu usuario al grupo")
        print("  'input' y reinicia la sesion:")
        print("     sudo usermod -aG input $USER")
        return 1
    print(f"  HAY FORCE FEEDBACK en {cand['ruta']} ({cand['nombre']}).")
    print("  El juego lo usara por la via directa de evdev, la misma que usan")
    print("  los juegos de Steam a traves de Proton.")
    print("  Compruebalo con:  python3 tools/ffb_info.py --probar")
    return 0


def probar(cand):
    """Empuja el volante a un lado y a otro. Si se mueve, funciona."""
    if cand is None or not cand["escritura"]:
        print("\n  Sin dispositivo utilizable: no hay nada que probar.")
        return 1
    v = ff.VolanteEvdev(cand["ruta"], cand["ff"])
    if not v.ok:
        print(f"\n  No se pudo preparar el efecto: {v.motivo}")
        v.close()
        return 1
    print(f"\n  PRUEBA DE FUERZA en {v.ruta} ({v.nombre})")
    print("  SUJETA EL VOLANTE. Va a empujar a un lado y al otro.\n")
    v.autocentrado(0.0)
    v.ganancia(1.0)
    try:
        for nivel, texto in ((0.35, "derecha, suave"),
                             (0.60, "derecha, fuerte"),
                             (-0.35, "izquierda, suave"),
                             (-0.60, "izquierda, fuerte")):
            print(f"    {texto} ...")
            v.constante(nivel)
            time.sleep(1.5)
            v.constante(0.0)
            time.sleep(0.5)
        if v.soporta(ff.FF_PERIODIC):
            print("    vibracion (textura del asfalto) ...")
            v.textura(0.6, 30)
            time.sleep(1.5)
            v.textura(0.0, 50)
    except KeyboardInterrupt:
        pass
    finally:
        v.close()
    print("\n  Si el volante se ha movido, el force feedback funciona.")
    print("  Si no se ha movido nada, copia toda esta salida.")
    return 0


def main(argv):
    cand = inventario()
    if "--probar" in argv:
        return probar(cand)
    return veredicto(cand)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
