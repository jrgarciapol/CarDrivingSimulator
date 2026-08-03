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

from . import config as cfg

CARS_DIR = os.path.join(os.path.dirname(__file__), "cars")
RECORDS_PATH = os.path.join(os.path.dirname(__file__), "..", "records.json")

# Parámetros que un archivo de coche puede definir
CAR_KEYS = {
    "NAME", "DESC", "CAR_COLOR", "CAMERA_HEIGHT", "CAMERA_FORWARD",
    "CAR_MASS", "CAR_INERTIA_Z", "CAR_INERTIA_PITCH", "CAR_INERTIA_ROLL",
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
    "AERO_DRAG", "AERO_DOWNFORCE", "AERO_DF_FRONT_SHARE", "ROLLING_RESIST",
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
        if key in ("NAME", "DESC"):
            continue
        setattr(cfg, key, val)
    # recalcular derivados de la geometría
    cfg.CAR_CG_TO_FRONT = cfg.WHEELBASE * (1.0 - cfg.WEIGHT_DIST_FRONT)
    cfg.CAR_CG_TO_REAR = cfg.WHEELBASE * cfg.WEIGHT_DIST_FRONT
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
