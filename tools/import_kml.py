"""Importador de circuitos desde un KML de Google Earth.

Convierte una línea (el eje de la pista, trazado a mano en Google Earth y
exportado como KML) al formato interno del simulador. A diferencia de
import_track.py (que parte de coordenadas métricas de la base TUM y
sintetiza el relieve), aquí:

  - La GEOMETRÍA sale de las coordenadas reales lon/lat del KML.
  - La RASANTE es REAL: la altura de cada punto se consulta en un modelo
    digital de elevación (OpenTopoData / EU-DEM 25 m). Como las líneas del
    KML van "pegadas al suelo", la cota del terreno es la de la pista.
  - El PERALTE se sintetiza (el DEM no lo capta), como en import_track.

La consulta de elevación se cachea en un JSON junto al KML para no
repetir peticiones (la API pública limita a 1000/día). Si no hay red, se
puede pasar un archivo de elevaciones ya descargado.

Uso:
  python tools/import_kml.py entrada.kml simulator/tracks/nombre.csv
  python tools/import_kml.py entrada.kml salida.csv --linea 1   # qué línea
  python tools/import_kml.py entrada.kml salida.csv --invertir  # sentido
"""

import json
import math
import os
import re
import subprocess
import sys
import time

SEGMENT_LENGTH = 4.0
KERB_KAPPA = 0.004
BANK_SCALE = 7.0
BANK_MAX_DEG = 6.0
ELEV_SMOOTH_M = 150.0    # suavizado de la rasante: quita el ruido del DEM
                         # de 25 m (puentes, desmontes) dejando pendientes
                         # realistas (~15 %) sin aplanar las cuestas largas
                         # como Eau Rouge/Raidillon (~200 m, sobreviven)


def parse_kml_lines(path):
    kml = open(path, encoding="utf-8").read()
    names = re.findall(r"<name>(.*?)</name>", kml, re.S)
    blocks = re.findall(r"<coordinates>(.*?)</coordinates>", kml, re.S)
    lines = []
    for b in blocks:
        pts = []
        for tok in b.split():
            lon, lat, *_ = tok.split(",")
            pts.append((float(lon), float(lat)))
        if math.dist(pts[0], pts[-1]) < 1e-6:
            pts.pop()
        lines.append(pts)
    return lines


def to_local_xy(pts):
    """lon/lat -> metros locales (equirectangular alrededor del centroide)."""
    lat0 = sum(p[1] for p in pts) / len(pts)
    mlat = 111320.0
    mlon = 111320.0 * math.cos(math.radians(lat0))
    return [((lon - pts[0][0]) * mlon, (lat - pts[0][1]) * mlat)
            for lon, lat in pts]


def fetch_elevations(pts, cache_path):
    """Elevación (m) de cada punto lon/lat. Cachea en cache_path."""
    if os.path.exists(cache_path):
        cached = json.load(open(cache_path))
        if len(cached) == len(pts):
            print(f"elevaciones desde caché ({len(cached)} puntos)")
            return cached
    elevs = []
    for bi in range(0, len(pts), 100):
        batch = pts[bi:bi + 100]
        locs = "|".join(f"{lat:.6f},{lon:.6f}" for lon, lat in batch)
        for attempt in range(5):
            r = subprocess.run(
                ["curl", "-sS", "--max-time", "30",
                 "https://api.opentopodata.org/v1/eudem25m",
                 "--data-urlencode", f"locations={locs}"],
                capture_output=True, text=True)
            try:
                data = json.loads(r.stdout)
            except ValueError:
                data = {"status": "parse_error"}
            if data.get("status") == "OK":
                elevs += [pt["elevation"] for pt in data["results"]]
                break
            time.sleep(2.0)
        else:
            raise SystemExit(f"la API de elevación falló en el lote {bi//100}")
    json.dump(elevs, open(cache_path, "w"))
    return elevs


def resample(xy, elev, step):
    """Remuestrea geometría y elevación a paso constante, cerrando el bucle.
    Devuelve (puntos_xy, elevaciones, longitud_total)."""
    n = len(xy)
    ring_xy = xy + [xy[0]]
    ring_e = elev + [elev[0]]
    cum = [0.0]
    for i in range(n):
        cum.append(cum[-1] + math.dist(ring_xy[i], ring_xy[i + 1]))
    total = cum[-1]
    m = max(8, int(round(total / step)))
    out_xy, out_e = [], []
    j = 0
    for k in range(m):
        target = total * k / m
        while cum[j + 1] < target:
            j += 1
        span = cum[j + 1] - cum[j]
        t = (target - cum[j]) / span if span > 0 else 0.0
        x = ring_xy[j][0] + (ring_xy[j + 1][0] - ring_xy[j][0]) * t
        y = ring_xy[j][1] + (ring_xy[j + 1][1] - ring_xy[j][1]) * t
        e = ring_e[j] + (ring_e[j + 1] - ring_e[j]) * t
        out_xy.append((x, y))
        out_e.append(e)
    return out_xy, out_e, total


def smooth_closed(vals, half):
    n = len(vals)
    return [sum(vals[(i + j) % n] for j in range(-half, half + 1))
            / (2 * half + 1) for i in range(n)]


def median_closed(vals, half):
    """Filtro de mediana circular: elimina picos atípicos del DEM (un
    árbol, un puente, un edificio leídos como terreno) sin desplazar las
    cuestas reales, cosa que un promedio no consigue."""
    n = len(vals)
    out = []
    for i in range(n):
        w = sorted(vals[(i + j) % n] for j in range(-half, half + 1))
        out.append(w[len(w) // 2])
    return out


def curvatures(xy, step, invert):
    n = len(xy)
    head = [math.atan2(xy[(i + 1) % n][1] - xy[i][1],
                       xy[(i + 1) % n][0] - xy[i][0]) for i in range(n)]
    ks = []
    for i in range(n):
        d = head[(i + 1) % n] - head[i]
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        ks.append(-d / step)          # +kappa = curva a la derecha
    ks = smooth_closed(ks, 2)
    if invert:
        ks = [-k for k in reversed(ks)]
    return ks


def main():
    argv = sys.argv[1:]
    invert = "--invertir" in argv
    line_idx = 1
    for a in argv:
        if a.startswith("--linea="):
            line_idx = int(a.split("=")[1])
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        raise SystemExit(1)
    src, dst = args
    lines = parse_kml_lines(src)
    pts = lines[line_idx]
    cache = os.path.splitext(src)[0] + "_elev.json"
    elev = fetch_elevations(pts, cache)

    # filtro de mediana sobre las muestras crudas del DEM (cada ~20 m):
    # quita los picos atípicos antes de resamplear
    elev = median_closed(elev, 2)

    xy = to_local_xy(pts)
    xy, elev, total = resample(xy, elev, SEGMENT_LENGTH)
    ks = curvatures(xy, SEGMENT_LENGTH, invert)
    if invert:
        elev = list(reversed(elev))
    # rasante real suavizada, con el error de cierre repartido
    half = max(1, int(ELEV_SMOOTH_M / SEGMENT_LENGTH / 2))
    elev = smooth_closed(elev, half)
    e0 = elev[0]
    err = elev[-1] - elev[0]
    n = len(elev)
    elev = [elev[i] - err * (i / n) - e0 for i in range(n)]  # 0 en la meta

    # peralte sintético hacia el interior
    win = max(1, int(15.0 / SEGMENT_LENGTH))
    cap = math.radians(BANK_MAX_DEG)
    banks = []
    for i in range(n):
        k = sum(ks[(i + j) % n] for j in range(-win, win + 1)) / (2 * win + 1)
        b = max(-cap, min(cap, k * BANK_SCALE))
        banks.append(b if abs(b) > 0.004 else 0.0)

    n_kerb = 0
    with open(dst, "w") as f:
        f.write("# Spa-Francorchamps: geometria y rasante REALES desde KML "
                "de Google Earth\n")
        f.write("# elevacion via OpenTopoData / EU-DEM 25m; peralte sintetico\n")
        f.write("# kappa_1pm,elev_m,kerb,peralte_rad  (segmentos de %.1f m)\n"
                % SEGMENT_LENGTH)
        for i, k in enumerate(ks):
            kerb = 1 if abs(k) > KERB_KAPPA else 0
            n_kerb += kerb
            f.write("%.6f,%.2f,%d,%.4f\n" % (k, elev[i], kerb, banks[i]))
    r_min = 1.0 / max(abs(k) for k in ks)
    print(f"{dst}: {n} segmentos, {total:.0f} m, radio min {r_min:.0f} m, "
          f"desnivel {max(elev)-min(elev):.0f} m, peralte max "
          f"{math.degrees(max(abs(b) for b in banks)):.1f} deg")


if __name__ == "__main__":
    main()
