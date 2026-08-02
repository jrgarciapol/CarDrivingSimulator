"""Importador de circuitos reales.

Convierte un CSV con el eje central de un circuito en coordenadas métricas
(formato TUMFTM/racetrack-database: ``x_m,y_m,w_tr_right_m,w_tr_left_m``,
válido también con solo ``x,y``) al formato interno del simulador: un CSV
con curvatura, elevación, piano y peralte por segmento de 4 m.

Pipeline:
  1. Suavizado ligero del eje (media móvil circular) para quitar el ruido
     de digitalización.
  2. Remuestreo a paso constante de SEGMENT_LENGTH por longitud de arco,
     cerrando el bucle.
  3. Curvatura con signo por diferencia de rumbo entre segmentos
     consecutivos (equivalente al circunscrito de 3 puntos, pero estable),
     suavizada de nuevo.
  4. Marcado de pianos donde el radio baja de ~250 m.
  5. PERALTE y RASANTE sintéticos (la base de datos TUM no los trae):
     - peralte proporcional a la curvatura suavizada (hacia el interior,
       como los circuitos reales), limitado a BANK_MAX_DEG;
     - rasante como suma de ondas senoidales sobre la vuelta completa
       (cerradas por construcción: la vuelta empieza y acaba a la misma
       cota), con pendientes máximas de ~5 %. Deterministas: importar el
       mismo circuito da siempre el mismo perfil.

Uso:
  python tools/import_track.py entrada.csv simulator/tracks/nombre.csv
  python tools/import_track.py --enriquecer simulator/tracks/nombre.csv
      (añade peralte y rasante a un circuito YA importado, sin el eje
       original; --sin-peralte / --sin-rasante desactivan cada cosa)
"""

import math
import sys

SEGMENT_LENGTH = 4.0
KERB_KAPPA = 0.004      # |kappa| > 1/250 m -> tramo con pianos
BANK_SCALE = 7.0        # rad de peralte por (1/m) de curvatura: R=100 m
                        # -> 4 grados hacia el interior
BANK_MAX_DEG = 6.0      # tope de peralte sintetizado (los circuitos de
                        # curvas reales rara vez pasan de 5-6 grados)
# Rasante sintética: lista de ondas (ciclos_por_vuelta, pendiente_maxima).
# Cada onda sube y baja 'ciclos' veces a lo largo de la vuelta con esa
# pendiente máxima (0.04 = 4 %); la amplitud en metros sale de ambas
# (amp = pendiente * longitud / (2*pi*ciclos)). Sumadas dan un perfil
# variado que empieza y acaba a la misma cota. Pendiente combinada en el
# peor punto ~9 %: se nota en el motor cuesta arriba y en la frenada.
GRADES = ((1, 0.038), (2, 0.030), (3, 0.022))


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


def synth_bank(ks, step):
    """Peralte sintético: hacia el interior de la curva, proporcional a
    la curvatura suavizada (~30 m, para que no invada la recta previa)
    y limitado a BANK_MAX_DEG."""
    n = len(ks)
    win = max(1, int(15.0 / step))
    cap = math.radians(BANK_MAX_DEG)
    out = []
    for i in range(n):
        k = sum(ks[(i + j) % n] for j in range(-win, win + 1)) / (2 * win + 1)
        bank = max(-cap, min(cap, k * BANK_SCALE))
        if abs(bank) < 0.004:      # <0.25 grados: dejarlo plano
            bank = 0.0
        out.append(bank)
    return out


def synth_elev(n_seg, step, total):
    """Rasante sintética: ondas senoidales sobre la vuelta (cerradas por
    construcción). Fases deterministas derivadas de la longitud."""
    out = []
    for i in range(n_seg):
        s = i * step
        e = 0.0
        for cycles, grade in GRADES:
            amp = grade * total / (2.0 * math.pi * cycles)
            phase = cycles * 2.399963 + (total % 100.0) * 0.0628
            e += amp * math.sin(2.0 * math.pi * cycles * s / total + phase)
        out.append(e)
    return out


def write_track(dst, ks, elevs, banks, total):
    n_kerb = 0
    with open(dst, "w") as f:
        f.write("# kappa_1pm,elev_m,kerb,peralte_rad  "
                "(segmentos de %.1f m, longitud %.0f m)\n"
                % (SEGMENT_LENGTH, total))
        for i, k in enumerate(ks):
            kerb = 1 if abs(k) > KERB_KAPPA else 0
            n_kerb += kerb
            f.write("%.6f,%.2f,%d,%.4f\n" % (k, elevs[i], kerb, banks[i]))
    r_min = 1.0 / max(abs(k) for k in ks)
    b_max = math.degrees(max(abs(b) for b in banks)) if banks else 0.0
    e_span = max(elevs) - min(elevs) if elevs else 0.0
    print(f"{dst}: {len(ks)} segmentos, {total:.0f} m, radio minimo "
          f"{r_min:.0f} m, {n_kerb} con piano, peralte max {b_max:.1f} deg, "
          f"desnivel {e_span:.0f} m")


def load_internal(path):
    """Lee un circuito en formato interno (3 o 4 columnas)."""
    ks = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cols = line.split(",")
            ks.append(float(cols[0]))
    return ks


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    do_bank = "--sin-peralte" not in flags
    do_elev = "--sin-rasante" not in flags

    if "--enriquecer" in flags and len(args) == 1:
        # añadir peralte/rasante a un circuito ya importado
        path = args[0]
        ks = load_internal(path)
        total = len(ks) * SEGMENT_LENGTH
        banks = synth_bank(ks, SEGMENT_LENGTH) if do_bank else [0.0] * len(ks)
        elevs = synth_elev(len(ks), SEGMENT_LENGTH, total) if do_elev \
            else [0.0] * len(ks)
        write_track(path, ks, elevs, banks, total)
        return

    if len(args) != 2:
        print(__doc__)
        raise SystemExit(1)
    src, dst = args
    pts = load_points(src)
    pts = smooth_closed(pts, win=1)
    pts, total = resample_closed(pts, SEGMENT_LENGTH)
    ks = curvatures(pts, SEGMENT_LENGTH)
    banks = synth_bank(ks, SEGMENT_LENGTH) if do_bank else [0.0] * len(ks)
    elevs = synth_elev(len(ks), SEGMENT_LENGTH, total) if do_elev \
        else [0.0] * len(ks)
    write_track(dst, ks, elevs, banks, total)


if __name__ == "__main__":
    main()
