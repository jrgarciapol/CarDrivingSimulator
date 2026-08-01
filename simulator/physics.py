"""Modelo físico del vehículo.

Modelo de bicicleta (2 GDL laterales + longitudinal) con:
  - neumáticos con curva de deriva tipo Pacejka simplificada y saturación,
  - transferencia de carga longitudinal (frenar carga el eje delantero),
  - círculo de fricción en el eje motriz (trasero),
  - motor con curva de par, limitador y caja de 6 marchas + marcha atrás,
  - cálculo del par de autoalineado en la columna para el force feedback.
"""

import math

from . import config as cfg

G = 9.81


def engine_torque(rpm: float) -> float:
    """Curva de par del motor en Nm."""
    if rpm < 1000.0:
        return 150.0
    if rpm < 4200.0:
        # sube de 150 a 320 Nm
        return 150.0 + (320.0 - 150.0) * (rpm - 1000.0) / 3200.0
    if rpm < cfg.ENGINE_REDLINE_RPM:
        # cae suavemente hasta 240 Nm en el corte
        t = (rpm - 4200.0) / (cfg.ENGINE_REDLINE_RPM - 4200.0)
        return 320.0 - 80.0 * t
    return 200.0


def tire_lateral_force(alpha: float, fz: float, mu: float) -> float:
    """Fuerza lateral de un eje (Pacejka simplificada). alpha en radianes."""
    return -mu * fz * math.sin(cfg.TIRE_C * math.atan(cfg.TIRE_B * alpha))


def pneumatic_trail(alpha: float) -> float:
    """El avance neumático cae con la deriva: el volante se aligera cuando
    el neumático delantero satura (aviso de subviraje). El avance mecánico
    del caster (~30 %) se mantiene siempre, como en un coche real."""
    sat = math.radians(cfg.TIRE_TRAIL_SAT_DEG)
    falloff = max(0.0, 1.0 - abs(alpha) / sat)
    return cfg.TIRE_TRAIL * (0.3 + 0.7 * falloff)


class CarState:
    """Estado del coche en coordenadas locales de la carretera."""

    def __init__(self):
        self.s = 0.0          # distancia recorrida a lo largo del circuito (m)
        self.n = 0.0          # desplazamiento lateral respecto al centro (m)
        self.psi = 0.0        # rumbo relativo a la tangente de la carretera (rad)
        self.vx = 0.0         # velocidad longitudinal (m/s)
        self.vy = 0.0         # velocidad lateral (m/s)
        self.yaw_rate = 0.0   # velocidad de guiñada (rad/s)
        self.rpm = cfg.ENGINE_IDLE_RPM
        self.gear = 1         # 1..6; 0 = punto muerto; -1 = marcha atrás
        self.ax = 0.0         # aceleración longitudinal (m/s²) para transferencia
        self.ay = 0.0         # aceleración lateral (m/s²)
        # Salidas para el FFB / HUD
        self.steer_column_torque = 0.0   # Nm en la columna de dirección
        self.alpha_front = 0.0
        self.alpha_rear = 0.0
        self.front_grip_used = 0.0       # 0..1 saturación del eje delantero
        self.rear_grip_used = 0.0
        self.limiter_on = False
        self.wheelspin = False

    @property
    def speed_kmh(self) -> float:
        return abs(self.vx) * 3.6


class Car:
    def __init__(self):
        self.state = CarState()
        self._shift_cooldown = 0.0

    def reset(self, s: float = 0.0):
        st = self.state
        st.s = s
        st.n = 0.0
        st.psi = 0.0
        st.vx = 0.0
        st.vy = 0.0
        st.yaw_rate = 0.0
        st.rpm = cfg.ENGINE_IDLE_RPM
        st.gear = 1

    # ------------------------------------------------------------------
    def shift_up(self):
        st = self.state
        if self._shift_cooldown > 0.0:
            return False
        if st.gear < len(cfg.GEAR_RATIOS):
            st.gear += 1
            self._shift_cooldown = 0.25
            return True
        return False

    def shift_down(self):
        st = self.state
        if self._shift_cooldown > 0.0:
            return False
        if st.gear > -1:
            st.gear -= 1
            self._shift_cooldown = 0.25
            return True
        return False

    # ------------------------------------------------------------------
    def _drive_ratio(self, gear: int) -> float:
        if gear > 0:
            return cfg.GEAR_RATIOS[gear - 1] * cfg.FINAL_DRIVE
        if gear < 0:
            return -cfg.REVERSE_RATIO * cfg.FINAL_DRIVE
        return 0.0

    def step(self, dt: float, steer_norm: float, throttle: float, brake: float,
             kappa: float, mu_surface: float):
        """Un paso de física.

        steer_norm: posición del volante -1..1 (izquierda negativa)
        kappa: curvatura de la carretera en la posición actual (1/m)
        mu_surface: agarre de la superficie bajo el coche
        """
        st = self.state
        self._shift_cooldown = max(0.0, self._shift_cooldown - dt)

        m = cfg.CAR_MASS
        a = cfg.CAR_CG_TO_FRONT
        b = cfg.CAR_CG_TO_REAR
        wheelbase = a + b

        # Ángulo de las ruedas delanteras a partir del volante real
        wheel_angle_rad = steer_norm * math.radians(cfg.WHEEL_ROTATION_DEG / 2.0)
        delta = wheel_angle_rad / cfg.STEER_RATIO

        # --- Cargas por eje con transferencia longitudinal -------------
        fz_front = m * G * b / wheelbase - m * st.ax * cfg.CAR_CG_HEIGHT / wheelbase
        fz_rear = m * G * a / wheelbase + m * st.ax * cfg.CAR_CG_HEIGHT / wheelbase
        fz_front = max(500.0, fz_front)
        fz_rear = max(500.0, fz_rear)

        # --- Tren motriz ----------------------------------------------
        ratio = self._drive_ratio(st.gear)
        vx_abs = abs(st.vx)

        if ratio != 0.0:
            rpm_from_wheels = vx_abs / cfg.CAR_WHEEL_RADIUS * abs(ratio) * 60.0 / (2 * math.pi)
        else:
            rpm_from_wheels = 0.0

        # Embrague automático a baja velocidad: el motor no baja del ralentí
        st.rpm = max(cfg.ENGINE_IDLE_RPM, rpm_from_wheels)
        st.limiter_on = st.rpm >= cfg.ENGINE_LIMITER_RPM
        eff_throttle = 0.0 if st.limiter_on else throttle
        st.rpm = min(st.rpm, cfg.ENGINE_LIMITER_RPM)

        drive_force = 0.0
        if ratio != 0.0:
            torque = engine_torque(st.rpm) * eff_throttle
            drive_force = torque * ratio * cfg.DRIVELINE_EFF / cfg.CAR_WHEEL_RADIUS
            # patinaje del embrague en la salida: limitar fuerza a baja rpm
            if rpm_from_wheels < cfg.ENGINE_IDLE_RPM and st.gear != 0:
                drive_force *= 0.75

        sign_v = 1.0 if st.vx >= 0.0 else -1.0
        brake_force = cfg.BRAKE_FORCE_MAX * brake
        drag = cfg.AERO_DRAG * st.vx * vx_abs
        rolling = cfg.ROLLING_RESIST * sign_v if vx_abs > 0.3 else 0.0

        # --- Neumáticos (modelo de bicicleta) --------------------------
        # Evitar singularidad a baja velocidad
        vx_eff = max(vx_abs, 2.5)
        st.alpha_front = math.atan2(st.vy + a * st.yaw_rate, vx_eff) - delta * sign_v
        st.alpha_rear = math.atan2(st.vy - b * st.yaw_rate, vx_eff)

        mu_rear = mu_surface * cfg.TIRE_REAR_GRIP_FACTOR
        fy_front = tire_lateral_force(st.alpha_front, fz_front, mu_surface)
        fy_rear = tire_lateral_force(st.alpha_rear, fz_rear, mu_rear)

        # Círculo de fricción en el eje trasero (motriz): acelerar resta
        # agarre lateral -> sobreviraje de potencia
        rear_cap = mu_rear * fz_rear
        fx_rear = drive_force - brake_force * (1.0 - cfg.BRAKE_BIAS_FRONT) * sign_v
        st.wheelspin = abs(fx_rear) > rear_cap
        if abs(fx_rear) > rear_cap:
            fx_rear = math.copysign(rear_cap, fx_rear)
        lat_avail = math.sqrt(max(0.0, rear_cap ** 2 - fx_rear ** 2))
        if abs(fy_rear) > lat_avail:
            fy_rear = math.copysign(lat_avail, fy_rear)

        fx_front = -brake_force * cfg.BRAKE_BIAS_FRONT * sign_v
        front_cap = mu_surface * fz_front
        if abs(fx_front) > front_cap:
            fx_front = math.copysign(front_cap, fx_front)
        lat_avail_f = math.sqrt(max(0.0, front_cap ** 2 - fx_front ** 2))
        if abs(fy_front) > lat_avail_f:
            fy_front = math.copysign(lat_avail_f, fy_front)

        st.front_grip_used = min(1.0, abs(fy_front) / max(1.0, lat_avail_f))
        st.rear_grip_used = min(1.0, abs(fy_rear) / max(1.0, lat_avail))

        # --- Dinámica --------------------------------------------------
        fx_total = fx_rear + fx_front - drag - rolling
        st.ax = fx_total / m
        st.ay = (fy_front + fy_rear) / m

        vy_dot = (fy_front * math.cos(delta) + fy_rear) / m - st.vx * st.yaw_rate
        r_dot = (a * fy_front * math.cos(delta) - b * fy_rear) / cfg.CAR_INERTIA_Z

        st.vx += st.ax * dt
        # el coche no cambia de sentido solo por frenar
        if brake > 0.05 and sign_v * st.vx < 0.0 and st.gear >= 0:
            st.vx = 0.0

        if vx_abs > 1.0:
            st.vy += vy_dot * dt
            st.yaw_rate += r_dot * dt
        else:
            # a velocidad de paseo, modelo cinemático estable
            st.vy *= 0.8
            st.yaw_rate = st.vx * math.tan(delta) / wheelbase

        # amortiguación numérica suave
        st.vy *= max(0.0, 1.0 - 0.4 * dt)
        st.yaw_rate *= max(0.0, 1.0 - 0.2 * dt)

        # --- Posición sobre la carretera -------------------------------
        st.psi += (st.yaw_rate - kappa * st.vx) * dt
        st.psi = max(-1.2, min(1.2, st.psi))
        st.n += (st.vx * math.sin(st.psi) + st.vy * math.cos(st.psi)) * dt
        st.s += (st.vx * math.cos(st.psi) - st.vy * math.sin(st.psi)) * dt

        # --- Par de autoalineado para el force feedback ----------------
        trail = pneumatic_trail(st.alpha_front)
        mz = -fy_front * trail                 # par en las manguetas
        st.steer_column_torque = mz / cfg.STEER_RATIO * 2.0
