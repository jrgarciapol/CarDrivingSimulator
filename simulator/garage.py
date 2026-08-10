"""Garaje, condiciones de pista y récords.

- Coches: un archivo por coche en simulator/cars/*.car con líneas
  ``PARAMETRO = valor`` (sintaxis Python literal, admite comentarios #).
  Solo se aceptan los parámetros del vehículo (lista blanca CAR_KEYS);
  el resto de la configuración (volante, FFB, gráficos) no se toca.
- Condiciones del asfalto: multiplicadores de agarre + paleta visual.
- Récords: mejor vuelta por (circuito, coche, condición) en records.json.
"""

import ast
import json
import os
import re

from . import config as cfg

CARS_DIR = os.path.join(os.path.dirname(__file__), "cars")
RECORDS_PATH = os.path.join(os.path.dirname(__file__), "..", "records.json")

# Parámetros que un archivo de coche puede definir
CAR_KEYS = {
    "NAME", "DESC", "CAR_COLOR", "CAMERA_HEIGHT", "CAMERA_FORWARD",
    "CAR_MASS", "CAR_INERTIA_Z", "CAR_INERTIA_PITCH", "CAR_INERTIA_ROLL",
    "CHASSIS_TORSION_STIFF", "WHEEL_SPEC", "UNSPRUNG_HUB_MASS",
    "WHEELBASE", "WEIGHT_DIST_FRONT", "CAR_CG_HEIGHT", "CAR_TRACK_WIDTH",
    "CAR_WHEEL_RADIUS", "CAR_WHEEL_INERTIA", "STEER_RATIO",
    "STEER_SCRUB_RADIUS",
    "DRIVE_TYPE", "AWD_FRONT_SPLIT", "DIFF_TYPE", "DIFF_LSD_COEFF",
    "ENGINE_MAX_TORQUE_NM", "ENGINE_TORQUE_PEAK_RPM", "ENGINE_IDLE_RPM",
    "ENGINE_REDLINE_RPM", "ENGINE_LIMITER_RPM", "ENGINE_BRAKE_COEFF",
    "GEAR_RATIOS", "FINAL_DRIVE", "REVERSE_RATIO", "DRIVELINE_EFF",
    "ENGINE_INERTIA", "SUSP_ANTI_PITCH",
    "TIRE_MU", "TIRE_MU_GRASS", "TIRE_PEAK_SLIP_ANGLE_DEG",
    "TIRE_PEAK_SLIP_RATIO", "TIRE_LOAD_SENS", "TIRE_LONG_GRIP_RATIO",
    "TIRE_RELAX_LENGTH", "TIRE_REAR_GRIP_FACTOR", "TIRE_TRAIL",
    "TIRE_TRAIL_SAT_DEG", "TIRE_CAMBER_THRUST", "TIRE_TEMP_OPT",
    "TIRE_VERT_STIFF", "TIRE_VERT_DAMP", "UNSPRUNG_MASS",
    "SUSP_SPRING_FRONT", "SUSP_SPRING_REAR", "SUSP_DAMPER",
    "ARB_FRONT", "ARB_REAR", "SUSP_CAMBER_GAIN",
    "AERO_DRAG", "AERO_DOWNFORCE", "CD", "CL", "FRONTAL_AREA",
    "AERO_DF_FRONT_SHARE", "ROLLING_RESIST",
    "BRAKE_FORCE_MAX", "BRAKE_BIAS_FRONT", "ABS_ENABLED", "ABS_SLIP_TARGET",
}

# Condiciones del asfalto: multiplicadores de agarre y rodadura
CONDITIONS = {
    "SECO":     {"mu": 1.00, "grass": 1.00, "roll": 1.0,
                 "desc": "aglomerado seco"},
    "HORMIGON": {"mu": 0.92, "grass": 1.00, "roll": 1.0,
                 "desc": "pavimento de hormigon"},
    "ARENA":    {"mu": 0.80, "grass": 0.90, "roll": 1.5,
                 "desc": "asfalto con arena"},
    "LLUVIA":   {"mu": 0.65, "grass": 0.70, "roll": 1.0,
                 "desc": "asfalto mojado"},
}
CONDITION_ORDER = ["SECO", "HORMIGON", "ARENA", "LLUVIA"]


_TIRE_RE = re.compile(r"^\s*(\d{3})\s*/\s*(\d{2,3})\s*R\s*(\d{2}(?:\.5)?)\s*$",
                      re.IGNORECASE)


def parse_wheel_spec(spec):
    """Interpreta una designación real de neumático 'ANCHO/PERFIL R LLANTA'
    (p.ej. '205/55R16', '295/80R22.5') y deriva la geometría y las masas de
    la rueda COMPLETA (llanta + cubierta), de forma que radio, masa e
    inercia sean CONSISTENTES entre sí:

      radio  = llanta/2 + ancho·perfil          (exacto, por definición)
      masas  = estimación empírica (cubierta crece con ancho y diámetro²;
               llanta de aleación con el diámetro²)
      inercia = anillo de la cubierta (~0.94·R) + disco de la llanta

    Devuelve {'radius','mass','inertia','rim_m','tire_m'} (m, kg, kg·m²)."""
    m = _TIRE_RE.match(str(spec))
    if not m:
        raise ValueError(f"designacion de rueda invalida: {spec!r} "
                         "(formato ANCHO/PERFIL R LLANTA, p.ej. 205/55R16)")
    w = float(m.group(1))          # ancho (mm)
    a = float(m.group(2))          # perfil (% del ancho)
    d = float(m.group(3))          # llanta (pulgadas)
    r_rim = d * 25.4 / 2000.0
    radius = r_rim + w * a / 100.0 / 1000.0
    tire_m = 9.5 * (w / 205.0) * (radius / 0.316) ** 2
    rim_m = 8.0 * (d / 16.0) ** 2
    inertia = 0.92 * tire_m * (0.94 * radius) ** 2 \
        + 0.55 * rim_m * r_rim ** 2
    return {"radius": radius, "mass": tire_m + rim_m, "inertia": inertia,
            "rim_m": rim_m, "tire_m": tire_m}


def parse_car_file(path):
    """Lee un .car y devuelve el dict de parámetros (validados)."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if "=" not in line:
                raise ValueError(f"{path}:{ln}: linea invalida")
            key, val = line.split("=", 1)
            key = key.strip()
            if key not in CAR_KEYS:
                raise ValueError(f"{path}:{ln}: parametro desconocido {key}")
            out[key] = ast.literal_eval(val.strip())
    return out


def list_cars():
    """[(nombre_visible, ruta, descripcion)] ordenados por archivo."""
    cars = []
    for fn in sorted(os.listdir(CARS_DIR)):
        if not fn.endswith(".car"):
            continue
        path = os.path.join(CARS_DIR, fn)
        try:
            data = parse_car_file(path)
        except (ValueError, SyntaxError):
            continue
        cars.append((data.get("NAME", fn[:-4].upper()), path,
                     data.get("DESC", "")))
    return cars


def load_car(path):
    """Aplica el coche sobre la configuración global. Devuelve su nombre."""
    data = parse_car_file(path)
    for key, val in data.items():
        if key in ("NAME", "DESC", "WHEEL_SPEC", "UNSPRUNG_HUB_MASS"):
            continue
        setattr(cfg, key, val)
    # RUEDAS por designación de neumático (WHEEL_SPEC): deriva radio, inercia
    # y masa CONSISTENTES entre sí. Un valor explícito en el .car siempre
    # gana sobre el derivado (p.ej. llanta de magnesio con menos inercia).
    if "WHEEL_SPEC" in data:
        ws = parse_wheel_spec(data["WHEEL_SPEC"])
        if "CAR_WHEEL_RADIUS" not in data:
            cfg.CAR_WHEEL_RADIUS = ws["radius"]
        if "CAR_WHEEL_INERTIA" not in data:
            cfg.CAR_WHEEL_INERTIA = ws["inertia"]
        # masa no suspendida = mangueta/freno/suspensión (hub) + rueda entera
        if "UNSPRUNG_HUB_MASS" in data and "UNSPRUNG_MASS" not in data:
            cfg.UNSPRUNG_MASS = data["UNSPRUNG_HUB_MASS"] + ws["mass"]
    # recalcular derivados de la geometría
    cfg.CAR_CG_TO_FRONT = cfg.WHEELBASE * (1.0 - cfg.WEIGHT_DIST_FRONT)
    cfg.CAR_CG_TO_REAR = cfg.WHEELBASE * cfg.WEIGHT_DIST_FRONT
    # aerodinámica: si el coche da Cd/Cl y área frontal, se calcula el
    # coeficiente agrupado ½·ρ·C·A (más físico y fácil de ajustar). Si en su
    # lugar trae AERO_DRAG/AERO_DOWNFORCE directos (formato antiguo), se
    # respetan.
    rho = getattr(cfg, "AIR_DENSITY", 1.225)
    if "CD" in data and "FRONTAL_AREA" in data:
        cfg.AERO_DRAG = 0.5 * rho * data["CD"] * data["FRONTAL_AREA"]
    if "CL" in data and "FRONTAL_AREA" in data:
        cfg.AERO_DOWNFORCE = 0.5 * rho * data["CL"] * data["FRONTAL_AREA"]
    return data.get("NAME", os.path.basename(path))


def apply_condition(cond):
    """Multiplica el agarre según la condición. Llamar DESPUÉS de load_car."""
    c = CONDITIONS[cond]
    cfg.TIRE_MU = cfg.TIRE_MU * c["mu"]
    cfg.TIRE_MU_GRASS = cfg.TIRE_MU_GRASS * c["grass"]
    cfg.ROLLING_RESIST = cfg.ROLLING_RESIST * c["roll"]


# ---------------------------------------------------------------------------
def _records_load():
    try:
        with open(RECORDS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def record_key(track_name, car_name, cond):
    return f"{track_name}|{car_name}|{cond}"


def record_get(track_name, car_name, cond):
    """Mejor vuelta guardada (s) o None."""
    return _records_load().get(record_key(track_name, car_name, cond))


def record_save(track_name, car_name, cond, seconds):
    """Guarda si mejora el récord. Devuelve True si es nuevo récord."""
    recs = _records_load()
    key = record_key(track_name, car_name, cond)
    prev = recs.get(key)
    if prev is not None and seconds >= prev:
        return False
    recs[key] = round(seconds, 2)
    try:
        with open(RECORDS_PATH, "w", encoding="utf-8") as f:
            json.dump(recs, f, indent=1, sort_keys=True)
    except OSError:
        pass
    return True
