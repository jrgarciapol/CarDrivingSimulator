"""Entrada de volante o mando, y force feedback.

Usa el subsistema de joystick, gamepad y háptico de SDL2. En Windows el
háptico se apoya en DirectInput (el mismo API que usan los juegos de
conducción con los Thrustmaster); en Linux, sobre la interfaz de force
feedback de evdev. El código es el mismo: por eso el simulador funciona
igual en un PC con volante que en una Steam Deck.

Hay TRES modos de entrada, elegidos automáticamente:

  - VOLANTE: se reconoce por el nombre (WHEEL_NAME_HINTS) o por tener
    suficientes ejes. Dirección proporcional al giro real, pedales
    analógicos y force feedback completo.
  - MANDO (Steam Deck, XBox, PlayStation...): stick izquierdo para la
    dirección y GATILLOS ANALOGICOS para acelerador y freno, con curva
    progresiva, límite de dirección por velocidad y vibración en vez de
    par. Sin esto, en una Steam Deck el juego era injugable: el mando se
    abría como si fuera un volante y el mapeo de pedales no tenía sentido.
  - TECLADO: último recurso, con las flechas.

Efectos hápticos del volante:
  - Fuerza constante: par de autoalineado calculado por la física. Es la
    sensación principal: el volante se endurece con el apoyo y se aligera
    cuando el neumático delantero pierde agarre.
  - Muelle: centrado suave solo a baja velocidad (maniobras/parking).
  - Amortiguador: pesadez a baja velocidad que desaparece en marcha.
  - Senoidal: texturas (asfalto, pianos, hierba, ralentí del motor).
"""

import ctypes
import os

import sdl2

from . import config as cfg
from . import ffb_evdev
from . import ffb_t300rs

VOLANTE, MANDO, TECLADO = "volante", "mando", "teclado"

#: Acciones del juego, independientes del mando físico que las produzca.
ACCIONES = ("shift_up", "shift_down", "toggle_auto", "toggle_view",
            "engine", "reset", "slowmo",
            "menu", "telemetry", "minimap", "plan", "line")

#: Botones de un gamepad estándar para cada acción. SDL normaliza cualquier
#: mando conocido a este esquema, así que vale igual para la Steam Deck que
#: para un mando de XBox o de PlayStation. La CRUCETA (d-pad) da acceso a
#: los paneles del HUD sin necesitar las teclas F1/F2, que el teclado
#: virtual de la Deck no tiene.
_PAD_BOTONES = {
    "shift_up": sdl2.SDL_CONTROLLER_BUTTON_RIGHTSHOULDER,
    "shift_down": sdl2.SDL_CONTROLLER_BUTTON_LEFTSHOULDER,
    "engine": sdl2.SDL_CONTROLLER_BUTTON_A,
    "reset": sdl2.SDL_CONTROLLER_BUTTON_B,
    "toggle_view": sdl2.SDL_CONTROLLER_BUTTON_X,
    "toggle_auto": sdl2.SDL_CONTROLLER_BUTTON_Y,
    "slowmo": sdl2.SDL_CONTROLLER_BUTTON_BACK,
    "menu": sdl2.SDL_CONTROLLER_BUTTON_START,          # volver al menu (ESC)
    "telemetry": sdl2.SDL_CONTROLLER_BUTTON_DPAD_UP,   # F2
    "plan": sdl2.SDL_CONTROLLER_BUTTON_DPAD_RIGHT,     # planta del tramo (N)
    "minimap": sdl2.SDL_CONTROLLER_BUTTON_DPAD_LEFT,   # plano completo (M)
    "line": sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN,      # trazada ideal (L)
}


def _axis_to_norm(raw: int) -> float:
    return max(-1.0, min(1.0, raw / 32767.0))


def _pedal_to_norm(raw: int) -> float:
    v = raw / 32767.0
    if cfg.PEDALS_INVERTED:
        return max(0.0, min(1.0, (1.0 - v) * 0.5))
    return max(0.0, min(1.0, (v + 1.0) * 0.5))


def _zona_muerta(v: float, dz: float) -> float:
    """Recorta la zona muerta y REESCALA lo que queda, para no perder
    recorrido útil del stick (si no, el tope se alcanzaría antes)."""
    if abs(v) <= dz:
        return 0.0
    return (abs(v) - dz) / (1.0 - dz) * (1.0 if v > 0 else -1.0)


def curva_direccion(bruto: float, speed_kmh: float, actual: float,
                    dt: float) -> float:
    """Convierte la posición cruda del stick (-1..1) en posición de volante.

    Función PURA para poder probarla sin hardware. Cuatro correcciones, las
    mismas que aplica cualquier juego de conducción con mando (sin ellas el
    coche es incontrolable, porque un stick recorre todo su rango en dos
    centímetros y vuelve al centro de golpe):

      1. ZONA MUERTA reescalada: los sticks derivan en reposo, pero recortar
         sin reescalar perdería recorrido útil.
      2. CURVA PROGRESIVA: cerca del centro responde poco (permite hilar
         fino en recta), en los extremos entrega todo el tope.
      3. LIMITE POR VELOCIDAD: a 200 km/h no se puede pedir el mismo ángulo
         que aparcando, o el coche trompea al menor toque. Es lo mismo que
         hace una dirección asistida progresiva.
      4. VELOCIDAD DE GIRO limitada: tampoco los brazos van de tope a tope
         al instante.
    """
    s = _zona_muerta(bruto, cfg.PAD_DEADZONE)
    expo = cfg.PAD_STEER_EXPO
    s = (1.0 - expo) * s + expo * s * s * s
    t = min(1.0, max(0.0, speed_kmh / max(1.0, cfg.PAD_STEER_FAST_KMH)))
    tope = cfg.PAD_STEER_MAX + (cfg.PAD_STEER_MAX_FAST - cfg.PAD_STEER_MAX) * t
    objetivo = s * tope
    margen = cfg.PAD_STEER_RATE * dt
    return actual + max(-margen, min(margen, objetivo - actual))


class WheelInput:
    """Lectura del volante, mando o teclado, con estado normalizado."""

    def __init__(self):
        self.joystick = None
        self.controller = None
        self.kind = TECLADO
        self.name = ""
        self.num_axes = 0
        self.num_buttons = 0
        self.num_hats = 0
        self.pad_nav = None
        self._open_device()
        # estado normalizado
        self.steering = 0.0
        self.throttle = 0.0
        self.brake = 0.0
        self.clutch = 0.0
        self._prev_buttons = {}
        self._prev_acciones = {}
        self._prev_menu = {}
        self._rep = {}                  # temporizadores de auto-repeticion

    @staticmethod
    def _guardar_informe(lineas, nombre="diagnostico_entrada.txt"):
        """Escribe el informe en la raiz del proyecto y dice donde queda.

        Asi no hay que transcribir nada de la pantalla: se abre el archivo y
        se copia, o se sube al repositorio con add + commit + push (un
        'git pull' NO sube nada: solo descarga)."""
        import datetime
        import platform
        ruta = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), nombre)
        try:
            with open(ruta, "w") as f:
                f.write(f"# Diagnostico de entrada - "
                        f"{datetime.datetime.now():%Y-%m-%d %H:%M}\n")
                f.write(f"# {platform.system()} {platform.release()} | "
                        f"python {platform.python_version()}\n\n")
                f.write("\n".join(lineas) + "\n")
            print(f"\n  Informe guardado en: {ruta}\n"
                  f"  Puedes abrirlo y copiarlo, o subirlo al repositorio:\n"
                  f"    git add -f {nombre} && git commit -m 'diagnostico "
                  f"volante' && git push\n"
                  f"  (ojo: 'git pull' solo DESCARGA; para subir hace falta "
                  f"'git push')")
        except OSError as e:
            print(f"\n  No se pudo guardar el informe: {e}")

    @staticmethod
    def diagnostico():
        """Lista TODO lo que ve SDL y explica a quien elegiria el juego.

        Es la herramienta para saber por que un volante no funciona: en una
        Steam Deck lanzada DESDE STEAM, Steam Input se apodera del volante y
        lo vuelve a presentar como un mando virtual, asi que el juego ya no
        ve un Thrustmaster sino un gamepad. Aqui se ve de un vistazo."""
        L = []

        def di(txt=""):
            print(txt)
            L.append(txt)

        count = sdl2.SDL_NumJoysticks()
        di(f"\nDISPOSITIVOS DE ENTRADA QUE VE SDL: {count}\n")
        if count == 0:
            di("  (ninguno)\n"
               "  - Conecta el volante ANTES de arrancar.\n"
               "  - En Linux, comprueba que aparece en /dev/input/ y que\n"
               "    tu usuario tiene permiso (grupo 'input').")
        volante = pad = -1
        for i in range(count):
            raw = sdl2.SDL_JoystickNameForIndex(i)
            name = raw.decode("utf-8", "replace") if raw else "?"
            low = name.lower()
            es_pad = bool(sdl2.SDL_IsGameController(i))
            js = sdl2.SDL_JoystickOpen(i)
            ejes = sdl2.SDL_JoystickNumAxes(js) if js else 0
            bot = sdl2.SDL_JoystickNumButtons(js) if js else 0
            hap = bool(sdl2.SDL_JoystickIsHaptic(js)) if js else False
            if js:
                sdl2.SDL_JoystickClose(js)
            por_nombre = any(h in low for h in cfg.WHEEL_NAME_HINTS)
            if por_nombre and volante < 0:
                volante = i
            if es_pad and pad < 0:
                pad = i
            di(f"  [{i}] {name}")
            di(f"      ejes={ejes}  botones={bot}  "
               f"gamepad_para_SDL={'si' if es_pad else 'no'}  "
               f"force_feedback={'si' if hap else 'no'}")
            di(f"      coincide con WHEEL_NAME_HINTS: "
               f"{'SI' if por_nombre else 'no'}")
        if volante < 0:
            for i in range(count):
                if sdl2.SDL_IsGameController(i):
                    continue
                js = sdl2.SDL_JoystickOpen(i)
                if not js:
                    continue
                ok = (sdl2.SDL_JoystickNumAxes(js) >= 3
                      and sdl2.SDL_JoystickNumButtons(js) >= 4)
                sdl2.SDL_JoystickClose(js)
                if ok:
                    volante = i
                    break
        di()
        if volante >= 0:
            di(f"  -> El juego usaria el VOLANTE del indice {volante}.")
        elif pad >= 0:
            di(f"  -> El juego usaria el MANDO del indice {pad}.")
            di("     Si lo que tienes conectado es un VOLANTE, es que algo\n"
                  "     lo esta presentando como mando. En una Steam Deck eso\n"
                  "     lo hace STEAM INPUT: en las propiedades del juego, en\n"
                  "     Mando, pon 'Desactivar Steam Input'. Luego repite\n"
                  "     esta prueba: debe aparecer el Thrustmaster por su\n"
               "     nombre. Tambien puedes forzarlo con --volante.")
        else:
            di("  -> El juego usaria el TECLADO.")
        di()
        WheelInput._guardar_informe(L)

    @staticmethod
    def diagnostico_ffb(indice=0):
        """Averigua POR QUE no hay force feedback y que efectos admite.

        En Linux el par del volante sale de la interfaz de force feedback de
        evdev. Que el volante gire al enchufarlo (autocalibracion) NO
        significa que haya FFB: eso lo hace el firmware. Para que el juego
        pueda mandar fuerza hacen falta tres cosas, y aqui se comprueban una
        a una: un driver que exponga la capacidad FF, permiso sobre el
        dispositivo, y que SDL consiga abrir el haptico."""
        L = []

        def di(t=""):
            print(t)
            L.append(t)

        di("\nDIAGNOSTICO DE FORCE FEEDBACK\n")
        di(f"  hapticos que ve SDL: {sdl2.SDL_NumHaptics()}")
        # Aunque SDL no vea el volante se sigue adelante: la parte importante
        # del diagnostico la da el NUCLEO, mas abajo, y funciona igual.
        hay_js = sdl2.SDL_NumJoysticks() > indice
        if not hay_js:
            di("  SDL no ve ningun dispositivo en el indice "
               f"{indice}: conecta el volante antes de arrancar.")
        js = sdl2.SDL_JoystickOpen(indice) if hay_js else None
        raw = sdl2.SDL_JoystickName(js) if js else None
        di(f"  dispositivo: "
           f"{raw.decode('utf-8', 'replace') if raw else '?'}")
        es_hap = bool(sdl2.SDL_JoystickIsHaptic(js)) if js else False
        di(f"  SDL_JoystickIsHaptic: {'si' if es_hap else 'NO'}")
        # Los hapticos por INDICE: en Linux el force feedback puede estar en
        # un nodo distinto del que da los ejes, y entonces IsHaptic dice NO
        # aunque el aparato este ahi. Por eso se listan aparte.
        for i in range(sdl2.SDL_NumHaptics()):
            raw = sdl2.SDL_HapticName(i)
            di(f"    haptico [{i}]: "
               f"{raw.decode('utf-8', 'replace') if raw else '?'}")
        hap = None
        del_volante = False
        constante = False
        if js and es_hap:
            hap = sdl2.SDL_HapticOpenFromJoystick(js)
            del_volante = bool(hap)
        else:
            # buscar por INDICE, pero SOLO uno que se llame como un volante:
            # el mando de la Deck tambien es haptico y no sirve para el par
            for i in range(sdl2.SDL_NumHaptics()):
                raw2 = sdl2.SDL_HapticName(i)
                nom = raw2.decode("utf-8", "replace").lower() if raw2 else ""
                if any(h in nom for h in cfg.WHEEL_NAME_HINTS):
                    hap = sdl2.SDL_HapticOpen(i)
                    del_volante = bool(hap)
                    if hap:
                        di("  (abierto POR INDICE: el juego usara esta via)")
                    break
            if hap is None and sdl2.SDL_NumHaptics() > 0:
                di("  NINGUN haptico corresponde al volante: los que hay son "
                   "de otros mandos.")
        if not hap:
            if hay_js:
                di(f"  SDL no consigue abrir ningun haptico del volante: "
                   f"{sdl2.SDL_GetError().decode()}")
        else:
            q = sdl2.SDL_HapticQuery(hap)
            constante = bool(q & sdl2.SDL_HAPTIC_CONSTANT)
            for nom, bit in (
                    ("fuerza constante (el par del volante)",
                     sdl2.SDL_HAPTIC_CONSTANT),
                    ("senoidal (texturas: asfalto, pianos)",
                     sdl2.SDL_HAPTIC_SINE),
                    ("muelle (autocentrado)", sdl2.SDL_HAPTIC_SPRING),
                    ("amortiguador", sdl2.SDL_HAPTIC_DAMPER)):
                di(f"    {'SI' if q & bit else 'no'}  {nom}")
            sdl2.SDL_HapticClose(hap)
        if js:
            sdl2.SDL_JoystickClose(js)

        # --- causas tipicas en Linux ---------------------------------------
        di("\n  Comprobaciones del sistema (Linux):")
        try:
            mods = open("/proc/modules").read()
            for m in ("hid_tmff2", "hid_thrustmaster", "ff_memless"):
                di(f"    modulo {m}: "
                   f"{'CARGADO' if m in mods else 'no cargado'}")
        except OSError:
            di("    (no se pudo leer /proc/modules)")

        # --- LA PRUEBA QUE DECIDE: que dice el NUCLEO, no SDL --------------
        # SDL puede no ver el haptico por mil motivos (nodo distinto, version
        # vieja de la biblioteca, permisos al arrancar). El nucleo, en cambio,
        # publica en /sys las capacidades reales del driver. Si aqui aparece
        # "fuerza constante", el force feedback EXISTE y el problema es solo
        # de camino: por eso el volante si tiene fuerza en los juegos de Steam.
        di("\n  Lo que dice el NUCLEO (/sys y /dev/input), al margen de SDL:")
        evs = ffb_evdev.listar()
        if not evs:
            di("    (no hay /dev/input/event*: ¿no es Linux?)")
        con_ff = [d for d in evs if d["ff"]]
        rw = sum(1 for d in evs if d["lectura"] and d["escritura"])
        di(f"    /dev/input/event*: {len(evs)} dispositivos, "
           f"{rw} con permiso de lectura+escritura")
        if not con_ff:
            di("    NINGUN dispositivo anuncia force feedback.")
        for d in con_ff:
            permisos = ("lectura+escritura" if d["escritura"]
                        else "SOLO LECTURA (no sirve para el FFB)")
            di(f"    {d['ruta']}  {d['nombre'] or '?'}  [{permisos}]")
            for e in ffb_evdev.efectos_de(d["ff"]):
                di(f"        SI  {e}")
        cand = ffb_evdev.buscar_volante(cfg.WHEEL_NAME_HINTS)

        # --- veredicto -----------------------------------------------------
        if hap and del_volante and constante:
            di("\n  HAY FORCE FEEDBACK por SDL: el juego lo usara.")
        elif cand is not None and cand["escritura"]:
            di("\n  HAY FORCE FEEDBACK, pero SDL no lo ve.")
            di(f"  El nucleo lo publica en {cand['ruta']} y el juego lo usara")
            di("  por la via directa de evdev (simulator/ffb_evdev.py), que es")
            di("  la misma que usan los juegos de Steam a traves de Proton.")
            v = ffb_evdev.VolanteEvdev(cand["ruta"], cand["ff"])
            di(f"  prueba de apertura: "
               f"{'CORRECTA' if v.ok else 'FALLO -> ' + v.motivo}")
            v.close()
        elif cand is not None:
            di("\n  El volante SI tiene force feedback, pero falta PERMISO de")
            di(f"  escritura sobre {cand['ruta']}. Anade tu usuario al grupo")
            di("  'input' y reinicia la sesion:")
            di("     sudo usermod -aG input $USER")
        else:
            di("\n  El volante NO expone force feedback al sistema.")
            di("  Si en los juegos de Steam SI hace fuerza, repite esta prueba")
            di("  con el volante encendido y sin Steam abierto: puede que otro")
            di("  proceso tenga tomado el dispositivo.")
            di("  Si tampoco lo hace en Steam, en una Steam Deck el T300RS")
            di("  necesita el modulo de kernel hid-tmff2 (fuera del kernel")
            di("  oficial), y hay que reinstalarlo tras cada actualizacion de")
            di("  SteamOS.")
        di()
        WheelInput._guardar_informe(L, "diagnostico_ffb.txt")

    @staticmethod
    def calibrar(indice=0, guardar=True):
        """Asistente de CALIBRACION: pide un mando cada vez y deduce el mapeo.

        Hace falta porque el mismo volante no numera los ejes igual en
        Windows (DirectInput) que en Linux (evdev), y porque los pedales
        pueden reposar en un extremo o en el otro. Mirar solo el recorrido
        total no basta: si se mueve todo a la vez, los cuatro ejes marcan el
        rango completo y no se distinguen. Aqui se mide POR SEPARADO:

          1. en reposo, para saber donde descansa cada eje;
          2. el volante;
          3. el acelerador;
          4. el freno.

        De ahi salen AXIS_STEERING, AXIS_THROTTLE, AXIS_BRAKE y
        PEDALS_INVERTED, que se guardan en settings.json."""
        import time
        from . import settings

        if sdl2.SDL_NumJoysticks() <= indice:
            print(f"No hay ningun dispositivo en el indice {indice}.")
            return
        js = sdl2.SDL_JoystickOpen(indice)
        if not js:
            print("No se pudo abrir:", sdl2.SDL_GetError().decode())
            return
        raw = sdl2.SDL_JoystickName(js)
        nombre = raw.decode("utf-8", "replace") if raw else "?"
        n = sdl2.SDL_JoystickNumAxes(js)

        def leer():
            sdl2.SDL_PumpEvents()
            sdl2.SDL_JoystickUpdate()
            return [sdl2.SDL_JoystickGetAxis(js, i) for i in range(n)]

        def fase(titulo, aviso, dur):
            """Mide dur segundos y devuelve, por eje, el valor mas alejado
            del reposo (con su signo) y cuanto se ha movido."""
            print(f"\n=== {titulo} ===\n{aviso}")
            for c in range(3, 0, -1):
                print(f"   empieza en {c}...", end="\r", flush=True)
                time.sleep(1.0)
            t0 = time.time()
            lo = [32767] * n
            hi = [-32768] * n
            while time.time() - t0 < dur:
                v = leer()
                for i in range(n):
                    lo[i] = min(lo[i], v[i])
                    hi[i] = max(hi[i], v[i])
                queda = dur - (time.time() - t0)
                print(f"   midiendo... {queda:3.0f} s   ", end="\r", flush=True)
                time.sleep(0.02)
            print("   hecho.                 ")
            return lo, hi

        print(f"\nCALIBRACION DE {nombre} ({n} ejes)\n"
              f"Sigue las instrucciones; cada paso avisa antes de empezar.")

        lo0, hi0 = fase("1/4  REPOSO",
                        "NO toques nada: suelta el volante y los pedales.", 3.0)
        reposo = [(lo0[i] + hi0[i]) // 2 for i in range(n)]

        def movimientos(lo, hi):
            """Cuanto se alejo del reposo CADA eje (para no ocultar nada)."""
            return [max(abs(hi[i] - reposo[i]), abs(lo[i] - reposo[i]))
                    for i in range(n)]

        def mas_movido(lo, hi, excluir):
            mov = movimientos(lo, hi)
            mejor, cual = 0, -1
            for i in range(n):
                if i in excluir:
                    continue
                if mov[i] > mejor:
                    mejor, cual = mov[i], i
            return cual, mejor

        detalle = []

        def anota(paso, lo, hi):
            mov = movimientos(lo, hi)
            detalle.append(f"  {paso:11} movimiento por eje: "
                           + "  ".join(f"eje{i}={mov[i]}" for i in range(n)))

        lo1, hi1 = fase("2/4  VOLANTE",
                        "Gira el volante a TOPE a un lado y a TOPE al otro.",
                        6.0)
        eje_v, mov_v = mas_movido(lo1, hi1, set())
        anota("VOLANTE", lo1, hi1)

        lo2, hi2 = fase("3/4  ACELERADOR",
                        "Pisa SOLO el acelerador a fondo y sueltalo. "
                        "No toques el volante.", 6.0)
        eje_a, mov_a = mas_movido(lo2, hi2, {eje_v})
        anota("ACELERADOR", lo2, hi2)

        lo3, hi3 = fase("4/4  FRENO",
                        "Pisa SOLO el freno a fondo y sueltalo. "
                        "No toques el volante.", 6.0)
        eje_f, mov_f = mas_movido(lo3, hi3, {eje_v, eje_a})
        anota("FRENO", lo3, hi3)

        # sentido de los pedales: si al pisar el valor BAJA respecto al
        # reposo, el pedal descansa arriba -> PEDALS_INVERTED = True
        def baja_al_pisar(lo, hi, eje):
            return abs(lo[eje] - reposo[eje]) > abs(hi[eje] - reposo[eje])

        inv = baja_al_pisar(lo2, hi2, eje_a) if eje_a >= 0 else cfg.PEDALS_INVERTED

        L = [f"{nombre}: {n} ejes", "",
             f"  reposo por eje: {reposo}", "",
             f"  VOLANTE     -> eje {eje_v}  (se movio {mov_v})",
             f"  ACELERADOR  -> eje {eje_a}  (se movio {mov_a})",
             f"  FRENO       -> eje {eje_f}  (se movio {mov_f})",
             f"  PEDALS_INVERTED = {inv}  "
             f"(en reposo el acelerador marca {reposo[eje_a] if eje_a >= 0 else '?'})",
             "",
             f"  antes: AXIS_STEERING={cfg.AXIS_STEERING}, "
             f"AXIS_THROTTLE={cfg.AXIS_THROTTLE}, AXIS_BRAKE={cfg.AXIS_BRAKE},"
             f" PEDALS_INVERTED={cfg.PEDALS_INVERTED}", "",
             "  Detalle (cuanto se alejo del reposo CADA eje en cada paso):"]
        L += detalle
        dudoso = [t for t, m in (("volante", mov_v), ("acelerador", mov_a),
                                 ("freno", mov_f)) if m < 8000]
        if dudoso:
            L.append(f"  AVISO: casi no se movio nada en: {', '.join(dudoso)}."
                     f" Repite la calibracion moviendo ese mando a fondo.")
        print("\n" + "\n".join(L))

        if guardar and not dudoso and -1 not in (eje_v, eje_a, eje_f):
            cfg.AXIS_STEERING = eje_v
            cfg.AXIS_THROTTLE = eje_a
            cfg.AXIS_BRAKE = eje_f
            cfg.PEDALS_INVERTED = bool(inv)
            for k in ("AXIS_STEERING", "AXIS_THROTTLE", "AXIS_BRAKE",
                      "PEDALS_INVERTED"):
                settings.record(k, getattr(cfg, k))
            settings.save()
            L.append("")
            L.append("  GUARDADO en settings.json: ya puedes jugar.")
            print("\n  GUARDADO en settings.json: ya puedes jugar.")
        sdl2.SDL_JoystickClose(js)
        WheelInput._guardar_informe(L, "diagnostico_calibracion.txt")

    @staticmethod
    def monitor_ejes(indice=0, segundos=0.0):
        """Monitor EN VIVO de ejes y botones, en la terminal.

        Sirve para averiguar el mapeo real del volante: el mismo aparato
        NO numera los ejes igual en Windows (DirectInput) que en Linux
        (evdev), y los pedales pueden reposar en un extremo o en el otro.
        Girando el volante y pisando cada pedal se ve al instante qué eje se
        mueve y en qué rango, que es justo lo que hay que poner en
        AXIS_STEERING / AXIS_THROTTLE / AXIS_BRAKE y PEDALS_INVERTED.

        Ctrl+C para salir."""
        import time
        if sdl2.SDL_NumJoysticks() <= indice:
            print(f"No hay ningun dispositivo en el indice {indice}.")
            return
        js = sdl2.SDL_JoystickOpen(indice)
        if not js:
            print("No se pudo abrir el dispositivo:",
                  sdl2.SDL_GetError().decode())
            return
        raw = sdl2.SDL_JoystickName(js)
        nombre = raw.decode("utf-8", "replace") if raw else "?"
        n_ejes = sdl2.SDL_JoystickNumAxes(js)
        n_bot = sdl2.SDL_JoystickNumButtons(js)
        print(f"\n{nombre}: {n_ejes} ejes, {n_bot} botones")
        if segundos > 0:
            print(f"Tienes {segundos:.0f} SEGUNDOS: gira el volante a los dos\n"
                  f"lados y pisa cada pedal por separado. Se para SOLO y\n"
                  f"guarda el informe (no hace falta Ctrl+C).\n")
        else:
            print("Gira el volante y pisa cada pedal por separado.\n"
                  "Para salir: Ctrl+C, o desde otra pestana de la terminal\n"
                  "'pkill -f simulator.main' (el teclado virtual de la Steam\n"
                  "Deck no tiene tecla Ctrl).\n")
        vmin = [32767] * n_ejes
        vmax = [-32768] * n_ejes
        t0 = time.time()
        try:
            while segundos <= 0 or time.time() - t0 < segundos:
                sdl2.SDL_PumpEvents()
                sdl2.SDL_JoystickUpdate()
                val = [sdl2.SDL_JoystickGetAxis(js, i) for i in range(n_ejes)]
                for i, v in enumerate(val):
                    vmin[i] = min(vmin[i], v)
                    vmax[i] = max(vmax[i], v)
                pulsados = [str(b) for b in range(n_bot)
                            if sdl2.SDL_JoystickGetButton(js, b)]
                lineas = []
                for i, v in enumerate(val):
                    ancho = 28
                    pos = int((v + 32768) / 65535.0 * (ancho - 1))
                    barra = "".join("#" if k == pos else "-"
                                    for k in range(ancho))
                    recorrido = vmax[i] - vmin[i]
                    marca = " <== SE MUEVE" if recorrido > 8000 else ""
                    lineas.append(f"  eje {i}: [{barra}] {v:+7d}  "
                                  f"visto {vmin[i]:+7d}..{vmax[i]:+7d}{marca}")
                if segundos > 0:
                    queda = max(0.0, segundos - (time.time() - t0))
                    pie = f"  quedan {queda:4.0f} s (se para solo)"
                else:
                    pie = ("  Ctrl+C para salir (o 'pkill -f simulator.main' "
                           "desde otra pestana).")
                print("\033[H\033[J" + f"{nombre}\n\n"
                      + "\n".join(lineas)
                      + f"\n\n  botones pulsados: "
                        f"{', '.join(pulsados) if pulsados else '-'}"
                      + "\n\n" + pie)
                time.sleep(0.08)
        except KeyboardInterrupt:
            pass
        finally:
            L = [f"{nombre}: {n_ejes} ejes, {n_bot} botones", "",
                 "Resumen del recorrido visto en cada eje:"]
            for i in range(n_ejes):
                rec = vmax[i] - vmin[i]
                pista = ""
                if rec > 8000:
                    if vmin[i] > -20000:
                        pista = ("  (reposa en un extremo: es un PEDAL; "
                                 "mira PEDALS_INVERTED)")
                    else:
                        pista = "  (recorre los dos lados: puede ser el VOLANTE)"
                L.append(f"  eje {i}: {vmin[i]:+7d} .. {vmax[i]:+7d}"
                         f"  recorrido {rec}{pista}")
            L.append("")
            L.append(f"  configuracion actual: AXIS_STEERING="
                     f"{cfg.AXIS_STEERING}, AXIS_THROTTLE={cfg.AXIS_THROTTLE},"
                     f" AXIS_BRAKE={cfg.AXIS_BRAKE}, PEDALS_INVERTED="
                     f"{cfg.PEDALS_INVERTED}")
            print("\n" + "\n".join(L[2:]))
            sdl2.SDL_JoystickClose(js)
            WheelInput._guardar_informe(L, "diagnostico_ejes.txt")

    def _open_device(self):
        modo = str(getattr(cfg, "INPUT_MODE", "auto")).lower()
        if modo == "teclado":
            return                              # no se abre ningun dispositivo

        count = sdl2.SDL_NumJoysticks()
        volante = pad = -1
        for i in range(count):
            raw = sdl2.SDL_JoystickNameForIndex(i)
            name = raw.decode("utf-8", "replace").lower() if raw else ""
            if any(h in name for h in cfg.WHEEL_NAME_HINTS):
                volante = i
            if pad < 0 and sdl2.SDL_IsGameController(i):
                pad = i
        if volante < 0:
            # 2) sin coincidencia por NOMBRE: un dispositivo que SDL no
            # reconoce como gamepad y que tiene ejes y botones de sobra es,
            # casi con seguridad, un volante (un volante con pedales expone
            # 3-4 ejes; los mandos conocidos SI se reconocen como gamepad,
            # asi que no se cuelan aqui). Cubre volantes que no estan en
            # WHEEL_NAME_HINTS.
            for i in range(count):
                if sdl2.SDL_IsGameController(i):
                    continue
                js = sdl2.SDL_JoystickOpen(i)
                if not js:
                    continue
                ejes = sdl2.SDL_JoystickNumAxes(js)
                botones = sdl2.SDL_JoystickNumButtons(js)
                sdl2.SDL_JoystickClose(js)
                if ejes >= 3 and botones >= 4:
                    volante = i
                    break

        pad_disponible = pad          # se conserva para la navegacion
        if modo == "volante":
            # forzar VOLANTE: el primer dispositivo (o el que coincida por
            # nombre). Util si el volante no esta en WHEEL_NAME_HINTS.
            volante = volante if volante >= 0 else (0 if count > 0 else -1)
            pad = -1
        elif modo == "mando":
            # forzar MANDO: solo si SDL lo reconoce como game controller.
            # Un mando sin mapeo (p.ej. la Deck fuera de Steam) NO se puede
            # leer bien como gamepad; en ese caso se avisa y se cae a teclado
            # en vez de fingir un volante con los pedales al reves.
            volante = -1
            if pad < 0:
                print("AVISO: se pidio --mando pero SDL no reconoce ningun "
                      "gamepad.\n  En una Steam Deck, LANZA EL JUEGO DESDE "
                      "STEAM (Steam Input lo\n  convierte en un mando de "
                      "Xbox). Por ahora, teclado.")
        else:  # "auto"
            # un VOLANTE reconocido manda; si no, un mando reconocido; y solo
            # si NO hay nada reconocido se prueba el primero como volante
            if volante < 0 and pad < 0 and count > 0:
                volante = 0

        if volante >= 0:
            self.joystick = sdl2.SDL_JoystickOpen(volante)
            self.kind = VOLANTE if self.joystick else TECLADO
        elif pad >= 0:
            self.controller = sdl2.SDL_GameControllerOpen(pad)
            if self.controller:
                self.joystick = sdl2.SDL_GameControllerGetJoystick(
                    self.controller)
                self.kind = MANDO
        if self.joystick:
            raw = sdl2.SDL_JoystickName(self.joystick)
            self.name = raw.decode("utf-8", "replace") if raw else "?"
            self.num_axes = sdl2.SDL_JoystickNumAxes(self.joystick)
            self.num_buttons = sdl2.SDL_JoystickNumButtons(self.joystick)
            self.num_hats = sdl2.SDL_JoystickNumHats(self.joystick)
        # Con un VOLANTE conectado el juego abria SOLO el volante, asi que en
        # una Steam Deck sus propios mandos quedaban muertos: no habia forma
        # de moverse por el menu (el volante tampoco lo movia). Se abre
        # ademas, si existe, un gamepad como mando SECUNDARIO de navegacion.
        if self.kind == VOLANTE and pad_disponible >= 0 \
                and pad_disponible != volante:
            self.pad_nav = sdl2.SDL_GameControllerOpen(pad_disponible)

    @property
    def connected(self) -> bool:
        return self.joystick is not None

    @property
    def es_mando(self) -> bool:
        return self.kind == MANDO

    # ------------------------------------------------------------------
    def raw_axes(self):
        if not self.joystick:
            return []
        return [sdl2.SDL_JoystickGetAxis(self.joystick, i)
                for i in range(self.num_axes)]

    def pressed_buttons(self):
        if not self.joystick:
            return []
        return [i for i in range(self.num_buttons)
                if sdl2.SDL_JoystickGetButton(self.joystick, i)]

    def button_pressed_edge(self, button: int) -> bool:
        """True solo en el flanco de pulsación (para las levas)."""
        if not self.joystick:
            return False
        now = bool(sdl2.SDL_JoystickGetButton(self.joystick, button))
        prev = self._prev_buttons.get(button, False)
        self._prev_buttons[button] = now
        return now and not prev

    def action_edge(self, accion: str) -> bool:
        """Flanco de pulsación de una ACCION del juego, venga del botón que
        venga. Así main.py no tiene que saber si hay volante o mando."""
        if self.kind == MANDO and self.controller:
            btn = _PAD_BOTONES.get(accion)
            now = bool(sdl2.SDL_GameControllerGetButton(self.controller, btn)) \
                if btn is not None else False
        elif self.kind == VOLANTE:
            btn = getattr(cfg, "BUTTON_" + accion.upper(), None)
            now = bool(sdl2.SDL_JoystickGetButton(self.joystick, btn)) \
                if btn is not None and btn < self.num_buttons else False
            # con volante, los botones de la Deck (mando secundario) siguen
            # sirviendo para las acciones del HUD
            nav = getattr(self, "pad_nav", None)
            if nav and not now:
                b2 = _PAD_BOTONES.get(accion)
                if b2 is not None:
                    now = bool(sdl2.SDL_GameControllerGetButton(nav, b2))
        else:
            return False
        prev = self._prev_acciones.get(accion, False)
        self._prev_acciones[accion] = now
        return now and not prev

    def menu_nav(self, dt=0.0):
        """Navegación de menús con el MANDO: devuelve el conjunto de
        acciones activas este frame entre {up, down, left, right, ok, back}.
        Sin esto, en una Steam Deck lanzada desde Steam el juego recibe un
        gamepad pero el MENU solo escucha el teclado, asi que el usuario se
        queda atascado en la seleccion sin poder elegir coche ni empezar.

        Se leen la cruceta Y el stick izquierdo. Las DIRECCIONES tienen
        auto-repeticion: al mantenerlas, tras una pausa breve se repiten
        solas (mover rapido por una lista larga); ok/back son solo flanco."""
        estado = {k: False for k in ("up", "down", "left", "right", "ok",
                                     "back", "def", "reset")}
        # --- mando (el principal si es MANDO, o el secundario de la Deck) ---
        c = self.controller if (self.kind == MANDO and self.controller) \
            else getattr(self, "pad_nav", None)
        if c:
            sdl2.SDL_GameControllerUpdate()

            def boton(b):
                return bool(sdl2.SDL_GameControllerGetButton(c, b))

            lx = _axis_to_norm(sdl2.SDL_GameControllerGetAxis(
                c, sdl2.SDL_CONTROLLER_AXIS_LEFTX))
            ly = _axis_to_norm(sdl2.SDL_GameControllerGetAxis(
                c, sdl2.SDL_CONTROLLER_AXIS_LEFTY))
            dz = 0.6                    # umbral alto: solo empujes claros
            estado.update({
                "up": boton(sdl2.SDL_CONTROLLER_BUTTON_DPAD_UP) or ly < -dz,
                "down": boton(sdl2.SDL_CONTROLLER_BUTTON_DPAD_DOWN) or ly > dz,
                "left": boton(sdl2.SDL_CONTROLLER_BUTTON_DPAD_LEFT) or lx < -dz,
                "right": boton(sdl2.SDL_CONTROLLER_BUTTON_DPAD_RIGHT) or lx > dz,
                "ok": boton(sdl2.SDL_CONTROLLER_BUTTON_A)
                or boton(sdl2.SDL_CONTROLLER_BUTTON_START),
                "back": boton(sdl2.SDL_CONTROLLER_BUTTON_B),
                "def": boton(sdl2.SDL_CONTROLLER_BUTTON_X),
                "reset": boton(sdl2.SDL_CONTROLLER_BUTTON_Y),
            })
        # --- VOLANTE: cruceta del aro, giro del volante y levas -------------
        if self.kind == VOLANTE and self.joystick:
            sdl2.SDL_JoystickUpdate()
            h = sdl2.SDL_JoystickGetHat(self.joystick, 0) \
                if getattr(self, "num_hats", 0) > 0 else 0

            def bt(nombre):
                b = getattr(cfg, "BUTTON_" + nombre, None)
                return (b is not None and b < self.num_buttons
                        and bool(sdl2.SDL_JoystickGetButton(self.joystick, b)))

            # girar el volante mueve a izquierda/derecha (cambia el valor)
            vol = _axis_to_norm(sdl2.SDL_JoystickGetAxis(
                self.joystick, cfg.AXIS_STEERING)) \
                if cfg.AXIS_STEERING < self.num_axes else 0.0
            estado["up"] |= bool(h & sdl2.SDL_HAT_UP) or bt("TOGGLE_VIEW")
            estado["down"] |= bool(h & sdl2.SDL_HAT_DOWN) or bt("TOGGLE_AUTO")
            estado["left"] |= bool(h & sdl2.SDL_HAT_LEFT)
            estado["right"] |= bool(h & sdl2.SDL_HAT_RIGHT)
            estado["ok"] |= bt("SHIFT_UP")        # leva derecha = ENTER
            estado["back"] |= bt("SHIFT_DOWN")    # leva izquierda = ESC
            # El giro del volante da UN paso por giro, y hay que volver al
            # centro para dar otro: NO se repite mientras se mantiene girado.
            # Con repeticion, al salir al menu con el volante girado (o si
            # se queda girado por el force feedback) las opciones cambiaban
            # sin parar hasta centrarlo.
            zona = getattr(self, "_vol_zona", 0)
            paso_vol = None
            if abs(vol) < 0.25:
                zona = 0
            elif vol > 0.45 and zona == 0:
                zona, paso_vol = 1, "right"
            elif vol < -0.45 and zona == 0:
                zona, paso_vol = -1, "left"
            self._vol_zona = zona
        else:
            paso_vol = None
        out = set()
        if paso_vol:
            out.add(paso_vol)
        _DELAY, _INT = 0.35, 0.06       # pausa inicial y ritmo de repeticion
        for k, v in estado.items():
            prev = self._prev_menu.get(k, False)
            if v and not prev:
                out.add(k)              # flanco: siempre dispara
                self._rep[k] = -_DELAY
            elif v and prev and k in ("up", "down", "left", "right"):
                self._rep[k] = self._rep.get(k, 0.0) + dt
                if self._rep[k] >= 0.0:
                    out.add(k)          # repeticion al mantener
                    self._rep[k] -= _INT
            elif not v:
                self._rep[k] = 0.0
        self._prev_menu = estado
        return out

    def _leer_mando(self, speed_kmh: float, dt: float):
        """Lee el mando: stick izquierdo a la dirección (pasando por
        curva_direccion) y gatillos analógicos a los pedales."""
        def eje(a):
            return sdl2.SDL_GameControllerGetAxis(self.controller, a)

        self.steering = curva_direccion(
            _axis_to_norm(eje(sdl2.SDL_CONTROLLER_AXIS_LEFTX)),
            speed_kmh, self.steering, dt)

        # gatillos ANALOGICOS: 0..32767, dosificación real de gas y freno
        self.throttle = max(0.0, min(1.0, eje(
            sdl2.SDL_CONTROLLER_AXIS_TRIGGERRIGHT) / 32767.0))
        self.brake = max(0.0, min(1.0, eje(
            sdl2.SDL_CONTROLLER_AXIS_TRIGGERLEFT) / 32767.0))
        self.clutch = 0.0

    def update(self, keys, speed_kmh: float = 0.0, dt: float = 1.0 / 60.0):
        """Actualiza el estado. `keys` es el array de SDL_GetKeyboardState
        para el fallback de teclado; `speed_kmh` solo lo usa el mando, para
        cerrar el tope de dirección con la velocidad."""
        sdl2.SDL_JoystickUpdate()
        if self.kind == MANDO and self.controller:
            sdl2.SDL_GameControllerUpdate()
            self._leer_mando(speed_kmh, dt)
        elif self.joystick:
            def axis(i):
                return sdl2.SDL_JoystickGetAxis(self.joystick, i) if i < self.num_axes else 0

            s = _axis_to_norm(axis(cfg.AXIS_STEERING))
            if abs(s) < cfg.STEERING_DEADZONE:
                s = 0.0
            self.steering = s
            self.throttle = _pedal_to_norm(axis(cfg.AXIS_THROTTLE)) if cfg.AXIS_THROTTLE < self.num_axes else 0.0
            self.brake = _pedal_to_norm(axis(cfg.AXIS_BRAKE)) if cfg.AXIS_BRAKE < self.num_axes else 0.0
            self.clutch = _pedal_to_norm(axis(cfg.AXIS_CLUTCH)) if cfg.AXIS_CLUTCH < self.num_axes else 0.0
        else:
            # Teclado: flechas para conducir
            target = 0.0
            if keys[sdl2.SDL_SCANCODE_LEFT]:
                target -= 0.5
            if keys[sdl2.SDL_SCANCODE_RIGHT]:
                target += 0.5
            self.steering += (target - self.steering) * 0.15
            self.throttle = 1.0 if keys[sdl2.SDL_SCANCODE_UP] else 0.0
            self.brake = 1.0 if keys[sdl2.SDL_SCANCODE_DOWN] else 0.0

    def close(self):
        if self.pad_nav:
            sdl2.SDL_GameControllerClose(self.pad_nav)
            self.pad_nav = None
        if self.controller:
            sdl2.SDL_GameControllerClose(self.controller)
            self.controller = None
            self.joystick = None      # lo cierra el propio GameController
        elif self.joystick:
            sdl2.SDL_JoystickClose(self.joystick)
            self.joystick = None


class ForceFeedback:
    """Gestión de los efectos hápticos DirectInput a través de SDL."""

    def __init__(self, wheel: WheelInput):
        self.haptic = None
        self.ok = False
        self.supports = 0
        self._ids = {}
        self._effects = {}
        self._jolt_timer = 0.0
        self.pad = None            # mando: vibración en vez de par
        self.evdev = None          # vía directa a /dev/input (Linux)
        if not cfg.FFB_ENABLED or not wheel.connected:
            return
        if wheel.es_mando:
            # Un mando no puede transmitir el par de la dirección, pero SI
            # puede vibrar. Se traduce lo que MAS informa al conducir: el
            # deslizamiento de los neumáticos y los golpes de piano/hierba.
            # No es force feedback, pero da la información esencial.
            self.pad = wheel.controller
            self.ok = bool(cfg.PAD_RUMBLE)
            return
        self.haptic = sdl2.SDL_HapticOpenFromJoystick(wheel.joystick)
        if not self.haptic:
            # RESPALDO: en Linux el volante puede exponer el force feedback en
            # un nodo de /dev/input DISTINTO del que da los ejes. Entonces
            # SDL_JoystickIsHaptic dice NO y esta llamada falla, aunque
            # SDL_NumHaptics() vea el aparato perfectamente. Pasaba en la
            # Steam Deck con el T300RS: "hapticos que ve SDL: 1" y aun asi
            # sin fuerza. Se busca el haptico POR INDICE, prefiriendo el que
            # se llame como el volante.
            # DOS condiciones, las dos imprescindibles: que se llame como un
            # volante Y que sepa hacer FUERZA CONSTANTE (el par de la
            # direccion). Sin la segunda se colaba el mando de la propia
            # Steam Deck ("Microsoft X-Box 360 pad"), que es haptico pero solo
            # vibra: el juego creia tener force feedback y no habia ninguno.
            for i in range(sdl2.SDL_NumHaptics()):
                raw = sdl2.SDL_HapticName(i)
                nom = raw.decode("utf-8", "replace").lower() if raw else ""
                if not any(h in nom for h in cfg.WHEEL_NAME_HINTS):
                    continue
                h = sdl2.SDL_HapticOpen(i)
                if not h:
                    continue
                if sdl2.SDL_HapticQuery(h) & sdl2.SDL_HAPTIC_CONSTANT:
                    self.haptic = h
                    print(f"FFB: haptico abierto por indice {i} ({nom})")
                    break
                sdl2.SDL_HapticClose(h)
        if not self.haptic:
            # ULTIMO RECURSO, y en la Steam Deck el que de verdad funciona:
            # hablar con evdev directamente. Si los juegos de Steam mueven el
            # volante en esta misma maquina es que el nucleo SI publica el
            # force feedback; lo que falla es el camino de SDL. Ver
            # simulator/ffb_evdev.py.
            self.evdev = self._abrir_evdev() or self._abrir_hidraw()
            if self.evdev is not None:
                self.evdev.autocentrado(0.0)
                self.evdev.ganancia(1.0)
                self.ok = True
            return
        self.supports = sdl2.SDL_HapticQuery(self.haptic)
        # desactivar el autocentrado del driver: lo sustituye nuestra física
        if self.supports & sdl2.SDL_HAPTIC_AUTOCENTER:
            sdl2.SDL_HapticSetAutocenter(self.haptic, 0)
        if self.supports & sdl2.SDL_HAPTIC_GAIN:
            sdl2.SDL_HapticSetGain(self.haptic, 100)
        self._create_effects()
        self.ok = self._ids.get("constant") is not None

    # ------------------------------------------------------------------
    @staticmethod
    def _abrir_evdev():
        """Abre el force feedback del volante por evdev, o None."""
        if not ffb_evdev.disponible():
            return None
        d = ffb_evdev.buscar_volante(cfg.WHEEL_NAME_HINTS)
        if d is None:
            return None
        v = ffb_evdev.VolanteEvdev(d["ruta"], d["ff"])
        if not v.ok:
            print(f"FFB: {d['ruta']} anuncia fuerza pero no se pudo usar: "
                  f"{v.motivo}")
            v.close()
            return None
        print(f"FFB por evdev en {d['ruta']} ({v.nombre})")
        return v

    @staticmethod
    def _abrir_hidraw():
        """Ultimo recurso: mandar la fuerza como informes HID de salida.

        Es lo que pasa en la Steam Deck con el T300RS. El nucleo lo toma con
        hid-generic, que NO implementa force feedback, asi que por evdev no
        hay nada. Pero el driver hid-tmff2 tampoco hace magia: escribe unos
        paquetes concretos en el canal de salida del volante, y ese canal
        esta abierto en /dev/hidraw. Ver simulator/ffb_t300rs.py.

        DESACTIVADA por defecto: en la prueba real el volante no se movio y
        se le apago el LED, asi que escribir ahi puede dejarlo colgado. Hasta
        aclarar el identificador del informe de salida, el juego NO toca el
        volante por esta via. Se activa a mano con FFB_HIDRAW_EXPERIMENTAL."""
        if not getattr(cfg, "FFB_HIDRAW_EXPERIMENTAL", False):
            return None
        if not ffb_evdev.disponible():
            return None
        info = ffb_t300rs.buscar(ffb_evdev.hidraws())
        if info is None:
            return None
        if not info["escritura"]:
            print(f"FFB: {info['ruta']} es del volante pero no se puede "
                  f"escribir en el (grupo 'input').")
            return None
        v = ffb_t300rs.VolanteT300RS(info)
        if not v.ok:
            print(f"FFB: {info['ruta']} no acepto los efectos: {v.motivo}")
            v.close()
            return None
        print(f"FFB por HID en {info['ruta']} ({info['modelo']}, "
              f"informe 0x{info['informe']:02x})")
        return v

    # -- envío de los efectos, por SDL o por evdev ----------------------
    def _set_constante(self, nivel):
        if self.evdev is not None:
            self.evdev.constante(nivel)
            return
        eff = self._effects.get("constant")
        if eff is not None:
            eff.constant.level = int(nivel * 32767)
            self._update("constant")

    def _set_textura(self, magnitud, periodo_ms):
        if self.evdev is not None:
            self.evdev.textura(magnitud, periodo_ms)
            return
        eff = self._effects.get("rumble")
        if eff is not None:
            eff.periodic.magnitude = int(max(0.0, min(1.0, magnitud)) * 32767)
            eff.periodic.period = periodo_ms
            self._update("rumble")

    def _set_condicion(self, clave, coef):
        if self.evdev is not None:
            self.evdev.condicion(clave, coef)
            return
        eff = self._effects.get(clave)
        if eff is not None:
            c = int(coef * 0x7FFF)
            eff.condition.right_coeff[0] = c
            eff.condition.left_coeff[0] = c
            self._update(clave)

    # ------------------------------------------------------------------
    def _new_effect(self, key, effect):
        eid = sdl2.SDL_HapticNewEffect(self.haptic, ctypes.byref(effect))
        if eid >= 0:
            self._ids[key] = eid
            self._effects[key] = effect
            sdl2.SDL_HapticRunEffect(self.haptic, eid, sdl2.SDL_HAPTIC_INFINITY)

    def _create_effects(self):
        # --- fuerza constante (par de dirección) -----------------------
        if self.supports & sdl2.SDL_HAPTIC_CONSTANT:
            e = sdl2.SDL_HapticEffect()
            e.type = sdl2.SDL_HAPTIC_CONSTANT
            e.constant.direction.type = sdl2.SDL_HAPTIC_CARTESIAN
            e.constant.direction.dir[0] = 1
            e.constant.length = sdl2.SDL_HAPTIC_INFINITY
            e.constant.level = 0
            self._new_effect("constant", e)

        # --- muelle de centrado ---------------------------------------
        if self.supports & sdl2.SDL_HAPTIC_SPRING:
            e = sdl2.SDL_HapticEffect()
            e.type = sdl2.SDL_HAPTIC_SPRING
            e.condition.length = sdl2.SDL_HAPTIC_INFINITY
            e.condition.right_sat[0] = 0xFFFF
            e.condition.left_sat[0] = 0xFFFF
            e.condition.right_coeff[0] = 0
            e.condition.left_coeff[0] = 0
            self._new_effect("spring", e)

        # --- amortiguador ---------------------------------------------
        if self.supports & sdl2.SDL_HAPTIC_DAMPER:
            e = sdl2.SDL_HapticEffect()
            e.type = sdl2.SDL_HAPTIC_DAMPER
            e.condition.length = sdl2.SDL_HAPTIC_INFINITY
            e.condition.right_sat[0] = 0xFFFF
            e.condition.left_sat[0] = 0xFFFF
            e.condition.right_coeff[0] = 0
            e.condition.left_coeff[0] = 0
            self._new_effect("damper", e)

        # --- vibración senoidal (texturas) -----------------------------
        if self.supports & sdl2.SDL_HAPTIC_SINE:
            e = sdl2.SDL_HapticEffect()
            e.type = sdl2.SDL_HAPTIC_SINE
            e.periodic.direction.type = sdl2.SDL_HAPTIC_CARTESIAN
            e.periodic.direction.dir[0] = 1
            e.periodic.length = sdl2.SDL_HAPTIC_INFINITY
            e.periodic.period = 50
            e.periodic.magnitude = 0
            self._new_effect("rumble", e)

    def _update(self, key):
        eid = self._ids.get(key)
        if eid is not None:
            sdl2.SDL_HapticUpdateEffect(self.haptic, eid,
                                        ctypes.byref(self._effects[key]))

    # ------------------------------------------------------------------
    def notify_gear_shift(self):
        self._jolt_timer = 0.10

    def _update_pad(self, dt: float, car_state, surface: str, speed_ms: float):
        """Vibración de un mando. Los dos motores se usan para cosas
        distintas, que es lo que los hace legibles:
          - motor BAJO (izquierdo): el eje que está perdiendo agarre. Es el
            aviso de subviraje/sobreviraje que en el volante llega como
            aligeramiento del par.
          - motor ALTO (derecho): textura del suelo (pianos, hierba) y el
            golpe seco del cambio de marcha.
        """
        st = car_state
        derrape = max(st.understeer, st.oversteer)
        bajo = min(1.0, derrape * cfg.PAD_RUMBLE_SLIP)
        alto = 0.0
        if surface == "kerb":
            alto = cfg.FFB_KERB_MAGNITUDE
        elif surface == "grass":
            alto = cfg.FFB_GRASS_MAGNITUDE
        alto *= min(1.0, speed_ms / 12.0)
        if self._jolt_timer > 0.0:
            self._jolt_timer -= dt
            alto = max(alto, cfg.FFB_SHIFT_JOLT)
        g = cfg.PAD_RUMBLE
        sdl2.SDL_GameControllerRumble(
            self.pad, int(max(0.0, min(1.0, bajo * g)) * 65535),
            int(max(0.0, min(1.0, alto * g)) * 65535), 120)

    def update(self, dt: float, car_state, surface: str, speed_ms: float):
        """Recalcula y envía los efectos al volante. Llamar cada frame."""
        if self.pad is not None:
            self._update_pad(dt, car_state, surface, speed_ms)
            return
        if not self.ok:
            return

        # --- par principal --------------------------------------------
        # Signo: probado en el T300RS, un nivel DirectInput positivo
        # empuja el volante en el sentido que ayuda a girar; el par de
        # autoalineado debe RESISTIRSE al giro (como en un coche real:
        # el volante pesa hacia el centro), así que se invierte aquí.
        # Si en otro volante saliera al revés, FFB_INVERT lo deshace.
        torque_norm = -car_state.steer_column_torque / cfg.FFB_MAX_TORQUE_NM
        level = torque_norm * cfg.FFB_GAIN
        # sacudida breve al cambiar de marcha
        if self._jolt_timer > 0.0:
            self._jolt_timer -= dt
            level += cfg.FFB_SHIFT_JOLT * (1.0 if int(self._jolt_timer * 100) % 2 else -1.0)
        if cfg.FFB_INVERT:
            level = -level
        level = max(-1.0, min(1.0, level))
        self._set_constante(level)

        # --- muelle y amortiguador según velocidad ---------------------
        low = max(0.0, 1.0 - speed_ms / 8.0)   # 1 parado -> 0 a 8 m/s
        self._set_condicion("spring", cfg.FFB_SPRING_LOWSPEED * low)
        self._set_condicion("damper",
                            cfg.FFB_DAMPER_HIGHSPEED +
                            (cfg.FFB_DAMPER_LOWSPEED -
                             cfg.FFB_DAMPER_HIGHSPEED) * low)

        # --- texturas --------------------------------------------------
        mag = 0.0
        period_ms = 50
        if getattr(car_state, "abs_active", False):
            # pulsación del ABS en el volante
            mag = 0.30
            period_ms = 35
        elif surface == "kerb":
            mag = cfg.FFB_KERB_MAGNITUDE
            period_ms = max(8, int(1000.0 / max(8.0, speed_ms * 3.0)))
        elif surface == "grass":
            mag = cfg.FFB_GRASS_MAGNITUDE * min(1.0, speed_ms / 10.0)
            period_ms = 45
        elif speed_ms > 5.0:
            # textura del asfalto, AMPLIFICADA en las zonas de firme rugoso o
            # dañado (road_roughness): en un parche roto el volante rasca más
            rough = getattr(car_state, "road_roughness", 0.0)
            mag = cfg.FFB_ROAD_TEXTURE * min(1.0, speed_ms / 40.0) * (1.0 + 4.0 * rough)
            period_ms = max(8, int(600.0 / max(5.0, speed_ms)))
        else:
            # vibración del motor al ralentí
            mag = cfg.FFB_ENGINE_IDLE
            period_ms = int(60000.0 / max(600.0, car_state.rpm) * 2.0)
        self._set_textura(mag, period_ms)

    def still(self):
        """Deja el volante en reposo (par y vibración a cero) sin cerrar los
        efectos: para los menús, entre tandas."""
        if self.pad is not None:
            sdl2.SDL_GameControllerRumble(self.pad, 0, 0, 0)
            return
        self._set_constante(0.0)
        self._set_textura(0.0, 50)

    def close(self):
        if self.pad is not None:
            sdl2.SDL_GameControllerRumble(self.pad, 0, 0, 0)
            self.pad = None
            return
        if self.evdev is not None:
            self.evdev.close()
            self.evdev = None
            self.ok = False
            return
        if self.haptic:
            for eid in self._ids.values():
                sdl2.SDL_HapticDestroyEffect(self.haptic, eid)
            sdl2.SDL_HapticClose(self.haptic)
            self.haptic = None
            self.ok = False
