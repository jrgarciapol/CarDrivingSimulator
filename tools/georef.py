"""Georreferencia un eje de circuito métrico (repo TUMFTM/racetrack-database,
formato x_m,y_m,...) a latitud/longitud, para poder bajarle la ALTIMETRÍA del
DEM y luego ajustar el alzado con profile_editor.

La planta de TUMFTM ya es limpia (calidad CAD): no hay que idealizarla. Solo
está en metros con origen y giro arbitrarios. Con DOS PUNTOS DE CONTROL
—un punto del CSV emparejado con su lat/lon real, leído sobre Google Earth /
satélite— se calcula la transformación de SEMEJANZA (giro + escala + traslación)
que lleva todo el eje a lat/lon CONSERVANDO su geometría suave. La escala sale
≈1 si el CSV ya está en metros (TUMFTM), o la que toque si viene normalizado.

Salida: un KML (LineString) con lat/lon, que import_kml consume para bajar la
altimetría y escribir el track:

  1. python tools/georef.py silverstone.csv salida.kml \\
         --c1=0:52.0786,-1.0169  --c2=735:52.0690,-1.0125
     (c1/c2 = INDICE_en_el_CSV : LAT,LON del punto real)
  2. python tools/import_kml.py salida.kml simulator/tracks/silverstone.csv
  3. python tools/profile_editor.py simulator/tracks/silverstone.csv
"""

import math
import sys

MLAT = 111320.0        # m por grado de latitud (esférico, suficiente a ~km)


def load_xy(path):
    pts = []
    for ln in open(path):
        ln = ln.strip()
        if not ln or ln.startswith("#") or ln.lower().startswith("x_m"):
            continue
        p = ln.replace(";", ",").split(",")
        pts.append((float(p[0]), float(p[1])))
    return pts


def _mlon(lat0):
    return MLAT * math.cos(math.radians(lat0))


def latlon_to_en(lat, lon, lat0, lon0):
    """lat/lon -> (este, norte) en metros alrededor de (lat0, lon0)."""
    return ((lon - lon0) * _mlon(lat0), (lat - lat0) * MLAT)


def en_to_latlon(e, n, lat0, lon0):
    """(este, norte) en metros -> lat/lon alrededor de (lat0, lon0)."""
    return (lat0 + n / MLAT, lon0 + e / _mlon(lat0))


def similarity(cA_xy, cA_ll, cB_xy, cB_ll):
    """Parámetros de la semejanza CSV->lat/lon a partir de 2 controles.
    Devuelve (lat0, lon0, alpha, scale, A_xy) usando el control A como
    origen local."""
    lat0, lon0 = cA_ll
    Ben = latlon_to_en(cB_ll[0], cB_ll[1], lat0, lon0)   # A es el origen (0,0)
    dxy = (cB_xy[0] - cA_xy[0], cB_xy[1] - cA_xy[1])
    ang_en = math.atan2(Ben[1], Ben[0])
    ang_xy = math.atan2(dxy[1], dxy[0])
    alpha = ang_en - ang_xy
    scale = math.hypot(*Ben) / (math.hypot(*dxy) or 1e-9)
    return lat0, lon0, alpha, scale, cA_xy


def georef_points(pts, cA_xy, cA_ll, cB_xy, cB_ll):
    """Lleva los puntos (x,y) métricos a [(lat, lon), ...] con la semejanza de
    2 controles."""
    lat0, lon0, alpha, scale, A = similarity(cA_xy, cA_ll, cB_xy, cB_ll)
    ca, sa = math.cos(alpha), math.sin(alpha)
    out = []
    for (x, y) in pts:
        rx, ry = x - A[0], y - A[1]
        e = scale * (ca * rx - sa * ry)
        n = scale * (sa * rx + ca * ry)
        out.append(en_to_latlon(e, n, lat0, lon0))
    return out


def write_kml(latlon, path, name="circuito"):
    coords = " ".join(f"{lon:.8f},{lat:.8f},0" for (lat, lon) in latlon)
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
                f'<Placemark><name>{name}</name><LineString>'
                '<tessellate>1</tessellate>'
                f'<coordinates>{coords}</coordinates>'
                '</LineString></Placemark></Document></kml>\n')


def _parse_control(s, pts):
    """'INDICE:LAT,LON' -> ((x,y) del CSV, (lat,lon))."""
    idx_s, ll = s.split(":")
    lat, lon = (float(v) for v in ll.split(","))
    i = int(idx_s) % len(pts)
    return pts[i], (lat, lon)


def main():
    argv = sys.argv[1:]
    args = [a for a in argv if not a.startswith("--")]
    c1 = c2 = None
    name = "circuito"
    for a in argv:
        if a.startswith("--c1="):
            c1 = a.split("=", 1)[1]
        if a.startswith("--c2="):
            c2 = a.split("=", 1)[1]
        if a.startswith("--nombre="):
            name = a.split("=", 1)[1]
    if len(args) != 2 or not c1 or not c2:
        print(__doc__)
        raise SystemExit(1)
    src, dst = args
    pts = load_xy(src)
    A_xy, A_ll = _parse_control(c1, pts)
    B_xy, B_ll = _parse_control(c2, pts)
    latlon = georef_points(pts, A_xy, A_ll, B_xy, B_ll)
    write_kml(latlon, dst, name)
    _, _, _, scale, _ = similarity(A_xy, A_ll, B_xy, B_ll)
    print(f"{dst}: {len(latlon)} puntos georreferenciados "
          f"(escala CSV->m = {scale:.4f}; ~1 si ya venia en metros)")
    print("  siguiente: python tools/import_kml.py "
          f"{dst} simulator/tracks/<nombre>.csv  (baja altimetria)")


if __name__ == "__main__":
    main()
