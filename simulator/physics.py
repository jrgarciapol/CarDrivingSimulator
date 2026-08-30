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
  - Suspensión con amortiguación separada por eje y por sentido
    (compresión / extensión) y TOPES DE RECORRIDO cuadráticos.
  - Geometría de tren completa: avance (caster), caída estática,
    convergencia y sus efectos acoplados.
  - Tracción configurable (RWD/FWD/AWD) con diferencial por eje: abierto,
    autoblocante de DISCOS con rampas y precarga (sensible al par),
    viscoso (sensible a la velocidad) o bloqueado.
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


def mu_with_load(mu_base: float, fz: float, fz_ref: float,
                 ls_scale: float = 1.0) -> float:
    """Sensibilidad a la carga: el mu cae al sobrecargar la rueda respecto
    a SU carga estática (que depende del reparto de pesos del vehículo).
    Esto hace que transferir peso reduzca el agarre total del eje.
    ls_scale la modula: un neumático ANCHO reparte la carga en más huella
    (menos presión de contacto), así que su mu cae menos al sobrecargar."""
    factor = 1.0 - cfg.TIRE_LOAD_SENS * ls_scale * (fz - fz_ref) / fz_ref
    return mu_base * max(0.6, min(1.3, factor))


def pneumatic_trail(alpha: float) -> float:
    """AVANCE NEUMATICO: nace de la DEFORMACION de la huella. Como la zona
    delantera agarra y la trasera desliza, la resultante de la fuerza lateral
    queda retrasada respecto al centro de la huella; esa distancia es el
    brazo de palanca. Al crecer la deriva la parte trasera deja de agarrar,
    la resultante se ADELANTA y el avance se derrumba: por eso el volante se
    aligera justo antes de que el tren delantero se vaya.

    Pasado el pico llega a hacerse ligeramente NEGATIVO (la resultante se
    adelanta al centro de la huella), lo que acentúa el aviso.
    Existe solo porque la goma se deforma: una rueda rígida no lo tendría."""
    sat = math.radians(cfg.TIRE_TRAIL_SAT_DEG)
    t = cfg.TIRE_TRAIL * (1.0 - abs(alpha) / sat)
    return max(-cfg.TIRE_TRAIL_NEG_FRAC * cfg.TIRE_TRAIL, t)


def mechanical_trail(radius: float) -> float:
    """AVANCE MECANICO: GEOMETRIA PURA, nada que ver con la deformación.
    El eje de dirección (la línea entre las rótulas de la mangueta) está
    inclinado hacia atrás el ángulo de AVANCE o caster; al prolongarlo corta
    el suelo POR DELANTE del punto de contacto. Como la fuerza lateral tira
    por DETRAS del pivote, aparece un par que alinea la rueda con el avance:
    es el mismo efecto que las ruedas locas de un carrito de la compra.

        t_mec = R · tan(caster) + offset

    Existe aunque la rueda fuese perfectamente rígida, y NO cae con la
    deriva: es el suelo que queda en el volante cuando el tren delantero ya
    ha saturado y el avance neumático se ha derrumbado.

    Que dependa del RADIO acopla el catálogo de ruedas con la dirección:
    montar rueda más grande alarga el brazo y endurece el volante."""
    return radius * math.tan(math.radians(cfg.CASTER_ANGLE_DEG)) \
        + cfg.STEER_TRAIL_OFFSET


def caster_camber(delta: float, side: float) -> float:
    """Caída ganada al girar por tener el eje de dirección inclinado
    (caster camber gain). Al pivotar sobre un eje tumbado hacia atrás, la
    rueda EXTERIOR de la curva se inclina HACIA DENTRO (caída negativa, que
    es la buena: empuja hacia el centro de la curva) mientras la interior se
    tumba hacia fuera. Es la razón de que los coches de competición monten
    mucho avance: caída negativa gratis justo cuando hace falta, sin
    penalizar la huella en recta.

    delta = giro de la rueda (rad, + = a la derecha)
    side  = -1 rueda izquierda, +1 rueda derecha
    Devuelve el incremento de inclinación en el mismo convenio que el
    balanceo: + = la rueda se tumba hacia la derecha."""
    return -side * math.sin(math.radians(cfg.CASTER_ANGLE_DEG)) * delta \
        * cfg.CASTER_CAMBER_GAIN


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
        self.chassis_twist = 0.0  # rad, torsión del bastidor (φ_del − φ_tras)
        # ruedas
        self.omega = [0.0, 0.0, 0.0, 0.0]      # rad/s
        self.fz = [0.0, 0.0, 0.0, 0.0]         # carga vertical (N)
        self.zu = [0.0, 0.0, 0.0, 0.0]         # posición vertical de la masa
                                               # no suspendida (m, + arriba,
                                               # desviación del equilibrio)
        self.zu_v = [0.0, 0.0, 0.0, 0.0]       # y su velocidad (m/s)
        self.tire_temp = [60.0, 60.0, 60.0, 60.0]  # C, goma templada de inicio
        self.susp_def = [0.0, 0.0, 0.0, 0.0]   # deflexión muelle (m, + comprimido)
        self.slip_ratio = [0.0, 0.0, 0.0, 0.0]
        self.slip_angle = [0.0, 0.0, 0.0, 0.0]
        self.on_bump_stop = [False] * 4        # apoyada en el tope de recorrido
        self.camber = [0.0, 0.0, 0.0, 0.0]     # rad, caída CONTRA EL ASFALTO
                                               # (estática + balanceo + gain
                                               # + caster); 0 = apoya plana
        self.wheel_surface = ["road"] * 4
        self.road_roughness = 0.0              # 0 firme liso .. 1 muy rugoso
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
        self.understeer = 0.0   # 0..1: cuánto se va el tren delantero
        self.oversteer = 0.0    # 0..1: cuánto se va el tren trasero
        self.alpha_front = 0.0
        self.steer_column_torque = 0.0
        self.gyro_roll_moment = 0.0   # N·m, precesión de las ruedas

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
        self._shift_cut = 0.0                      # corte de par en el cambio
        self._brake_scale = [1.0, 1.0, 1.0, 1.0]   # modulación del ABS
        self._fy_state = [0.0, 0.0, 0.0, 0.0]      # relaxation length
        self._prev_bump = [0.0, 0.0, 0.0, 0.0]
        self._bump_kick = 0.0
        self._kick_lp = 0.0
        self._limiter_cut = False
        # régimen del cigüeñal (rad/s) para ENGINE_MODEL="inertia"
        self._omega_e = cfg.ENGINE_IDLE_RPM * 2.0 * math.pi / 60.0
        self._fx_tires = 0.0
        self._steer_prev = 0.0
        self._steer_rate_lp = 0.0
        self._torque_lp = 0.0
        self._auto_dwell = 0.0
        self._fy_tires = 0.0
        self._fy_front = 0.0      # fuerza lateral del eje delantero (torsión)
        a, b = cfg.CAR_CG_TO_FRONT, cfg.CAR_CG_TO_REAR
        t2 = cfg.CAR_TRACK_WIDTH / 2.0
        self.X_POS = [a, a, -b, -b]
        self.Y_POS = [-t2, t2, -t2, t2]
        # RUEDAS POR EJE: cada eje puede llevar su montura (staggered), como
        # un RWD potente con goma mayor detrás. Si el coche no define el eje
        # trasero, se usa el delantero en las cuatro.
        rf = cfg.CAR_WHEEL_RADIUS
        rr = getattr(cfg, "CAR_WHEEL_RADIUS_REAR", None) or rf
        if_ = cfg.CAR_WHEEL_INERTIA
        ir = getattr(cfg, "CAR_WHEEL_INERTIA_REAR", None) or if_
        self.R_w = [rf, rf, rr, rr]
        self.I_w = [if_, if_, ir, ir]
        # ANCHO del neumático (del WHEEL_SPEC): más huella = menos presión de
        # contacto = algo más de mu, MENOS caída por sobrecarga y goma que se
        # calienta más despacio. Referencia: 205 mm.
        wf = getattr(cfg, "TIRE_WIDTH_MM", 205.0)
        wr = getattr(cfg, "TIRE_WIDTH_MM_REAR", None) or wf
        self._w_mu = [(w / 205.0) ** 0.10 for w in (wf, wf, wr, wr)]
        self._w_ls = [(205.0 / w) ** 0.6 for w in (wf, wf, wr, wr)]
        self._w_heat = [(205.0 / w) ** 0.5 for w in (wf, wf, wr, wr)]
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
        self._omega_e = cfg.ENGINE_IDLE_RPM * 2.0 * math.pi / 60.0
        self._fx_tires = 0.0
        self._fy_tires = 0.0
        self._fy_front = 0.0
        self._steer_prev = 0.0
        self._steer_rate_lp = 0.0
        self._torque_lp = 0.0
        self._auto_dwell = 0.0
        self._shift_cut = 0.0

    # ------------------------------------------------------------------
    def shift_up(self):
        st = self.state
        if self._shift_cooldown > 0.0:
            return False
        if st.gear < len(cfg.GEAR_RATIOS):
            st.gear += 1
            self._shift_cooldown = 0.25
            self._shift_cut = cfg.SHIFT_CUT_TIME    # corte de par del cambio
            return True
        return False

    def shift_down(self):
        st = self.state
        if self._shift_cooldown > 0.0:
            return False
        if st.gear > -1:
            st.gear -= 1
            self._shift_cooldown = 0.25
            self._shift_cut = cfg.SHIFT_CUT_TIME    # corte de par del cambio
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

    def _engine_inertia(self, st, throttle, ratio, om_mean, rpm_wheels, dt):
        """Motor con INERCIA de cigüeñal + embrague (ENGINE_MODEL='inertia').

        A diferencia del filtro de 1er orden del modo 'legacy', el régimen es
        un grado de libertad de verdad:

            I_e · dω/dt = combustión − freno motor − embrague

        El embrague es un acoplamiento tipo muelle (par = rigidez·deslizamiento)
        limitado a una capacidad y escalado por el ENGRANE, que crece con el gas
        y con la velocidad: parado y sin gas está suelto (el motor no tira al
        ralentí), y en marcha queda del todo acoplado (en régimen estacionario
        el par a la rueda coincide con el del modo legacy). Así emergen el
        acelerón libre en punto muerto, el patinaje/flare del embrague en la
        salida y reducciones con el régimen subiendo por sí solo.

        Devuelve (par_total_a_las_ruedas, clutch_slipping). El cigüeñal es un
        GDL propio, así que se devuelve clutch_slipping=True para que la rueda
        NO cargue además la inercia del motor reflejada (sería contarla dos
        veces): aquí el motor y la rueda son dos masas acopladas por el
        embrague, no una sola inercia equivalente."""
        two_pi = 2.0 * math.pi
        idle_w = cfg.ENGINE_IDLE_RPM * two_pi / 60.0
        lim_w = cfg.ENGINE_LIMITER_RPM * two_pi / 60.0

        # === EN MARCHA Y ENGRANADO: rígido, IGUAL que legacy ===============
        # Una vez el coche rueda, el cigüeñal y las ruedas motrices están
        # rígidamente unidos: el motor gira EXACTAMENTE con las ruedas
        # (incluida su sobre-velocidad en un patinazo, que legacy ya maneja).
        # No hay grado de libertad independiente aquí; intentar mantenerlo
        # hacía que el motor flarease hasta el corte o que el embrague
        # frenara las ruedas en wheelspin. La inercia del motor la carga la
        # rueda (reflejada), por eso clutch_slipping=False.
        if ratio != 0.0 and rpm_wheels >= cfg.CLUTCH_LOCK_RPM:
            rpm = max(cfg.ENGINE_IDLE_RPM, rpm_wheels)
            if rpm >= cfg.ENGINE_LIMITER_RPM:
                self._limiter_cut = True
            elif rpm < cfg.ENGINE_LIMITER_RPM - 300.0:
                self._limiter_cut = False
            st.limiter_on = self._limiter_cut
            eff_throttle = 0.0 if st.limiter_on else throttle
            rpm = min(rpm, cfg.ENGINE_LIMITER_RPM)
            st.rpm = rpm
            self._omega_e = rpm * two_pi / 60.0    # sincroniza la próxima salida
            engine_brake = cfg.ENGINE_BRAKE_COEFF * (rpm / cfg.ENGINE_LIMITER_RPM)
            t_engine = engine_torque(rpm) * eff_throttle \
                - engine_brake * (1.0 - eff_throttle)
            if not st.engine_on:
                t_engine = -(engine_brake + 20.0)
            return t_engine * ratio * cfg.DRIVELINE_EFF, False

        # === PUNTO MUERTO o SALIDA (hasta ~la velocidad de engrane) ========
        # Aquí sí es un GDL propio: I_e·dω/dt = combustión − freno − embrague.
        # El embrague patina con par limitado (salida suave, flare), o está
        # suelto en punto muerto (acelerón libre).
        we = self._omega_e
        rpm_now = we * 60.0 / two_pi
        if rpm_now >= cfg.ENGINE_LIMITER_RPM:
            self._limiter_cut = True
        elif rpm_now < cfg.ENGINE_LIMITER_RPM - 300.0:
            self._limiter_cut = False
        st.limiter_on = self._limiter_cut
        eff_throttle = 0.0 if st.limiter_on else throttle
        engine_brake = cfg.ENGINE_BRAKE_COEFF * (rpm_now / cfg.ENGINE_LIMITER_RPM)
        if st.engine_on:
            t_int = engine_torque(rpm_now) * eff_throttle \
                - engine_brake * (1.0 - eff_throttle)
        else:
            t_int = -(engine_brake + 20.0) if ratio != 0.0 else 0.0
        if ratio == 0.0:
            t_clutch = 0.0                         # punto muerto: motor libre
        else:
            omega_ws = om_mean * ratio             # vel. lado motor de las ruedas
            eng = min(1.0, max(1.5 * throttle, rpm_wheels / cfg.CLUTCH_LOCK_RPM))
            cap = eng * cfg.CLUTCH_CAPACITY        # par limitado: patina en la salida
            t_clutch = max(-cap, min(cap, cfg.CLUTCH_STIFFNESS * (we - omega_ws)))
        we += (t_int - t_clutch) / cfg.ENGINE_INERTIA * dt
        if st.engine_on:
            we = max(idle_w, min(lim_w, we))       # ni cala ni pasa del corte
        else:
            we = max(0.0, min(lim_w, we))
        self._omega_e = we
        st.rpm = we * 60.0 / two_pi
        return t_clutch * ratio * cfg.DRIVELINE_EFF, True

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

    def _diff_torques(self, t_axle, om_left, om_right, dt=1/480.0,
                      inercia=1.4):
        """Reparto del par de un eje entre sus dos ruedas según el tipo de
        diferencial.

        El AUTOBLOCANTE DE DISCOS ("lsd") es sensible al PAR, no a la
        velocidad: unos discos de embrague se aprietan por dos vías y de ahí
        sale el par máximo que puede transferir de una rueda a la otra:

            T_bloqueo = PRECARGA + rampa · |par del eje|

          - PRECARGA: unos muelles Belleville aprietan los discos SIEMPRE,
            incluso con el motor parado. Manda con el coche soltado, en el
            punto de inflexión de la curva.
          - RAMPAS: unas cuñas convierten el par que pasa en fuerza axial
            sobre los discos. Hay DOS con ángulos distintos, y ahí está la
            gracia del reglaje: la de ACELERACION suele bloquear mucho (da
            tracción a la salida, a costa de subvirar al abrir gas) y la de
            RETENCION bastante menos (si bloquea de más, el coche entra
            perezoso en curva).

        Alcanzado ese tope, los discos deslizan: es rozamiento SECO, no
        viscoso. Se satura con una tangente hiperbólica en vez de un corte
        en seco para que no oscile numéricamente cuando las dos ruedas van
        casi igual de rápido.

        La diferencia práctica frente al viscoso que había antes: el de
        discos bloquea EN CUANTO PASA PAR, mientras que el viscoso tiene que
        esperar a que la rueda ya esté patinando para reaccionar.
        """
        mitad = t_axle / 2.0
        tipo = cfg.DIFF_TYPE
        if tipo == "open":
            return mitad, mitad
        if tipo == "viscous":
            # modelo antiguo: acoplamiento proporcional a la DIFERENCIA DE
            # VELOCIDAD (tipo Ferguson). Se conserva porque es lo que monta
            # un turismo con tracción total permanente.
            transfer = cfg.DIFF_LSD_COEFF * (om_left - om_right)
            transfer = max(-250.0, min(250.0, transfer))
            return mitad - transfer, mitad + transfer
        if tipo == "locked":
            t_lock = 1.0e4
        else:                                  # "lsd": rampas + precarga
            rampa = (cfg.DIFF_RAMP_POWER if t_axle >= 0.0
                     else cfg.DIFF_RAMP_COAST)
            # Las rampas se dan en PORCENTAJE DE BLOQUEO, que es como se
            # especifican en la realidad ("un 45/20"):
            #     bloqueo % = (T_rueda_alta − T_rueda_baja) / T_total
            # Como aquí se reparte ±transfer sobre la mitad de cada lado, la
            # diferencia entre ruedas es 2·transfer: de ahí el factor 0.5.
            # Sin él, un "45 %" bloquearía en realidad el 90 %.
            t_lock = 0.5 * (cfg.DIFF_PRELOAD + rampa * abs(t_axle))
            # los discos tienen una CAPACIDAD máxima: con mucho par de eje el
            # bloqueo no crece sin fin, satura en DIFF_MAX_LOCK
            t_lock = min(t_lock, getattr(cfg, "DIFF_MAX_LOCK", 1.0e4))
        # La banda de transición no puede ser más estrecha de lo que el paso
        # de integración es capaz de resolver: si un solo paso puede cambiar
        # la diferencia de giro más de lo que mide la banda, el bloqueo
        # oscila de un extremo a otro (chattering) y el eje nunca se
        # estabiliza. Se ensancha lo justo para que eso no ocurra, lo que
        # deja la RIGIDEZ efectiva acotada sin recortar el par de bloqueo.
        banda = max(1e-3, cfg.DIFF_LOCK_BAND,
                    2.0 * t_lock * dt / max(0.05, inercia))
        transfer = t_lock * math.tanh((om_left - om_right) / banda)
        return mitad - transfer, mitad + transfer

    # ------------------------------------------------------------------
    def step(self, dt: float, steer_norm: float, throttle: float, brake: float,
             track):
        st = self.state
        self._shift_cooldown = max(0.0, self._shift_cooldown - dt)
        self._shift_cut = max(0.0, self._shift_cut - dt)
        self._auto_dwell = max(0.0, self._auto_dwell - dt)

        m = cfg.CAR_MASS
        R_w = self.R_w                  # radio POR RUEDA (montura por eje)
        R = R_w[0]
        wheel_angle = steer_norm * math.radians(cfg.WHEEL_ROTATION_DEG / 2.0)
        delta = wheel_angle / cfg.STEER_RATIO
        cos_d, sin_d = math.cos(delta), math.sin(delta)
        # ANGULO REAL DE CADA RUEDA = dirección (solo el eje directriz) más
        # su CONVERGENCIA estática, que es de reglaje y va en sentido
        # opuesto en cada lado. Convergencia (+) = las ruedas apuntan hacia
        # dentro; da estabilidad en recta a costa de arrastre, porque las
        # dos tiran una contra otra. Divergencia (−) afila la entrada en
        # curva: la rueda exterior llega ya girada hacia la curva.
        # Nota: la lleva TAMBIEN el eje trasero, y ahí es lo que evita que
        # la cola se mueva sola al levantar el pie.
        toe_f = math.radians(getattr(cfg, "TOE_FRONT_DEG", 0.0))
        toe_r = math.radians(getattr(cfg, "TOE_REAR_DEG", 0.0))
        d_w = [0.0] * 4
        for _i in range(4):
            _side = 1.0 if self.Y_POS[_i] > 0.0 else -1.0
            d_w[_i] = (delta if _i < 2 else 0.0) \
                - _side * (toe_f if _i < 2 else toe_r)
        cos_w = [math.cos(a) for a in d_w]
        sin_w = [math.sin(a) for a in d_w]

        # --- peralte del tramo (inclinación transversal del asfalto) ----
        # bank > 0 = borde izquierdo elevado (peralte de curva a derechas).
        # Los circuitos sin peralte devuelven 0 y todo queda como antes.
        bank_fn = getattr(track, "bank_at", None)
        bank = bank_fn(st.s) if bank_fn is not None else 0.0
        sin_b = math.sin(bank)

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
            # temperatura de la goma: parábola invertida centrada en el
            # óptimo — fría no agarra (hay que calentarla) y recalentada
            # por abusar del derrape tampoco
            dev = st.tire_temp[i] - cfg.TIRE_TEMP_OPT
            mu *= max(0.72, 1.0 - cfg.TIRE_TEMP_SENS * dev * dev)
            mu_wheel[i] = mu * self._w_mu[i]  # huella ancha: algo más de mu
            bump[i] = track.bump_at(s_i, n_i, surf)
        # RUGOSIDAD sentida (0 liso .. 1 roto): amplifica el temblor de cámara
        # y la vibración del volante. Se toma del DAÑO real del firme (raro en
        # el asfalto, alto en piano/hierba), no del desnivel bruto, para que
        # solo suba en los parches malos y no en todo el asfalto.
        if "kerb" in st.wheel_surface:
            st.road_roughness = 0.85
        elif "grass" in st.wheel_surface:
            st.road_roughness = 0.70
        else:
            dmg_fn = getattr(track, "damage_at", None)
            st.road_roughness = dmg_fn(st.s) if dmg_fn else 0.0

        # --- suspensión: chasis <-> masa no suspendida <-> asfalto ------
        # Cada rueda tiene su propio GDL vertical (zu): el muelle y el
        # amortiguador trabajan entre el chasis y la MANGUETA, y el
        # neumático es otro muelle (mucho más rígido) entre la mangueta y
        # el asfalto. Sobre un piano agresivo la rueda "vuela": el
        # neumático se descomprime y la carga cae aunque el chasis apenas
        # se entere (la carga de Pacejka sale del muelle del neumático).
        grade = track.grade_at(st.s)
        vcurv = track.vcurv_at(st.s)
        a_road = vcurv * st.vx * st.vx   # aceleración vertical impuesta
        # por la rasante (cresta: vcurv<0 -> el suelo "cae")
        # --- RIGIDEZ TORSIONAL DEL CHASIS -------------------------------
        # El bastidor no es infinitamente rígido: el tren delantero y el
        # trasero balancean ángulos distintos, acoplados por el muelle de
        # torsión del chasis (K_c). Se resuelve el equilibrio cuasi-estático
        # (los modos de torsión reales, 20-40 Hz, quedan muy por encima de
        # la dinámica de conducción):
        #     K_f·φ_f + K_c·(φ_f − φ_r) = M_f
        #     K_r·φ_r + K_c·(φ_r − φ_f) = M_r
        # cuya diferencia es  Δφ = (M_f·K_r − M_r·K_f)/(K_f·K_r + K_c·(K_f+K_r))
        # con K_f/K_r = rigidez de balanceo de cada eje (muelles + barra) y
        # M_f/M_r = momento de vuelco generado por cada eje. Con K_c → ∞,
        # Δφ → 0 (chasis rígido = comportamiento anterior). Un chasis blando
        # deja que cada eje "vaya por su cuenta": el reparto de transferencia
        # de carga se acerca al de los momentos y las barras pierden efecto
        # (por eso un chasis que flexa no se deja reglar).
        t2c = cfg.CAR_TRACK_WIDTH * cfg.CAR_TRACK_WIDTH / 2.0
        k_roll_f = (cfg.SUSP_SPRING_FRONT + cfg.ARB_FRONT) * t2c
        k_roll_r = (cfg.SUSP_SPRING_REAR + cfg.ARB_REAR) * t2c
        k_c = math.degrees(1.0) * getattr(cfg, "CHASSIS_TORSION_STIFF", 0.0)
        if k_c > 0.0:
            m_f = self._fy_front * cfg.CAR_CG_HEIGHT
            m_r = (self._fy_tires - self._fy_front) * cfg.CAR_CG_HEIGHT
            twist_t = (m_f * k_roll_r - m_r * k_roll_f) \
                / (k_roll_f * k_roll_r + k_c * (k_roll_f + k_roll_r))
            # filtro corto (~50 ms): la torsión sigue a la carga sin vibrar
            st.chassis_twist += (twist_t - st.chassis_twist) \
                * min(1.0, dt / 0.05)
        else:
            st.chassis_twist = 0.0    # sin dato = bastidor rígido (como antes)

        # AMORTIGUACION por eje y por SENTIDO. Un amortiguador real no opone
        # lo mismo comprimiéndose que extendiéndose: la extensión suele ser
        # 2-3 veces más dura, porque en compresión pelea contra el muelle
        # (que ya sostiene el coche) mientras que en extensión controla la
        # energía que el muelle devuelve, que es lo que hace rebotar.
        # Si el coche no define los cuatro, se derivan del valor único.
        _dmp = getattr(cfg, "SUSP_DAMPER", 4300.0)
        c_bf = getattr(cfg, "SUSP_DAMPER_BUMP_F", None) or _dmp * 0.6
        c_rf = getattr(cfg, "SUSP_DAMPER_REB_F", None) or _dmp * 1.3
        c_br = getattr(cfg, "SUSP_DAMPER_BUMP_R", None) or _dmp * 0.6
        c_rr = getattr(cfg, "SUSP_DAMPER_REB_R", None) or _dmp * 1.3
        gap_f = getattr(cfg, "SUSP_BUMP_GAP_F", 0.07)
        gap_r = getattr(cfg, "SUSP_BUMP_GAP_R", 0.08)
        k_tope = getattr(cfg, "SUSP_BUMP_STIFF", 0.0)

        d = [0.0] * 4
        dv = [0.0] * 4
        f_susp = [0.0] * 4
        for i in range(4):
            # convenio: roll positivo = lado derecho ELEVADO (en curva a la
            # derecha el balanceo sale positivo: carga las ruedas izquierdas)
            # el balanceo de CADA EJE es el del chasis rígido ± media torsión
            roll_i = st.roll + (0.5 if i < 2 else -0.5) * st.chassis_twist
            corner_h = st.heave + st.pitch * self.X_POS[i] + roll_i * self.Y_POS[i]
            corner_v = st.heave_v + st.pitch_v * self.X_POS[i] + st.roll_v * self.Y_POS[i]
            d[i] = st.zu[i] - corner_h
            dv[i] = st.zu_v[i] - corner_v
            k = cfg.SUSP_SPRING_FRONT if i < 2 else cfg.SUSP_SPRING_REAR
            # dv > 0 = la rueda sube respecto al chasis = COMPRESION
            if dv[i] > 0.0:
                c = c_bf if i < 2 else c_br
            else:
                c = c_rf if i < 2 else c_rr
            f_susp[i] = k * d[i] + c * dv[i]
            # TOPE DE RECORRIDO: agotado el hueco libre, la suspensión deja
            # de ser un muelle y se vuelve casi rígida. Es CUADRATICO, como
            # un tope de poliuretano: los primeros milímetros apenas se
            # notan y luego se dispara.
            if k_tope > 0.0:
                exceso = d[i] - (gap_f if i < 2 else gap_r)
                if exceso > 0.0:
                    f_susp[i] += k_tope * exceso * exceso
                    st.on_bump_stop[i] = True
                else:
                    st.on_bump_stop[i] = False
            st.susp_def[i] = d[i]

        # barras estabilizadoras: fuerza según diferencia izda/dcha por eje
        arb_f = cfg.ARB_FRONT * (d[FL] - d[FR]) / 2.0
        arb_r = cfg.ARB_REAR * (d[RL] - d[RR]) / 2.0
        f_susp[FL] += arb_f
        f_susp[FR] -= arb_f
        f_susp[RL] += arb_r
        f_susp[RR] -= arb_r

        # muelle del neumático + dinámica de la masa no suspendida
        f_tire_v = [0.0] * 4
        for i in range(4):
            bump_v = (bump[i] - self._prev_bump[i]) / dt if dt > 0 else 0.0
            self._prev_bump[i] = bump[i]
            comp = bump[i] - st.zu[i]          # compresión de la goma
            comp_v = bump_v - st.zu_v[i]
            # el neumático solo EMPUJA, nunca tira: en cuanto la fuerza
            # total de contacto (estática + desviación) se anula, la rueda
            # está en el aire y ni el muelle ni la amortiguación de la
            # goma actúan. Trabajamos en desviaciones sobre el equilibrio,
            # así que el despegue no es comp = 0 (esa es la compresión
            # nominal en parado) sino f_desviación = -carga_estática.
            f_tire_v[i] = max(-self._static_fz[i],
                              cfg.TIRE_VERT_STIFF * comp
                              + cfg.TIRE_VERT_DAMP * comp_v)
            # la rueda también vive en el sistema de la carretera: la
            # rasante (a_road) la acelera igual que al chasis
            zu_acc = (f_tire_v[i] - f_susp[i]) / cfg.UNSPRUNG_MASS - a_road
            st.zu_v[i] += zu_acc * dt
            st.zu[i] += st.zu_v[i] * dt

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
            # la carga de contacto sale del MUELLE DEL NEUMÁTICO (no del
            # de suspensión): si la goma se despega del asfalto, Fz = 0
            # aunque el muelle de suspensión siga empujando la mangueta
            st.fz[i] = max(0.0, self._static_fz[i] + f_tire_v[i] + aero + geo)

        # --- dinámica vertical del chasis -------------------------------
        sum_f = sum(f_susp)
        sum_mx = sum(f_susp[i] * self.X_POS[i] for i in range(4))
        sum_my = sum(f_susp[i] * self.Y_POS[i] for i in range(4))
        # peralte: la aceleración lateral tiene una componente que aprieta
        # el coche CONTRA el asfalto inclinado (multiplica las cargas y el
        # agarre en un óvalo peraltado); la gravedad normal se reduce un
        # poco con la inclinación (cos). En llano press = 0 exacto.
        press = m * (st.ay * sin_b + G * (math.cos(bank) - 1.0))
        heave_acc = sum_f / m - a_road - press / m
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
        # el momento de balanceo lo generan las fuerzas laterales de los
        # neumáticos a nivel del suelo (no la aceleración neta): así, en un
        # peralte la carrocería se tumba hacia el lado bajo aunque el coche
        # vaya recto, igual que el cabeceo funciona parado en pendiente
        roll_acc = (sum_my + self._fy_tires * cfg.CAR_CG_HEIGHT) / cfg.CAR_INERTIA_ROLL
        # --- PRECESION GIROSCOPICA de las ruedas -------------------------
        # Cada rueda es un giróscopo: su momento angular de giro L = I·ω
        # apunta según su eje (transversal). Al girar ese eje —guiñada del
        # coche, y en las delanteras también la propia dirección— aparece un
        # par de precesión perpendicular a ambos: un MOMENTO DE BALANCEO.
        # Con el convenio de aquí (guiñada + = derecha, balanceo + = lado
        # derecho elevado) el par sale +yaw_rate·L, o sea que SUMA al
        # balanceo de la curva. En un coche es un efecto pequeño frente a
        # las fuerzas del neumático; en moto sería dominante.
        gyro_g = getattr(cfg, "GYRO_GAIN", 0.0)
        if gyro_g > 0.0:
            # las delanteras giran además con el volante: su eje precesa a
            # (guiñada + velocidad de giro de la dirección)
            l_front = sum(self.I_w[i] * st.omega[i] for i in (FL, FR))
            l_rear = sum(self.I_w[i] * st.omega[i] for i in (RL, RR))
            self._l_front = l_front
            rate_f = st.yaw_rate + self._steer_rate_lp / cfg.STEER_RATIO
            m_gyro = gyro_g * (rate_f * l_front + st.yaw_rate * l_rear)
            st.gyro_roll_moment = m_gyro
            roll_acc += m_gyro / cfg.CAR_INERTIA_ROLL
        else:
            self._l_front = 0.0
            st.gyro_roll_moment = 0.0
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

        om_mean = 0.0
        if ratio != 0.0 and driven:
            om_mean = sum(st.omega[i] for i in driven) / len(driven)
            rpm_wheels = abs(om_mean) * abs(ratio) * 60.0 / (2.0 * math.pi)
        else:
            rpm_wheels = 0.0

        if getattr(cfg, "ENGINE_MODEL", "legacy") == "inertia":
            # el cigüeñal es un grado de libertad propio + embrague de verdad
            t_wheel_total, clutch_slipping = self._engine_inertia(
                st, throttle, ratio, om_mean, rpm_wheels, dt)
        else:
            clutch_slipping = rpm_wheels < cfg.ENGINE_IDLE_RPM
            # el régimen sigue a las ruedas con inercia (filtro de 0.12 s)
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

        # CORTE DE PAR en el cambio: durante los primeros ms tras engranar,
        # el par a las ruedas cae casi a cero (embrague/inyección) y se
        # recupera de forma progresiva. Es el tirón real de cada cambio; sin
        # esto el cambio era instantáneo y liso.
        if self._shift_cut > 0.0 and cfg.SHIFT_CUT_TIME > 0.0:
            frac = min(1.0, self._shift_cut / cfg.SHIFT_CUT_TIME)
            t_wheel_total *= 1.0 - 0.9 * frac

        split_f, split_r = self._axle_torque_split()
        t_fl, t_fr = self._diff_torques(t_wheel_total * split_f,
                                        st.omega[FL], st.omega[FR],
                                        dt, self.I_w[FL])
        t_rl, t_rr = self._diff_torques(t_wheel_total * split_r,
                                        st.omega[RL], st.omega[RR],
                                        dt, self.I_w[RL])
        t_drive = [t_fl, t_fr, t_rl, t_rr]
        if ratio == 0.0:
            t_drive = [0.0] * 4

        # --- par de freno por rueda (con ABS) ---------------------------
        t_brake_max = [0.0] * 4
        per_front = cfg.BRAKE_FORCE_MAX * cfg.BRAKE_BIAS_FRONT / 2.0 * R_w[0]
        per_rear = cfg.BRAKE_FORCE_MAX * (1.0 - cfg.BRAKE_BIAS_FRONT) / 2.0 \
            * R_w[2]
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
        tire_brush = getattr(cfg, "TIRE_MODEL", "legacy") == "brush"
        # rigidez longitudinal para el régimen de rodadura estable (más abajo):
        # en brush usa la forma longitudinal propia, en legacy la compartida
        tb_long = cfg.TIRE_B_LONG if tire_brush else cfg.TIRE_B
        tc_long = cfg.TIRE_C_LONG if tire_brush else cfg.TIRE_C
        fx_w = [0.0] * 4
        fy_w = [0.0] * 4
        grip_used = [0.0] * 4
        for i in range(4):
            # velocidad del punto de contacto (chasis)
            vxi = st.vx - st.yaw_rate * self.Y_POS[i]
            vyi = st.vy + st.yaw_rate * self.X_POS[i]
            # todas las ruedas pueden ir giradas: las delanteras por la
            # dirección y las cuatro por su convergencia
            v_along = vxi * cos_w[i] + vyi * sin_w[i]
            v_side = -vxi * sin_w[i] + vyi * cos_w[i]
            denom = max(abs(v_along), 1.5)
            slip = (st.omega[i] * R_w[i] - v_along) / denom
            alpha = math.atan2(v_side, max(abs(v_along), 1.5))
            st.slip_ratio[i] = slip
            st.slip_angle[i] = alpha

            # --- CAIDA (camber) de esta rueda respecto al ASFALTO ---------
            # Se suman cuatro aportaciones, y lo que importa siempre es el
            # ángulo RESULTANTE contra el suelo, no cada una por separado:
            #  1. CAIDA ESTATICA: la que lleva de reglaje, parada y en recta.
            #     Negativa = la rueda "abraza" el coche por arriba. Se pone
            #     precisamente para que la rueda EXTERIOR quede plana cuando
            #     la carrocería se tumbe en curva.
            #  2. BALANCEO: la carrocería se tumba hacia FUERA y arrastra a
            #     las ruedas con ella (deshace la caída estática).
            #  3. CAMBER GAIN: al comprimirse, la geometría devuelve caída
            #     negativa (opuesto en cada lado).
            #  4. CASTER (solo el eje directriz): la ganada al girar.
            side = 1.0 if self.Y_POS[i] > 0.0 else -1.0
            gamma_st = math.radians(cfg.STATIC_CAMBER_FRONT_DEG if i < 2
                                    else cfg.STATIC_CAMBER_REAR_DEG)
            lean = side * gamma_st - st.roll \
                - side * cfg.SUSP_CAMBER_GAIN * st.susp_def[i]
            if i < 2:
                lean += caster_camber(delta, side)

            # EFECTO EN LA HUELLA: una rueda inclinada NO apoya plana. La
            # carga se concentra en un hombro, la huella efectiva se reduce y
            # el agarre disponible baja. La pérdida es CUADRATICA: un grado
            # apenas se nota (la goma absorbe la diferencia de presión), pero
            # a partir de tres o cuatro se dispara.
            #
            # Que sea cuadrática mientras el empuje por caída es LINEAL es lo
            # que crea el óptimo real del reglaje: para inclinaciones pequeñas
            # el empuje gana (compensa de sobra lo poco que cuesta la huella),
            # y a partir de cierto punto la huella manda y todo lo que se
            # añada resta. Ese equilibrio está en torno a 1 grado de caída
            # CONTRA EL ASFALTO en la rueda cargada, que es justo lo que
            # busca un ingeniero de pista. De ahí sale el compromiso:
            #   - En RECTA la rueda va inclinada su caída estática y pierde
            #     algo de agarre (frena y tracciona peor, desgasta el hombro).
            #   - En CURVA el balanceo la endereza hacia ese óptimo.
            #   - Pasarse de caída estática la inclina de más en ambos casos.
            # Penaliza el AGARRE disponible, no el empuje por caída: son
            # efectos distintos que conviven.
            patch = max(0.35, 1.0 - cfg.TIRE_CAMBER_PATCH * lean * lean)
            mu_i = mu_with_load(mu_wheel[i], st.fz[i], self._static_fz[i],
                                self._w_ls[i]) * patch
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
                if tire_brush:
                    # cada eje tiene SU curva: la forma (B, C) se interpola
                    # segun cuanto del deslizamiento es longitudinal (w) o
                    # lateral (1-w). Longitudinal puro -> B_long/C_long;
                    # lateral puro -> B_lat/C_lat. La elipse sigue acoplando
                    # ambos (no se puede el maximo en los dos a la vez).
                    w = (s_e * s_e) / (rho * rho)
                    bb = w * cfg.TIRE_B_LONG + (1.0 - w) * cfg.TIRE_B_LAT
                    cc = w * cfg.TIRE_C_LONG + (1.0 - w) * cfg.TIRE_C_LAT
                    f_total = mu_i * st.fz[i] * math.sin(cc * math.atan(bb * rho))
                else:
                    f_total = tire_force_magnitude(rho, mu_i, st.fz[i])
                fx = f_total * (s_e / rho) * ratio_l
                fy_ss = -f_total * (a_n / rho)
                grip_used[i] = min(1.0, rho)
            # EMPUJE POR CAIDA (camber thrust): una rueda inclinada genera
            # fuerza lateral hacia el lado al que se tumba aunque su deriva
            # sea cero, como una moto. Con el balanceo las ruedas se tumban
            # hacia FUERA y este empuje RESTA agarre lateral: castiga a los
            # coches altos y blandos (autobús, todoterreno) y apenas a los
            # rígidos (fórmula). La caída estática y el camber gain lo
            # compensan enderezando la rueda exterior en el apoyo.
            st.camber[i] = lean
            fy_ss += cfg.TIRE_CAMBER_THRUST * lean * st.fz[i]
            # retardo de respuesta lateral (relaxation length)
            blend = min(1.0, (vx_abs + 0.5) * dt / cfg.TIRE_RELAX_LENGTH)
            self._fy_state[i] += (fy_ss - self._fy_state[i]) * blend
            fx_w[i] = fx
            fy_w[i] = self._fy_state[i]
            # termodinámica: la potencia de fricción calienta la goma
            # (P = |F|·|v_deslizamiento|) y el aire la refrigera con la
            # velocidad (más un residuo de convección en parado)
            v_slip_mag = math.hypot(slip * denom, v_side)
            p_fric = math.hypot(fx, self._fy_state[i]) * v_slip_mag
            # tasa limitada: la masa térmica de la goma no permite subir
            # más de ~6 C/s ni en el derrape más salvaje
            # ...y la caída concentra el trabajo en un hombro, así que la
            # goma se calienta MAS que si apoyara plana. Es el desgaste
            # asimétrico clásico de un coche con mucha caída estática que
            # hace más kilómetros de recta que de curva.
            camber_heat = 1.0 + cfg.TIRE_CAMBER_HEAT * abs(lean)
            heat = min(6.0, cfg.TIRE_HEAT_GAIN * p_fric * self._w_heat[i]
                       * camber_heat)
            cool = cfg.TIRE_COOL_COEFF * (2.0 + vx_abs) \
                * (st.tire_temp[i] - cfg.TIRE_TEMP_AMB)
            st.tire_temp[i] += (heat - cool) * dt
            st.tire_temp[i] = max(cfg.TIRE_TEMP_AMB,
                                  min(160.0, st.tire_temp[i]))

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
        fy_front = 0.0
        yaw_moment = 0.0
        for i in range(4):
            fx_b = fx_w[i] * cos_w[i] - fy_w[i] * sin_w[i]
            fy_b = fx_w[i] * sin_w[i] + fy_w[i] * cos_w[i]
            if i < 2:
                fy_front += fy_b
            fx_total += fx_b
            fy_total += fy_b
            yaw_moment += self.X_POS[i] * fy_b - self.Y_POS[i] * fx_b

        # guardar las sumas de fuerzas de neumático para el cabeceo, el
        # balanceo y la torsión del chasis del siguiente paso
        self._fx_tires = fx_total
        self._fy_tires = fy_total
        self._fy_front = fy_front

        # peralte: la gravedad empuja el coche hacia el lado bajo del
        # asfalto (hacia el vértice si el peralte está bien construido:
        # se puede curvar más rápido con el mismo neumático)
        gravity_y = m * G * sin_b

        st.ax = (fx_total - drag - rolling + gravity_x) / m
        st.ay = (fy_total + gravity_y) / m
        vy_dot = (fy_total + gravity_y) / m - st.vx * st.yaw_rate
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
            v_along = vxi * cos_w[i] \
                + (st.vy + st.yaw_rate * self.X_POS[i]) * sin_w[i]
            omega_free = v_along / R_w[i]
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
                i_eff = self.I_w[i] \
                    + cfg.ENGINE_INERTIA * ratio * ratio / len(driven)
            else:
                i_eff = self.I_w[i]
            mu_i = mu_with_load(mu_wheel[i], st.fz[i], self._static_fz[i],
                                self._w_ls[i])
            grip_force = mu_i * st.fz[i] * cfg.TIRE_LONG_GRIP_RATIO
            slip_now = (st.omega[i] * R_w[i] - v_along) / denom
            deep_slip = abs(slip_now) > 0.9 * peak_s \
                or abs(t_app) / R_w[i] > 0.9 * grip_force
            if not deep_slip and st.fz[i] > 50.0:
                # régimen de rodadura (fricción estática): relajación
                # exponencial exacta al deslizamiento de equilibrio, que
                # transmite el par aplicado al suelo. Incondicionalmente
                # estable a cualquier dt.
                k_v = grip_force * tc_long * tb_long / (peak_s * denom)
                tau = i_eff / (k_v * R_w[i] * R_w[i])
                omega_eq = (v_along + (t_app / R_w[i]) / k_v) / R_w[i]
                blend = math.exp(-dt / tau) if tau > 1e-6 else 0.0
                new_omega = omega_eq + (st.omega[i] - omega_eq) * blend
            else:
                # deslizamiento profundo (bloqueo o patinaje): integración
                # explícita con la fuerza de la curva del neumático
                t_net = t_app - fx_w[i] * R_w[i]
                new_omega = st.omega[i] + t_net / i_eff * dt
                # si cruza la rodadura libre sin par para seguir deslizando,
                # vuelve al régimen de rodadura
                if (st.omega[i] - omega_free) * (new_omega - omega_free) < 0.0 \
                        and abs(t_app) < grip_force * R_w[i]:
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

        # balance dinámico subviraje/sobreviraje (0..1), en "unidades de
        # pico" de deriva: el eje que MÁS pasado del pico va marca la
        # tendencia. Subviraje = el delantero se va antes; sobreviraje =
        # el trasero (por deriva o por patinaje de tracción). Solo cuenta
        # si hay deriva real (no patinaje en línea recta) y a velocidad de
        # conducción. Es la señal que alimentan el chirrido y el ADAS.
        af = max(abs(st.slip_angle[FL]), abs(st.slip_angle[FR])) / peak_a
        ar = max(abs(st.slip_angle[RL]), abs(st.slip_angle[RR])) / peak_a
        sr_rear = max(abs(st.slip_ratio[RL]), abs(st.slip_ratio[RR])) / peak_s
        rear_axle = max(ar, sr_rear * 0.5)   # el patinaje pesa la mitad
        # el aviso arranca en la APROXIMACIÓN al límite (ADAS_WARN_FROM del
        # pico), no una vez pasado: así da tiempo a corregir. El eje que se
        # va antes marca la tendencia; en equilibrio neutro (ambos ejes
        # igual de cargados) no se marca ninguno, evitando el pitido
        # constante en el apoyo balanceado.
        floor = getattr(cfg, "ADAS_WARN_FROM", 0.72)
        if max(af, ar) > 0.5 and vx_abs > 6.0:
            st.understeer = max(0.0, min(1.0, af - max(rear_axle, floor)))
            st.oversteer = max(0.0, min(1.0, rear_axle - max(af, floor)))
        else:
            st.understeer = 0.0
            st.oversteer = 0.0

        # --- par en la columna para el force feedback -------------------
        # El brazo de palanca son DOS avances independientes que se suman:
        # el NEUMATICO (nace de la deformación, se derrumba con la deriva) y
        # el MECANICO (geometría del caster, constante). Que el primero caiga
        # y el segundo no es lo que hace que el par de autoalineado alcance su
        # máximo ANTES que la fuerza lateral: el volante se aligera como aviso
        # anticipado de subviraje, pero nunca queda muerto.
        mz = 0.0
        for i in (FL, FR):
            trail = pneumatic_trail(st.slip_angle[i]) + mechanical_trail(R_w[i])
            mz += -fy_w[i] * trail
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
        # reacción giroscópica en la DIRECCION: al balancear la carrocería,
        # el eje de giro de las ruedas delanteras precesa alrededor del eje
        # longitudinal y devuelve un par alrededor del pivote de dirección
        # (M = ω_balanceo × L). Es el "peso vivo" que se nota al cambiar de
        # apoyo rápido a alta velocidad.
        gyro_ffb = getattr(cfg, "GYRO_FFB_GAIN", 0.0)
        t_gyro = 0.0
        if gyro_ffb > 0.0:
            t_gyro = gyro_ffb * st.roll_v * getattr(self, "_l_front", 0.0) \
                / cfg.STEER_RATIO
        raw_torque = mz / cfg.STEER_RATIO * 2.0 + self._bump_kick + damping \
            + t_gyro
        # suavizado final del par: corta la excitación de alta frecuencia
        # que produce bandazos del volante en recta (FFB_SMOOTHING_S)
        if cfg.FFB_SMOOTHING_S > 1e-4:
            blend_t = min(1.0, dt / cfg.FFB_SMOOTHING_S)
            self._torque_lp += (raw_torque - self._torque_lp) * blend_t
            st.steer_column_torque = self._torque_lp
        else:
            st.steer_column_torque = raw_torque
