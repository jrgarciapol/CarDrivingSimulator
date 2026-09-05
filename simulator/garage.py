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
    "NAME", "DESC", "CAR_COLOR", "CAR_MODEL_3D", "CAMERA_HEIGHT",
    "CAMERA_FORWARD", "CAMERA_HEIGHT_CHASE", "CAMERA_BACK_CHASE",
    "CAMERA_HEIGHT_REAR", "CAMERA_BACK_REAR", "CAR_BODY_MOTION_EXAG",
    "CAR_MASS", "CAR_INERTIA_Z", "CAR_INERTIA_PITCH", "CAR_INERTIA_ROLL",
    "CHASSIS_TORSION_STIFF", "WHEEL_SPEC", "UNSPRUNG_HUB_MASS",
    "WHEEL_OPTIONS", "TIRE_WIDTH_MM", "WHEEL_SPEC_FRONT", "WHEEL_SPEC_REAR",
    "CAR_WHEEL_RADIUS_REAR", "CAR_WHEEL_INERTIA_REAR", "TIRE_WIDTH_MM_REAR",
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
    "TIRE_TRAIL_SAT_DEG", "TIRE_TRAIL_NEG_FRAC", "CASTER_ANGLE_DEG",
    "STEER_TRAIL_OFFSET", "CASTER_CAMBER_GAIN",
    "TIRE_CAMBER_THRUST", "TIRE_TEMP_OPT",
    "STATIC_CAMBER_FRONT_DEG", "STATIC_CAMBER_REAR_DEG",
    "TIRE_CAMBER_PATCH", "TIRE_CAMBER_HEAT",
    "TIRE_VERT_STIFF", "TIRE_VERT_DAMP", "UNSPRUNG_MASS",
    "SUSP_SPRING_FRONT", "SUSP_SPRING_REAR", "SUSP_DAMPER",
    "SUSP_DAMPER_BUMP_F", "SUSP_DAMPER_REB_F",
    "SUSP_DAMPER_BUMP_R", "SUSP_DAMPER_REB_R",
    "SUSP_BUMP_GAP_F", "SUSP_BUMP_GAP_R", "SUSP_BUMP_STIFF",
    "DIFF_PRELOAD", "DIFF_RAMP_POWER", "DIFF_RAMP_COAST", "DIFF_LOCK_BAND",
    "DIFF_MAX_LOCK",
    "TOE_FRONT_DEG", "TOE_REAR_DEG",
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

# Catálogo general de monturas, con su uso habitual. Sirve para el selector
# del menú (cualquier coche puede calzar cualquiera: es un simulador) y para
# que se reconozcan de un vistazo.
WHEEL_CATALOG = [
    ("135/80R13",   "RUEDA DE GALLETA (EMERGENCIA)"),
    ("155/70R13",   "URBANO ANTIGUO / ECONOMICO"),
    ("165/70R13",   "UTILITARIO CLASICO"),
    ("175/65R14",   "UTILITARIO ACTUAL"),
    ("185/60R15",   "COMPACTO"),
    ("195/65R15",   "BERLINA MEDIA / RALLY ASFALTO"),
    ("205/55R16",   "COMPACTO DEPORTIVO (LA MAS COMUN)"),
    ("225/45R17",   "DEPORTIVO DE CALLE"),
    ("225/40R18",   "BERLINA DEPORTIVA"),
    ("245/35R18",   "DEPORTIVO POTENTE"),
    ("245/40R19",   "BERLINA DE LUJO / GRAN TURISMO"),
    ("265/35R19",   "DEPORTIVO - EJE TRASERO"),
    ("285/30R20",   "SUPERDEPORTIVO - EJE TRASERO"),
    ("305/30R20",   "SUPERDEPORTIVO EXTREMO"),
    ("325/30R21",   "HIPERDEPORTIVO - EJE TRASERO"),
    ("205/60R15",   "GT CLASICO / YOUNGTIMER"),
    ("235/40R18",   "TURISMO DE COMPETICION (TCR)"),
    ("300/65R18",   "GT3 DELANTERA (SLICK)"),
    ("310/71R18",   "GT3 TRASERA (SLICK)"),
    ("270/60R13",   "FORMULA CLASICA DELANTERA"),
    ("330/50R13",   "FORMULA CLASICA TRASERA"),
    ("305/55R13",   "FORMULA 1 DELANTERA (13\", 670 MM)"),
    ("405/42R13",   "FORMULA 1 TRASERA (13\", 670 MM)"),
    ("305/35R18",   "FORMULA 1 MODERNA DELANTERA (18\")"),
    ("405/26R18",   "FORMULA 1 MODERNA TRASERA (18\")"),
    ("185/70R14",   "RALLY TIERRA (ESTRECHA Y ALTA)"),
    ("205/50R16",   "RALLY ASFALTO"),
    ("235/85R16",   "TODOTERRENO ESTRECHA (BARRO)"),
    ("245/75R16",   "TODOTERRENO / PICK-UP"),
    ("265/70R17",   "TODOTERRENO ACTUAL"),
    ("285/75R16",   "TODOTERRENO EXTREMO (35\")"),
    ("315/70R17",   "4X4 EXTREMO / TROFEO"),
    ("275/70R22.5", "CAMION / AUTOBUS URBANO"),
    ("295/80R22.5", "AUTOBUS DE CARRETERA"),
    ("315/70R22.5", "CAMION PESADO"),
    ("385/65R22.5", "SEMIRREMOLQUE (EJE ANCHO)"),
]

_CATALOG_USE = {spec: use for spec, use in WHEEL_CATALOG}


def catalog_use(spec):
    """Uso habitual de una montura del catálogo ('' si no está)."""
    return _CATALOG_USE.get(str(spec).strip(), "")


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
            "rim_m": rim_m, "tire_m": tire_m, "width": w}


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


def _car_defaults():
    """Foto de los valores de fábrica de config.py para todas las claves que
    un .car puede sobrescribir. Se toma UNA vez, antes de cargar ningún
    coche, y sirve de base limpia en cada cambio de vehículo."""
    global _DEFAULTS
    if _DEFAULTS is None:
        _DEFAULTS = {k: getattr(cfg, k) for k in CAR_KEYS if hasattr(cfg, k)}
    return _DEFAULTS


_DEFAULTS = None


def load_car(path):
    """Aplica el coche sobre la configuración global. Devuelve su nombre."""
    data = parse_car_file(path)
    # PARTIR SIEMPRE DE LOS VALORES DE FABRICA. Sin esto, un parámetro que
    # solo declaran ALGUNOS coches se quedaría pegado del vehículo anterior:
    # elegir el fórmula y luego el deportivo le dejaba a este el reglaje de
    # neumático, el anti-dive y hasta el ABS del fórmula. Cada coche debe
    # comportarse igual sea cual sea el que se condujo antes.
    for key, val in _car_defaults().items():
        setattr(cfg, key, val)
    for key, val in data.items():
        if key in ("NAME", "DESC", "WHEEL_SPEC", "UNSPRUNG_HUB_MASS",
                   "WHEEL_OPTIONS", "WHEEL_SPEC_FRONT", "WHEEL_SPEC_REAR"):
            continue
        setattr(cfg, key, val)
    # RUEDAS por designación de neumático: deriva radio, inercia, ancho y masa
    # CONSISTENTES entre sí, por EJE (un coche puede calzar distinto delante y
    # detrás). Un valor explícito en el .car siempre gana sobre el derivado
    # (p.ej. llanta de magnesio con menos inercia).
    spec_f, spec_r = car_wheel_specs(path)
    if spec_f:
        ws = parse_wheel_spec(spec_f)
        if "CAR_WHEEL_RADIUS" not in data:
            cfg.CAR_WHEEL_RADIUS = ws["radius"]
        if "CAR_WHEEL_INERTIA" not in data:
            cfg.CAR_WHEEL_INERTIA = ws["inertia"]
        if "TIRE_WIDTH_MM" not in data:
            cfg.TIRE_WIDTH_MM = ws["width"]
        wr = parse_wheel_spec(spec_r) if spec_r else ws
        if "CAR_WHEEL_RADIUS_REAR" not in data:
            cfg.CAR_WHEEL_RADIUS_REAR = wr["radius"]
        if "CAR_WHEEL_INERTIA_REAR" not in data:
            cfg.CAR_WHEEL_INERTIA_REAR = wr["inertia"]
        if "TIRE_WIDTH_MM_REAR" not in data:
            cfg.TIRE_WIDTH_MM_REAR = wr["width"]
        # masa no suspendida = mangueta/freno/suspensión (hub) + rueda media
        if "UNSPRUNG_HUB_MASS" in data and "UNSPRUNG_MASS" not in data:
            cfg.UNSPRUNG_MASS = data["UNSPRUNG_HUB_MASS"] \
                + 0.5 * (ws["mass"] + wr["mass"])
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


def car_wheel_specs(path):
    """Monturas de serie del coche: (delantera, trasera). Un coche puede
    llevar ruedas distintas por eje (WHEEL_SPEC_FRONT/_REAR)."""
    try:
        data = parse_car_file(path)
    except (ValueError, SyntaxError, OSError):
        return (None, None)
    base = data.get("WHEEL_SPEC")
    return (data.get("WHEEL_SPEC_FRONT", base),
            data.get("WHEEL_SPEC_REAR", base))


def wheel_options(path):
    """Monturas para el selector: primero las del coche (serie y homologadas)
    y después TODO el catálogo general, con su uso habitual.
    [(spec, etiqueta)]."""
    try:
        data = parse_car_file(path)
    except (ValueError, SyntaxError, OSError):
        data = {}
    serie_f, serie_r = car_wheel_specs(path)
    opts = []
    for o in (serie_f, serie_r):
        if o and o not in opts:
            opts.append(o)
    for o in data.get("WHEEL_OPTIONS", []):
        if o not in opts:
            opts.append(o)
    propias = set(opts)
    for spec, _use in WHEEL_CATALOG:
        if spec not in opts:
            opts.append(spec)
    out = []
    for o in opts:
        try:
            ws = parse_wheel_spec(o)
        except ValueError:
            continue
        use = catalog_use(o)
        if o in propias:
            marca = "SERIE" if o in (serie_f, serie_r) else "OPCION"
            tag = f"{marca}" + (f" - {use}" if use else "")
        else:
            tag = use or f"{ws['radius'] * 2000:.0f} MM"
        out.append((o, f"{o}  ({tag})"))
    return out


def _hub_mass(data, serie_spec, fallback_total):
    """Masa de mangueta/freno/suspensión sin la rueda."""
    hub = data.get("UNSPRUNG_HUB_MASS")
    if hub is not None:
        return hub
    base = parse_wheel_spec(serie_spec)["mass"] if serie_spec else 0.0
    return max(2.0, fallback_total - base)


def apply_wheel(spec_front, car_path, spec_rear=None):
    """Monta otra rueda sobre el coche YA cargado (llamar DESPUÉS de
    load_car): rehace radio, inercia, ancho y masa no suspendida de cada eje
    de forma consistente. Si spec_rear es None se calza igual delante y
    detrás. Además RE-ESCALA el grupo final si GEARING_KEEP_ON_WHEEL_CHANGE,
    para que el desarrollo (y con él el carácter del coche) no cambie solo
    por montar otra rueda: es lo que haría un ingeniero al recalzar."""
    spec_rear = spec_rear or spec_front
    wf = parse_wheel_spec(spec_front)
    wr = parse_wheel_spec(spec_rear)
    try:
        data = parse_car_file(car_path)
    except (ValueError, SyntaxError, OSError):
        data = {}
    serie_f, serie_r = car_wheel_specs(car_path)
    # radio motriz ANTES de recalzar (para conservar el desarrollo)
    drive = getattr(cfg, "DRIVE_TYPE", "RWD")
    r_old_f = cfg.CAR_WHEEL_RADIUS
    r_old_r = getattr(cfg, "CAR_WHEEL_RADIUS_REAR", None) or r_old_f

    hub = _hub_mass(data, serie_f, getattr(cfg, "UNSPRUNG_MASS", 35.0))
    cfg.CAR_WHEEL_RADIUS = wf["radius"]
    cfg.CAR_WHEEL_INERTIA = wf["inertia"]
    cfg.TIRE_WIDTH_MM = wf["width"]
    cfg.CAR_WHEEL_RADIUS_REAR = wr["radius"]
    cfg.CAR_WHEEL_INERTIA_REAR = wr["inertia"]
    cfg.TIRE_WIDTH_MM_REAR = wr["width"]
    cfg.UNSPRUNG_MASS = hub + 0.5 * (wf["mass"] + wr["mass"])

    if getattr(cfg, "GEARING_KEEP_ON_WHEEL_CHANGE", True):
        def r_drive(rf, rr):
            if drive == "FWD":
                return rf
            if drive == "RWD":
                return rr
            return 0.5 * (rf + rr)
        r0 = r_drive(r_old_f, r_old_r)
        r1 = r_drive(wf["radius"], wr["radius"])
        if r0 > 1e-6:
            cfg.FINAL_DRIVE = cfg.FINAL_DRIVE * (r1 / r0)
    return wf, wr


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
