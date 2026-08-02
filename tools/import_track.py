"""Importador de circuitos reales.

Convierte un CSV con el eje central de un circuito en coordenadas métricas
(formato TUMFTM/racetrack-database: ``x_m,y_m,w_tr_right_m,w_tr_left_m``,
válido también con solo ``x,y``) al formato interno del simulador: un CSV
con curvatura, elevación y piano por segmento de 4 m.

Pipeline:
  1. Suavizado ligero del eje (media móvil circular) para quitar el ruido
     de digitalización.
  2. Remuestreo a paso constante de SEGMENT_LENGTH por longitud de arco,
     cerrando el bucle.
  3. Curvatura con signo por diferencia de rumbo entre segmentos
     consecutivos (equivalente al circunscrito de 3 puntos, pero estable),
     suavizada de nuevo.
  4. Marcado de pianos donde el radio baja de ~250 m.

Uso:
  python tools/import_track.py entrada.csv simulator/tracks/nombre.csv
"""

import math
import sys

SEGMENT_LENGTH = 4.0
KERB_KAPPA = 0.004      # |kappa| > 1/250 m -> tramo con pianos


def load_points(path):
    pts = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.replace(";", ",").split(",")
            pts.append((float(parts[0]), float(parts[1])))
    if len(pts) < 10:
        raise SystemExit("CSV con muy pocos puntos")
    # si el último punto repite el primero, quitarlo (lo cerramos nosotros)
    if math.dist(pts[0], pts[-1]) < 1.0:
        pts.pop()
    return pts


def smooth_closed(pts, win=1):
    n = len(pts)
    out = []
    for i in range(n):
        sx = sy = 0.0
        for j in range(-win, win + 1):
            px, py = pts[(i + j) % n]
            sx += px
            sy += py
        k = 2 * win + 1
        out.append((sx / k, sy / k))
    return out


def resample_closed(pts, step):
    """Puntos equiespaciados 'step' metros a lo largo del bucle cerrado."""
    n = len(pts)
    ring = pts + [pts[0]]
    cum = [0.0]
    for i in range(n):
        cum.append(cum[-1] + math.dist(ring[i], ring[i + 1]))
    total = cum[-1]
    n_seg = max(8, int(round(total / step)))
    out = []
    j = 0
    for k in range(n_seg):
        target = total * k / n_seg
        while cum[j + 1] < target:
            j += 1
        span = cum[j + 1] - cum[j]
        t = (target - cum[j]) / span if span > 0 else 0.0
        x = ring[j][0] + (ring[j + 1][0] - ring[j][0]) * t
        y = ring[j][1] + (ring[j + 1][1] - ring[j][1]) * t
        out.append((x, y))
    return out, total


def curvatures(pts, step):
    """Curvatura con signo por segmento (convenio del simulador:
    positiva = curva a la derecha en el sentido de la marcha)."""
    n = len(pts)
    headings = []
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        headings.append(math.atan2(y1 - y0, x1 - x0))
    kappas = []
    for i in range(n):
        d = headings[(i + 1) % n] - headings[i]
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        # en el plano XY matemático, girar a la derecha es rumbo decreciente
        kappas.append(-d / step)
    # suavizado corto para eliminar el ruido punto a punto
    out = []
    for i in range(n):
        acc = sum(kappas[(i + j) % n] for j in range(-2, 3))
        out.append(acc / 5.0)
    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(1)
    src, dst = sys.argv[1], sys.argv[2]
    pts = load_points(src)
    pts = smooth_closed(pts, win=1)
    pts, total = resample_closed(pts, SEGMENT_LENGTH)
    ks = curvatures(pts, SEGMENT_LENGTH)

    n_kerb = 0
    with open(dst, "w") as f:
        f.write("# kappa_1pm,elev_m,kerb  (segmentos de %.1f m, longitud %.0f m)\n"
                % (SEGMENT_LENGTH, total))
        for k in ks:
            kerb = 1 if abs(k) > KERB_KAPPA else 0
            n_kerb += kerb
            f.write("%.6f,%.2f,%d\n" % (k, 0.0, kerb))

    r_min = 1.0 / max(abs(k) for k in ks)
    print(f"{dst}: {len(ks)} segmentos, {total:.0f} m, "
          f"radio minimo {r_min:.0f} m, {n_kerb} segmentos con piano")


if __name__ == "__main__":
    main()
