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

import sdl2

from . import config as cfg

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
        self._open_device()
        # estado normalizado
        self.steering = 0.0
        self.throttle = 0.0
        self.brake = 0.0
        self.clutch = 0.0
        self._prev_buttons = {}
        self._prev_acciones = {}

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
        else:
            return False
        prev = self._prev_acciones.get(accion, False)
        self._prev_acciones[accion] = now
        return now and not prev

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
        eff = self._effects.get("constant")
        if eff is not None:
            eff.constant.level = int(level * 32767)
            self._update("constant")

        # --- muelle y amortiguador según velocidad ---------------------
        low = max(0.0, 1.0 - speed_ms / 8.0)   # 1 parado -> 0 a 8 m/s
        spring = cfg.FFB_SPRING_LOWSPEED * low
        damper = cfg.FFB_DAMPER_HIGHSPEED + \
            (cfg.FFB_DAMPER_LOWSPEED - cfg.FFB_DAMPER_HIGHSPEED) * low
        eff = self._effects.get("spring")
        if eff is not None:
            c = int(spring * 0x7FFF)
            eff.condition.right_coeff[0] = c
            eff.condition.left_coeff[0] = c
            self._update("spring")
        eff = self._effects.get("damper")
        if eff is not None:
            c = int(damper * 0x7FFF)
            eff.condition.right_coeff[0] = c
            eff.condition.left_coeff[0] = c
            self._update("damper")

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
            mag = cfg.FFB_ROAD_TEXTURE * min(1.0, speed_ms / 40.0)
            period_ms = max(10, int(600.0 / max(5.0, speed_ms)))
        else:
            # vibración del motor al ralentí
            mag = cfg.FFB_ENGINE_IDLE
            period_ms = int(60000.0 / max(600.0, car_state.rpm) * 2.0)
        eff = self._effects.get("rumble")
        if eff is not None:
            eff.periodic.magnitude = int(max(0.0, min(1.0, mag)) * 32767)
            eff.periodic.period = period_ms
            self._update("rumble")

    def still(self):
        """Deja el volante en reposo (par y vibración a cero) sin cerrar los
        efectos: para los menús, entre tandas."""
        if self.pad is not None:
            sdl2.SDL_GameControllerRumble(self.pad, 0, 0, 0)
            return
        eff = self._effects.get("constant")
        if eff is not None:
            eff.constant.level = 0
            self._update("constant")
        eff = self._effects.get("rumble")
        if eff is not None:
            eff.periodic.magnitude = 0
            self._update("rumble")

    def close(self):
        if self.pad is not None:
            sdl2.SDL_GameControllerRumble(self.pad, 0, 0, 0)
            self.pad = None
            return
        if self.haptic:
            for eid in self._ids.values():
                sdl2.SDL_HapticDestroyEffect(self.haptic, eid)
            sdl2.SDL_HapticClose(self.haptic)
            self.haptic = None
            self.ok = False
