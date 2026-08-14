"""Ajustes del usuario: persistencia y reglajes.

Resuelve tres cosas que faltaban:

  1. EL BUG. Los cambios de AJUSTES a parametros DEL COCHE (caster, toe,
     muelles...) se perdian, porque al pulsar EMPEZAR el juego llama a
     garage.load_car(), que resetea todos los parametros del coche a los del
     archivo. Aqui se guardan aparte y se REAPLICAN despues de load_car.

  2. PERSISTENCIA. Los ajustes de CONFIGURACION (pantalla, mando, fuerza,
     graficos...) y la ultima seleccion (coche/circuito/asfalto) se guardan
     en settings.json y se recuperan al arrancar.

  3. Se distingue entre dos clases de parametro:
     - DE COCHE (los de garage.CAR_KEYS): son un REGLAJE. Se aplican al
       coche de la sesion y se conservan guardandolos como coche nuevo. No
       se persisten globalmente: cambiar de coche los descarta.
     - DE CONFIGURACION (el resto): preferencias globales de la aplicacion.
       Se persisten en settings.json y valen para cualquier coche.
"""

import json
import os

from . import config as cfg
from . import garage

_PATH = os.path.join(os.path.dirname(__file__), "..", "settings.json")

# preferencias globales que el usuario cambio (parametros NO de coche)
config_overrides = {}
# reglaje vivo del coche actual (parametros de coche) y a que coche pertenece
car_overrides = {}
_car_path = None
# ultima seleccion del menu, para recuperarla al arrancar
last = {}


def es_de_coche(name):
    """True si el parametro pertenece al coche (es un reglaje), no a la app."""
    return name in garage.CAR_KEYS


# ---------------------------------------------------------------------------
def record(name, value):
    """Anota un cambio hecho en AJUSTES, clasificandolo solo."""
    if es_de_coche(name):
        car_overrides[name] = value
    else:
        config_overrides[name] = value


def forget(name):
    """Olvida un cambio (al volver un parametro a su valor por defecto)."""
    car_overrides.pop(name, None)
    config_overrides.pop(name, None)


def clear_car():
    """Descarta el reglaje del coche (al cambiar de coche o al guardarlo)."""
    car_overrides.clear()


def set_car_path(path):
    """Registra a que coche pertenece el reglaje vivo. Si cambia el coche,
    el reglaje anterior ya no vale."""
    global _car_path
    if _car_path is not None and _car_path != path:
        clear_car()
    _car_path = path


# ---------------------------------------------------------------------------
def apply_config():
    """Vuelca las preferencias globales sobre cfg."""
    for k, v in config_overrides.items():
        setattr(cfg, k, v)


def apply_car():
    """Vuelca el reglaje del coche sobre cfg. Se llama DESPUES de load_car,
    para que los cambios del usuario ganen a los del archivo (esto es lo que
    arregla el bug del caster/toe)."""
    for k, v in car_overrides.items():
        setattr(cfg, k, v)


# ---------------------------------------------------------------------------
def load():
    """Lee settings.json (si existe) y aplica la configuracion global."""
    global config_overrides, last
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = json.load(f)
        config_overrides = dict(data.get("config", {}))
        last = dict(data.get("last", {}))
    except (OSError, ValueError):
        config_overrides = {}
        last = {}
    apply_config()
    return last


def save():
    """Escribe settings.json con la configuracion global y la ultima
    seleccion. El reglaje del coche NO se guarda aqui: para conservarlo se
    guarda como coche nuevo (guardar_coche)."""
    data = {"config": config_overrides, "last": last}
    try:
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def remember(car_path, track_path, cond, wheel=None, wheel_rear=None):
    """Guarda la seleccion actual para recuperarla en el proximo arranque."""
    last.update({"car": car_path, "track": track_path, "cond": cond,
                 "wheel": wheel, "wheel_rear": wheel_rear})
    save()


# ---------------------------------------------------------------------------
#: parametros de coche que NO se serializan (se derivan de otros o no viven
#: en cfg): las designaciones de rueda y los auxiliares del catalogo.
_NO_GUARDAR = {"WHEEL_SPEC", "WHEEL_SPEC_FRONT", "WHEEL_SPEC_REAR",
               "WHEEL_OPTIONS", "UNSPRUNG_HUB_MASS"}


def slug(nombre):
    """Nombre de archivo a partir del nombre visible: MAYUSCULAS, sin
    acentos ni espacios, solo lo valido para un nombre de fichero."""
    tr = str(nombre).strip().upper().translate(
        str.maketrans("ÁÉÍÓÚÜÑ ", "AEIOUUN_"))
    ok = [c for c in tr if c.isalnum() or c in "_-"]
    return ("".join(ok) or "COCHE")[:40]


def guardar_coche(nombre):
    """Escribe el coche actual (los valores de cfg de todos los parametros
    de coche, incluido el reglaje ya aplicado) en un .car nuevo, para poder
    elegirlo en el menu. Devuelve la ruta relativa creada.

    Se escribe con el nombre elegido; el reglaje vivo se da por consolidado
    en ese coche y se limpia."""
    fn = slug(nombre) + ".car"
    ruta = os.path.join(garage.CARS_DIR, fn)
    # la fuente del juego es ASCII: el NAME visible se translitera
    visible = str(nombre).strip().upper().translate(
        str.maketrans("ÁÉÍÓÚÜÑ", "AEIOUUN")) or "COCHE"
    lineas = ["# Coche guardado por el usuario",
              f'NAME = "{visible}"',
              'DESC = "REGLAJE PERSONALIZADO"']
    for k in sorted(garage.CAR_KEYS):
        if k in ("NAME", "DESC") or k in _NO_GUARDAR:
            continue
        if not hasattr(cfg, k):
            continue
        lineas.append(f"{k} = {getattr(cfg, k)!r}")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    clear_car()                    # el reglaje queda consolidado en el coche
    set_car_path("cars/" + fn)
    return "cars/" + fn
