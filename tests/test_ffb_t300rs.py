"""Pruebas del force feedback del T300RS por /dev/hidraw (sin volante).

Aqui se comprueba byte a byte que los paquetes que le mandamos al volante son
los mismos que manda el driver hid-tmff2 (src/tmt300rs/hid-tmt300rs.c). No hay
forma de depurar esto a distancia: un byte movido de sitio no da ningun error,
simplemente el volante no hace nada, o hace algo raro.

Las referencias son las estructuras __packed del driver:

    t300rs_packet_header    { zero, id, code }                        3 bytes
    t300rs_packet_envelope  { attack_len, attack_lvl, fade_len, fade_lvl }  8
    t300rs_packet_timing    { 0x4f, duration, 0,0, offset, 0, 0xffff }     10
    upload constant  (0x6a) header + level + envelope + zero + timing      24
    update constant  (0x6a) header + level + envelope + 0x00 + 0x45
                            + duration + offset                            19
    upload periodic  (0x6b) header + mag + off + phase + period + 0x8000
                            + envelope + waveform + timing                 32
    update periodic  (0x6e) header + 0x0f + mag + off + phase + period
                            + envelope + waveform + 0x45 + dur + off       26
    play             (0x89) header + 0x41 + count                           6
    stop             (0x89) header + 0x00                                   4

    python tests/test_ffb_t300rs.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import ffb_t300rs as t3


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


def main():
    r = []

    # --- cabecera: el identificador viaja SUMANDO UNO -----------------
    r.append(check("la cabecera lleva id+1 y el codigo",
                   t3._cabecera(0, 0x6A) == b"\x00\x01\x6a",
                   t3._cabecera(0, 0x6A).hex()))
    r.append(check("cabecera del segundo efecto",
                   t3._cabecera(1, 0x89) == b"\x00\x02\x89"))

    # --- tiempos: marca de inicio 0x4f y de fin 0xffff ----------------
    t = t3._tiempos(0xFFFF, 0)
    r.append(check("los tiempos ocupan 10 bytes y llevan sus marcas",
                   len(t) == 10 and t[0] == 0x4F and t[-2:] == b"\xff\xff",
                   t.hex()))

    # --- tamaños de cada paquete --------------------------------------
    tam = {
        "subir constante": (t3.paq_subir_constante(0, 0), 24),
        "actualizar constante": (t3.paq_actualizar_constante(0, 0), 19),
        "subir periodico": (t3.paq_subir_periodico(1, 0, 50), 32),
        "actualizar periodico": (t3.paq_actualizar_periodico(1, 0, 50), 26),
        "reproducir": (t3.paq_reproducir(0), 6),
        "parar": (t3.paq_parar(0), 4),
    }
    for nombre, (paq, esperado) in tam.items():
        r.append(check(f"{nombre}: {esperado} bytes",
                       len(paq) == esperado, f"son {len(paq)}"))

    # --- fuerza constante: nivel con signo, little endian --------------
    p = t3.paq_subir_constante(0, -16384)
    r.append(check("el nivel negativo va en complemento a dos, little endian",
                   p[3:5] == b"\x00\xc0", p[3:5].hex()))
    p = t3.paq_subir_constante(0, 16383)
    r.append(check("el nivel positivo tambien",
                   p[3:5] == b"\xff\x3f", p[3:5].hex()))
    r.append(check("la envolvente va a cero (sin ataque ni caida)",
                   p[5:13] == b"\x00" * 8))
    r.append(check("duracion infinita = 0xffff en los tiempos",
                   p[14:17] == b"\x4f\xff\xff", p[14:17].hex()))

    # --- actualizar lleva la marca 0x45 -------------------------------
    p = t3.paq_actualizar_constante(0, 1000, duracion=0xFFFF)
    r.append(check("actualizar constante marca 0x00 0x45",
                   p[13] == 0x00 and p[14] == 0x45, p.hex()))

    # --- periodico -----------------------------------------------------
    p = t3.paq_subir_periodico(1, 20000, 30)
    r.append(check("subir periodico: codigo 0x6b",
                   p[2] == 0x6B, hex(p[2])))
    r.append(check("magnitud y periodo en su sitio",
                   p[3:5] == (20000).to_bytes(2, "little") and
                   p[9:11] == (30).to_bytes(2, "little"), p.hex()))
    r.append(check("la marca 0x8000 va tras el periodo",
                   p[11:13] == b"\x00\x80", p[11:13].hex()))
    r.append(check("la forma de onda es la de evdev menos 0x57 (seno -> 3)",
                   p[21] == t3.FF_SINE - 0x57, hex(p[21])))
    r.append(check("la magnitud del periodico nunca es negativa",
                   t3.paq_subir_periodico(1, -20000, 30)[3:5] ==
                   (20000).to_bytes(2, "little")))
    p = t3.paq_actualizar_periodico(1, 100, 40)
    r.append(check("actualizar periodico: codigo 0x6e y tipo 0x0f",
                   p[2] == 0x6E and p[3] == 0x0F, p[:4].hex()))

    # --- reproducir y parar --------------------------------------------
    r.append(check("reproducir sin fin manda 0x41 y cuenta cero",
                   t3.paq_reproducir(0) == b"\x00\x01\x89\x41\x00\x00",
                   t3.paq_reproducir(0).hex()))
    r.append(check("parar deja la cuenta a cero sin 0x41",
                   t3.paq_parar(0) == b"\x00\x01\x89\x00"))

    # --- ajustes globales ----------------------------------------------
    r.append(check("apertura = 0x01 0x05", t3.paq_abrir() == b"\x01\x05"))
    r.append(check("de la ganancia solo viaja el byte alto",
                   t3.paq_ganancia(0xFFFF) == b"\x02\xff" and
                   t3.paq_ganancia(0x8000) == b"\x02\x80"))
    a = t3.paq_autocentrado(0)
    r.append(check("el autocentrado son dos paquetes: habilitar y valor",
                   a[0] == b"\x08\x04\x01\x00" and a[1] == b"\x08\x03\x00\x00"))
    r.append(check("el rango escala por 0x3c (900 grados -> 0xd2f0)",
                   t3.paq_rango(900) == b"\x08\x11" +
                   (900 * 0x3C).to_bytes(2, "little"),
                   t3.paq_rango(900).hex()))
    r.append(check("el rango se recorta a [40, 1080]",
                   t3.paq_rango(5) == t3.paq_rango(40) and
                   t3.paq_rango(9000) == t3.paq_rango(1080)))

    # --- lectura del descriptor de informes ----------------------------
    # Trozo de descriptor con un informe de SALIDA 0x60 de 63 bytes, igual
    # que el del volante: Report ID, Report Size 8, Report Count 63, Output.
    desc = bytes([
        0x85, 0x07,              # Report ID (7)
        0x75, 0x10, 0x95, 0x01,  # size 16, count 1
        0x81, 0x02,              # INPUT -> no cuenta
        0x85, 0x60,              # Report ID (0x60)
        0x75, 0x08, 0x95, 0x3F,  # size 8, count 63
        0x91, 0x02,              # OUTPUT
    ])
    sal = t3.informes_salida(desc)
    r.append(check("encuentra el informe de salida 0x60 de 63 bytes",
                   sal == [(0x60, 63)], str(sal)))
    r.append(check("un descriptor sin salidas no inventa ninguna",
                   t3.informes_salida(bytes([0x85, 0x07, 0x81, 0x02])) == []))
    r.append(check("un descriptor vacio no revienta",
                   t3.informes_salida(b"") == []))
    # elemento con 4 bytes de datos (bSize = 3): no debe descolocar el paso
    r.append(check("los elementos de 4 bytes se saltan bien",
                   t3.informes_salida(
                       bytes([0x27, 0xFF, 0xFF, 0x00, 0x00]) + desc)
                   == [(0x60, 63)]))

    # --- eleccion del aparato ------------------------------------------
    ajenos = [{"ruta": "/dev/hidraw0", "vid": "28de", "pid": "1205",
               "nombre": "Valve Software Steam Deck Controller"},
              {"ruta": "/dev/hidraw5", "vid": "046d", "pid": "b021",
               "nombre": "Logitech Pebble"}]
    r.append(check("no toca aparatos que no sean el volante",
                   t3.buscar(ajenos) is None))
    r.append(check("b66e esta reconocido como T300RS en modo PC",
                   "b66e" in t3.PIDS_T300RS))

    # --- lo que se ESCRIBE de verdad en el aparato ---------------------
    # Se abre un fichero corriente como si fuera /dev/hidrawN y se mira byte
    # a byte: cada escritura tiene que ser el identificador del informe, la
    # carga, y ceros hasta completar el informe. Ni uno mas ni uno menos: el
    # aparato descarta los informes de tamano equivocado sin dar error.
    import tempfile
    ruta = os.path.join(tempfile.mkdtemp(), "hidraw_falso")
    open(ruta, "wb").close()
    v = t3.VolanteT300RS({"ruta": ruta, "nombre": "T300RS de prueba",
                          "informe": 0x60, "largo": 63,
                          "modelo": "T300RS (modo PC/PS3)"})
    r.append(check("se abre y deja los dos efectos preparados", v.ok, v.motivo))
    v.constante(1.0)
    v.textura(0.5, 30)
    v.close()
    with open(ruta, "rb") as f:
        crudo = f.read()
    r.append(check("todas las escrituras miden 64 bytes (1 + 63)",
                   len(crudo) % 64 == 0, f"{len(crudo)} bytes en total"))
    marcos = [crudo[i:i + 64] for i in range(0, len(crudo), 64)]
    r.append(check("cada marco empieza por el identificador del informe",
                   all(m[0] == 0x60 for m in marcos)))
    r.append(check("el primer marco es la apertura",
                   marcos[0][1:3] == b"\x01\x05", marcos[0][1:4].hex()))
    r.append(check("se rellena de ceros hasta el final",
                   marcos[0][3:] == b"\x00" * 61))
    cuerpos = [m[1:] for m in marcos]
    r.append(check("el par a fondo manda el nivel maximo del volante",
                   any(c.startswith(b"\x00\x01\x6a\xff\x3f") for c in cuerpos)))
    r.append(check("al cerrar se para todo y se manda el cierre",
                   cuerpos[-1].startswith(b"\x01\x00")))
    # llamar dos veces con el mismo valor no debe volver a escribir
    open(ruta, "wb").close()
    v2 = t3.VolanteT300RS({"ruta": ruta, "informe": 0x60, "largo": 63})
    antes = os.path.getsize(ruta)
    v2.constante(0.5)
    medio = os.path.getsize(ruta)
    v2.constante(0.5)
    despues = os.path.getsize(ruta)
    r.append(check("repetir el mismo par no gasta una escritura",
                   medio > antes and despues == medio))
    v2.close()

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
