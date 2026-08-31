"""Genera TRES carreteras cerradas, una por tipo de via, trazadas con la
Norma 3.1-IC (Trazado). Cada una esta disenada INTEGRAMENTE para su
VELOCIDAD DE PROYECTO (el numero de la denominacion espanola, en km/h):

  - a-120.csv  autovia / variante,        Vp = 120 km/h  (rectas, radios grandes)
  - c-90.csv   convencional de puerto,     Vp = 90 km/h   (curvas amplias)
  - c-50.csv   convencional de montana,    Vp = 50 km/h   (revirada)

En cada trazado TODAS las curvas caen en la banda de radios de su tipo y se
respetan sus condicionantes (Norma 3.1-IC):
  - Radio minimo en planta  R_min = V^2 / (127 * (f_t + p_max))
  - Clotoide de transicion   A ~ 0.55 R  (dentro de R/3 <= A <= R), acotada
    para no girar mas que la propia deflexion de la curva
  - Peralte segun el radio, hasta p_max (8% autovia, 7% convencional)
  - Pendiente longitudinal por debajo del maximo del tipo de via
  - Acuerdos verticales con Kv muy holgado

METODO. Cada trazado en planta es un POLIGONO CERRADO de vertices 2D (cierra
en posicion y rumbo por construccion: la suma de deflexiones es 360). Cada
esquina se redondea con clotoide-arco-clotoide de radio ADAPTATIVO, acotado
por arriba y por abajo a la banda del tipo, y la curvatura se emite con GIRO
EXACTO por curva (cierre 360 exacto, gap de pocos metros). Arranca en la
mitad de la recta mas larga, llana y sin peralte: la costura es continua.

Salida en simulator/tracks/ (formato interno del simulador):
    kappa_1_per_m, elev_m, piano(0/1), peralte_rad, semiancho_m

    python tools/make_carretera.py
"""

import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clothoid as cl

SEG = 4.0                       # m por segmento (formato interno del sim)


# ---------------------------------------------------------------------------
# 1. PARAMETROS DE LA NORMA 3.1-IC POR VELOCIDAD DE PROYECTO
# ---------------------------------------------------------------------------
# ft = rozamiento transversal maximo movilizado ; pmax = peralte maximo
# grade_max = pendiente longitudinal maxima ; half_w = semiancho util (m)
# r_cap = radio maximo dibujado en ese tipo (acota la banda por arriba)
TIPOS = {
    "A-120": dict(vp=120, ft=0.085, pmax=0.08, grade_max=0.040, half_w=4.75,
                  r_cap=2000.0),
    "C-90":  dict(vp=90,  ft=0.118, pmax=0.07, grade_max=0.050, half_w=3.75,
                  r_cap=680.0),
    "C-50":  dict(vp=50,  ft=0.165, pmax=0.07, grade_max=0.070, half_w=3.25,
                  r_cap=330.0),
}


def r_min(t):
    d = TIPOS[t]
    return d["vp"] ** 2 / (127.0 * (d["ft"] + d["pmax"]))


def peralte(t, R):
    """Peralte (fraccion): en R_min vale p_max y decrece hacia 2% al crecer R."""
    d = TIPOS[t]
    p = d["pmax"] * math.sqrt(r_min(t) / R)
    return max(0.02, min(d["pmax"], p))


def clot_len(R, defl):
    """A=0.55R, pero nunca gira mas que la deflexion de la curva."""
    return min((0.55 * R) ** 2 / R, R * abs(defl))


def tangent_len(R, defl):
    L = clot_len(R, defl)
    p, cx, _ = cl.clothoid_shift(L, R, 1.0)
    return cx + (R + p) * math.tan(abs(defl) / 2.0)


# ---------------------------------------------------------------------------
# 2. VERTICES DE CADA ANILLO (poligono cerrado 2D, en metros)
# ---------------------------------------------------------------------------
def _weave(Pa, Pb, amp, k):
    """k puntos ondulando suave por el corredor Pa->Pb (eses de montana)."""
    dx, dy = Pb[0] - Pa[0], Pb[1] - Pa[1]
    Lc = math.hypot(dx, dy)
    nx, ny = -dy / Lc, dx / Lc
    out = []
    for j in range(1, k + 1):
        t = j / (k + 1)
        off = amp * math.sin(math.pi * t * k)
        out.append((Pa[0] + dx * t + nx * off, Pa[1] + dy * t + ny * off))
    return out


def verts_a120():
    """Anillo grande de 9 vertices: curvas suaves de radio grande y rectas
    largas. Todas las curvas quedan por encima del R_min de la autovia."""
    nv, base, pert, ys = 9, 1700.0, 120.0, 0.90
    V = []
    for a in range(nv):
        ang = 2.0 * math.pi * a / nv
        rr = base + (pert if a % 2 else -pert * 0.5)
        V.append((rr * math.cos(ang), rr * math.sin(ang) * ys))
    return V


def verts_c90():
    """Carretera de puerto: curvas amplias enlazadas por rectas medias."""
    return [(-1200, -120), (-150, -360), (1050, -230), (1750, 350),
            (1620, 1120), (950, 1600), (150, 1500), (-650, 1650),
            (-1450, 1050), (-1650, 380)]


def verts_c50():
    """Carretera de montana revirada: dos tandas de eses (ondulacion) unidas
    por tramos cortos; radios cerrados, cerca del R_min."""
    V = [(-800, -60), (-100, -200), (650, -120)]
    V += _weave((650, -120), (950, 900), 120.0, 4)
    V += [(700, 1150), (150, 1250)]
    V += _weave((150, 1250), (-700, 300), 120.0, 4)
    V += [(-850, 60)]
    return V


PRESETS = [
    ("A-120", "a-120.csv", verts_a120),
    ("C-90",  "c-90.csv",  verts_c90),
    ("C-50",  "c-50.csv",  verts_c50),
]


# ---------------------------------------------------------------------------
# 3. GEOMETRIA: deflexiones, radios adaptativos y perfil por segmento
# ---------------------------------------------------------------------------
def deflections(V):
    n = len(V)
    D = []
    for i in range(n):
        a, b, c = V[(i - 1) % n], V[i], V[(i + 1) % n]
        h1 = math.atan2(b[1] - a[1], b[0] - a[0])
        h2 = math.atan2(c[1] - b[1], c[0] - b[0])
        D.append((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
    return D


def edge_lengths(V):
    n = len(V)
    return [math.hypot(V[(i + 1) % n][0] - V[i][0],
                       V[(i + 1) % n][1] - V[i][1]) for i in range(n)]


def choose_radii(D, E, floor, cap):
    """Mayor radio cuya tangente cabe en las dos rectas (T <= 0.46*min),
    acotado a la banda [floor, cap] del tipo de via."""
    n = len(D)
    R = []
    for i in range(n):
        lim = 0.46 * min(E[(i - 1) % n], E[i])
        best = floor
        r = floor
        while r <= cap:
            if tangent_len(r, D[i]) <= lim:
                best = r
            r += 2.0
        R.append(best)
    return R


def build_profile(t, V, D, E, R):
    """kappa, peralte y semiancho por segmento (giro exacto, ancho constante
    del tipo de via)."""
    n = len(V)
    hw = TIPOS[t]["half_w"]
    T = [tangent_len(R[i], D[i]) for i in range(n)]
    kap, ban = [], []
    for i in range(n):
        Ri = R[i]
        sgn = 1.0 if D[i] >= 0 else -1.0
        Lc = clot_len(Ri, D[i])
        ct = Lc / (2.0 * Ri)
        at = max(0.0, abs(D[i]) - 2.0 * ct)
        p_full = sgn * peralte(t, Ri)
        nc = max(1, int(round(Lc / SEG)))
        na = max(0, int(round(at * Ri / SEG)))
        wsum = sum(j + 0.5 for j in range(nc))
        for j in range(nc):                                  # clotoide entrada
            kap.append(sgn * ct * ((j + 0.5) / wsum) / SEG)
            ban.append(p_full * (j + 0.5) / nc)
        for _ in range(na):                                  # arco
            kap.append(sgn * at / na / SEG)
            ban.append(p_full)
        for j in range(nc):                                  # clotoide salida
            jj = nc - 1 - j
            kap.append(sgn * ct * ((jj + 0.5) / wsum) / SEG)
            ban.append(p_full * (jj + 0.5) / nc)
        L_str = E[i] - T[i] - T[(i + 1) % n]
        for _ in range(max(0, int(round(L_str / SEG)))):     # recta
            kap.append(0.0)
            ban.append(0.0)
    wid = [hw] * len(kap)
    return kap, ban, wid


def roll_to_longest_straight(arrs):
    kap = arrs[0]
    n = len(kap)
    best_len = best_start = 0
    i = 0
    while i < n:
        if abs(kap[i]) < 1e-9:
            j = i
            while j < n and abs(kap[j]) < 1e-9:
                j += 1
            if j - i > best_len:
                best_len, best_start = j - i, i
            i = j
        else:
            i += 1
    off = (best_start + best_len // 2) % n
    return [a[off:] + a[:off] for a in arrs]


def elevation(n, grade_max):
    """Rasante que cierra cota y pendiente a 0; pendiente maxima ~ grade_max
    del tipo de via."""
    L = n * SEG
    frac = [(1, 0.40), (2, 0.35), (3, 0.175), (5, 0.075)]     # suman 1.0
    amp = [(m, f * grade_max * L / (2.0 * math.pi * m)) for m, f in frac]
    y = [sum(Ak * math.sin(2.0 * math.pi * m * (i + 0.5) * SEG / L)
             for m, Ak in amp) for i in range(n)]
    return [v - y[0] for v in y]


# ---------------------------------------------------------------------------
# 4. GENERAR LOS TRES TRAZADOS
# ---------------------------------------------------------------------------
def _integrate(kap):
    h = x = y = 0.0
    for k in kap:
        x += math.cos(h) * SEG
        y += math.sin(h) * SEG
        h += k * SEG
    return math.hypot(x, y), math.degrees(h)


def _zone(R):
    if R >= r_min("A-120"):
        return "A-120"
    if R >= r_min("C-90"):
        return "C-90"
    return "C-50"


def generate(t, fname, vfun):
    V = vfun()
    D = deflections(V)
    E = edge_lengths(V)
    R = choose_radii(D, E, r_min(t), TIPOS[t]["r_cap"])
    kap, ban, wid = build_profile(t, V, D, E, R)
    kap, ban, wid = roll_to_longest_straight([kap, ban, wid])
    y = elevation(len(kap), TIPOS[t]["grade_max"])

    gap, hnet = _integrate(kap)
    gmax = max(abs(y[i] - y[i - 1]) / SEG for i in range(1, len(y)))
    pmax = max(peralte(t, r) for r in R)
    fuera = [round(r) for r in R if _zone(r) != t]

    path = os.path.join(os.path.dirname(__file__), "..",
                        "simulator", "tracks", fname)
    with open(path, "w") as f:
        f.write(f"# {t} generada por tools/make_carretera.py (Norma 3.1-IC)\n")
        f.write(f"# Vp={TIPOS[t]['vp']} km/h, R_min={r_min(t):.0f} m, "
                f"peralte<= {TIPOS[t]['pmax'] * 100:.0f}%, "
                f"pendiente<= {TIPOS[t]['grade_max'] * 100:.0f}%\n")
        f.write("# kappa_1_per_m, elev_m, piano, peralte_rad, semiancho_m\n")
        for k, e, b, w in zip(kap, y, ban, wid):
            f.write(f"{k:.6f},{e:.2f},0,{b:.4f},{w:.2f}\n")

    print(f"{fname}: {len(kap) * SEG / 1000:.2f} km, {len(R)} curvas | "
          f"cierre {hnet:.2f} deg, gap {gap:.1f} m")
    print(f"    R_min norma {r_min(t):.0f} m | radios "
          f"{sorted(round(r) for r in R)} m")
    print(f"    peralte max {pmax * 100:.1f}% (<= {TIPOS[t]['pmax'] * 100:.0f}%) | "
          f"pendiente max {gmax * 100:.1f}% (<= {TIPOS[t]['grade_max'] * 100:.0f}%) | "
          f"fuera de banda: {fuera or 'ninguna'}")


def main():
    for t, fname, vfun in PRESETS:
        generate(t, fname, vfun)


if __name__ == "__main__":
    main()
