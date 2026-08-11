"""Pruebas del modelo físico de 4 ruedas (sin SDL, ejecutable en cualquier
sistema):  python tests/test_physics.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import config as cfg
from simulator import physics
from simulator.physics import Car, FL, FR, RL, RR
from simulator.track import Track

DT = 1.0 / cfg.PHYSICS_HZ


class FlatTrack:
    """Pista recta, llana y de asfalto infinito para pruebas controladas."""

    def surface_at(self, n, s):
        return "road", cfg.TIRE_MU

    def kappa_at(self, s):
        return 0.0

    def grade_at(self, s):
        return 0.0

    def vcurv_at(self, s):
        return 0.0

    def bump_at(self, s, n, surface):
        return 0.0


class SlopeTrack(FlatTrack):
    def __init__(self, grade=0.0, vcurv=0.0):
        self.grade = grade
        self.vcurv = vcurv

    def grade_at(self, s):
        return self.grade

    def vcurv_at(self, s):
        return self.vcurv


class GrassRightTrack(FlatTrack):
    """Hierba solo a la derecha del centro (n > 0)."""

    def surface_at(self, n, s):
        if n > 0:
            return "grass", cfg.TIRE_MU_GRASS
        return "road", cfg.TIRE_MU


class BankTrack(FlatTrack):
    """Pista con peralte (y opcionalmente curvatura) constantes."""

    def __init__(self, bank=0.0, kappa=0.0):
        self.bank = bank
        self.kappa = kappa

    def bank_at(self, s):
        return self.bank

    def kappa_at(self, s):
        return self.kappa


def settle(car, track, seconds=1.0):
    for _ in range(int(seconds / DT)):
        car.step(DT, 0.0, 0.0, 0.0, track)


def set_speed(car, v):
    st = car.state
    st.vx = v
    for i in range(4):
        st.omega[i] = v / cfg.CAR_WHEEL_RADIUS
    # engranar la marcha que deje el motor a un régimen razonable
    st.gear = 1
    for g in range(len(cfg.GEAR_RATIOS), 0, -1):
        ratio = cfg.GEAR_RATIOS[g - 1] * cfg.FINAL_DRIVE
        rpm = v / cfg.CAR_WHEEL_RADIUS * ratio * 60.0 / (2 * math.pi)
        if rpm > 2500.0 or g == 1:
            st.gear = g
            break


def hooked_up(car):
    """True si ninguna rueda motriz patina (para cambiar de marcha)."""
    return max(car.state.slip_ratio) < 0.5


def run(car, track, seconds, steer=0.0, throttle=0.0, brake=0.0,
        auto_shift=False):
    for _ in range(int(seconds / DT)):
        if auto_shift and car.state.rpm > 6300 and hooked_up(car):
            car.shift_up()
        car.step(DT, steer, throttle, brake, track)


def check(name, cond, detail=""):
    status = "OK " if cond else "FALLO"
    print(f"[{status}] {name} {detail}")
    return cond


def main():
    results = []
    flat = FlatTrack()
    # las pruebas del circuito usan el trazado integrado (determinista)
    cfg.TRACK_FILE = ""

    # ------------------------------------------------------------------
    print("--- Aceleracion y frenada ---")
    car = Car()
    settle(car, flat, 1.0)
    t = 0.0
    while car.state.speed_kmh < 100.0 and t < 15.0:
        if car.state.rpm > 6300 and hooked_up(car):
            car.shift_up()
        car.step(DT, 0.0, 1.0, 0.0, flat)
        t += DT
    results.append(check("0-100 km/h en 4-9 s", 4.0 < t < 9.0, f"t={t:.1f}s"))

    run(car, flat, 12.0, throttle=1.0, auto_shift=True)
    vmax = car.state.speed_kmh
    results.append(check("alcanza >170 km/h", vmax > 170.0, f"v={vmax:.0f}"))

    # frenada con ABS
    cfg.ABS_ENABLED = True
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 100 / 3.6)
    dist0 = car.state.s
    t = 0.0
    abs_seen = False
    while car.state.vx > 1.0 and t < 10.0:
        car.step(DT, 0.0, 0.0, 1.0, flat)
        abs_seen = abs_seen or car.state.abs_active
        t += DT
    d_abs = car.state.s - dist0
    results.append(check("frenada 100-0 con ABS 33-60 m", 33.0 < d_abs < 60.0,
                         f"d={d_abs:.1f}m"))
    results.append(check("el ABS ha actuado", abs_seen))

    # frenada sin ABS: las ruedas se bloquean y frena PEOR
    cfg.ABS_ENABLED = False
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 100 / 3.6)
    dist0 = car.state.s
    locked_seen = False
    t = 0.0
    while car.state.vx > 1.0 and t < 12.0:
        car.step(DT, 0.0, 0.0, 1.0, flat)
        locked_seen = locked_seen or car.state.front_locked
        t += DT
    d_lock = car.state.s - dist0
    results.append(check("sin ABS se bloquean las ruedas", locked_seen))
    results.append(check("bloqueado frena peor que con ABS", d_lock > d_abs,
                         f"{d_lock:.1f}m vs {d_abs:.1f}m"))

    # bloqueo delantero = sin capacidad directriz
    cfg.ABS_ENABLED = False
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 90 / 3.6)
    yaw_locked = 0.0
    for _ in range(int(2.0 / DT)):
        car.step(DT, 0.4, 0.0, 1.0, flat)  # frenada a fondo + volante girado
        yaw_locked = max(yaw_locked, abs(car.state.yaw_rate))
    car2 = Car()
    settle(car2, flat, 1.0)
    set_speed(car2, 90 / 3.6)
    yaw_free = 0.0
    for _ in range(int(2.0 / DT)):
        car2.step(DT, 0.4, 0.0, 0.0, flat)  # mismo volante sin frenar
        yaw_free = max(yaw_free, abs(car2.state.yaw_rate))
    results.append(check("bloqueo delantero anula la direccion",
                         yaw_locked < 0.35 * yaw_free,
                         f"giro frenando={yaw_locked:.2f} vs libre={yaw_free:.2f}"))
    cfg.ABS_ENABLED = True

    # ------------------------------------------------------------------
    print("--- Suspension y transferencias ---")
    car = Car()
    settle(car, flat, 1.5)
    st = car.state
    total = sum(st.fz)
    results.append(check("cargas estaticas suman el peso",
                         abs(total - cfg.CAR_MASS * 9.81) < 600.0,
                         f"total={total:.0f}N"))

    # curva a la derecha sostenida: cargan las ruedas IZQUIERDAS (exteriores)
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 22.0)
    run(car, flat, 2.0, steer=0.12, throttle=0.25)
    st = car.state
    left = st.fz[FL] + st.fz[RL]
    right = st.fz[FR] + st.fz[RR]
    results.append(check("curva dcha carga ruedas izquierdas", left > right * 1.15,
                         f"izda={left:.0f} dcha={right:.0f}"))

    # frenada: carga el eje delantero
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 30.0)
    for _ in range(int(0.6 / DT)):
        car.step(DT, 0.0, 0.0, 0.8, flat)
    st = car.state
    front = st.fz[FL] + st.fz[FR]
    rear = st.fz[RL] + st.fz[RR]
    static_front = cfg.CAR_MASS * 9.81 * cfg.CAR_CG_TO_REAR / \
        (cfg.CAR_CG_TO_FRONT + cfg.CAR_CG_TO_REAR)
    results.append(check("frenada carga el eje delantero",
                         front > static_front + 800.0,
                         f"del={front:.0f} tras={rear:.0f}"))

    # cresta: descarga la suspension
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 35.0)
    crest = SlopeTrack(grade=0.0, vcurv=-0.004)
    for _ in range(int(1.0 / DT)):
        car.step(DT, 0.0, 0.3, 0.0, crest)
    total_crest = sum(car.state.fz)
    results.append(check("cresta descarga el coche",
                         total_crest < cfg.CAR_MASS * 9.81 * 0.75,
                         f"carga={total_crest:.0f}N vs peso={cfg.CAR_MASS*9.81:.0f}N"))

    # reparto de pesos derivado de la configuracion (ficha tecnica)
    car = Car()
    settle(car, flat, 1.5)
    st = car.state
    front_share = (st.fz[FL] + st.fz[FR]) / max(1.0, sum(st.fz))
    results.append(check("reparto estatico = WEIGHT_DIST_FRONT",
                         abs(front_share - cfg.WEIGHT_DIST_FRONT) < 0.02,
                         f"medido={front_share:.3f} config={cfg.WEIGHT_DIST_FRONT}"))

    # parado en bajada con freno: el morro se hunde (carga delantera extra)
    car = Car()
    downhill = SlopeTrack(grade=-0.10)
    for _ in range(int(3.0 / DT)):
        car.step(DT, 0.0, 0.0, 1.0, downhill)
    st = car.state
    front = st.fz[FL] + st.fz[FR]
    static_front = cfg.CAR_MASS * 9.81 * cfg.WEIGHT_DIST_FRONT
    results.append(check("parado cuesta abajo carga el morro",
                         front > static_front + 80.0,
                         f"del={front:.0f} estatico={static_front:.0f}"))
    results.append(check("parada rigida: sin jitter de ruedas",
                         all(abs(o) < 0.01 for o in st.omega) and abs(st.vx) < 0.2,
                         f"omega={[round(o, 3) for o in st.omega]}"))

    # downforce: a alta velocidad el coche pesa mas
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 50.0)
    for _ in range(int(1.5 / DT)):
        car.step(DT, 0.0, 0.5, 0.0, flat)
    total_fast = sum(car.state.fz)
    results.append(check("downforce anade carga a alta velocidad",
                         total_fast > cfg.CAR_MASS * 9.81 + 700.0,
                         f"carga={total_fast:.0f}N vs peso={cfg.CAR_MASS*9.81:.0f}N"))

    # pendiente: subir frena
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 25.0)
    car.state.gear = 0  # punto muerto
    uphill = SlopeTrack(grade=0.08)
    v0 = car.state.vx
    for _ in range(int(3.0 / DT)):
        car.step(DT, 0.0, 0.0, 0.0, uphill)
    decel_up = (v0 - car.state.vx) / 3.0
    results.append(check("la subida frena mas que el llano", decel_up > 0.9,
                         f"decel={decel_up:.2f} m/s2"))

    # freno motor: soltar gas en marcha decelera mas que en punto muerto
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 30.0)
    car.state.gear = 3
    v0 = car.state.vx
    run(car, flat, 3.0)
    decel_gear = (v0 - car.state.vx) / 3.0
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 30.0)
    car.state.gear = 0
    v0 = car.state.vx
    run(car, flat, 3.0)
    decel_neutral = (v0 - car.state.vx) / 3.0
    results.append(check("freno motor decelera mas que punto muerto",
                         decel_gear > decel_neutral + 0.15,
                         f"marcha={decel_gear:.2f} muerto={decel_neutral:.2f} m/s2"))

    # ------------------------------------------------------------------
    print("--- Equilibrio y tracciones ---")
    # subviraje estable con mucho volante
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 30.0)
    run(car, flat, 3.0, steer=0.35, throttle=0.15)
    st = car.state
    af = abs(math.degrees(st.alpha_front))
    ar = abs(math.degrees((st.slip_angle[RL] + st.slip_angle[RR]) / 2.0))
    results.append(check("pasado de volante: subvira (deriva del > tras)",
                         af > ar + 2.0, f"del={af:.1f} tras={ar:.1f} deg"))

    # RWD: gas a fondo en curva -> patina el eje trasero
    cfg.DRIVE_TYPE = "RWD"
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 14.0)
    car.state.gear = 2
    spin_rwd = False
    for _ in range(int(2.5 / DT)):
        car.step(DT, 0.25, 1.0, 0.0, flat)
        if max(car.state.slip_ratio[RL], car.state.slip_ratio[RR]) > 0.25:
            spin_rwd = True
    results.append(check("RWD: patinaje trasero acelerando en curva", spin_rwd))

    # FWD: mismo caso -> patinan las delanteras, no las traseras
    cfg.DRIVE_TYPE = "FWD"
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 14.0)
    car.state.gear = 2
    spin_f, spin_r = 0.0, 0.0
    for _ in range(int(2.5 / DT)):
        car.step(DT, 0.25, 1.0, 0.0, flat)
        spin_f = max(spin_f, car.state.slip_ratio[FL], car.state.slip_ratio[FR])
        spin_r = max(spin_r, car.state.slip_ratio[RL], car.state.slip_ratio[RR])
    results.append(check("FWD: patinan las delanteras", spin_f > 0.25,
                         f"del={spin_f:.2f}"))
    results.append(check("FWD: las traseras no patinan", spin_r < 0.1,
                         f"tras={spin_r:.2f}"))

    # AWD: acelera mas fuerte desde parado que RWD (reparte la traccion)
    def launch_time(drive):
        cfg.DRIVE_TYPE = drive
        c = Car()
        settle(c, flat, 1.0)
        t = 0.0
        while c.state.speed_kmh < 60.0 and t < 10.0:
            if c.state.rpm > 6300 and hooked_up(c):
                c.shift_up()
            c.step(DT, 0.0, 1.0, 0.0, flat)
            t += DT
        return t

    t_awd = launch_time("AWD")
    t_rwd = launch_time("RWD")
    results.append(check("AWD sale de parado igual o mejor que RWD",
                         t_awd <= t_rwd + 0.1,
                         f"awd={t_awd:.2f}s rwd={t_rwd:.2f}s"))
    cfg.DRIVE_TYPE = "RWD"

    # diferencial: el abierto limita la traccion con cargas asimetricas
    def accel_with_diff(diff):
        cfg.DIFF_TYPE = diff
        c = Car()
        settle(c, flat, 1.0)
        set_speed(c, 12.0)
        c.state.gear = 2
        run(c, flat, 2.0, steer=0.20, throttle=1.0)
        return c.state.vx

    v_locked = accel_with_diff("locked")
    v_open = accel_with_diff("open")
    results.append(check("diferencial bloqueado tracciona igual o mas que abierto",
                         v_locked >= v_open - 0.2,
                         f"locked={v_locked:.1f} open={v_open:.1f} m/s"))
    cfg.DIFF_TYPE = "lsd"

    # media pista de hierba: el coche tira hacia un lado al frenar
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 25.0)
    grass_r = GrassRightTrack()
    for _ in range(int(1.5 / DT)):
        car.step(DT, 0.0, 0.0, 0.7, grass_r)
    results.append(check("frenar con hierba a la derecha desvia el coche",
                         abs(car.state.yaw_rate) > 0.03 or abs(car.state.psi) > 0.01,
                         f"yaw={car.state.yaw_rate:.3f} psi={car.state.psi:.3f}"))

    # ------------------------------------------------------------------
    print("--- peralte y caida (camber) ---")

    # peralte sin girar: la gravedad empuja el coche hacia el lado bajo
    # (bank > 0 = borde izquierdo elevado -> resbala hacia la derecha, +n)
    car = Car()
    banked = BankTrack(bank=math.radians(10.0))
    settle(car, flat, 1.0)
    set_speed(car, 30.0)
    run(car, banked, 2.5, steer=0.0, throttle=0.25)
    results.append(check("el peralte empuja hacia el lado bajo",
                         car.state.n > 0.4,
                         f"n={car.state.n:.2f} m"))

    # curva peraltada vs llana al mismo paso: el peralte aprieta el coche
    # contra el suelo (mas carga) y el neumatico trabaja menos
    def corner(track_obj):
        c = Car()
        settle(c, flat, 1.0)
        set_speed(c, 30.0)
        grip_acc, fz_acc, steps = 0.0, 0.0, 0
        for k in range(int(3.0 / DT)):
            st = c.state
            steer = max(-0.6, min(0.6, 0.11 - st.psi * 0.5 - st.n * 0.03))
            c.step(DT, steer, 0.35, 0.0, track_obj)
            if k > int(1.5 / DT):
                grip_acc += st.front_grip_used
                fz_acc += sum(st.fz)
                steps += 1
        return grip_acc / steps, fz_acc / steps, c.state.n

    kappa_c = 1.0 / 110.0
    g_flat, fz_flat, n_flat = corner(BankTrack(bank=0.0, kappa=kappa_c))
    g_bank, fz_bank, n_bank = corner(BankTrack(bank=math.radians(14.0),
                                               kappa=kappa_c))
    results.append(check("curva peraltada carga mas el coche",
                         fz_bank > fz_flat * 1.03,
                         f"fz={fz_bank:.0f} vs llano {fz_flat:.0f} N"))
    results.append(check("el peralte alivia el trabajo del neumatico",
                         g_bank < g_flat - 0.05,
                         f"uso agarre={g_bank:.2f} vs llano {g_flat:.2f}"))

    # camber thrust: al tumbarse la carroceria en el apoyo pierde agarre
    # lateral -> con el mismo volante, gira menos que sin el efecto
    def steady_yaw(camber):
        old = cfg.TIRE_CAMBER_THRUST
        cfg.TIRE_CAMBER_THRUST = camber
        # aisla la caida por BALANCEO: sin esto, la caida ganada al girar por
        # el caster (que va en sentido contrario, a favor de la curva)
        # compensaria parte del efecto y la prueba mediria la suma de ambos
        old_cc = cfg.CASTER_CAMBER_GAIN
        cfg.CASTER_CAMBER_GAIN = 0.0
        c = Car()
        settle(c, flat, 1.0)
        set_speed(c, 25.0)
        acc, steps = 0.0, 0
        for k in range(int(2.5 / DT)):
            c.step(DT, 0.35, 0.3, 0.0, flat)
            if k > int(1.5 / DT):
                acc += abs(c.state.yaw_rate)
                steps += 1
        cfg.TIRE_CAMBER_THRUST = old
        cfg.CASTER_CAMBER_GAIN = old_cc
        return acc / steps

    yaw_no_camber = steady_yaw(0.0)
    yaw_camber = steady_yaw(0.9)
    results.append(check("la caida por balanceo resta giro (subvira)",
                         yaw_camber < yaw_no_camber * 0.99,
                         f"yaw={yaw_camber:.3f} vs sin efecto {yaw_no_camber:.3f}"))

    # ------------------------------------------------------------------
    print("--- masas no suspendidas y temperatura ---")

    # sobre un piano corrugado a velocidad, la rueda (masa no suspendida)
    # no puede seguir los dientes: "vuela" y la carga de contacto cae casi
    # a cero aunque el chasis apenas se entere
    class KerbTrack(FlatTrack):
        def surface_at(self, n, s):
            return "kerb", cfg.TIRE_MU * 0.92

        def bump_at(self, s, n, surface):
            return 0.028 * max(0.0, math.sin(s * (2 * math.pi / 0.4)))

    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 20.0)
    kerb = KerbTrack()
    min_fz = 1e9
    max_heave = 0.0
    max_zu = 0.0
    for k in range(int(1.0 / DT)):
        car.step(DT, 0.0, 0.2, 0.0, kerb)
        if k > int(0.3 / DT):
            min_fz = min(min_fz, min(car.state.fz[0], car.state.fz[1]))
            max_heave = max(max_heave, abs(car.state.heave))
            max_zu = max(max_zu, max(abs(z) for z in car.state.zu))
    static_f = cfg.CAR_MASS * 9.81 * cfg.WEIGHT_DIST_FRONT / 2.0
    results.append(check("la rueda vuela sobre el piano corrugado",
                         min_fz < static_f * 0.45,
                         f"fz min={min_fz:.0f} N (estatica {static_f:.0f})"))
    results.append(check("el chasis filtra el piano (no lo copia)",
                         max_heave < 0.02, f"heave max={max_heave*1000:.1f} mm"))
    # en el aire el neumatico no tira de la rueda hacia el suelo: el
    # recorrido de la masa no suspendida queda acotado (sin explosiones)
    results.append(check("la rueda en el aire queda acotada",
                         max_zu < 0.12, f"zu max={max_zu*1000:.0f} mm"))

    # derrapar calienta la goma; rodar tranquilo la enfria
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 15.0)
    for k in range(int(6.0 / DT)):
        car.step(DT, 0.5, 1.0, 0.0, flat)
    t_hot = max(car.state.tire_temp)
    for k in range(int(20.0 / DT)):
        car.step(DT, 0.0, 0.25, 0.0, flat)
    t_cool = max(car.state.tire_temp)
    results.append(check("derrapar calienta la goma", t_hot > 75.0,
                         f"T={t_hot:.0f} C tras 6 s de derrape"))
    results.append(check("el aire enfria la goma en marcha",
                         t_cool < t_hot - 5.0,
                         f"T={t_cool:.0f} C tras 20 s tranquilos"))

    # la goma fria rinde menos que a temperatura optima
    def yaw_at_temp(temp):
        c = Car()
        settle(c, flat, 1.0)
        set_speed(c, 25.0)
        acc, steps = 0.0, 0
        for k in range(int(2.0 / DT)):
            for i in range(4):
                c.state.tire_temp[i] = temp   # forzada: aislar el efecto
            c.step(DT, 0.35, 0.3, 0.0, flat)
            if k > int(1.2 / DT):
                acc += abs(c.state.yaw_rate)
                steps += 1
        return acc / steps

    y_cold = yaw_at_temp(25.0)
    y_opt = yaw_at_temp(cfg.TIRE_TEMP_OPT)
    results.append(check("la goma fria agarra menos", y_cold < y_opt * 0.97,
                         f"yaw={y_cold:.3f} vs {y_opt:.3f} en optimo"))

    # el camber gain endereza la rueda exterior y recupera agarre
    def yaw_camber_gain(gain):
        old = cfg.SUSP_CAMBER_GAIN
        cfg.SUSP_CAMBER_GAIN = gain
        c = Car()
        settle(c, flat, 1.0)
        set_speed(c, 25.0)
        acc, steps = 0.0, 0
        for k in range(int(2.5 / DT)):
            c.step(DT, 0.35, 0.3, 0.0, flat)
            if k > int(1.5 / DT):
                acc += abs(c.state.yaw_rate)
                steps += 1
        cfg.SUSP_CAMBER_GAIN = old
        return acc / steps

    y_rigid = yaw_camber_gain(0.0)
    y_geo = yaw_camber_gain(1.6)
    results.append(check("el camber gain recupera agarre en el apoyo",
                         y_geo > y_rigid * 1.003,
                         f"yaw={y_geo:.3f} vs {y_rigid:.3f} sin geometria"))

    # ------------------------------------------------------------------
    print("--- balance: subviraje / sobreviraje ---")

    # dirección creciente a velocidad fija: el delantero satura antes ->
    # la senal de subviraje sube y la de sobreviraje se queda en cero
    def balance_at(steer, thr, v, gear=None):
        c = Car()
        settle(c, flat, 0.5)
        set_speed(c, v)
        if gear:
            c.state.gear = gear
        for k in range(int(1.5 / DT)):
            c.step(DT, steer, thr, 0.0, flat)
        return c.state.understeer, c.state.oversteer

    u_soft, o_soft = balance_at(0.12, 0.3, 30.0)
    u_hard, o_hard = balance_at(0.30, 0.3, 30.0)
    results.append(check("el subviraje sube con la direccion",
                         u_hard > u_soft and u_hard > 0.3,
                         f"U {u_soft:.2f} -> {u_hard:.2f}"))
    results.append(check("subvirando no se marca sobreviraje",
                         o_hard < 0.05, f"O={o_hard:.2f}"))

    # aviso TEMPRANO: en la aproximación al límite (tren delantero cargado
    # ~90 % pero aún NO pasado del pico) el subviraje ya es no nulo, para
    # que el pitido ADAS dé margen a corregir antes del deslizamiento
    u_appr, o_appr = balance_at(0.14, 0.3, 30.0)
    results.append(check("el aviso arranca en la aproximacion al limite",
                         0.05 < u_appr < 0.35,
                         f"U={u_appr:.2f} (grip ~0.9, aun sin subvirar)"))

    # RWD a fondo en 2a con algo de volante: el trasero patina -> sobreviraje
    u_pow, o_pow = balance_at(0.15, 1.0, 14.0, gear=2)
    results.append(check("el sobreviraje se marca al patinar el trasero",
                         o_pow > 0.3, f"O={o_pow:.2f}"))

    # acelerar en linea RECTA (sin volante) no debe marcar balance: es
    # patinaje, no perdida de eje
    u_line, o_line = balance_at(0.0, 1.0, 14.0, gear=2)
    results.append(check("acelerar recto no marca sobreviraje",
                         o_line < 0.05, f"O={o_line:.2f}"))

    # ------------------------------------------------------------------
    print("--- FFB y circuito real ---")
    car = Car()
    settle(car, flat, 1.0)
    set_speed(car, 25.0)
    run(car, flat, 2.0, steer=0.12, throttle=0.2)
    tq_normal = abs(car.state.steer_column_torque)
    results.append(check("par de FFB presente en curva", 4.0 < tq_normal < 45.0,
                         f"par={tq_normal:.1f} Nm"))

    # vuelta al circuito real con un piloto trivial: no debe explotar nada
    track = Track()
    car = Car()
    settle(car, track, 1.0)
    steps = int(60.0 / DT)
    ok = True
    for k in range(steps):
        st = car.state
        kappa_ahead = track.kappa_at(st.s + 30.0)
        steer = max(-0.5, min(0.5, kappa_ahead * 18.0 - st.n * 0.02 - st.psi * 0.4))
        target = 20.0 if abs(kappa_ahead) < 0.005 else 11.0
        throttle = 0.5 if st.vx < target else 0.0
        brake = 0.5 if st.vx > target + 3.0 else 0.0
        if st.rpm > 6000:
            car.shift_up()
        car.step(DT, steer, throttle, brake, track)
        if not all(math.isfinite(x) for x in
                   (st.vx, st.vy, st.yaw_rate, st.heave, st.pitch, st.roll)):
            ok = False
            break
    results.append(check("60 s de conduccion en circuito sin divergencias", ok,
                         f"s={car.state.s:.0f}m v={car.state.speed_kmh:.0f}km/h"))
    results.append(check("el coche avanza por el circuito", car.state.s > 400.0,
                         f"s={car.state.s:.0f}m"))

    # ------------------------------------------------------------------
    print("--- Rigidez torsional del chasis ---")
    # En curva sostenida, con el tren delantero mucho más rígido que el
    # trasero (barra delantera gorda), un chasis RÍGIDO reacciona casi toda
    # la transferencia en el eje delantero; un chasis BLANDO desacopla los
    # ejes y la barra pierde autoridad -> baja la fracción delantera de la
    # transferencia (y con ella el subviraje). También: con chasis blando
    # debe aparecer torsión (twist != 0) y con rígido, no.
    old_arb_f, old_arb_r = cfg.ARB_FRONT, cfg.ARB_REAR
    old_kc = cfg.CHASSIS_TORSION_STIFF
    cfg.ARB_FRONT, cfg.ARB_REAR = 60000.0, 2000.0

    def front_share_and_twist(kc):
        cfg.CHASSIS_TORSION_STIFF = kc
        c = Car()
        settle(c, flat, 1.0)
        set_speed(c, 22.0)
        for _ in range(int(3.0 / DT)):
            c.step(DT, 0.30, 0.35, 0.0, flat)     # curva a la derecha
        s = c.state
        tf = s.fz[FL] - s.fz[FR]                  # transferencia delante
        tr = s.fz[RL] - s.fz[RR]                  # y detrás
        return tf / max(1e-6, tf + tr), s.chassis_twist

    share_rigid, twist_rigid = front_share_and_twist(0.0)
    share_soft, twist_soft = front_share_and_twist(4000.0)
    results.append(check("chasis rigido: sin torsion (comportamiento previo)",
                         abs(twist_rigid) < 1e-9,
                         f"twist={twist_rigid:.2e} rad"))
    results.append(check("chasis blando: aparece torsion del bastidor",
                         abs(twist_soft) > 1e-5,
                         f"twist={math.degrees(twist_soft):.3f} deg"))
    results.append(check("chasis blando: la barra delantera pierde autoridad",
                         share_soft < share_rigid - 0.01,
                         f"frac. delantera {share_rigid:.3f} -> {share_soft:.3f}"))
    cfg.ARB_FRONT, cfg.ARB_REAR = old_arb_f, old_arb_r
    cfg.CHASSIS_TORSION_STIFF = old_kc

    # ------------------------------------------------------------------
    print("--- Catalogo de ruedas (WHEEL_SPEC) ---")
    from simulator import garage
    ws = garage.parse_wheel_spec("205/55R16")
    # radio por definición: 16·25.4/2 + 205·0.55 = 203.2 + 112.75 = 315.95 mm
    results.append(check("radio exacto desde la designacion (205/55R16)",
                         abs(ws["radius"] - 0.31595) < 1e-4,
                         f"R={ws['radius']*1000:.1f} mm"))
    ws_big = garage.parse_wheel_spec("315/30R19")
    results.append(check("rueda mayor -> mas radio, masa e inercia",
                         ws_big["radius"] > ws["radius"]
                         and ws_big["mass"] > ws["mass"]
                         and ws_big["inertia"] > ws["inertia"],
                         f"I {ws['inertia']:.2f} -> {ws_big['inertia']:.2f} "
                         f"kg*m2"))
    ok_bad = False
    try:
        garage.parse_wheel_spec("gigante")
    except ValueError:
        ok_bad = True
    results.append(check("designacion invalida rechazada con aviso", ok_bad))

    # --- ancho -> agarre (sensibilidad a la carga y termica) ----------
    from simulator.physics import mu_with_load
    m_norm = mu_with_load(1.0, 6000.0, 4000.0)           # sobrecargada
    m_wide = mu_with_load(1.0, 6000.0, 4000.0, 0.66)     # goma ancha
    results.append(check("neumatico ancho: menos caida de mu al sobrecargar",
                         m_wide > m_norm,
                         f"mu {m_norm:.3f} -> {m_wide:.3f}"))

    def lateral_ab(width):
        cfg.TIRE_WIDTH_MM = width
        c = Car()
        settle(c, flat, 1.0)
        set_speed(c, 30.0)
        for _ in range(int(3.0 / DT)):
            c.step(DT, 0.5, 0.4, 0.0, flat)   # apoyo saturado
        return abs(c.state.ay), max(c.state.tire_temp)
    old_w = cfg.TIRE_WIDTH_MM
    ay_n, tmp_n = lateral_ab(155.0)
    ay_w, tmp_w = lateral_ab(305.0)
    results.append(check("neumatico ancho: mas apoyo lateral al limite",
                         ay_w > ay_n * 1.03,
                         f"ay {ay_n:.2f} -> {ay_w:.2f} m/s2"))
    # el factor termico se comprueba AISLADO (en pista el ancho tambien
    # agarra mas -> mas potencia de friccion, y los efectos se compensan)
    old_wr = getattr(cfg, "TIRE_WIDTH_MM_REAR", None)
    cfg.TIRE_WIDTH_MM = cfg.TIRE_WIDTH_MM_REAR = 155.0
    h_n = Car()._w_heat[0]
    cfg.TIRE_WIDTH_MM = cfg.TIRE_WIDTH_MM_REAR = 305.0
    h_w = Car()._w_heat[0]
    cfg.TIRE_WIDTH_MM = old_w
    cfg.TIRE_WIDTH_MM_REAR = old_wr
    results.append(check("neumatico ancho: mas masa termica (calienta menos "
                         "por unidad de trabajo)", h_w < h_n * 0.8,
                         f"factor {h_n:.2f} -> {h_w:.2f}"))

    # --- selector de monturas (apply_wheel consistente) ----------------
    DEP = "simulator/cars/3_deportivo.car"
    garage.load_car(DEP)
    r0, i0, m0 = cfg.CAR_WHEEL_RADIUS, cfg.CAR_WHEEL_INERTIA, cfg.UNSPRUNG_MASS
    old_keep = cfg.GEARING_KEEP_ON_WHEEL_CHANGE
    cfg.GEARING_KEEP_ON_WHEEL_CHANGE = False
    garage.apply_wheel("265/35R19", DEP)
    results.append(check("apply_wheel: radio, inercia y masa cambian juntos",
                         cfg.CAR_WHEEL_RADIUS > r0
                         and cfg.CAR_WHEEL_INERTIA > i0
                         and cfg.UNSPRUNG_MASS > m0
                         and abs(cfg.TIRE_WIDTH_MM - 265.0) < 1e-6,
                         f"R {r0:.3f}->{cfg.CAR_WHEEL_RADIUS:.3f} "
                         f"I {i0:.2f}->{cfg.CAR_WHEEL_INERTIA:.2f} "
                         f"m {m0:.1f}->{cfg.UNSPRUNG_MASS:.1f}"))
    opts = garage.wheel_options(DEP)
    results.append(check("catalogo: serie del coche + catalogo general",
                         len(opts) > 20 and "SERIE" in opts[0][1]
                         and any("AUTOBUS" in o[1] for o in opts)
                         and any("FORMULA 1" in o[1] for o in opts),
                         f"{len(opts)} monturas"))

    # --- ruedas DISTINTAS por eje (staggered) --------------------------
    garage.load_car(DEP)
    garage.apply_wheel("225/45R17", DEP, "305/30R20")
    results.append(check("montura por eje: delante y detras distintas",
                         cfg.CAR_WHEEL_RADIUS_REAR > cfg.CAR_WHEEL_RADIUS
                         and cfg.TIRE_WIDTH_MM_REAR > cfg.TIRE_WIDTH_MM,
                         f"R {cfg.CAR_WHEEL_RADIUS:.3f}/"
                         f"{cfg.CAR_WHEEL_RADIUS_REAR:.3f} m  ancho "
                         f"{cfg.TIRE_WIDTH_MM:.0f}/{cfg.TIRE_WIDTH_MM_REAR:.0f}"))
    c = Car()
    results.append(check("la fisica usa el radio y la inercia de cada eje",
                         c.R_w[FL] < c.R_w[RL] and c.I_w[FL] < c.I_w[RL]
                         and c._w_ls[RL] < c._w_ls[FL],
                         f"R_w={[round(r,3) for r in c.R_w]}"))
    # goma mas ancha DETRAS en un RWD: mas agarre trasero, asi que al limite
    # el eje trasero DERIVA MENOS (es el motivo real del montaje escalonado)
    def rear_slip(spec_r):
        garage.load_car(DEP)
        garage.apply_wheel("225/45R17", DEP, spec_r)
        cc = Car()
        settle(cc, flat, 1.0)
        set_speed(cc, 28.0)
        for _ in range(int(2.5 / DT)):
            cc.step(DT, 0.25, 0.30, 0.0, flat)
        return math.degrees(abs(cc.state.slip_angle[RL]))
    sl = [(s, rear_slip(s)) for s in
          ("205/55R16", "225/45R17", "275/35R17", "305/30R20")]
    monotona = all(sl[i][1] > sl[i + 1][1] for i in range(len(sl) - 1))
    results.append(check("goma trasera mas ancha -> el eje trasero deriva "
                         "menos (montaje escalonado)", monotona,
                         "  ".join(f"{s.split('/')[0]}:{v:.1f}gra"
                                   for s, v in sl)))

    # el desarrollo: SIN recalzar, la rueda grande alarga y resta empuje
    def launch(spec_r, keep):
        garage.load_car(DEP)
        cfg.GEARING_KEEP_ON_WHEEL_CHANGE = keep
        garage.apply_wheel("225/45R17", DEP, spec_r)
        cc = Car()
        settle(cc, flat, 1.0)
        d = 0.0
        for _ in range(int(3.0 / DT)):
            cc.step(DT, 0.0, 1.0, 0.0, flat)
            d += cc.state.vx * DT
        return d
    d_keep = launch("305/30R20", True)
    d_sin = launch("305/30R20", False)
    results.append(check("sin recalzar, la rueda grande alarga el desarrollo",
                         d_sin < d_keep,
                         f"{d_keep:.1f} m (recalzado) vs {d_sin:.1f} m (sin)"))
    # el grupo final compensa el recalzado (conserva el desarrollo)
    garage.load_car(DEP)
    fd0 = cfg.FINAL_DRIVE
    cfg.GEARING_KEEP_ON_WHEEL_CHANGE = True
    garage.apply_wheel("245/35R18", DEP, "325/30R21")
    results.append(check("recalzar reescala el grupo final (mismo desarrollo)",
                         cfg.FINAL_DRIVE > fd0,
                         f"{fd0:.2f} -> {cfg.FINAL_DRIVE:.2f}"))
    cfg.GEARING_KEEP_ON_WHEEL_CHANGE = old_keep

    # --- efecto giroscopico de las ruedas ------------------------------
    print("--- Precesion giroscopica ---")
    old_gyro = cfg.GYRO_GAIN
    garage.load_car(DEP)

    def roll_in_turn(gain):
        cfg.GYRO_GAIN = gain
        cc = Car()
        settle(cc, flat, 1.0)
        set_speed(cc, 45.0)
        for _ in range(int(2.0 / DT)):
            cc.step(DT, 0.22, 0.35, 0.0, flat)
        return cc.state.roll, cc.state.gyro_roll_moment
    roll_off, m_off = roll_in_turn(0.0)
    roll_on, m_on = roll_in_turn(1.0)
    results.append(check("sin giroscopo no hay par de precesion",
                         abs(m_off) < 1e-12, f"M={m_off:.2e} N*m"))
    results.append(check("girando a la derecha, la precesion SUMA al balanceo",
                         m_on > 0.0 and roll_on > roll_off,
                         f"M={m_on:.0f} N*m, balanceo {math.degrees(roll_off):.3f}"
                         f" -> {math.degrees(roll_on):.3f} grados"))
    # con rueda mayor (mas inercia) el par de precesion crece
    garage.apply_wheel("325/30R21", DEP)
    _, m_big = roll_in_turn(1.0)
    results.append(check("rueda mayor -> mas momento angular -> mas precesion",
                         m_big > m_on, f"{m_on:.0f} -> {m_big:.0f} N*m"))
    cfg.GYRO_GAIN = old_gyro

    # ------------------------------------------------------------------
    print("--- Angulo de avance (caster) ---")
    garage.load_car(DEP)
    old_caster = cfg.CASTER_ANGLE_DEG
    old_off = cfg.STEER_TRAIL_OFFSET
    old_ccg = cfg.CASTER_CAMBER_GAIN

    # el avance MECANICO es geometria pura: NO depende de la deriva
    t_mec = [physics.mechanical_trail(0.32) for _ in range(3)]
    a_ext = [0.0, math.radians(5.0), math.radians(20.0)]
    results.append(check("el avance mecanico no cae con la deriva",
                         len(set(t_mec)) == 1 and t_mec[0] > 0.0,
                         f"{t_mec[0]*1000:.1f} mm constante"))

    # ...mientras que el NEUMATICO se derrumba y llega a hacerse negativo
    t_pn = [physics.pneumatic_trail(a) for a in a_ext]
    results.append(check("el avance neumatico se derrumba y se hace negativo",
                         t_pn[0] > t_pn[1] > 0.0 > t_pn[2],
                         f"{t_pn[0]*1000:.1f} -> {t_pn[1]*1000:.1f} -> "
                         f"{t_pn[2]*1000:.1f} mm"))

    # geometria: t = R*tan(caster) + offset
    cfg.CASTER_ANGLE_DEG, cfg.STEER_TRAIL_OFFSET = 6.0, 0.0
    esperado = 0.32 * math.tan(math.radians(6.0))
    results.append(check("t_mecanico = R*tan(caster)",
                         abs(physics.mechanical_trail(0.32) - esperado) < 1e-9,
                         f"{physics.mechanical_trail(0.32)*1000:.2f} mm "
                         f"= {esperado*1000:.2f} mm"))

    # mas caster -> mas brazo -> volante mas pesado
    def par_en_apoyo(caster):
        cfg.CASTER_ANGLE_DEG = caster
        c = Car()
        settle(c, flat, 1.0)
        set_speed(c, 28.0)
        acc, n = 0.0, 0
        for k in range(int(2.5 / DT)):
            c.step(DT, 0.30, 0.30, 0.0, flat)
            if k > int(1.5 / DT):
                acc += abs(c.state.steer_column_torque)
                n += 1
        return acc / n

    par_poco, par_mucho = par_en_apoyo(2.0), par_en_apoyo(10.0)
    results.append(check("mas avance -> volante mas pesado",
                         par_mucho > par_poco * 1.3,
                         f"{par_poco:.1f} -> {par_mucho:.1f} N*m"))

    # el offset ajusta el avance mecanico SIN tocar el caster (ni la caida)
    cfg.CASTER_ANGLE_DEG = 6.0
    cfg.STEER_TRAIL_OFFSET = 0.02
    t_con_off = physics.mechanical_trail(0.32)
    cfg.STEER_TRAIL_OFFSET = 0.0
    results.append(check("el offset mueve el avance sin tocar el caster",
                         abs(t_con_off - esperado - 0.02) < 1e-9,
                         f"{esperado*1000:.1f} -> {t_con_off*1000:.1f} mm"))

    # CAIDA GANADA AL GIRAR: la rueda EXTERIOR se tumba hacia dentro de la
    # curva (signo + con el convenio de balanceo) y la interior hacia fuera
    cfg.CASTER_ANGLE_DEG, cfg.CASTER_CAMBER_GAIN = 8.0, 1.0
    delta = math.radians(10.0)          # giro a la DERECHA
    lean_izq = physics.caster_camber(delta, -1.0)   # exterior de la curva
    lean_dch = physics.caster_camber(delta, +1.0)   # interior
    results.append(check("el caster inclina la rueda exterior hacia la curva",
                         lean_izq > 0.0 > lean_dch,
                         f"ext {math.degrees(lean_izq):+.2f} deg, "
                         f"int {math.degrees(lean_dch):+.2f} deg"))

    # ...y eso se traduce en MAS giro real con el mismo volante
    def yaw_con_caster(ccg):
        cfg.CASTER_CAMBER_GAIN = ccg
        c = Car()
        settle(c, flat, 1.0)
        set_speed(c, 22.0)
        acc, n = 0.0, 0
        for k in range(int(2.5 / DT)):
            c.step(DT, 0.45, 0.30, 0.0, flat)
            if k > int(1.5 / DT):
                acc += abs(c.state.yaw_rate)
                n += 1
        return acc / n

    yaw_sin, yaw_con = yaw_con_caster(0.0), yaw_con_caster(1.0)
    results.append(check("la caida ganada por caster hace girar mas",
                         yaw_con > yaw_sin,
                         f"yaw {yaw_sin:.4f} -> {yaw_con:.4f} rad/s"))

    # rueda mas grande = brazo mas largo (acopla el catalogo con la direccion)
    cfg.CASTER_ANGLE_DEG = 6.0
    results.append(check("rueda mayor -> mas avance mecanico",
                         physics.mechanical_trail(0.36)
                         > physics.mechanical_trail(0.28) * 1.2,
                         f"{physics.mechanical_trail(0.28)*1000:.1f} -> "
                         f"{physics.mechanical_trail(0.36)*1000:.1f} mm"))

    cfg.CASTER_ANGLE_DEG = old_caster
    cfg.STEER_TRAIL_OFFSET = old_off
    cfg.CASTER_CAMBER_GAIN = old_ccg

    # un coche debe comportarse IGUAL se haya conducido lo que se haya
    # conducido antes: los parametros que solo declaran algunos .car no
    # pueden quedarse pegados del vehiculo anterior
    def ficha():
        return tuple(getattr(cfg, k) for k in (
            "TIRE_PEAK_SLIP_ANGLE_DEG", "ABS_ENABLED", "SUSP_ANTI_PITCH",
            "STEER_TRAIL_OFFSET", "ENGINE_IDLE_RPM", "TIRE_RELAX_LENGTH",
            "STEER_SCRUB_RADIUS", "TIRE_TEMP_OPT", "AERO_DF_FRONT_SHARE"))

    garage.load_car(DEP)
    ficha_limpia = ficha()
    for _n, p, _d in garage.list_cars():     # pasa por TODOS los coches
        garage.load_car(p)
    garage.load_car(DEP)
    results.append(check("el coche no hereda reglajes del anterior",
                         ficha() == ficha_limpia,
                         "ficha identica tras cargar los 8 coches"))

    # ------------------------------------------------------------------
    print("--- Garaje: los 8 coches ---")
    snapshot = {k: getattr(cfg, k) for k in garage.CAR_KEYS
                if hasattr(cfg, k)}
    snapshot["CAR_CG_TO_FRONT"] = cfg.CAR_CG_TO_FRONT
    snapshot["CAR_CG_TO_REAR"] = cfg.CAR_CG_TO_REAR
    floors = {"AUTOBUS": 40.0, "UTILITARIO": 60.0, "BERLINA DE LUJO": 90.0,
              "TODOTERRENO": 80.0}
    for name, path, desc in garage.list_cars():
        garage.load_car(path)
        c = Car()
        settle(c, flat, 1.0)
        t = 0.0
        while t < 8.0:
            c.auto_shift(1.0)
            c.step(DT, 0.0, 1.0, 0.0, flat)
            t += DT
        v_top = c.state.speed_kmh
        for _ in range(int(4.0 / DT)):
            c.step(DT, 0.05, 0.0, 1.0, flat)
        stable = all(math.isfinite(x) for x in
                     (c.state.vx, c.state.vy, c.state.yaw_rate,
                      c.state.roll, c.state.pitch))
        ok_car = stable and v_top > floors.get(name, 95.0) \
            and c.state.speed_kmh < v_top * 0.6
        results.append(check(f"{name}: acelera, frena y no diverge", ok_car,
                             f"vmax={v_top:.0f} km/h vfinal={c.state.speed_kmh:.0f}"))
    for k, v in snapshot.items():
        setattr(cfg, k, v)

    # ------------------------------------------------------------------
    n_ok = sum(1 for r in results if r)
    print(f"\n{n_ok}/{len(results)} pruebas correctas")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
