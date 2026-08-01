"""Entrada del volante Thrustmaster y force feedback.

Usa el subsistema de joystick y háptico de SDL2, que en Windows se apoya en
DirectInput: el mismo API que usan los juegos de conducción para el force
feedback de los volantes Thrustmaster.

Efectos utilizados:
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


def _axis_to_norm(raw: int) -> float:
    return max(-1.0, min(1.0, raw / 32767.0))


def _pedal_to_norm(raw: int) -> float:
    v = raw / 32767.0
    if cfg.PEDALS_INVERTED:
        return max(0.0, min(1.0, (1.0 - v) * 0.5))
    return max(0.0, min(1.0, (v + 1.0) * 0.5))


class WheelInput:
    """Lectura del volante/pedales con fallback a teclado."""

    def __init__(self):
        self.joystick = None
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

    def _open_device(self):
        count = sdl2.SDL_NumJoysticks()
        chosen = -1
        for i in range(count):
            name = sdl2.SDL_JoystickNameForIndex(i)
            name = name.decode("utf-8", "replace").lower() if name else ""
            if any(h in name for h in cfg.WHEEL_NAME_HINTS):
                chosen = i
                break
        if chosen < 0 and count > 0:
            chosen = 0
        if chosen >= 0:
            self.joystick = sdl2.SDL_JoystickOpen(chosen)
        if self.joystick:
            raw = sdl2.SDL_JoystickName(self.joystick)
            self.name = raw.decode("utf-8", "replace") if raw else "?"
            self.num_axes = sdl2.SDL_JoystickNumAxes(self.joystick)
            self.num_buttons = sdl2.SDL_JoystickNumButtons(self.joystick)

    @property
    def connected(self) -> bool:
        return self.joystick is not None

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

    def update(self, keys):
        """Actualiza el estado. `keys` es el array de SDL_GetKeyboardState
        para el fallback de teclado (flechas)."""
        sdl2.SDL_JoystickUpdate()
        if self.joystick:
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
        if self.joystick:
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
        if not cfg.FFB_ENABLED or not wheel.connected:
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

    def update(self, dt: float, car_state, surface: str, speed_ms: float):
        """Recalcula y envía los efectos al volante. Llamar cada frame."""
        if not self.ok:
            return

        # --- par principal --------------------------------------------
        torque_norm = car_state.steer_column_torque / cfg.FFB_MAX_TORQUE_NM
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
        if surface == "kerb":
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

    def close(self):
        if self.haptic:
            for eid in self._ids.values():
                sdl2.SDL_HapticDestroyEffect(self.haptic, eid)
            sdl2.SDL_HapticClose(self.haptic)
            self.haptic = None
            self.ok = False
