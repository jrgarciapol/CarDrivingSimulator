"""Pruebas del menu de AJUSTES: los pasos de las flechas son numeros redondos.

Lo que se reporto: el giro del volante (WHEEL_ROTATION_DEG, 180..1080) iba
de 22,5 en 22,5 grados, y una vez tocado no habia forma de volver a poner
900 (la rejilla del paso grande, 112,5, no pasa por 900 desde 922,5). Los
pasos salen ahora de la serie 1, 2, 5 x 10^k mas cercana al paso de
calculo (rango/40 y rango/8), y la rejilla pasa por los valores redondos.

    python tests/test_ajustes.py
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import tuning                                   # noqa: E402


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return bool(cond)


def rejilla(cur, paso, direccion, lo=None, hi=None):
    """Lo que hace ``ajustar`` con un parametro real: un paso, encajar en
    la rejilla y acotar al rango."""
    v = cur + paso * direccion
    v = round(round(v / paso) * paso, 6)
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def main():
    r = []
    r.append(check("_paso_redondo: serie 1, 2, 5 x 10^k (22,5 -> 20; 112,5 -> 100; "
                   "0,0375 -> 0,05; 0,1875 -> 0,2; 3 -> 2; 7 -> 5)",
                   [tuning._paso_redondo(x) for x in (22.5, 112.5, 0.0375, 0.1875, 3.0, 7.0)]
                   == [20.0, 100.0, 0.05, 0.2, 2.0, 5.0]))
    ent = {e["name"]: e for e in tuning._parse_config()}
    vol = ent["WHEEL_ROTATION_DEG"]
    r.append(check("el giro del volante va de 20 en 20 grados (100 con MAYUS)",
                   tuning._step(vol, False) == 20.0 and tuning._step(vol, True) == 100.0,
                   f"{tuning._step(vol, False)} / {tuning._step(vol, True)}"))
    # desde un valor "roto" (922,5) se vuelve a 900 con un paso pequeno o
    # con uno grande
    r.append(check("...y desde 922,5 un paso pequeno vuelve a 900, y el grande "
                   "cae en la centena (800) y de ahi sube a 900",
                   rejilla(922.5, tuning._step(vol, False), -1) == 900.0
                   and rejilla(922.5, tuning._step(vol, True), -1) == 800.0
                   and rejilla(800.0, tuning._step(vol, True), 1) == 900.0))
    gain = ent["CAMERA_LOOK_GAIN"]
    v = 0.22
    for _ in range(10):
        v = rejilla(v, tuning._step(gain, False), -1, gain["lo"], gain["hi"])
    r.append(check("un parametro con rango [0 .. 1,5] baja de 0,05 en 0,05 y "
                   "llega EXACTAMENTE a 0 (apagado)",
                   tuning._step(gain, False) == 0.05 and v == 0.0, f"{v}"))
    ent_int = ent["SPEEDO_STEP_KMH"]
    r.append(check("los enteros conservan pasos enteros (2 y 10 para 20..100)",
                   tuning._step(ent_int, False) == 2 and tuning._step(ent_int, True) == 10))
    # --- las vistas van en submenus propios (secciones de config.py) -------
    secciones = {e["section"]: e["name"] for e in tuning.get_entries()}
    vistas = [s for s in secciones if s.startswith("VISTA")]
    r.append(check("cada vista (o pareja) tiene su categoria en el menu: interior "
                   "y cabina, trasera y exterior, elevada, planta e isometrica, "
                   "mas la comun de camara y la del HUD",
                   len(vistas) == 4
                   and ent["CAMERA_HEIGHT"]["section"] == ent["CAMERA_SIDE_COCKPIT"]["section"]
                   and ent["CAMERA_HEIGHT_HIGH"]["section"].startswith("VISTA 5")
                   and ent["CAMERA_ISO_YAW"]["section"] == ent["CAMERA_HEIGHT_PLAN"]["section"]
                   and ent["CAMERA_GRADE_GAIN"]["section"].startswith("CAMARA: COMUN")
                   and ent["RACING_LINE"]["section"].startswith("HUD")
                   and ent["CAMERA_HEIGHT"]["section"] != ent["CAMERA_HEIGHT_REAR"]["section"],
                   ", ".join(vistas)))
    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
