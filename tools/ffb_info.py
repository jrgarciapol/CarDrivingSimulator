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
from simulator import ffb_t300rs as t300     # noqa: E402  (solo stdlib)

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

    presencia(evs, hr)
    return ff.buscar_volante(cfg.WHEEL_NAME_HINTS)


def _es_volante(d):
    return (d.get("vid") == t300.VID_THRUSTMASTER
            or any(p in (d.get("nombre") or "").lower()
                   for p in cfg.WHEEL_NAME_HINTS))


def presencia(evs, hr):
    """Lo PRIMERO que hay que saber: ¿esta el volante ahi?

    Sin esto, un informe tomado con el volante apagado parece un fallo del
    force feedback cuando en realidad no hay ningun volante que mover. Pasa
    con facilidad: el T300RS necesita su alimentacion propia, y si no
    arranca (sin LED y sin el giro inicial de calibracion) el sistema no lo
    ve siquiera."""
    ent = [d for d in evs if _es_volante(d)]
    raw = [d for d in hr if _es_volante(d)]
    bus = ff.usb(t300.VID_THRUSTMASTER)
    di("\n  VOLANTE:")
    if not ent and not raw:
        if not bus:
            di("    NO ESTA NI EN EL BUS USB. El sistema no ve ningun aparato")
            di("    Thrustmaster, ni siquiera sin inicializar, asi que esto no")
            di("    es cosa del sistema operativo ni del juego: o no le llega")
            di("    corriente (el volante necesita su transformador propio), o")
            di("    es el cable, o la base. Pruebalo enchufado directamente al")
            di("    equipo, sin hub.")
        else:
            for d in bus:
                di(f"    en el bus USB: {d['nodo']}  {d['vid']}:{d['pid']}  "
                   f"{d['nombre'] or '?'}")
            if any(d["pid"] == t300.PID_BOOTLOADER for d in bus):
                di("    ESTA EN MODO BOOTLOADER. No es que le falte el driver:")
                di("    es que no tiene firmware utilizable. Por eso el equipo")
                di("    suena al conectarlo pero no lo reconoce ninguna")
                di("    aplicacion, ni la de Thrustmaster ni una consola, y no")
                di("    enciende el LED ni hace el giro de calibracion.")
                di("    NO esta roto: se recupera reinstalando el firmware")
                di("    desde Windows con la utilidad de Thrustmaster, que")
                di("    habla con el volante precisamente en este modo.")
                di("    Hazlo con el transformador conectado y en un puerto USB")
                di("    directo del equipo, sin hub, y sin tocar nada mientras.")
            elif any(d["pid"] == t300.PID_SIN_INICIAR for d in bus):
                di("    ENUMERA PERO SE QUEDA SIN INICIALIZAR. Este es el modo")
                di("    generico de arranque: el aparato responde al conectarlo")
                di("    pero todavia no es un volante, y por eso no lo reconoce")
                di("    ninguna aplicacion, ni la de Thrustmaster ni la consola.")
                di("    Si tampoco enciende el LED ni hace el giro de")
                di("    calibracion, el cambio de modo no llega a completarse:")
                di("    es cosa del propio volante, no del ordenador. La via de")
                di("    Thrustmaster para esto es reinstalar el firmware, que se")
                di("    hace precisamente con el volante en este modo.")
            else:
                di("    Enumera en el bus pero no llega a HID: es un problema")
                di("    de driver, no de corriente.")
        di("    Hasta que aparezca, el resto de este informe no dice nada")
        di("    sobre el force feedback.")
        return False
    for d in ent + raw:
        di(f"    {d['ruta']}  {d['nombre']}  ({d['vid']}:{d['pid']})")
    if any(d.get("pid") == t300.PID_SIN_INICIAR for d in ent + raw):
        di("    ESTA SIN INICIALIZAR: sigue en el modo generico de arranque.")
        di("    Los Thrustmaster empiezan como 'FFB Wheel' y solo se convierten")
        di("    en el volante de verdad cuando reciben la peticion de cambio de")
        di("    modo (la manda el modulo hid_thrustmaster). Ese es el momento")
        di("    del LED y del giro de calibracion. Sin eso no hay ni ejes ni")
        di("    fuerza. Desconecta y vuelve a conectar el volante ya encendido.")
        return False
    return True


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
    if cand is not None and cand["escritura"]:
        di(f"  HAY FORCE FEEDBACK en {cand['ruta']} ({cand['nombre']}).")
        di("  El juego lo usara por la via directa de evdev.")
        di("  Compruebalo con:  python3 tools/ffb_info.py --probar")
        return 0
    if cand is not None:
        di(f"  El volante SI tiene force feedback en {cand['ruta']}, pero falta")
        di("  PERMISO DE ESCRITURA. Anade tu usuario al grupo 'input' y")
        di("  reinicia la sesion:")
        di("     sudo usermod -aG input $USER")
        return 1

    di("  El volante NO expone force feedback por evdev.")
    t3 = _t300rs()
    if t3 is not None:
        di(f"  Pero es un {t3['modelo']} y tiene {t3['ruta']} con permiso de")
        di(f"  escritura, con informe de salida 0x{t3['informe']:02x} de "
           f"{t3['largo']} bytes.")
        di("  Se le puede mandar la fuerza como informes HID de salida, que es")
        di("  lo que hace el driver hid-tmff2, pero sin tocar el kernel.")
        di("  Compruebalo con:  python3 tools/ffb_info.py --probar")
        return 0
    hr = _volante_hidraw()
    if hr is None:
        di("  Ademas, no aparece ningun /dev/hidraw suyo. Comprueba que el")
        di("  volante este encendido y conectado, y repitelo SIN Steam")
        di("  abierto por si tiene tomado el dispositivo.")
    else:
        di(f"  Tiene {hr['ruta']} ({hr['vid']}:{hr['pid']}, driver "
           f"{hr['driver'] or '?'}), "
           f"{'CON' if hr['escritura'] else 'SIN'} permiso de escritura, pero")
        di("  no es un modelo del que se conozca el protocolo de fuerza.")
    return 1


def _t300rs():
    """Datos del T300RS por HID, si es el volante que hay conectado."""
    info = t300.buscar(ff.hidraws())
    return info if info and info["escritura"] else None


def abrir_para_probar(cand):
    """La primera via que funcione: evdev, y si no, informes HID."""
    if cand is not None and cand["escritura"]:
        v = ff.VolanteEvdev(cand["ruta"], cand["ff"])
        if v.ok:
            return v, "evdev"
        di(f"\n  evdev: {v.motivo}")
        v.close()
    info = _t300rs()
    if info is not None:
        v = t300.VolanteT300RS(info)
        if v.ok:
            return v, f"informes HID ({info['modelo']})"
        di(f"\n  HID: {v.motivo}")
        v.close()
    return None, ""


def probar(cand):
    """Empuja el volante a un lado y a otro. Si se mueve, funciona."""
    v, via = abrir_para_probar(cand)
    if v is None:
        return veredicto(cand)
    di(f"\n  PRUEBA DE FUERZA en {v.ruta} por {via}")
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
