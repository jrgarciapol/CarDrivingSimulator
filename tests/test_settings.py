"""Pruebas del sistema de AJUSTES: persistencia y reglaje del coche (sin SDL).

Cubre lo que el usuario reporto que fallaba:
  - los cambios de un parametro DEL COCHE (caster, toe...) se perdian al
    EMPEZAR porque load_car los reseteaba -> ahora sobreviven,
  - la CONFIGURACION (pantalla, mando...) no se guardaba -> ahora persiste,
  - guardar el reglaje como un COCHE NUEVO.

    python tests/test_settings.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import config as cfg
from simulator import garage
from simulator import settings

DEPORTIVO = os.path.join(garage.CARS_DIR, "3_deportivo.car")
FORMULA = os.path.join(garage.CARS_DIR, "5_formula.car")


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


def _limpiar():
    settings.config_overrides.clear()
    settings.car_overrides.clear()
    settings.last.clear()
    settings._car_path = None


def main():
    r = []

    # --- clasificacion coche vs configuracion --------------------------
    r.append(check("un parametro del coche se reconoce como reglaje",
                   settings.es_de_coche("CASTER_ANGLE_DEG")))
    r.append(check("un parametro de pantalla NO es reglaje de coche",
                   not settings.es_de_coche("WINDOW_FULLSCREEN")))

    # --- EL BUG: el reglaje del coche sobrevive a load_car -------------
    _limpiar()
    settings.set_car_path(DEPORTIVO)
    garage.load_car(DEPORTIVO)
    base_caster = cfg.CASTER_ANGLE_DEG
    settings.record("CASTER_ANGLE_DEG", base_caster + 4)
    cfg.CASTER_ANGLE_DEG = base_caster + 4
    settings.record("TOE_FRONT_DEG", 0.42)
    cfg.TOE_FRONT_DEG = 0.42
    garage.load_car(DEPORTIVO)                 # EMPEZAR recarga el coche
    tras_load = cfg.CASTER_ANGLE_DEG
    settings.apply_car()                       # el arreglo
    r.append(check("load_car por si solo borra el cambio (era el bug)",
                   abs(tras_load - base_caster) < 1e-6,
                   f"caster {tras_load}"))
    r.append(check("apply_car reaplica el reglaje tras load_car",
                   abs(cfg.CASTER_ANGLE_DEG - (base_caster + 4)) < 1e-6
                   and abs(cfg.TOE_FRONT_DEG - 0.42) < 1e-6,
                   f"caster {cfg.CASTER_ANGLE_DEG} toe {cfg.TOE_FRONT_DEG}"))

    # --- cambiar de coche descarta el reglaje del anterior -------------
    settings.set_car_path(FORMULA)
    r.append(check("cambiar de coche descarta su reglaje",
                   settings.car_overrides == {},
                   f"quedan {len(settings.car_overrides)}"))

    # --- volver un parametro a su valor lo olvida ----------------------
    _limpiar()
    settings.record("FFB_GAIN" if hasattr(cfg, "FFB_GAIN") else "PAD_STEER_EXPO",
                    0.9)
    settings.forget("FFB_GAIN" if hasattr(cfg, "FFB_GAIN") else "PAD_STEER_EXPO")
    r.append(check("olvidar un cambio lo quita de los overrides",
                   settings.config_overrides == {}))

    # --- PERSISTENCIA de la configuracion ------------------------------
    _limpiar()
    param = "PAD_STEER_EXPO" if hasattr(cfg, "PAD_STEER_EXPO") else "MAP_AHEAD_METERS"
    settings.record(param, 0.73)
    settings.remember(DEPORTIVO, "tracks/x.csv", "SECO")
    guardado = os.path.exists(settings._PATH)
    # releer desde cero
    settings.config_overrides.clear()
    settings.last.clear()
    setattr(cfg, param, 0.0)
    ultimo = settings.load()
    r.append(check("la configuracion se guarda y se reaplica al arrancar",
                   guardado and abs(getattr(cfg, param) - 0.73) < 1e-6,
                   f"{param}={getattr(cfg, param)}"))
    r.append(check("se recuerda la ultima seleccion (coche/circuito/asfalto)",
                   ultimo.get("car") == DEPORTIVO
                   and ultimo.get("cond") == "SECO"))
    try:
        os.remove(settings._PATH)
    except OSError:
        pass

    # --- GUARDAR COMO COCHE NUEVO --------------------------------------
    _limpiar()
    settings.set_car_path(DEPORTIVO)
    garage.load_car(DEPORTIVO)
    cfg.CASTER_ANGLE_DEG = 9.5
    settings.record("CASTER_ANGLE_DEG", 9.5)
    settings.guardar_coche("Prueba Reglaje")
    nuevo = os.path.join(garage.CARS_DIR, "PRUEBA_REGLAJE.car")
    creado = os.path.exists(nuevo)
    en_menu = any(c[1] == nuevo for c in garage.list_cars()) if creado else False
    if creado:
        garage.load_car(nuevo)                 # recargarlo restaura el reglaje
    r.append(check("guardar como coche crea un .car que sale en el menu",
                   creado and en_menu))
    r.append(check("el coche guardado conserva el reglaje (caster 9.5)",
                   creado and abs(cfg.CASTER_ANGLE_DEG - 9.5) < 1e-6,
                   f"caster {cfg.CASTER_ANGLE_DEG}"))
    r.append(check("tras guardar, el reglaje vivo queda consolidado (vacio)",
                   settings.car_overrides == {}))
    if creado:
        os.remove(nuevo)

    _limpiar()
    # --- GUARDAR EN ESTE COCHE: el reglaje va al archivo del coche -----
    _limpiar()
    prueba = os.path.join(garage.CARS_DIR, "zz_prueba_guardar.car")
    with open(DEPORTIVO, encoding="utf-8") as f:
        original = f.read()
    with open(prueba, "w", encoding="utf-8") as f:
        f.write(original.replace('NAME = "DEPORTIVO"', 'NAME = "ZZ PRUEBA"'))
    try:
        garage.load_car(prueba)
        settings.set_car_path("cars/zz_prueba_guardar.car")
        settings.record("CASTER_ANGLE_DEG", 9.25)         # linea existente
        settings.record("CAMERA_BACK_CHASE", 11.0)        # no estaba en el .car
        ruta = settings.guardar_en_este_coche()
        with open(prueba, encoding="utf-8") as f:
            txt = f.read()
        lineas = [l for l in txt.splitlines() if l.startswith("CASTER_ANGLE_DEG")]
        r.append(check("GUARDAR EN ESTE COCHE reescribe el archivo del coche",
                       ruta == "cars/zz_prueba_guardar.car"))
        r.append(check("...sustituye la linea existente conservando el comentario",
                       len(lineas) == 1 and lineas[0].startswith("CASTER_ANGLE_DEG = 9.25")
                       and "#" in lineas[0], lineas[0] if lineas else "sin linea"))
        r.append(check("...anade al final lo que el coche no declaraba",
                       "CAMERA_BACK_CHASE = 11.0" in txt))
        r.append(check("...y el reglaje vivo queda consolidado (vacio)",
                       not settings.car_overrides))
        garage.load_car(prueba)
        r.append(check("...y al recargar el coche trae los valores guardados",
                       abs(cfg.CASTER_ANGLE_DEG - 9.25) < 1e-9
                       and cfg.CAMERA_BACK_CHASE == 11.0))
        r.append(check("sin reglaje vivo no hay nada que guardar (None)",
                       settings.guardar_en_este_coche() is None))
    finally:
        if os.path.exists(prueba):
            os.remove(prueba)
        garage.load_car(DEPORTIVO)
        _limpiar()

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
