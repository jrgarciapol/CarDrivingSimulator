"""Force feedback hablando DIRECTAMENTE con evdev (Linux), sin SDL.

Por qué existe este módulo
--------------------------
En la Steam Deck el T300RS se leía perfectamente (dirección, tres pedales,
botones) pero SDL decía que no era háptico: ``SDL_JoystickIsHaptic`` devolvía
NO y el único háptico del sistema era el mando interno de la propia Deck. Sin
embargo, **los juegos de Steam sí mueven el volante con fuerza en esa misma
máquina**. Si Proton/Wine consigue el par es porque el núcleo SÍ está
publicando la interfaz de force feedback de evdev en algún ``/dev/input/eventN``
del volante: lo que falla no es el driver, es el camino por el que nuestro
proceso pide la fuerza.

Casos conocidos en los que SDL no ve el háptico y evdev sí:

  - El volante publica los ejes en un nodo y el force feedback en otro; SDL
    solo mira el que le dio el joystick.
  - SDL abrió el nodo en solo lectura (el FFB necesita ESCRIBIR) o el
    permiso de escritura llegó por ``uaccess`` después de arrancar SDL.
  - La copia de SDL que traen los binarios de ``pysdl2-dll`` es más antigua
    que la que usa Steam y no reconoce ese modelo.

Este módulo se salta el problema entero: busca el nodo de evento del volante,
comprueba en ``/sys`` que anuncia ``FF_CONSTANT`` y manda los efectos con
``ioctl(EVIOCSFF)``, que es exactamente lo que hace Wine por debajo.

Solo funciona en Linux. En Windows no hay ``/dev/input``: allí manda SDL con
DirectInput, y este módulo se queda callado (``disponible()`` da False).
"""

import ctypes
import fcntl
import glob
import os
import struct

# --- códigos de linux/input-event-codes.h ------------------------------
EV_FF = 0x15

FF_RUMBLE = 0x50
FF_PERIODIC = 0x51
FF_CONSTANT = 0x52
FF_SPRING = 0x53
FF_FRICTION = 0x54
FF_DAMPER = 0x55
FF_INERTIA = 0x56
FF_RAMP = 0x57

FF_SQUARE = 0x58
FF_TRIANGLE = 0x59
FF_SINE = 0x5A

FF_GAIN = 0x60
FF_AUTOCENTER = 0x61

#: Nombre legible de cada capacidad, para los informes de diagnóstico.
NOMBRES_FF = {
    FF_CONSTANT: "fuerza constante (el par de la direccion)",
    FF_PERIODIC: "periodico (texturas: asfalto, pianos)",
    FF_SPRING: "muelle (autocentrado)",
    FF_DAMPER: "amortiguador",
    FF_RUMBLE: "vibracion",
    FF_RAMP: "rampa",
    FF_FRICTION: "friccion",
    FF_INERTIA: "inercia",
}


# --- struct ff_effect, tal cual la define linux/input.h ----------------
class _Envelope(ctypes.Structure):
    _fields_ = [("attack_length", ctypes.c_uint16),
                ("attack_level", ctypes.c_uint16),
                ("fade_length", ctypes.c_uint16),
                ("fade_level", ctypes.c_uint16)]


class _Constant(ctypes.Structure):
    _fields_ = [("level", ctypes.c_int16), ("envelope", _Envelope)]


class _Ramp(ctypes.Structure):
    _fields_ = [("start_level", ctypes.c_int16),
                ("end_level", ctypes.c_int16),
                ("envelope", _Envelope)]


class _Condition(ctypes.Structure):
    _fields_ = [("right_saturation", ctypes.c_uint16),
                ("left_saturation", ctypes.c_uint16),
                ("right_coeff", ctypes.c_int16),
                ("left_coeff", ctypes.c_int16),
                ("deadband", ctypes.c_uint16),
                ("center", ctypes.c_int16)]


class _Periodic(ctypes.Structure):
    _fields_ = [("waveform", ctypes.c_uint16),
                ("period", ctypes.c_uint16),
                ("magnitude", ctypes.c_int16),
                ("offset", ctypes.c_int16),
                ("phase", ctypes.c_uint16),
                ("envelope", _Envelope),
                ("custom_len", ctypes.c_uint32),
                ("custom_data", ctypes.POINTER(ctypes.c_int16))]


class _Rumble(ctypes.Structure):
    _fields_ = [("strong_magnitude", ctypes.c_uint16),
                ("weak_magnitude", ctypes.c_uint16)]


class _UnionFF(ctypes.Union):
    _fields_ = [("constant", _Constant), ("ramp", _Ramp),
                ("periodic", _Periodic), ("condition", _Condition * 2),
                ("rumble", _Rumble)]


class _Trigger(ctypes.Structure):
    _fields_ = [("button", ctypes.c_uint16), ("interval", ctypes.c_uint16)]


class _Replay(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint16), ("delay", ctypes.c_uint16)]


class FFEffect(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint16), ("id", ctypes.c_int16),
                ("direction", ctypes.c_uint16), ("trigger", _Trigger),
                ("replay", _Replay), ("u", _UnionFF)]


def _iow(nr, size):
    return (1 << 30) | (size << 16) | (ord("E") << 8) | nr


def _ior(nr, size):
    return (2 << 30) | (size << 16) | (ord("E") << 8) | nr


EVIOCSFF = _iow(0x80, ctypes.sizeof(FFEffect))
EVIOCRMFF = _iow(0x81, 4)
EVIOCGEFFECTS = _ior(0x84, 4)


def _eviocgname(n):
    return _ior(0x06, n)


# --- utilidades ---------------------------------------------------------
def disponible() -> bool:
    """True solo en sistemas con evdev (Linux)."""
    return os.path.isdir("/dev/input")


def _nombre(fd) -> str:
    buf = ctypes.create_string_buffer(256)
    try:
        fcntl.ioctl(fd, _eviocgname(256), buf)
    except OSError:
        return ""
    return buf.value.decode("utf-8", "replace")


def _mascara_sysfs(evento: str, cap: str) -> int:
    """Lee /sys/class/input/eventN/device/capabilities/<cap>.

    El fichero trae la máscara en palabras hexadecimales separadas por
    espacios, de la más significativa a la menos. No hace falta abrir el
    dispositivo para leerlo, así que sirve aunque no haya permiso de
    escritura: justo lo que interesa para distinguir "el driver no publica
    FF" de "el driver lo publica pero no puedo escribir"."""
    ruta = f"/sys/class/input/{evento}/device/capabilities/{cap}"
    try:
        with open(ruta) as f:
            palabras = f.read().split()
    except OSError:
        return 0
    valor = 0
    for p in palabras:                      # de mayor a menor peso
        valor = (valor << 64) | int(p, 16)
    return valor


def _nombre_sysfs(evento: str) -> str:
    try:
        with open(f"/sys/class/input/{evento}/device/name") as f:
            return f.read().strip()
    except OSError:
        return ""


def _uevent(ruta_sys: str) -> dict:
    """Lee un fichero uevent de /sys como diccionario CLAVE=valor."""
    d = {}
    try:
        with open(ruta_sys) as f:
            for linea in f:
                if "=" in linea:
                    k, _, v = linea.strip().partition("=")
                    d[k] = v
    except OSError:
        pass
    return d


#: Donde publica el nucleo los aparatos del bus USB. Es una constante para
#: poder apuntarla a un arbol de mentira en las pruebas.
RUTA_USB = "/sys/bus/usb/devices"


def usb(vid=None):
    """Aparatos del bus USB, opcionalmente filtrados por fabricante.

    Es el escalón de más abajo, por debajo de HID y de evdev. Sirve para
    separar tres averías que se parecen mucho desde arriba:

      - no sale NADA en el bus: no llega corriente, o el cable, o la base
        está estropeada; el sistema operativo no tiene la culpa de nada,
      - sale en el bus pero sin /dev/hidraw: el aparato enumera y el
        problema es de driver,
      - sale con hidraw: el aparato está bien y lo que falla es más arriba.

    ``vid`` es el identificador de fabricante en hexadecimal ("044f")."""
    out = []
    base = RUTA_USB

    def leer(ruta):
        try:
            with open(ruta) as f:
                return f.read().strip()
        except OSError:
            return ""

    try:
        nodos = sorted(os.listdir(base))
    except OSError:
        return out
    for n in nodos:
        v = leer(f"{base}/{n}/idVendor")
        if not v or (vid is not None and v.lower() != vid.lower()):
            continue
        out.append({
            "nodo": n,
            "vid": v.lower(),
            "pid": leer(f"{base}/{n}/idProduct").lower(),
            "nombre": leer(f"{base}/{n}/product"),
            "fabricante": leer(f"{base}/{n}/manufacturer"),
        })
    return out


def hidraws():
    """Inventario de /dev/hidraw*: nombre del aparato, VID:PID y driver.

    Es la OTRA vía posible al force feedback. Los drivers de volante
    Thrustmaster (hid-tmff2 y compañía) no inventan nada raro: mandan
    informes HID de salida por el mismo canal que aquí queda abierto en
    espacio de usuario. Si el núcleo no publica FF por evdev pero el volante
    tiene un /dev/hidraw con permiso de escritura, esa puerta sigue ahí, y es
    por donde puede estar entrando la fuerza en los juegos de Steam."""
    out = []
    try:
        nodos = sorted(os.listdir("/sys/class/hidraw"),
                       key=lambda n: int(n.replace("hidraw", "") or 0))
    except OSError:
        return out
    for nodo in nodos:
        u = _uevent(f"/sys/class/hidraw/{nodo}/device/uevent")
        # HID_ID = bus:VVVVVVVV:PPPPPPPP en hexadecimal
        partes = u.get("HID_ID", "").split(":")
        vid = pid = ""
        if len(partes) == 3:
            vid, pid = partes[1][-4:].lower(), partes[2][-4:].lower()
        ruta = f"/dev/{nodo}"
        out.append({
            "ruta": ruta,
            "nombre": u.get("HID_NAME", ""),
            "vid": vid,
            "pid": pid,
            "driver": u.get("DRIVER", ""),
            "lectura": os.access(ruta, os.R_OK),
            "escritura": os.access(ruta, os.W_OK),
        })
    return out


def listar():
    """Inventario de /dev/input/event*: nombre, capacidades FF y permisos.

    Devuelve una lista de diccionarios con las claves ``ruta``, ``nombre``,
    ``ff`` (máscara de efectos), ``lectura`` y ``escritura``. Es la base del
    diagnóstico: si un nodo tiene ``ff`` distinto de cero, el núcleo SÍ
    ofrece force feedback aunque SDL diga lo contrario."""
    out = []
    for ruta in sorted(glob.glob("/dev/input/event*"),
                       key=lambda r: int(r.rsplit("event", 1)[-1] or 0)):
        evento = os.path.basename(ruta)
        nombre = _nombre_sysfs(evento)
        if not nombre and os.access(ruta, os.R_OK):
            try:
                fd = os.open(ruta, os.O_RDONLY)
            except OSError:
                fd = -1
            if fd >= 0:
                nombre = _nombre(fd)
                os.close(fd)
        # El padre del dispositivo de entrada es el aparato HID: de ahi salen
        # el driver que lo ha tomado y el VID:PID, que dicen en que modo esta
        # el volante (el T300RS cambia de PID entre modo PC y modo PlayStation).
        u = _uevent(f"/sys/class/input/{evento}/device/device/uevent")
        partes = u.get("HID_ID", "").split(":")
        vid = pid = ""
        if len(partes) == 3:
            vid, pid = partes[1][-4:].lower(), partes[2][-4:].lower()
        out.append({
            "ruta": ruta,
            "nombre": nombre,
            "ff": _mascara_sysfs(evento, "ff"),
            "driver": u.get("DRIVER", ""),
            "vid": vid,
            "pid": pid,
            "lectura": os.access(ruta, os.R_OK),
            "escritura": os.access(ruta, os.W_OK),
        })
    return out


def efectos_de(mascara: int):
    """Lista legible de los efectos que anuncia una máscara FF."""
    return [NOMBRES_FF[b] for b in sorted(NOMBRES_FF) if mascara >> b & 1]


def buscar_volante(pistas):
    """Nodo de evento del volante con force feedback, o None.

    ``pistas`` son trozos de nombre en minúsculas (``cfg.WHEEL_NAME_HINTS``).
    Se exige ``FF_CONSTANT``: es el par de la dirección, lo único
    imprescindible. Se prefiere un nodo cuyo nombre encaje con las pistas;
    si ninguno encaja pero hay un solo nodo con FF_CONSTANT que no sea un
    mando, se acepta ese (algunos volantes publican el FF en un nodo
    hermano con otro nombre)."""
    candidatos = [d for d in listar() if d["ff"] >> FF_CONSTANT & 1]
    if not candidatos:
        return None
    for d in candidatos:
        n = d["nombre"].lower()
        if any(p in n for p in pistas):
            return d
    ajenos = ("x-box", "xbox", "gamepad", "steam deck", "sony", "dualshock",
              "dualsense", "keyboard", "mouse")
    sueltos = [d for d in candidatos
               if not any(a in d["nombre"].lower() for a in ajenos)]
    return sueltos[0] if len(sueltos) == 1 else None


# --- el objeto que usa el juego ----------------------------------------
class VolanteEvdev:
    """Efectos de force feedback sobre un nodo evdev abierto en lectura y
    escritura. La interfaz imita a la de SDL para que ``ForceFeedback`` la
    use sin enterarse de cuál de las dos vías está activa."""

    def __init__(self, ruta, mascara=None):
        self.ruta = ruta
        self.fd = -1
        self.ok = False
        self.mascara = 0
        self.motivo = ""
        self._ef = {}          # clave -> FFEffect (con su id ya asignado)
        evento = os.path.basename(ruta)
        self.mascara = mascara if mascara is not None else \
            _mascara_sysfs(evento, "ff")
        self.nombre = _nombre_sysfs(evento)
        if not self.mascara >> FF_CONSTANT & 1:
            self.motivo = "el dispositivo no anuncia fuerza constante"
            return
        try:
            self.fd = os.open(ruta, os.O_RDWR)
        except OSError as e:
            self.motivo = f"no se pudo abrir {ruta} para escribir ({e.strerror})"
            return
        if not self.nombre:
            self.nombre = _nombre(self.fd)
        # el driver limita cuántos efectos puede tener un proceso a la vez
        self.max_efectos = self._num_efectos()
        self._crear_efectos()
        self.ok = "constant" in self._ef
        if not self.ok and not self.motivo:
            self.motivo = "el driver rechazo el efecto de fuerza constante"

    # -- montaje --------------------------------------------------------
    def _num_efectos(self):
        buf = ctypes.c_int(0)
        try:
            fcntl.ioctl(self.fd, EVIOCGEFFECTS, buf)
        except OSError:
            return 16
        return max(1, buf.value)

    def _subir(self, clave, ef):
        """Sube el efecto al driver (EVIOCSFF) y lo deja sonando.

        Con ``id = -1`` el núcleo reserva una ranura y escribe el id en la
        estructura; a partir de ahí, repetir EVIOCSFF con ese mismo id
        ACTUALIZA el efecto en marcha, que es como se manda el par frame a
        frame sin cortes."""
        ef.id = -1
        try:
            fcntl.ioctl(self.fd, EVIOCSFF, ef)
        except OSError:
            return False
        self._ef[clave] = ef
        self._reproducir(ef.id, 1)
        return True

    def _reproducir(self, eid, veces):
        try:
            os.write(self.fd, struct.pack("llHHi", 0, 0, EV_FF, eid, veces))
        except OSError:
            pass

    def _crear_efectos(self):
        # Dirección 0x4000 = 90 grados = "hacia la derecha" en el convenio de
        # evdev para volantes. El signo del par se lleva en el nivel.
        if self.mascara >> FF_CONSTANT & 1:
            e = FFEffect()
            e.type = FF_CONSTANT
            e.direction = 0x4000
            e.replay.length = 0          # 0 = infinito mientras no se pare
            e.u.constant.level = 0
            self._subir("constant", e)
        if self.mascara >> FF_PERIODIC & 1:
            e = FFEffect()
            e.type = FF_PERIODIC
            e.direction = 0x4000
            e.replay.length = 0
            e.u.periodic.waveform = FF_SINE
            e.u.periodic.period = 50
            e.u.periodic.magnitude = 0
            self._subir("rumble", e)
        for clave, tipo in (("spring", FF_SPRING), ("damper", FF_DAMPER)):
            if not self.mascara >> tipo & 1:
                continue
            e = FFEffect()
            e.type = tipo
            e.direction = 0x4000
            e.replay.length = 0
            for i in range(2):
                e.u.condition[i].right_saturation = 0xFFFF
                e.u.condition[i].left_saturation = 0xFFFF
                e.u.condition[i].right_coeff = 0
                e.u.condition[i].left_coeff = 0
            self._subir(clave, e)

    # -- ajustes globales ----------------------------------------------
    def ganancia(self, valor=1.0):
        v = int(max(0.0, min(1.0, valor)) * 0xFFFF)
        try:
            os.write(self.fd, struct.pack("llHHi", 0, 0, EV_FF, FF_GAIN, v))
        except OSError:
            pass

    def autocentrado(self, valor=0.0):
        """El autocentrado del driver estorba: lo sustituye nuestra física."""
        v = int(max(0.0, min(1.0, valor)) * 0xFFFF)
        try:
            os.write(self.fd,
                     struct.pack("llHHi", 0, 0, EV_FF, FF_AUTOCENTER, v))
        except OSError:
            pass

    # -- efectos --------------------------------------------------------
    def _actualiza(self, clave):
        ef = self._ef.get(clave)
        if ef is None:
            return
        try:
            fcntl.ioctl(self.fd, EVIOCSFF, ef)
        except OSError:
            pass

    def constante(self, nivel: float):
        """Par de la dirección, de -1 a 1."""
        ef = self._ef.get("constant")
        if ef is None:
            return
        ef.u.constant.level = int(max(-1.0, min(1.0, nivel)) * 32767)
        self._actualiza("constant")

    def textura(self, magnitud: float, periodo_ms: int):
        ef = self._ef.get("rumble")
        if ef is None:
            return
        ef.u.periodic.magnitude = int(max(0.0, min(1.0, magnitud)) * 32767)
        ef.u.periodic.period = max(1, int(periodo_ms))
        self._actualiza("rumble")

    def condicion(self, clave: str, coef: float):
        ef = self._ef.get(clave)
        if ef is None:
            return
        c = int(max(0.0, min(1.0, coef)) * 0x7FFF)
        for i in range(2):
            ef.u.condition[i].right_coeff = c
            ef.u.condition[i].left_coeff = c
        self._actualiza(clave)

    def soporta(self, tipo: int) -> bool:
        return bool(self.mascara >> tipo & 1)

    def parar(self):
        self.constante(0.0)
        self.textura(0.0, 50)

    def close(self):
        if self.fd < 0:
            return
        self.parar()
        for ef in self._ef.values():
            self._reproducir(ef.id, 0)
            try:
                # EVIOCRMFF recibe el id POR VALOR, no un puntero
                fcntl.ioctl(self.fd, EVIOCRMFF, ef.id)
            except OSError:
                pass
        self._ef.clear()
        os.close(self.fd)
        self.fd = -1
        self.ok = False
