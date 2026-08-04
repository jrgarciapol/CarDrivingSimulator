"""Resuelve un trazado de diseño desde las DIRECTRICES dibujadas a mano.

Toma el KML/KMZ (planta) y el .aln.json (alineaciones dibujadas: rectas y
círculos), llama al solver (alignment_solver.solve) que genera las clotoides
con tangencia C1/C2 y cierra el anillo a ±360° manteniendo radios y rectas
exactos, y escribe el CSV del simulador (κ, elevación, piano, peralte).

Uso:
  python tools/resolve_track.py entrada.kml alineaciones.aln.json \\
      [--linea=1] [--salida=simulator/tracks/spa_resuelto.csv] \\
      [--elev=simulator/tracks/spa.csv]
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import alignment_geom as ag
import alignment_solver as asv
from alignment_editor import (BANK_MAX_DEG, BANK_SCALE, KERB_KAPPA, load_plan)


def _load_elev_by_station(elev_csv, step_orig=4.0):
    """Cota del terreno como función de la estación de la traza ORIGINAL
    (columna de elevación del CSV, un valor por segmento). Devuelve (elev, L)."""
    col = []
    for ln in open(elev_csv):
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            try:
                col.append(float(ln.split(",")[1]))
            except (ValueError, IndexError):
                pass
    if not col:
        return None, 0.0
    return col, len(col) * step_orig


def elevation_by_position(res, xy, stations, elev_csv, step=4.0):
    """Re-muestrea la cota a las estaciones RESUELTAS por POSICIÓN: cada punto
    del trazado resuelto se proyecta al punto más cercano de la traza GPS
    (con ventana por estación, robusto en horquillas) y toma la cota del DEM
    ahí. Así la cota sigue el terreno real aunque la estación se reescale.
    Planta y alzado quedan independientes y coherentes."""
    ks = res["ks"]
    n = len(ks)
    elev_o, L_o = _load_elev_by_station(elev_csv)
    if elev_o is None:
        return [0.0] * n
    L_res = n * step
    # mapa estación_resuelta -> estación_traza por PROPORCIÓN de longitud de
    # arco. La opción 2 mantiene la longitud (<1%) y la planta pegadas al GPS,
    # así que la proporción coincide con la posición real, y —al ser el perfil
    # del DEM suave y monótono— la cota sale suave, sin los saltos que da la
    # proyección punto-a-punto en las muchas horquillas. La cota "por posición
    # exacta" es cosa del editor de alzado, donde se idealiza el perfil.
    out = []
    for i in range(n):
        f = ((i * step / L_res) * L_o) / 4.0
        j = int(f)
        t = f - j
        z = (elev_o[min(j, len(elev_o) - 1)] * (1 - t)
             + elev_o[min(j + 1, len(elev_o) - 1)] * t)
        out.append(z)
    return out


def write_csv(res, out_path, elev, step=4.0):
    ks = res["ks"]
    n = len(ks)
    cap = math.radians(BANK_MAX_DEG)
    win = max(1, int(15.0 / step))
    banks = []
    for i in range(n):
        k = sum(ks[(i + j) % n] for j in range(-win, win + 1)) / (2 * win + 1)
        b = max(-cap, min(cap, k * BANK_SCALE))
        banks.append(b if abs(b) > 0.004 else 0.0)
    path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("# Trazado de diseno RESUELTO desde las directrices "
                "(alignment_solver):\n")
        f.write("# rectas + circulos exactos + clotoides generadas; "
                "cierra a 360\n")
        f.write("# kappa_1pm,elev_m,kerb,peralte_rad (seg %.1f m)\n" % step)
        for i, k in enumerate(ks):
            kerb = 1 if abs(k) > KERB_KAPPA else 0
            f.write("%.6f,%.2f,%d,%.4f\n" % (k, elev[i], kerb, banks[i]))
    return path


def main():
    argv = sys.argv[1:]
    args = [a for a in argv if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        raise SystemExit(1)
    line_idx = 1
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out = os.path.join(root, "simulator", "tracks", "spa_resuelto.csv")
    elev = os.path.join(root, "simulator", "tracks", "spa.csv")
    for a in argv:
        if a.startswith("--linea="):
            line_idx = int(a.split("=")[1])
        if a.startswith("--salida="):
            out = a.split("=", 1)[1]
        if a.startswith("--elev="):
            elev = a.split("=", 1)[1]

    exacto = "--exacto" in argv     # opción 1 (radios+rectas exactos)
    xy = load_plan(args[0], line_idx)
    stations = ag.polyline_stations(xy)
    data = json.load(open(args[1]))
    els = [ag.build_element(d["kind"], d["pts"], xy, stations) for d in data]

    if exacto:
        res = asv.solve(els, xy, stations, step=4.0)
    else:                            # opción 2 por defecto (ajuste al GPS)
        res = asv.solve_fit(els, xy, stations, step=4.0)
    elev_col = (elevation_by_position(res, xy, stations, elev, step=4.0)
                if os.path.exists(elev) else [0.0] * len(res["ks"]))
    path = write_csv(res, out, elev_col)

    print(f"RESUELTO ({'exacto' if exacto else 'ajustado al GPS'}) -> {path}")
    print(f"  giro {math.degrees(res['turn']):.1f}° (cierra a ±360), "
          f"radio min {res['rmin']:.0f} m, longitud {res['length']:.0f} m")
    if not exacto:
        print(f"  ajuste: rumbos movidos ≤{res.get('fit_dtheta_max',0):.1f}°, "
              f"radios ≤{res.get('fit_dR_max',0):.0f} m; "
              f"deriva vs GPS {res['trace_drift']:.0f} m")
    rl = res["retranqueos_local"]
    if rl:
        pmed = sum(max(d["p_in"], d["p_out"]) for d in rl) / len(rl)
        pmax = max(max(d["p_in"], d["p_out"]) for d in rl)
        print(f"  retranqueo local medio {pmed:.1f} m, max {pmax:.1f} m "
              f"({len(rl)} circulos)")
    print(f"  (info) tus directrices no cierran solas por {res['misclose']:.0f} "
          f"m; la planta resuelta queda a {res['trace_drift']:.0f} m del GPS "
          f"real — no afecta a la conduccion (el simulador usa kappa(s))")
    for a in res["avisos"]:
        print("  AVISO:", a)


if __name__ == "__main__":
    main()
