"""Modelo físico del vehículo — 4 ruedas independientes.

Componentes simulados:
  - 4 ruedas con velocidad angular propia: deslizamiento longitudinal,
    bloqueo de frenada real (rueda parada = fricción dinámica, menor),
    patinaje de tracción y ABS opcional por rueda.
  - Neumático con curva combinada tipo Pacejka (círculo de fricción
    continuo), sensibilidad a la carga (mu cae al cargar la rueda) y
    retardo de respuesta lateral (relaxation length).
  - Suspensión: altura, cabeceo y balanceo del chasis con muelle y
    amortiguador por rueda y barras estabilizadoras por eje. De aquí
    salen las cargas por rueda (transferencia longitudinal Y lateral,
    baches, pianos y aligeramiento en los cambios de rasante).
  - Tracción configurable (RWD/FWD/AWD) con diferencial por eje
    (abierto / autoblocante viscoso / bloqueado).
  - Motor con curva de par, freno motor, limitador y caja de 6 marchas.
  - Pendientes: la gravedad frena en subida y empuja en bajada; las
    crestas descargan la suspensión (y los baches la sacuden).
  - Par de autoalineado por rueda delantera para el force feedback,
    incluida la sacudida por baches asimétricos.

Convenio de ejes: x adelante, y a la DERECHA, guiñada positiva = giro a
la derecha. Ruedas: 0=del.izda, 1=del.dcha, 2=tras.izda, 3=tras.dcha.
"""

import math

from . import config as cfg

G = 9.81
FL, FR, RL, RR = 0, 1, 2, 3


def engine_torque(rpm: float) -> float:
    """Curva de par del motor en Nm (a gas pleno), generada desde la
    configuración: sube desde ~47 % del par máximo en bajos hasta el
    máximo en ENGINE_TORQUE_PEAK_RPM y cae un 25 % hacia el corte."""
    t_max = cfg.ENGINE_MAX_TORQUE_NM
    peak = cfg.ENGINE_TORQUE_PEAK_RPM
    if rpm < 1000.0:
        return 0.47 * t_max
    if rpm < peak:
        return t_max * (0.47 + 0.53 * (rpm - 1000.0) / (peak - 1000.0))
    if rpm < cfg.ENGINE_REDLINE_RPM:
        t = (rpm - peak) / (cfg.ENGINE_REDLINE_RPM - peak)
        return t_max * (1.0 - 0.25 * t)
    return 0.625 * t_max


def engine_peak_power_cv() -> float:
    """Potencia máxima resultante de la curva de par, en CV."""
    best = 0.0
    rpm = 1000.0
    while rpm <= cfg.ENGINE_LIMITER_RPM:
        p = engine_torque(rpm) * rpm * 2.0 * math.pi / 60.0
        best = max(best, p)
        rpm += 100.0
    return best / 735.5


def tire_force_magnitude(rho: float, mu: float, fz: float) -> float:
    """Fuerza total del neumático para un deslizamiento combinado
    normalizado rho (=1 en el pico). Pasado el pico cae hacia ~80 %:
    una rueda bloqueada o patinando agarra menos que una al límite."""
    return mu * fz * math.sin(cfg.TIRE_C * math.atan(cfg.TIRE_B * rho))


def mu_with_load(mu_base: float, fz: float, fz_ref: float) -> float:
    """Sensibilidad a la carga: el mu cae al sobrecargar la rueda respecto
    a SU carga estática (que depende del reparto de pesos del vehículo).
    Esto hace que transferir peso reduzca el agarre total del eje."""
    factor = 1.0 - cfg.TIRE_LOAD_SENS * (fz - fz_ref) / fz_ref
    return mu_base * max(0.6, min(1.3, factor))


def pneumatic_trail(alpha: float) -> float:
    """El avance neumático cae con la deriva (el volante se aligera al
    saturar el tren delantero); el avance mecánico (~15 %) permanece.
    El contraste alto hace el aviso de subviraje claramente perceptible."""
    sat = math.radians(cfg.TIRE_TRAIL_SAT_DEG)
    falloff = max(0.0, 1.0 - abs(alpha) / sat)
    return cfg.TIRE_TRAIL * (0.15 + 0.85 * falloff)


class CarState:
    """Estado del coche en coordenadas locales de la carretera."""

    def __init__(self):
        self.s = 0.0          # distancia a lo largo del circuito (m)
        self.n = 0.0          # desplazamiento lateral (m, + = derecha)
        self.psi = 0.0        # rumbo relativo a la carretera (rad)
        self.vx = 0.0         # velocidad longitudinal (m/s)
        self.vy = 0.0         # velocidad lateral (m/s)
        self.yaw_rate = 0.0   # guiñada (rad/s)
        self.ax = 0.0
        self.ay = 0.0
        # suspensión (chasis)
        self.heave = 0.0      # m (+ arriba, relativo al plano de la vía)
        self.pitch = 0.0      # rad (+ morro arriba)
        self.roll = 0.0       # rad (+ lado derecho elevado)
        self.heave_v = 0.0
        self.pitch_v = 0.0
        self.roll_v = 0.0
        # ruedas
        self.omega = [0.0, 0.0, 0.0, 0.0]      # rad/s
        self.fz = [0.0, 0.0, 0.0, 0.0]         # carga vertical (N)
        self.susp_def = [0.0, 0.0, 0.0, 0.0]   # deflexión muelle (m, + comprimido)
        self.slip_ratio = [0.0, 0.0, 0.0, 0.0]
        self.slip_angle = [0.0, 0.0, 0.0, 0.0]
        self.wheel_surface = ["road"] * 4
        # motor
        self.rpm = cfg.ENGINE_IDLE_RPM
        self.gear = 1         # 1..6; 0 = punto muerto; -1 = marcha atrás
        self.limiter_on = False
        self.engine_on = True
        # indicadores
        self.abs_active = False
        self.front_locked = False
        self.rear_locked = False
        self.wheelspin = False
        self.front_grip_used = 0.0
        self.rear_grip_used = 0.0
        self.alpha_front = 0.0
        self.steer_column_torque = 0.0

    @property
    def speed_kmh(self) -> float:
        return abs(self.vx) * 3.6


class Car:
    # posiciones de las ruedas respecto al CG (x adelante, y derecha)
    X_POS = None
    Y_POS = None

    def __init__(self):
        self.state = CarState()
        self._shift_cooldown = 0.0
        self._brake_scale = [1.0, 1.0, 1.0, 1.0]   # modulación del ABS
        self._fy_state = [0.0, 0.0, 0.0, 0.0]      # relaxation length
        self._prev_bump = [0.0, 0.0, 0.0, 0.0]
        self._bump_kick = 0.0
        self._kick_lp = 0.0
        self._limiter_cut = False
        self._fx_tires = 0.0
        self._steer_prev = 0.0
        self._steer_rate_lp = 0.0
        self._torque_lp = 0.0
        self._auto_dwell = 0.0
        a, b = cfg.CAR_CG_TO_FRONT, cfg.CAR_CG_TO_REAR
        t2 = cfg.CAR_TRACK_WIDTH / 2.0
        self.X_POS = [a, a, -b, -b]
        self.Y_POS = [-t2, t2, -t2, t2]
        # reparto estático de peso por rueda
        L = a + b
        wf = cfg.CAR_MASS * G * b / L / 2.0
        wr = cfg.CAR_MASS * G * a / L / 2.0
        self._static_fz = [wf, wf, wr, wr]

    def reset(self, s: float = 0.0):
        st = CarState()
        st.s = s
        st.gear = 1
        self.state = st
        self._brake_scale = [1.0] * 4
        self._fy_state = [0.0] * 4
        self._prev_bump = [0.0] * 4
        self._bump_kick = 0.0
        self._kick_lp = 0.0
        self._limiter_cut = False
        self._fx_tires = 0.0
        self._steer_prev = 0.0
        self._steer_rate_lp = 0.0
        self._torque_lp = 0.0
        self._auto_dwell = 0.0

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

    def toggle_engine(self) -> bool:
        """Arranca o para el motor. Devuelve el nuevo estado."""
        st = self.state
        st.engine_on = not st.engine_on
        if st.engine_on:
            st.rpm = cfg.ENGINE_IDLE_RPM
        return st.engine_on

    def auto_shift(self, throttle: float) -> bool:
        """Cambio automático: sube cerca del corte (si no hay patinaje),
        baja a bajas vueltas o por kick-down pisando a fondo. Con tiempo
        de permanencia entre cambios para no cazar marchas, y protección
        de sobrerégimen al reducir. N y R se manejan a mano."""
        st = self.state
        if st.gear < 1 or self._auto_dwell > 0.0:
            return False
        # umbrales relativos al motor del coche (un autobús corta a
        # 2500 rpm; un fórmula, a 12000)
        lim = cfg.ENGINE_LIMITER_RPM
        if st.rpm > lim * 0.93 and st.gear < len(cfg.GEAR_RATIOS) \
                and max(st.slip_ratio) < 0.4:
            if self.shift_up():
                self._auto_dwell = 1.2
                return True
        low_rpm = st.rpm < max(cfg.ENGINE_IDLE_RPM * 1.4, lim * 0.30)
        # el kick-down no baja a 1a: esa marcha es solo de salida
        kick_down = throttle > 0.85 and st.rpm < lim * 0.52 and st.gear > 2
        if st.gear > 1 and (low_rpm or kick_down):
            # no reducir si dejaría el motor pasado de vueltas
            projected = st.rpm * cfg.GEAR_RATIOS[st.gear - 2] / cfg.GEAR_RATIOS[st.gear - 1]
            if projected < cfg.ENGINE_REDLINE_RPM * 0.92 and self.shift_down():
                self._auto_dwell = 1.2
                return True
        return False

    # ------------------------------------------------------------------
    def _drive_ratio(self, gear: int) -> float:
        if gear > 0:
            return cfg.GEAR_RATIOS[gear - 1] * cfg.FINAL_DRIVE
        if gear < 0:
            return -cfg.REVERSE_RATIO * cfg.FINAL_DRIVE
        return 0.0

    def _driven_wheels(self):
        if cfg.DRIVE_TYPE == "FWD":
            return [FL, FR]
        if cfg.DRIVE_TYPE == "AWD":
            return [FL, FR, RL, RR]
        return [RL, RR]

    def _axle_torque_split(self):
        """(par_eje_delantero, par_eje_trasero) como fracciones."""
        if cfg.DRIVE_TYPE == "FWD":
            return 1.0, 0.0
        if cfg.DRIVE_TYPE == "AWD":
            return cfg.AWD_FRONT_SPLIT, 1.0 - cfg.AWD_FRONT_SPLIT
        return 0.0, 1.0

    def _diff_torques(self, t_axle, om_left, om_right):
        """Reparto del par de un eje entre sus dos ruedas según el
        tipo de diferencial."""
        if cfg.DIFF_TYPE == "open":
            return t_axle / 2.0, t_axle / 2.0
        if cfg.DIFF_TYPE == "lsd":
            k, cap = cfg.DIFF_LSD_COEFF, 250.0
        else:  # locked
            k, cap = 5.0 * cfg.DIFF_LSD_COEFF, 450.0
        # acoplamiento viscoso: transfiere par de la rueda rápida a la lenta
        transfer = k * (om_left - om_right)
        transfer = max(-cap, min(cap, transfer))
        return t_axle / 2.0 - transfer, t_axle / 2.0 + transfer

    # ------------------------------------------------------------------
    def step(self, dt: float, steer_norm: float, throttle: float, brake: float,
             track):
        st = self.state
        self._shift_cooldown = max(0.0, self._shift_cooldown - dt)
        self._auto_dwell = max(0.0, self._auto_dwell - dt)

        m = cfg.CAR_MASS
        R = cfg.CAR_WHEEL_RADIUS
        wheel_angle = steer_norm * math.radians(cfg.WHEEL_ROTATION_DEG / 2.0)
        delta = wheel_angle / cfg.STEER_RATIO
        cos_d, sin_d = math.cos(delta), math.sin(delta)

        # --- superficie y baches bajo cada rueda ------------------------
        mu_wheel = [0.0] * 4
        bump = [0.0] * 4
        for i in range(4):
            s_i = st.s + self.X_POS[i]
            n_i = st.n + self.Y_POS[i]
            surf, mu = track.surface_at(n_i, s_i)
            st.wheel_surface[i] = surf
            if i >= 2:
                mu *= cfg.TIRE_REAR_GRIP_FACTOR
            mu_wheel[i] = mu
            bump[i] = track.bump_at(s_i, n_i, surf)

        # --- suspensión: cargas por rueda -------------------------------
        # deflexión dinámica de cada esquina (positiva = comprimida)
        d = [0.0] * 4
        dv = [0.0] * 4
        f_susp = [0.0] * 4
        for i in range(4):
            # convenio: roll positivo = lado derecho ELEVADO (en curva a la
            # derecha el balanceo sale positivo: carga las ruedas izquierdas)
            corner_h = st.heave + st.pitch * self.X_POS[i] + st.roll * self.Y_POS[i]
            corner_v = st.heave_v + st.pitch_v * self.X_POS[i] + st.roll_v * self.Y_POS[i]
            bump_v = (bump[i] - self._prev_bump[i]) / dt if dt > 0 else 0.0
            self._prev_bump[i] = bump[i]
            d[i] = bump[i] - corner_h
            dv[i] = bump_v - corner_v
            k = cfg.SUSP_SPRING_FRONT if i < 2 else cfg.SUSP_SPRING_REAR
            f_susp[i] = k * d[i] + cfg.SUSP_DAMPER * dv[i]
            st.susp_def[i] = d[i]

        # barras estabilizadoras: fuerza según diferencia izda/dcha por eje
        arb_f = cfg.ARB_FRONT * (d[FL] - d[FR]) / 2.0
        arb_r = cfg.ARB_REAR * (d[RL] - d[RR]) / 2.0
        f_susp[FL] += arb_f
        f_susp[FR] -= arb_f
        f_susp[RL] += arb_r
        f_susp[RR] -= arb_r

        # carga aerodinámica: crece con el cuadrado de la velocidad y se
        # reparte entre ejes; pasa por la sensibilidad a la carga del
        # neumático como cualquier otra carga
        df = cfg.AERO_DOWNFORCE * st.vx * st.vx
        df_front = df * cfg.AERO_DF_FRONT_SHARE / 2.0
        df_rear = df * (1.0 - cfg.AERO_DF_FRONT_SHARE) / 2.0
        # transferencia directa por la geometría anti-dive/anti-squat:
        # frenando (fx<0) carga las delanteras al instante sin pasar por
        # los muelles; acelerando, las traseras
        wb = cfg.CAR_CG_TO_FRONT + cfg.CAR_CG_TO_REAR
        anti_fz = -cfg.SUSP_ANTI_PITCH * self._fx_tires \
            * cfg.CAR_CG_HEIGHT / (wb * 2.0)
        for i in range(4):
            aero = df_front if i < 2 else df_rear
            geo = anti_fz if i < 2 else -anti_fz
            st.fz[i] = max(0.0, self._static_fz[i] + f_susp[i] + aero + geo)

        # --- dinámica vertical del chasis -------------------------------
        grade = track.grade_at(st.s)
        vcurv = track.vcurv_at(st.s)
        a_road = vcurv * st.vx * st.vx   # aceleración vertical impuesta
        # por la rasante (cresta: vcurv<0 -> el suelo "cae" -> descarga)
        sum_f = sum(f_susp)
        sum_mx = sum(f_susp[i] * self.X_POS[i] for i in range(4))
        sum_my = sum(f_susp[i] * self.Y_POS[i] for i in range(4))
        heave_acc = sum_f / m - a_road
        # el momento de cabeceo lo generan las fuerzas longitudinales de los
        # neumáticos (aplicadas al nivel del suelo, a CG_HEIGHT por debajo
        # del centro de masas), NO la aceleración neta: así, parado en
        # pendiente con freno, los neumáticos sostienen el coche y el morro
        # se hunde aunque ax sea cero.
        # Geometría anti-dive/anti-squat: los brazos de suspensión desvían
        # una fracción de esa fuerza directamente al chasis, así que solo
        # (1 - anti) pasa por los muelles (menos cabeceo). La fracción
        # desviada NO desaparece: se reinyecta como transferencia de carga
        # directa e instantánea en las cargas por rueda (más abajo).
        anti = cfg.SUSP_ANTI_PITCH
        pitch_acc = (sum_mx + self._fx_tires * cfg.CAR_CG_HEIGHT
                     * (1.0 - anti)) / cfg.CAR_INERTIA_PITCH
        roll_acc = (sum_my + m * st.ay * cfg.CAR_CG_HEIGHT) / cfg.CAR_INERTIA_ROLL
        st.heave_v += heave_acc * dt
        st.pitch_v += pitch_acc * dt
        st.roll_v += roll_acc * dt
        st.heave += st.heave_v * dt
        st.pitch += st.pitch_v * dt
        st.roll += st.roll_v * dt

        # --- motor y transmisión ----------------------------------------
        ratio = self._drive_ratio(st.gear)
        driven = self._driven_wheels()
        vx_abs = abs(st.vx)

        if ratio != 0.0 and driven:
            om_mean = sum(st.omega[i] for i in driven) / len(driven)
            rpm_wheels = abs(om_mean) * abs(ratio) * 60.0 / (2.0 * math.pi)
        else:
            rpm_wheels = 0.0
        clutch_slipping = rpm_wheels < cfg.ENGINE_IDLE_RPM
        # el régimen tiene inercia: no sigue instantáneamente a las ruedas
        if st.engine_on:
            rpm_target = max(cfg.ENGINE_IDLE_RPM, rpm_wheels)
        else:
            # motor parado: en marcha lo arrastran las ruedas, si no cae a 0
            rpm_target = rpm_wheels if ratio != 0.0 else 0.0
        st.rpm += (rpm_target - st.rpm) * min(1.0, dt / 0.12)
        # limitador con histéresis
        if st.rpm >= cfg.ENGINE_LIMITER_RPM:
            self._limiter_cut = True
        elif st.rpm < cfg.ENGINE_LIMITER_RPM - 300.0:
            self._limiter_cut = False
        st.limiter_on = self._limiter_cut
        eff_throttle = 0.0 if st.limiter_on else throttle
        st.rpm = min(st.rpm, cfg.ENGINE_LIMITER_RPM)

        # par del motor: positivo con gas, freno motor al levantar
        t_engine = engine_torque(st.rpm) * eff_throttle
        engine_brake = cfg.ENGINE_BRAKE_COEFF * (st.rpm / cfg.ENGINE_LIMITER_RPM)
        t_engine -= engine_brake * (1.0 - eff_throttle)
        if not st.engine_on:
            # motor parado: no empuja y arrastra (compresión) si va engranado
            t_engine = -(engine_brake + 20.0) if ratio != 0.0 else 0.0
        if clutch_slipping:
            t_engine *= 0.75            # embrague patinando en la salida
            if t_engine < 0.0:
                t_engine = 0.0          # sin freno motor con embrague abierto

        t_wheel_total = t_engine * ratio * cfg.DRIVELINE_EFF
        split_f, split_r = self._axle_torque_split()
        t_fl, t_fr = self._diff_torques(t_wheel_total * split_f,
                                        st.omega[FL], st.omega[FR])
        t_rl, t_rr = self._diff_torques(t_wheel_total * split_r,
                                        st.omega[RL], st.omega[RR])
        t_drive = [t_fl, t_fr, t_rl, t_rr]
        if ratio == 0.0:
            t_drive = [0.0] * 4

        # --- par de freno por rueda (con ABS) ---------------------------
        t_brake_max = [0.0] * 4
        per_front = cfg.BRAKE_FORCE_MAX * cfg.BRAKE_BIAS_FRONT / 2.0 * R
        per_rear = cfg.BRAKE_FORCE_MAX * (1.0 - cfg.BRAKE_BIAS_FRONT) / 2.0 * R
        st.abs_active = False
        for i in range(4):
            base = per_front if i < 2 else per_rear
            if cfg.ABS_ENABLED:
                # modulación: suelta el freno si la rueda desliza de más
                if st.slip_ratio[i] < -cfg.ABS_SLIP_TARGET and vx_abs > 2.0:
                    self._brake_scale[i] = max(0.25, self._brake_scale[i] - 8.0 * dt)
                    st.abs_active = True
                else:
                    self._brake_scale[i] = min(1.0, self._brake_scale[i] + 4.0 * dt)
            else:
                self._brake_scale[i] = 1.0
            t_brake_max[i] = base * brake * self._brake_scale[i]

        # --- fuerzas de neumático por rueda -----------------------------
        peak_a = math.radians(cfg.TIRE_PEAK_SLIP_ANGLE_DEG)
        peak_s = cfg.TIRE_PEAK_SLIP_RATIO
        fx_w = [0.0] * 4
        fy_w = [0.0] * 4
        grip_used = [0.0] * 4
        for i in range(4):
            # velocidad del punto de contacto (chasis)
            vxi = st.vx - st.yaw_rate * self.Y_POS[i]
            vyi = st.vy + st.yaw_rate * self.X_POS[i]
            if i < 2:  # ruedas delanteras giradas
                v_along = vxi * cos_d + vyi * sin_d
                v_side = -vxi * sin_d + vyi * cos_d
            else:
                v_along, v_side = vxi, vyi
            denom = max(abs(v_along), 1.5)
            slip = (st.omega[i] * R - v_along) / denom
            alpha = math.atan2(v_side, max(abs(v_along), 1.5))
            st.slip_ratio[i] = slip
            st.slip_angle[i] = alpha

            mu_i = mu_with_load(mu_wheel[i], st.fz[i], self._static_fz[i])
            # elipse de fricción: más capacidad longitudinal que lateral
            ratio_l = cfg.TIRE_LONG_GRIP_RATIO
            s_n = slip / peak_s
            a_n = alpha / peak_a
            s_e = s_n / ratio_l
            rho = math.hypot(s_e, a_n)
            if rho < 1e-6:
                fx, fy_ss = 0.0, 0.0
                grip_used[i] = 0.0
            else:
                f_total = tire_force_magnitude(rho, mu_i, st.fz[i])
                fx = f_total * (s_e / rho) * ratio_l
                fy_ss = -f_total * (a_n / rho)
                grip_used[i] = min(1.0, rho)
            # retardo de respuesta lateral (relaxation length)
            blend = min(1.0, (vx_abs + 0.5) * dt / cfg.TIRE_RELAX_LENGTH)
            self._fy_state[i] += (fy_ss - self._fy_state[i]) * blend
            fx_w[i] = fx
            fy_w[i] = self._fy_state[i]

        # --- fuerzas sobre el chasis ------------------------------------
        sign_v = 1.0 if st.vx >= 0.0 else -1.0
        drag = cfg.AERO_DRAG * st.vx * vx_abs
        rolling = cfg.ROLLING_RESIST * sign_v if vx_abs > 0.3 else 0.0
        # la hierba se hunde: gran resistencia a la rodadura en esas ruedas
        if vx_abs > 0.3:
            rolling += sum(0.08 * st.fz[i] for i in range(4)
                           if st.wheel_surface[i] == "grass") * sign_v
        gravity_x = -m * G * grade   # pendiente: frena subiendo

        fx_total = 0.0
        fy_total = 0.0
        yaw_moment = 0.0
        for i in range(4):
            if i < 2:
                fx_b = fx_w[i] * cos_d - fy_w[i] * sin_d
                fy_b = fx_w[i] * sin_d + fy_w[i] * cos_d
            else:
                fx_b, fy_b = fx_w[i], fy_w[i]
            fx_total += fx_b
            fy_total += fy_b
            yaw_moment += self.X_POS[i] * fy_b - self.Y_POS[i] * fx_b

        # guardar la suma de fuerzas de neumático para el cabeceo del
        # siguiente paso (se aplican a nivel del suelo)
        self._fx_tires = fx_total

        st.ax = (fx_total - drag - rolling + gravity_x) / m
        st.ay = fy_total / m
        vy_dot = fy_total / m - st.vx * st.yaw_rate
        r_dot = yaw_moment / cfg.CAR_INERTIA_Z

        st.vx += st.ax * dt
        if vx_abs > 1.0:
            st.vy += vy_dot * dt
            st.yaw_rate += r_dot * dt
            st.vy *= max(0.0, 1.0 - 0.3 * dt)
            st.yaw_rate *= max(0.0, 1.0 - 0.15 * dt)
        else:
            # a velocidad de paseo, modelo cinemático estable
            st.vy *= 0.8
            wheelbase = cfg.CAR_CG_TO_FRONT + cfg.CAR_CG_TO_REAR
            st.yaw_rate = st.vx * math.tan(delta) / wheelbase

        # --- posición sobre la carretera --------------------------------
        kappa = track.kappa_at(st.s)
        st.psi += (st.yaw_rate - kappa * st.vx) * dt
        st.psi = max(-1.2, min(1.2, st.psi))
        st.n += (st.vx * math.sin(st.psi) + st.vy * math.cos(st.psi)) * dt
        st.s += (st.vx * math.cos(st.psi) - st.vy * math.sin(st.psi)) * dt

        # --- rotación de cada rueda -------------------------------------
        st.front_locked = False
        st.rear_locked = False
        st.wheelspin = False
        for i in range(4):
            vxi = st.vx - st.yaw_rate * self.Y_POS[i]
            if i < 2:
                v_along = vxi * cos_d + (st.vy + st.yaw_rate * self.X_POS[i]) * sin_d
            else:
                v_along = vxi
            omega_free = v_along / R
            denom = max(abs(v_along), 1.5)
            # el freno se opone al giro de la rueda (o al giro inminente)
            if abs(st.omega[i]) > 0.5:
                t_b = -math.copysign(t_brake_max[i], st.omega[i])
            elif abs(omega_free) > 0.1:
                t_b = -math.copysign(t_brake_max[i], omega_free)
            else:
                t_b = 0.0
            t_app = t_drive[i] + t_b
            # parada rígida: coche casi detenido con el freno dominando
            if abs(st.vx) < 0.15 and t_brake_max[i] > abs(t_drive[i]) + 5.0:
                st.omega[i] = 0.0
                continue
            # inercia efectiva: con el embrague acoplado, la rueda arrastra
            # la masa rotacional del motor multiplicada por el desarrollo
            # al cuadrado (acelerar/retener en 1a cuesta mucho más que en 6a)
            if i in driven and st.engine_on and not clutch_slipping \
                    and ratio != 0.0:
                i_eff = cfg.CAR_WHEEL_INERTIA \
                    + cfg.ENGINE_INERTIA * ratio * ratio / len(driven)
            else:
                i_eff = cfg.CAR_WHEEL_INERTIA
            mu_i = mu_with_load(mu_wheel[i], st.fz[i], self._static_fz[i])
            grip_force = mu_i * st.fz[i] * cfg.TIRE_LONG_GRIP_RATIO
            slip_now = (st.omega[i] * R - v_along) / denom
            deep_slip = abs(slip_now) > 0.9 * peak_s \
                or abs(t_app) / R > 0.9 * grip_force
            if not deep_slip and st.fz[i] > 50.0:
                # régimen de rodadura (fricción estática): relajación
                # exponencial exacta al deslizamiento de equilibrio, que
                # transmite el par aplicado al suelo. Incondicionalmente
                # estable a cualquier dt.
                k_v = grip_force * cfg.TIRE_C * cfg.TIRE_B / (peak_s * denom)
                tau = i_eff / (k_v * R * R)
                omega_eq = (v_along + (t_app / R) / k_v) / R
                blend = math.exp(-dt / tau) if tau > 1e-6 else 0.0
                new_omega = omega_eq + (st.omega[i] - omega_eq) * blend
            else:
                # deslizamiento profundo (bloqueo o patinaje): integración
                # explícita con la fuerza de la curva del neumático
                t_net = t_app - fx_w[i] * R
                new_omega = st.omega[i] + t_net / i_eff * dt
                # si cruza la rodadura libre sin par para seguir deslizando,
                # vuelve al régimen de rodadura
                if (st.omega[i] - omega_free) * (new_omega - omega_free) < 0.0 \
                        and abs(t_app) < grip_force * R:
                    new_omega = omega_free
                # bloqueo: la rueda no invierte el sentido por frenar
                if abs(omega_free) > 0.3 and st.omega[i] * omega_free >= 0.0 \
                        and new_omega * omega_free < 0.0 and t_brake_max[i] > 0.0:
                    new_omega = 0.0
            st.omega[i] = new_omega
            # indicadores
            if t_brake_max[i] > 0.0 and abs(omega_free) > 3.0 \
                    and abs(st.omega[i]) < 0.15 * abs(omega_free):
                if i < 2:
                    st.front_locked = True
                else:
                    st.rear_locked = True
            if st.slip_ratio[i] > peak_s * 1.5:
                st.wheelspin = True

        # --- indicadores agregados --------------------------------------
        st.alpha_front = (st.slip_angle[FL] + st.slip_angle[FR]) / 2.0
        st.front_grip_used = max(grip_used[FL], grip_used[FR])
        st.rear_grip_used = max(grip_used[RL], grip_used[RR])

        # --- par en la columna para el force feedback -------------------
        mz = 0.0
        for i in (FL, FR):
            mz += -fy_w[i] * pneumatic_trail(st.slip_angle[i])
        # radio de pivotamiento (scrub radius): la diferencia de fuerza
        # longitudinal entre las ruedas delanteras tira del volante
        # (torque steer en FWD, tirón al frenar con media pista de hierba,
        # pulsación natural del ABS...)
        mz += (fx_w[FL] - fx_w[FR]) * cfg.STEER_SCRUB_RADIUS
        # amortiguación de columna: se opone a la velocidad de giro del
        # volante para evitar oscilaciones autoexcitadas; crece con la
        # velocidad porque el lazo de FFB se desestabiliza en recta rápida
        rate = (wheel_angle - self._steer_prev) / dt if dt > 0 else 0.0
        self._steer_prev = wheel_angle
        self._steer_rate_lp += (rate - self._steer_rate_lp) * min(1.0, 30.0 * dt)
        damp_coeff = cfg.FFB_COLUMN_DAMPING * (1.0 + vx_abs / 25.0)
        damping = -damp_coeff * self._steer_rate_lp
        # sacudida por baches asimétricos en el eje delantero, filtrada
        # paso-alto: la transferencia de carga estacionaria de las curvas
        # no debe entrar, solo los transitorios (pianos, baches)
        kick_raw = (f_susp[FL] - f_susp[FR]) * cfg.FFB_KICK_GAIN
        self._kick_lp += (kick_raw - self._kick_lp) * min(1.0, 2.0 * dt)
        kick_hp = kick_raw - self._kick_lp
        self._bump_kick += (kick_hp - self._bump_kick) * min(1.0, 25.0 * dt)
        raw_torque = mz / cfg.STEER_RATIO * 2.0 + self._bump_kick + damping
        # suavizado final del par: corta la excitación de alta frecuencia
        # que produce bandazos del volante en recta (FFB_SMOOTHING_S)
        if cfg.FFB_SMOOTHING_S > 1e-4:
            blend_t = min(1.0, dt / cfg.FFB_SMOOTHING_S)
            self._torque_lp += (raw_torque - self._torque_lp) * blend_t
            st.steer_column_torque = self._torque_lp
        else:
            st.steer_column_torque = raw_torque
