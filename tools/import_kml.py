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

Con --idealizar, además, el trazado se ajusta a alineaciones de diseño de
carreteras matemáticamente coherentes, eliminando el temblor de trazar a
mano. El formato interno ES el diagrama de curvatura (κ por segmento), y un
trazado correcto es, en ese diagrama, una poligonal continua: tramos planos
(rectas si κ=0, círculos si κ=cte) unidos por rampas (clotoides, κ lineal).
Igual el alzado en el diagrama de pendiente: rasantes rectas (g=cte) unidas
por acuerdos parabólicos (g lineal). Planta y alzado se idealizan por
separado. La simplificación (Douglas-Peucker sobre cada diagrama) se calibra
para que la desviación lateral/vertical LOCAL no supere una tolerancia en
metros (--tol, 3 m por defecto), y se fuerza el cierre exacto del bucle.

Uso:
  python tools/import_kml.py entrada.kml simulator/tracks/nombre.csv
  python tools/import_kml.py entrada.kml salida.csv --idealizar   # rectas+
                                            # circulos+clotoides / parabolicas
  python tools/import_kml.py entrada.kml salida.csv --idealizar --tol=2
  python tools/import_kml.py entrada.kml salida.csv --linea=1     # qué línea
  python tools/import_kml.py entrada.kml salida.csv --invertir    # sentido
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


def resample(xy, elev, step, widths=None):
    """Remuestrea geometría y elevación (y opcionalmente el semiancho) a paso
    constante, cerrando el bucle. Devuelve (puntos_xy, elevaciones, longitud);
    si se pasan widths, devuelve (puntos_xy, elevaciones, semianchos, longitud)."""
    n = len(xy)
    ring_xy = xy + [xy[0]]
    ring_e = elev + [elev[0]]
    ring_w = (widths + [widths[0]]) if widths is not None else None
    cum = [0.0]
    for i in range(n):
        cum.append(cum[-1] + math.dist(ring_xy[i], ring_xy[i + 1]))
    total = cum[-1]
    m = max(8, int(round(total / step)))
    out_xy, out_e, out_w = [], [], []
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
        if ring_w is not None:
            out_w.append(ring_w[j] + (ring_w[j + 1] - ring_w[j]) * t)
    if widths is not None:
        return out_xy, out_e, out_w, total
    return out_xy, out_e, total


def build_track(pts, dst, widths=None, cache=None, invert=False):
    """Construye un track del simulador (κ + cota REAL del DEM + piano +
    peralte sintético[, semiancho]) a partir de una polilínea lat/lon, SIN
    idealizar la planta (para fuentes ya limpias como TUMFTM). Si se pasan
    widths (semiancho por punto de `pts`), se escribe una 5ª columna con el
    semiancho remuestreado. Devuelve (n_segmentos, longitud)."""
    cache = cache or (os.path.splitext(dst)[0] + "_elev.json")
    elev = median_closed(fetch_elevations(pts, cache), 2)
    xy = to_local_xy(pts)
    if widths is not None:
        xy, elev, ws, total = resample(xy, elev, SEGMENT_LENGTH, widths)
    else:
        xy, elev, total = resample(xy, elev, SEGMENT_LENGTH)
        ws = None
    ks = curvatures(xy, SEGMENT_LENGTH, invert)
    n = len(ks)
    half = max(1, int(ELEV_SMOOTH_M / SEGMENT_LENGTH / 2))
    elev = smooth_closed(elev, half)
    err = elev[-1] - elev[0]
    elev = [elev[i] - err * (i / n) for i in range(n)]
    e0 = elev[0]
    elev = [e - e0 for e in elev]
    win = max(1, int(15.0 / SEGMENT_LENGTH))
    cap = math.radians(BANK_MAX_DEG)
    banks = []
    for i in range(n):
        k = sum(ks[(i + j) % n] for j in range(-win, win + 1)) / (2 * win + 1)
        b = max(-cap, min(cap, k * BANK_SCALE))
        banks.append(b if abs(b) > 0.004 else 0.0)
    with open(dst, "w") as f:
        f.write("# Track importado (planta cruda + cota REAL del DEM)\n")
        f.write("# kappa_1pm,elev_m,kerb,peralte_rad" +
                (",semiancho_m\n" if ws is not None else "\n"))
        for i, k in enumerate(ks):
            kerb = 1 if abs(k) > KERB_KAPPA else 0
            if ws is not None:
                f.write("%.6f,%.2f,%d,%.4f,%.2f\n"
                        % (k, elev[i], kerb, banks[i], ws[i]))
            else:
                f.write("%.6f,%.2f,%d,%.4f\n" % (k, elev[i], kerb, banks[i]))
    return n, total


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


def dp_simplify(vals, eps):
    """Simplifica una señal 1D a poligonal continua cuyos vértices distan
    < eps (distancia VERTICAL) de la señal. Es Douglas-Peucker en el eje
    del valor: cada vértice conservado es un CAMBIO DE ALINEACIÓN. Los
    tramos entre vértices son rectas (pendiente 0 en el diagrama) o rampas.
    Devuelve la lista de índices conservados."""
    n = len(vals)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        va, vb = vals[a], vals[b]
        span = b - a
        dmax, idx = 0.0, -1
        for i in range(a + 1, b):
            # valor de la poligonal (recta a-b) en i, distancia vertical
            v_lin = va + (vb - va) * (i - a) / span
            d = abs(vals[i] - v_lin)
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps and idx > 0:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [i for i in range(n) if keep[i]]


def pwl_from_vertices(vals, idx):
    """Reconstruye la señal como poligonal continua interpolando linealmente
    entre los vértices conservados (idx)."""
    n = len(vals)
    out = [0.0] * n
    for k in range(len(idx) - 1):
        a, b = idx[k], idx[k + 1]
        va, vb = vals[a], vals[b]
        for i in range(a, b + 1):
            out[i] = va + (vb - va) * (i - a) / (b - a)
    return out


def _integrate_heading_xy(ks, step, h0):
    x = y = 0.0
    h = h0
    pts = [(0.0, 0.0)]
    for k in ks:
        h += k * step
        x += math.cos(h) * step
        y += math.sin(h) * step
        pts.append((x, y))
    return pts


def local_dev_plan(cand, ref, step, win_m=250.0):
    """Desviación lateral LOCAL entre dos curvaturas: integra ambas en
    ventanas re-ancladas (mismo marco), sin acumular la deriva global de
    una vuelta de 7 km. Es la noción de 'offset perpendicular al eje' del
    diseño de carreteras, no un error acumulado."""
    n = len(cand)
    win = max(4, int(win_m / step))
    worst = 0.0
    for start in range(0, n, win // 2):
        hc = hr = xc = yc = xr = yr = d = 0.0
        for i in range(start, min(n, start + win)):
            hc += cand[i] * step
            xc += math.cos(hc) * step
            yc += math.sin(hc) * step
            hr += ref[i] * step
            xr += math.cos(hr) * step
            yr += math.sin(hr) * step
            d = max(d, math.hypot(xc - xr, yc - yr))
        worst = max(worst, d)
    return worst


def local_dev_1d(cand, ref, step, win_m=250.0):
    """Desviación LOCAL de una cota respecto a otra a partir de sus
    pendientes (integración simple en ventanas re-ancladas)."""
    n = len(cand)
    win = max(4, int(win_m / step))
    worst = 0.0
    for start in range(0, n, win // 2):
        zc = zr = d = 0.0
        for i in range(start, min(n, start + win)):
            zc += cand[i] * step
            zr += ref[i] * step
            d = max(d, abs(zc - zr))
        worst = max(worst, d)
    return worst


def _calibrate_eps(sig, dev_fn, tol, lo=1e-5, hi=2e-2):
    """Busca por bisección el mayor eps de simplificación cuya desviación
    local no supere tol. Devuelve los índices de vértices resultantes."""
    for _ in range(26):
        eps = math.sqrt(lo * hi)
        cand = pwl_from_vertices(sig, dp_simplify(sig, eps))
        if dev_fn(cand) > tol:
            hi = eps
        else:
            lo = eps
    return dp_simplify(sig, lo)


def idealize_plan(ks, raw_xy, step, tol_m):
    """Ajusta el diagrama de curvatura κ(s) a rectas, círculos y clotoides.
    La tolerancia es la desviación lateral LOCAL respecto al eje trazado."""
    ks_s = smooth_closed(ks, 10)          # ±40 m: limpia el ruido de trazar
    idx = _calibrate_eps(ks_s, lambda c: local_dev_plan(c, ks_s, step), tol_m)
    kv = pwl_from_vertices(ks_s, idx)
    # snap conservador: solo curvaturas de R>5000 m (prácticamente rectas)
    # se fijan a κ=0. Al tocar el VALOR DE LOS VÉRTICES se mantiene la
    # continuidad de κ (clave de recta->clotoide->círculo).
    straight_kappa = 1.0 / 5000.0
    for i in idx:
        if abs(kv[i]) < straight_kappa:
            kv[i] = 0.0
    kv = pwl_from_vertices(kv, idx)
    # cierre: la vuelta debe girar exactamente ±2π. Se escala (mantiene
    # las rectas en κ=0), con factor ~1.
    turn = sum(kv) * step
    if abs(turn) > 1e-6:
        f = math.copysign(2 * math.pi, turn) / turn
        kv = [k * f for k in kv]
    return kv, idx


def idealize_profile(elev, step, tol_m):
    """Ajusta el diagrama de pendiente g(s) a rasantes rectas unidas por
    acuerdos parabólicos (rampa en g = parábola en cota). Integra a cota.
    La tolerancia es la desviación vertical LOCAL respecto a la rasante."""
    n = len(elev)
    g = [(elev[(i + 1) % n] - elev[i]) / step for i in range(n)]
    g = smooth_closed(g, 13)              # ±52 m: quita el ruido del DEM
    idx = _calibrate_eps(g, lambda c: local_dev_1d(c, g, step), tol_m)
    gv = pwl_from_vertices(g, idx)
    # cierre exacto: pendiente media nula -> la vuelta vuelve a su cota
    gv = [gi - sum(gv) / n for gi in gv]
    z = [elev[0]]
    for gi in gv:
        z.append(z[-1] + gi * step)
    return z[:n], idx


def classify(kv, idx, step):
    """Cuenta rectas, círculos y clotoides del diagrama idealizado."""
    straight_k = 1.0 / 1500.0
    n_straight = n_arc = n_cloth = 0
    for k in range(len(idx) - 1):
        a, b = idx[k], idx[k + 1]
        ka, kb = kv[a], kv[b]
        if abs(kb - ka) < 5e-5 * (b - a):     # pendiente ~0 -> tramo plano
            if max(abs(ka), abs(kb)) < straight_k:
                n_straight += 1
            else:
                n_arc += 1
        else:
            n_cloth += 1
    return n_straight, n_arc, n_cloth


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
    idealizar = "--idealizar" in argv
    plan_tol = 3.0        # m de desviación lateral admitida en planta
    alz_tol = 2.0         # m de desviación en alzado
    line_idx = None       # None = automático (la LineString más larga)
    for a in argv:
        if a.startswith("--linea="):
            line_idx = int(a.split("=")[1])
        if a.startswith("--tol="):
            plan_tol = float(a.split("=")[1])
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        raise SystemExit(1)
    src, dst = args
    lines = parse_kml_lines(src)
    if not lines:
        print("el KML no contiene ninguna LineString")
        raise SystemExit(1)
    if line_idx is None:
        # por defecto, la línea con más puntos (el eje principal); asi valen
        # tanto el KML de una sola linea (georef_tool) como los de varias
        line_idx = max(range(len(lines)), key=lambda i: len(lines[i]))
    elif line_idx < 0 or line_idx >= len(lines):
        print(f"aviso: el KML solo tiene {len(lines)} linea(s); uso la 0")
        line_idx = 0
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
        xy = list(reversed(xy))
    n = len(elev)

    if idealizar:
        ks_ref = smooth_closed(ks, 10)
        # PLANTA: κ(s) -> rectas + círculos + clotoides
        ks, plan_idx = idealize_plan(ks, xy, SEGMENT_LENGTH, plan_tol)
        plan_dev = local_dev_plan(ks, ks_ref, SEGMENT_LENGTH)
        # ALZADO: g(s) -> rasantes rectas + acuerdos parabólicos
        elev, alz_idx = idealize_profile(elev, SEGMENT_LENGTH, alz_tol)
        n_s, n_a, n_c = classify(ks, plan_idx, SEGMENT_LENGTH)
        alz_lines = len(alz_idx) - 1
    else:
        half = max(1, int(ELEV_SMOOTH_M / SEGMENT_LENGTH / 2))
        elev = smooth_closed(elev, half)
        err = elev[-1] - elev[0]
        elev = [elev[i] - err * (i / n) for i in range(n)]
    # normalizar cota: 0 en la meta
    e0 = elev[0]
    elev = [e - e0 for e in elev]

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
        modo = "IDEALIZADA (rectas+circulos+clotoides)" if idealizar else "cruda"
        f.write("# Spa-Francorchamps: geometria %s + rasante REAL (KML+DEM)\n"
                % modo)
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
    if idealizar:
        print(f"  PLANTA idealizada: {n_s} rectas, {n_a} circulos, "
              f"{n_c} clotoides (desv. lateral max {plan_dev:.1f} m)")
        print(f"  ALZADO idealizado: {alz_lines} alineaciones "
              f"(rasantes + acuerdos parabolicos)")


if __name__ == "__main__":
    main()
