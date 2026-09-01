"""Pruebas de la via DIRECTA de force feedback por evdev (sin SDL, sin volante).

Lo que se comprueba aqui es lo unico que no se puede depurar a distancia: que
las estructuras y los numeros de ioctl que le mandamos al nucleo son EXACTAMENTE
los que define linux/input.h. Un byte de mas en struct ff_effect y el ioctl
falla con EINVAL sin decir por que, que es justo el fallo silencioso que costo
encontrar el problema del T300RS en la Steam Deck.

Los valores de referencia estan sacados de la cabecera del nucleo en x86_64:

    EVIOCSFF      = _IOW('E', 0x80, struct ff_effect)  -> 0x40304580
    EVIOCRMFF     = _IOW('E', 0x81, int)               -> 0x40044581
    EVIOCGEFFECTS = _IOR('E', 0x84, int)               -> 0x80044584
    EVIOCGNAME(256)                                    -> 0x81004506
    sizeof(struct ff_effect)                           -> 48

    python tests/test_ffb_evdev.py
"""

import ctypes
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import ffb_evdev as ff


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


def main():
    r = []

    # --- la estructura que viaja al nucleo ----------------------------
    r.append(check("sizeof(struct ff_effect) = 48 bytes",
                   ctypes.sizeof(ff.FFEffect) == 48,
                   f"son {ctypes.sizeof(ff.FFEffect)}"))
    e = ff.FFEffect
    off = {n: getattr(e, n).offset for n, _ in e._fields_}
    r.append(check("los campos caen donde dice linux/input.h",
                   off == {"type": 0, "id": 2, "direction": 4,
                           "trigger": 6, "replay": 10, "u": 16},
                   str(off)))

    # --- numeros de ioctl ---------------------------------------------
    r.append(check("EVIOCSFF", ff.EVIOCSFF == 0x40304580, hex(ff.EVIOCSFF)))
    r.append(check("EVIOCRMFF", ff.EVIOCRMFF == 0x40044581, hex(ff.EVIOCRMFF)))
    r.append(check("EVIOCGEFFECTS", ff.EVIOCGEFFECTS == 0x80044584,
                   hex(ff.EVIOCGEFFECTS)))
    r.append(check("EVIOCGNAME(256)", ff._eviocgname(256) == 0x81004506,
                   hex(ff._eviocgname(256))))

    # --- el evento que arranca y para un efecto -----------------------
    ev = struct.pack("llHHi", 0, 0, ff.EV_FF, 3, 1)
    r.append(check("struct input_event = 24 bytes", len(ev) == 24,
                   f"son {len(ev)}"))

    # --- lectura de la mascara de capacidades de /sys -----------------
    # El fichero trae palabras de 64 bits de MAYOR a menor peso. FF_CONSTANT
    # es el bit 0x52 = 82, o sea el bit 18 de la segunda palabra.
    import builtins
    import io
    guardado = builtins.open
    builtins.open = lambda *a, **k: io.StringIO("40000 0\n")
    try:
        m = ff._mascara_sysfs("event7", "ff")
    finally:
        builtins.open = guardado
    r.append(check("la mascara de /sys se lee de mayor a menor peso",
                   m >> ff.FF_CONSTANT & 1 == 1, hex(m)))
    r.append(check("el desplazamiento entre palabras es de 64 bits",
                   m.bit_length() == 83, str(m.bit_length())))

    # --- traduccion de la mascara a texto ------------------------------
    mask = (1 << ff.FF_CONSTANT) | (1 << ff.FF_PERIODIC) | (1 << ff.FF_SPRING)
    nombres = ff.efectos_de(mask)
    r.append(check("efectos_de nombra los tres efectos y solo esos",
                   len(nombres) == 3 and any("constante" in n for n in nombres),
                   str(nombres)))
    r.append(check("efectos_de con mascara vacia no inventa nada",
                   ff.efectos_de(0) == []))

    # --- eleccion del nodo: el mando de la Deck NO vale ----------------
    guardado_listar = ff.listar
    CONST = 1 << ff.FF_CONSTANT
    try:
        ff.listar = lambda: [
            {"ruta": "/dev/input/event3", "nombre": "Microsoft X-Box 360 pad 0",
             "ff": 1 << ff.FF_RUMBLE, "lectura": True, "escritura": True},
            {"ruta": "/dev/input/event9",
             "nombre": "Thrustmaster T300RS Racing wheel",
             "ff": CONST, "lectura": True, "escritura": True},
        ]
        d = ff.buscar_volante(("t300", "thrustmaster", "logitech"))
        r.append(check("elige el volante y no el mando de la Deck",
                       d is not None and d["ruta"] == "/dev/input/event9",
                       str(d and d["ruta"])))

        # el mando vibra (FF_RUMBLE) pero no hace fuerza: no debe colarse
        ff.listar = lambda: [
            {"ruta": "/dev/input/event3", "nombre": "Microsoft X-Box 360 pad 0",
             "ff": 1 << ff.FF_RUMBLE, "lectura": True, "escritura": True},
        ]
        r.append(check("sin fuerza constante no hay candidato",
                       ff.buscar_volante(("t300",)) is None))

        # nombre desconocido, pero es el unico con fuerza y no es un mando
        ff.listar = lambda: [
            {"ruta": "/dev/input/event3", "nombre": "Microsoft X-Box 360 pad 0",
             "ff": 1 << ff.FF_RUMBLE, "lectura": True, "escritura": True},
            {"ruta": "/dev/input/event9", "nombre": "Generic USB Wheel",
             "ff": CONST, "lectura": True, "escritura": True},
        ]
        d = ff.buscar_volante(("t300",))
        r.append(check("acepta un unico nodo con fuerza aunque no lo conozca",
                       d is not None and d["ruta"] == "/dev/input/event9",
                       str(d and d["ruta"])))

        # dos desconocidos: no se adivina, mejor no mover nada
        ff.listar = lambda: [
            {"ruta": "/dev/input/event8", "nombre": "Aparato A",
             "ff": CONST, "lectura": True, "escritura": True},
            {"ruta": "/dev/input/event9", "nombre": "Aparato B",
             "ff": CONST, "lectura": True, "escritura": True},
        ]
        r.append(check("con dos desconocidos no elige a ciegas",
                       ff.buscar_volante(("t300",)) is None))
    finally:
        ff.listar = guardado_listar

    # --- el escalon de abajo: el bus USB -------------------------------
    # Es lo que separa "no le llega corriente" de "enumera pero no hay
    # driver". Se monta un /sys de mentira con dos aparatos.
    import shutil
    import tempfile
    raiz = tempfile.mkdtemp()
    for nodo, vid, pid, nombre in (("1-1", "044f", "b66e", "T300RS"),
                                   ("1-2", "046d", "b021", "Pebble")):
        d = os.path.join(raiz, nodo)
        os.makedirs(d)
        for fich, val in (("idVendor", vid), ("idProduct", pid),
                          ("product", nombre)):
            with open(os.path.join(d, fich), "w") as fh:
                fh.write(val + "\n")
    os.makedirs(os.path.join(raiz, "usb1"))       # sin idVendor: se ignora
    guardado_usb = ff.RUTA_USB
    try:
        ff.RUTA_USB = raiz
        todos = ff.usb()
        thrust = ff.usb("044f")
        r.append(check("usb() lista los aparatos con fabricante",
                       len(todos) == 2, str(len(todos))))
        r.append(check("usb(vid) filtra por fabricante",
                       len(thrust) == 1 and thrust[0]["pid"] == "b66e",
                       str(thrust)))
        r.append(check("un nodo sin idVendor no cuenta como aparato",
                       all(d["nodo"] != "usb1" for d in todos)))
        ff.RUTA_USB = os.path.join(raiz, "no-existe")
        r.append(check("sin /sys de USB devuelve lista vacia, no un error",
                       ff.usb("044f") == []))
    finally:
        ff.RUTA_USB = guardado_usb
        shutil.rmtree(raiz, ignore_errors=True)

    # --- un nodo sin fuerza no se abre ---------------------------------
    v = ff.VolanteEvdev("/dev/input/event99", 0)
    r.append(check("VolanteEvdev sin FF_CONSTANT no abre nada y explica por que",
                   not v.ok and v.fd < 0 and "constante" in v.motivo, v.motivo))
    v.close()

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
