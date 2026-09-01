"""Force feedback del Thrustmaster T300RS por /dev/hidraw, sin driver.

Por qué existe
--------------
En la Steam Deck el núcleo toma el T300RS con ``hid-generic``, que no
implementa force feedback: en ``/dev/input`` no aparece ninguna capacidad de
fuerza, y por tanto ni SDL ni el camino de evdev (``ffb_evdev.py``) tienen
nada que usar. La solución habitual es compilar el módulo de kernel
`hid-tmff2 <https://github.com/Kimplul/hid-tmff2>`_, que en SteamOS obliga a
desactivar el sistema de archivos de solo lectura y a repetirlo tras cada
actualización.

Pero ese módulo no hace nada que necesite estar en el núcleo: **manda
informes HID de salida**, y un informe HID de salida se puede escribir desde
espacio de usuario en ``/dev/hidraw``, que en la Deck ya tiene permiso de
escritura. Esto es exactamente eso: los mismos paquetes, escritos desde
Python.

El protocolo está tomado de ``src/tmt300rs/hid-tmt300rs.c`` de hid-tmff2
(GPL-2.0-or-later), y se documenta paquete a paquete más abajo para que se
pueda revisar sin leer el driver.

Alcance
-------
Fuerza constante (el par de la dirección, que es lo importante) y efecto
periódico (texturas). Muelle y amortiguador no: los sustituye la física del
juego, que ya calcula el par completo.

Solo Linux, y solo los T300RS. Con cualquier otro aparato ``buscar()``
devuelve None y no se escribe un solo byte.
"""

import os
import struct

#: Thrustmaster.
VID_THRUSTMASTER = "044f"

#: Identificadores del T300RS que hid-tmff2 reconoce. El volante cambia de
#: identidad según el conmutador: b66e es el modo PC/PS3 normal.
PIDS_T300RS = {
    "b66e": "T300RS (modo PC/PS3)",
    "b66f": "T300RS (modo PS3 avanzado)",
    "b66d": "T300RS (modo PS4)",
}

#: Tamaño del informe de salida en modo normal (63 en PS4 son 31, pero el
#: valor real se saca del descriptor del propio aparato).
LARGO_NORMAL = 63

#: Formas de onda del efecto periódico, en el convenio de evdev.
FF_SQUARE, FF_TRIANGLE, FF_SINE = 0x58, 0x59, 0x5A

_SIN_ENVOLVENTE = b"\x00" * 8       # ataque y caída a cero


# --- lectura del descriptor de informes --------------------------------
def informes_salida(desc: bytes):
    """Informes de SALIDA de un descriptor HID: ``[(id, nº de bytes)]``.

    Hace falta para saber con qué identificador empezar cada escritura en
    ``/dev/hidraw``. En vez de dar por hecho un valor, se lee el descriptor
    real del aparato: es lo único que no cambia entre versiones de SteamOS.

    Recorre los elementos cortos del descriptor llevando la cuenta de los
    tres estados globales que importan (identificador, tamaño y número de
    campos) y anota lo que declare cada elemento principal de salida."""
    i, n = 0, len(desc)
    rid, tam, cuenta = 0, 0, 0
    bits = {}
    while i < n:
        pref = desc[i]
        if pref == 0xFE:                      # elemento largo: se salta
            i += 2 + (desc[i + 1] if i + 1 < n else 0)
            continue
        largo = pref & 0x03
        largo = 4 if largo == 3 else largo
        datos = desc[i + 1:i + 1 + largo]
        valor = int.from_bytes(datos, "little") if datos else 0
        tag = pref & 0xFC
        if tag == 0x84:                       # Report ID (global)
            rid = valor
        elif tag == 0x74:                     # Report Size
            tam = valor
        elif tag == 0x94:                     # Report Count
            cuenta = valor
        elif tag == 0x90:                     # Output (main)
            bits[rid] = bits.get(rid, 0) + tam * cuenta
        i += 1 + largo
    return [(k, v // 8) for k, v in sorted(bits.items())]


def _descriptor(nodo: str) -> bytes:
    try:
        with open(f"/sys/class/hidraw/{nodo}/device/report_descriptor",
                  "rb") as f:
            return f.read()
    except OSError:
        return b""


def buscar(hidraws):
    """El T300RS entre una lista de ``ffb_evdev.hidraws()``, o None.

    Devuelve el diccionario del aparato con dos claves añadidas:
    ``informe`` (identificador del informe de salida) y ``largo`` (bytes de
    carga útil). Si el descriptor no declara ningún informe de salida, no
    hay por donde mandar la fuerza y se devuelve None."""
    for d in hidraws:
        if d.get("vid") != VID_THRUSTMASTER or d.get("pid") not in PIDS_T300RS:
            continue
        salidas = informes_salida(_descriptor(os.path.basename(d["ruta"])))
        if not salidas:
            continue
        # el informe de la fuerza es el grande (63 bytes); si hubiera varios
        # se coge el mayor, que es el unico con sitio para los efectos
        rid, largo = max(salidas, key=lambda s: s[1])
        info = dict(d)
        info["informe"] = rid
        info["largo"] = largo
        info["modelo"] = PIDS_T300RS[d["pid"]]
        return info
    return None


# --- construcción de los paquetes --------------------------------------
# Todos los numeros de varios bytes van en little endian. Las estructuras
# son las de hid-tmt300rs.c; se indica al lado la que corresponde.

def _cabecera(eid: int, codigo: int) -> bytes:
    """t300rs_packet_header: un cero, el identificador MAS UNO, y el codigo."""
    return bytes((0x00, (eid + 1) & 0xFF, codigo))


def _tiempos(duracion: int, retardo: int) -> bytes:
    """t300rs_packet_timing: marca 0x4f, duracion, hueco, retardo, 0xffff."""
    return (b"\x4f" + struct.pack("<H", duracion) + b"\x00\x00" +
            struct.pack("<H", retardo) + b"\x00" + b"\xff\xff")


def paq_abrir():
    """t300rs_send_open. Hay que mandarlo antes de ningun efecto."""
    return b"\x01\x05"


def paq_cerrar():
    return b"\x01"


def paq_ganancia(ganancia16: int):
    """Solo viaja el byte alto: la resolucion real es de 8 bits."""
    return bytes((0x02, (ganancia16 >> 8) & 0xFF))


def paq_autocentrado(valor16: int):
    """Dos paquetes: primero habilitar, luego el valor."""
    return (b"\x08\x04\x01\x00",
            b"\x08\x03" + struct.pack("<H", valor16 & 0xFFFF))


def paq_rango(grados: int):
    """Grados de giro del volante, de 40 a 1080."""
    grados = max(40, min(1080, int(grados)))
    return b"\x08\x11" + struct.pack("<H", (grados * 0x3C) & 0xFFFF)


def paq_subir_constante(eid, nivel, duracion=0xFFFF, retardo=0):
    """t300rs_upload_constant (codigo 0x6a).

    ``nivel`` va en el rango del volante, [-16384, 16383]: es la mitad del
    rango de evdev, tal como hace el driver de Windows."""
    return (_cabecera(eid, 0x6A) + struct.pack("<h", nivel) +
            _SIN_ENVOLVENTE + b"\x00" + _tiempos(duracion, retardo))


def paq_actualizar_constante(eid, nivel, duracion=0xFFFF, retardo=0):
    """t300rs_update_constant: mismo codigo, otra forma. 0x45 = actualizar."""
    return (_cabecera(eid, 0x6A) + struct.pack("<h", nivel) +
            _SIN_ENVOLVENTE + b"\x00" + b"\x45" +
            struct.pack("<HH", duracion, retardo))


def paq_subir_periodico(eid, magnitud, periodo_ms, forma=FF_SINE,
                        desfase=0, offset=0, duracion=0xFFFF, retardo=0):
    """t300rs_upload_periodic (codigo 0x6b). La magnitud es SIEMPRE positiva:
    el volante no admite periodicos negativos."""
    return (_cabecera(eid, 0x6B) +
            struct.pack("<Hh HH H", abs(magnitud), offset, desfase,
                        periodo_ms, 0x8000) +
            _SIN_ENVOLVENTE + bytes((forma - 0x57,)) +
            _tiempos(duracion, retardo))


def paq_actualizar_periodico(eid, magnitud, periodo_ms, forma=FF_SINE,
                             desfase=0, offset=0, duracion=0xFFFF, retardo=0):
    """t300rs_update_periodic (codigo 0x6e, tipo 0x0f)."""
    return (_cabecera(eid, 0x6E) + b"\x0f" +
            struct.pack("<Hh HH", abs(magnitud), offset, desfase, periodo_ms) +
            _SIN_ENVOLVENTE + bytes((forma - 0x57,)) + b"\x45" +
            struct.pack("<HH", duracion, retardo))


def paq_reproducir(eid, veces=0):
    """0 veces = sin fin, hasta que se pare."""
    return _cabecera(eid, 0x89) + b"\x41" + struct.pack("<H", veces & 0xFFFF)


def paq_parar(eid):
    return _cabecera(eid, 0x89) + b"\x00"


# --- el objeto que usa el juego ----------------------------------------
#: Identificadores de efecto que reserva el juego. El volante admite 16.
EF_CONSTANTE, EF_TEXTURA = 0, 1


class VolanteT300RS:
    """Force feedback del T300RS escribiendo informes HID de salida.

    Misma interfaz que ``ffb_evdev.VolanteEvdev``, para que
    ``ForceFeedback`` pueda usar una u otra sin enterarse."""

    def __init__(self, info):
        self.ruta = info["ruta"]
        self.nombre = info.get("nombre", "")
        self.modelo = info.get("modelo", "")
        self.informe = info["informe"]
        self.largo = info.get("largo") or LARGO_NORMAL
        self.fd = -1
        self.ok = False
        self.motivo = ""
        self._nivel = None          # ultimo par mandado, para no repetir
        self._textura = None
        try:
            self.fd = os.open(self.ruta, os.O_WRONLY)
        except OSError as e:
            self.motivo = f"no se pudo abrir {self.ruta} ({e.strerror})"
            return
        if not self._enviar(paq_abrir()):
            self.motivo = "el volante no acepto el paquete de apertura"
            os.close(self.fd)
            self.fd = -1
            return
        # se suben los dos efectos en reposo y se dejan sonando: a partir de
        # ahi solo se actualizan, que es una escritura por fotograma
        self._enviar(paq_subir_constante(EF_CONSTANTE, 0))
        self._enviar(paq_reproducir(EF_CONSTANTE))
        self._enviar(paq_subir_periodico(EF_TEXTURA, 0, 50))
        self._enviar(paq_reproducir(EF_TEXTURA))
        self.ok = True

    # -- transporte -----------------------------------------------------
    def _enviar(self, carga: bytes) -> bool:
        """Escribe un informe de salida: identificador + carga + ceros."""
        if self.fd < 0 or len(carga) > self.largo:
            return False
        marco = (bytes((self.informe,)) + carga +
                 b"\x00" * (self.largo - len(carga)))
        try:
            os.write(self.fd, marco)
        except OSError:
            return False
        return True

    # -- ajustes globales ----------------------------------------------
    def ganancia(self, valor=1.0):
        v = int(max(0.0, min(1.0, valor)) * 0xFFFF)
        self._enviar(paq_ganancia(v))

    def autocentrado(self, valor=0.0):
        """El autocentrado del volante estorba: lo sustituye la física."""
        for p in paq_autocentrado(int(max(0.0, min(1.0, valor)) * 0xFFFF)):
            self._enviar(p)

    def rango(self, grados):
        self._enviar(paq_rango(grados))

    # -- efectos --------------------------------------------------------
    def constante(self, nivel: float):
        """Par de la dirección, de -1 a 1."""
        # El volante usa la mitad del rango de evdev, como el driver de
        # Windows: [-16384, 16383].
        v = int(max(-1.0, min(1.0, nivel)) * 16383)
        if v == self._nivel:
            return                      # sin cambios: no se gasta el bus
        self._nivel = v
        self._enviar(paq_actualizar_constante(EF_CONSTANTE, v))

    def textura(self, magnitud: float, periodo_ms: int):
        m = int(max(0.0, min(1.0, magnitud)) * 32767)
        p = max(1, min(0xFFFF, int(periodo_ms)))
        if (m, p) == self._textura:
            return
        self._textura = (m, p)
        self._enviar(paq_actualizar_periodico(EF_TEXTURA, m, p))

    def condicion(self, clave, coef):
        """Muelle y amortiguador: no se usan, los calcula la física."""

    def soporta(self, tipo) -> bool:
        from . import ffb_evdev
        return tipo in (ffb_evdev.FF_CONSTANT, ffb_evdev.FF_PERIODIC)

    def parar(self):
        self.constante(0.0)
        self.textura(0.0, 50)

    def close(self):
        if self.fd < 0:
            return
        self.parar()
        for eid in (EF_CONSTANTE, EF_TEXTURA):
            self._enviar(paq_parar(eid))
        self._enviar(paq_cerrar())
        os.close(self.fd)
        self.fd = -1
        self.ok = False
