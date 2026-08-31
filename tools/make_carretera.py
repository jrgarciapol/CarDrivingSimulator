"""Genera una CARRETERA cerrada trazada con la Norma 3.1-IC (Trazado).

No es un circuito, es una carretera de las de conducir a diario: un anillo
cerrado que recorre TRES tipos de via, cada uno con sus condicionantes de
trazado en planta y alzado segun su VELOCIDAD DE PROYECTO (el numero de la
denominacion espanola, en km/h):

  - C-50  carretera convencional de montana, Vp = 50 km/h  (revirada)
  - C-90  carretera convencional de puerto,  Vp = 90 km/h  (curvas amplias)
  - A-120 autovia / variante rapida,         Vp = 120 km/h (rectas, radios grandes)

Para cada tipo se respetan (Norma 3.1-IC):
  - Radio minimo en planta  R_min = V^2 / (127 * (f_t + p_max))
  - Clotoide de transicion   A ~ 0.55 R  (dentro de R/3 <= A <= R), acotada
    para que nunca gire mas que la propia deflexion de la curva
  - Peralte segun el radio, hasta p_max (8% autovia, 7% convencional)
  - Pendiente longitudinal por debajo del limite mas estricto presente
  - Acuerdos verticales con Kv muy por encima del minimo de parada

METODO. El trazado en planta es un POLIGONO CERRADO de vertices 2D (cierra en
posicion y rumbo por construccion: la suma de deflexiones de un poligono
simple es 360). Cada esquina se redondea con clotoide-arco-clotoide de radio
ADAPTATIVO: el mayor radio que cabe en sus dos rectas, con lo que un giro
suave sale amplio (A-120) y uno cerrado sale corto (C-50); el tipo de via se
DEDUCE del radio segun los R_min de la norma. El puerto revirado se genera
como una ondulacion suave (5 eses) para que las deflexiones queden acotadas.
La curvatura se emite con GIRO EXACTO por curva (cada curva integra su
deflexion exacta, sin deriva de redondeo), asi el anillo cierra al metro.
Arranca en la mitad de la recta mas larga, llana y sin peralte: la costura
es fisicamente continua.

Salida: simulator/tracks/carretera.csv en el formato interno del simulador:
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
R_CAP = 1200.0                  # radio maximo dibujado (mas alla, recta)


# ---------------------------------------------------------------------------
# 1. PARAMETROS DE LA NORMA 3.1-IC POR VELOCIDAD DE PROYECTO
# ---------------------------------------------------------------------------
# ft = rozamiento transversal maximo movilizado ; pmax = peralte maximo
# grade_max = pendiente longitudinal maxima ; half_w = semiancho util (m)
TIPOS = {
    "A-120": dict(vp=120, ft=0.085, pmax=0.08, grade_max=0.040, half_w=4.75),
    "C-90":  dict(vp=90,  ft=0.118, pmax=0.07, grade_max=0.050, half_w=3.75),
    "C-50":  dict(vp=50,  ft=0.165, pmax=0.07, grade_max=0.070, half_w=3.25),
}


def r_min(t):
    d = TIPOS[t]
    return d["vp"] ** 2 / (127.0 * (d["ft"] + d["pmax"]))


def zone_of(R):
    if R >= r_min("A-120"):
        return "A-120"
    if R >= r_min("C-90"):
        return "C-90"
    return "C-50"


def peralte(t, R):
    """Peralte (fraccion): en R_min vale p_max y decrece hacia 2% al crecer R."""
    d = TIPOS[t]
    p = d["pmax"] * math.sqrt(r_min(t) / R)
    return max(0.02, min(d["pmax"], p))


def clot_len(R, defl):
    """Longitud de clotoide: A=0.55R, pero nunca mas larga de lo que la curva
    puede girar (para que dos clotoides no giren mas que la deflexion)."""
    return min((0.55 * R) ** 2 / R, R * abs(defl))


def tangent_len(R, defl):
    """Tangente PI->TS: T = cx + (R+p)*tan(defl/2), con la clotoide acotada."""
    L = clot_len(R, defl)
    p, cx, _ = cl.clothoid_shift(L, R, 1.0)
    return cx + (R + p) * math.tan(abs(defl) / 2.0)


# ---------------------------------------------------------------------------
# 2. VERTICES DEL ANILLO (poligono cerrado 2D, en metros)
# ---------------------------------------------------------------------------
def _weave(Pa, Pb, amp, k):
    """k puntos ondulando suave (seno) por el corredor Pa->Pb: genera el
    puerto revirado con deflexiones acotadas (eses de radio corto -> C-50)."""
    dx, dy = Pb[0] - Pa[0], Pb[1] - Pa[1]
    Lc = math.hypot(dx, dy)
    nx, ny = -dy / Lc, dx / Lc
    out = []
    for j in range(1, k + 1):
        t = j / (k + 1)
        off = amp * math.sin(math.pi * t * k)
        out.append((Pa[0] + dx * t + nx * off, Pa[1] + dy * t + ny * off))
    return out


def vertices():
    V = [(-1400, -80), (-350, -220), (750, -160), (1650, 220),   # A-120 / C-90
         (1980, 820), (1900, 1240)]                              # subida al puerto
    V += _weave((1900, 1240), (1050, 2070), 150.0, 5)            # puerto revirado C-50
    V += [(450, 2060), (-550, 1720), (-1250, 1120), (-1600, 470)]  # bajada C-90 / A-120
    return V


# ---------------------------------------------------------------------------
# 3. DEFLEXIONES Y RADIOS ADAPTATIVOS
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


def choose_radii(D, E):
    """Mayor radio cuya tangente cabe en las dos rectas (T <= 0.46*min),
    acotado entre R_min(C-50) y R_CAP."""
    n = len(D)
    R = []
    for i in range(n):
        lim = 0.46 * min(E[(i - 1) % n], E[i])
        best = r_min("C-50")
        r = best
        while r <= R_CAP:
            if tangent_len(r, D[i]) <= lim:
                best = r
            r += 2.0
        R.append(best)
    return R


# ---------------------------------------------------------------------------
# 4. PERFIL EN PLANTA: kappa, peralte, ancho y zona por segmento (giro exacto)
# ---------------------------------------------------------------------------
def build_profile(V, D, E, R):
    n = len(V)
    T = [tangent_len(R[i], D[i]) for i in range(n)]
    kap, ban, wid, zon = [], [], [], []
    last_w = TIPOS["A-120"]["half_w"]

    for i in range(n):
        Ri = R[i]
        sgn = 1.0 if D[i] >= 0 else -1.0
        z = zone_of(Ri)
        Lc = clot_len(Ri, D[i])
        ct = Lc / (2.0 * Ri)
        at = max(0.0, abs(D[i]) - 2.0 * ct)
        La = at * Ri
        w = TIPOS[z]["half_w"]
        p_full = sgn * peralte(z, Ri)
        nc = max(1, int(round(Lc / SEG)))
        na = max(0, int(round(La / SEG)))
        wsum = sum(j + 0.5 for j in range(nc))
        # clotoide de entrada (giro suma exacto = ct; peralte lineal 0->pleno)
        for j in range(nc):
            kap.append(sgn * ct * ((j + 0.5) / wsum) / SEG)
            ban.append(p_full * (j + 0.5) / nc)
            wid.append(w)
            zon.append(z)
        for _ in range(na):                                  # arco
            kap.append(sgn * at / na / SEG)
            ban.append(p_full)
            wid.append(w)
            zon.append(z)
        for j in range(nc):                                  # clotoide de salida
            jj = nc - 1 - j
            kap.append(sgn * ct * ((jj + 0.5) / wsum) / SEG)
            ban.append(p_full * (jj + 0.5) / nc)
            wid.append(w)
            zon.append(z)
        last_w = w
        # recta que sigue (conserva el ancho de la via de esta curva)
        L_str = E[i] - T[i] - T[(i + 1) % n]
        ns = max(0, int(round(L_str / SEG)))
        for _ in range(ns):
            kap.append(0.0)
            ban.append(0.0)
            wid.append(last_w)
            zon.append("recta")
    return kap, ban, wid, zon


def smooth_width(wid, win=16):
    n = len(wid)
    return [sum(wid[max(0, i - win):min(n, i + win + 1)])
            / (min(n, i + win + 1) - max(0, i - win)) for i in range(n)]


def roll_to_longest_straight(arrs):
    """Rota los arrays para empezar en la mitad de la recta mas larga."""
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


# ---------------------------------------------------------------------------
# 5. ALZADO: rasante con pendiente acotada, cierra cota y pendiente a 0
# ---------------------------------------------------------------------------
def elevation(n):
    L = n * SEG
    modos = [(1, 0.016), (2, 0.014), (3, 0.007), (5, 0.003)]     # (armonico, pdte)
    amp = [(m, g * L / (2.0 * math.pi * m)) for m, g in modos]   # -> metros
    y = [sum(Ak * math.sin(2.0 * math.pi * m * (i + 0.5) * SEG / L)
             for m, Ak in amp) for i in range(n)]
    return [v - y[0] for v in y]


# ---------------------------------------------------------------------------
# 6. INFORME Y SALIDA
# ---------------------------------------------------------------------------
def _integrate(kap):
    h = x = y = 0.0
    for k in kap:
        x += math.cos(h) * SEG
        y += math.sin(h) * SEG
        h += k * SEG
    return math.hypot(x, y), math.degrees(h)


def main():
    V = vertices()
    D = deflections(V)
    E = edge_lengths(V)
    R = choose_radii(D, E)
    kap, ban, wid, zon = build_profile(V, D, E, R)
    wid = smooth_width(wid)
    kap, ban, wid, zon = roll_to_longest_straight([kap, ban, wid, zon])
    y = elevation(len(kap))

    gap, hnet = _integrate(kap)
    gmax = max(abs(y[i] - y[i - 1]) / SEG for i in range(1, len(y)))
    kvmin = min((1.0 / abs((y[i + 1] - 2 * y[i] + y[i - 1]) / SEG ** 2)
                 for i in range(1, len(y) - 1)
                 if abs(y[i + 1] - 2 * y[i] + y[i - 1]) > 1e-9), default=0.0)
    curvas = [zone_of(r) for r in R]
    pmax_zona = {}
    for i, r in enumerate(R):
        z = zone_of(r)
        pmax_zona[z] = max(pmax_zona.get(z, 0.0), peralte(z, r))

    print(f"carretera.csv: {len(kap)} segmentos, {len(kap) * SEG / 1000:.2f} km")
    print(f"  cierre: gap {gap:.1f} m | rumbo neto {hnet:.2f} deg")
    print(f"  curvas por tipo: {dict(Counter(curvas))}")
    for t in TIPOS:
        rs = sorted(round(R[i]) for i in range(len(R)) if zone_of(R[i]) == t)
        if rs:
            print(f"    {t}: R_min norma {r_min(t):.0f} m | radios {rs} m"
                  f" | peralte max {pmax_zona[t] * 100:.1f}% (<= {TIPOS[t]['pmax'] * 100:.0f}%)")
    print(f"  pendiente maxima: {gmax * 100:.1f}% (limite mas estricto 4.0%)")
    print(f"  Kv efectivo minimo: {kvmin:.0f} m")

    path = os.path.join(os.path.dirname(__file__), "..",
                        "simulator", "tracks", "carretera.csv")
    with open(path, "w") as f:
        f.write("# CARRETERA generada por tools/make_carretera.py\n")
        f.write("# Norma 3.1-IC: C-50 (montana), C-90 (puerto), A-120 "
                "(variante)\n")
        f.write("# kappa_1_per_m, elev_m, piano, peralte_rad, semiancho_m\n")
        for k, e, b, w in zip(kap, y, ban, wid):
            f.write(f"{k:.6f},{e:.2f},0,{b:.4f},{w:.2f}\n")
    print(f"  escrito: {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
