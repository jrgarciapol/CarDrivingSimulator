"""Genera TRES carreteras cerradas LARGAS y serpenteantes, una por tipo de
via, trazadas con la Norma 3.1-IC (Trazado). Cada una recorre unos 30 min a
su VELOCIDAD DE PROYECTO (el numero de la denominacion espanola, en km/h):

  - a-120.csv  autovia / variante,     Vp = 120 km/h  ~60 km  (radios grandes)
  - c-90.csv   convencional de puerto,  Vp = 90 km/h   ~45 km  (curvas amplias)
  - c-50.csv   convencional de montana, Vp = 50 km/h   ~25 km  (revirada)

No son ovalos: la traza es una CURVA CERRADA ONDULANTE cuya curvatura cambia
de signo (curvas a IZQUIERDA y a DERECHA), con lobulos que entran y salen. Se
construye en forma polar r(t)=R0*(1+sum g*f_k*sin(k t+phi_k)); al ser r(t)>0 y
periodica, la traza es simple (no se corta) y cierra por construccion. La
curvatura varia de forma continua, asi que las transiciones recta<->curva son
suaves (clotoide implicita), y en los puntos de inflexion la curvatura pasa
por cero (tramos casi rectos entre curvas de distinto sentido).

Cumplimiento de la Norma 3.1-IC:
  - la traza se escala para que su RADIO MINIMO sea >= R_min del tipo
    (R_min = V^2/(127*(f_t+p_max))); todas las curvas quedan en banda;
  - peralte segun el radio local, hasta p_max (8% autovia, 7% convencional),
    y 0 en los tramos rectos;
  - pendiente longitudinal por debajo del maximo del tipo, con acuerdos suaves.

Salida en simulator/tracks/ (formato interno del simulador):
    kappa_1_per_m, elev_m, piano(0/1), peralte_rad, semiancho_m

    python tools/make_carretera.py
"""

import math
import os

SEG = 4.0                       # m por segmento (formato interno del sim)


# ---------------------------------------------------------------------------
# 1. PARAMETROS DE LA NORMA 3.1-IC POR VELOCIDAD DE PROYECTO
# ---------------------------------------------------------------------------
# ft = rozamiento transversal maximo ; pmax = peralte maximo
# grade_max = pendiente longitudinal maxima ; half_w = semiancho util (m)
# largo = longitud objetivo (m, ~30 min a Vp) ; rmin_uso = radio minimo con el
#         que se dibuja (>= R_min de la norma; en autovia se usa mayor)
TIPOS = {
    "A-120": dict(vp=120, ft=0.085, pmax=0.08, grade_max=0.040, half_w=4.75,
                  largo=60000.0, rmin_uso=850.0),
    "C-90":  dict(vp=90,  ft=0.118, pmax=0.07, grade_max=0.050, half_w=3.75,
                  largo=45000.0, rmin_uso=430.0),
    "C-50":  dict(vp=50,  ft=0.165, pmax=0.07, grade_max=0.070, half_w=3.25,
                  largo=25000.0, rmin_uso=95.0),
}

# plantilla de armonicos (k, peso, fase) que define la FORMA (numero y reparto
# de curvas) de cada trazado. La amplitud global se ajusta por biseccion.
TMPL = {
    "A-120": [(2, 0.6, 0.0), (3, 0.9, 1.1), (4, 0.5, 0.3), (5, 0.6, 0.4),
              (7, 0.35, 2.2), (9, 0.15, 1.0)],
    "C-90":  [(2, 0.5, 0.0), (3, 0.9, 0.6), (5, 0.8, 1.7), (7, 0.45, 0.3),
              (9, 0.2, 2.0)],
    "C-50":  [(3, 0.4, 0.0), (5, 0.7, 0.4), (7, 0.8, 1.1), (9, 0.7, 2.3),
              (11, 0.5, 0.7), (13, 0.3, 1.9), (17, 0.15, 0.5)],
}


def r_min_norma(t):
    d = TIPOS[t]
    return d["vp"] ** 2 / (127.0 * (d["ft"] + d["pmax"]))


def peralte(t, R):
    """Peralte (fraccion) para un radio R: en R_min vale p_max y decrece
    hacia 2% al crecer R. En recta (R muy grande) se aplica 0 aparte."""
    d = TIPOS[t]
    p = d["pmax"] * math.sqrt(r_min_norma(t) / R)
    return max(0.02, min(d["pmax"], p))


# ---------------------------------------------------------------------------
# 2. CURVA POLAR ONDULANTE
# ---------------------------------------------------------------------------
def _rd(harm, g, t):
    """r, r', r'' (adimensionales, R0=1) en el parametro t."""
    r, rp, rpp = 1.0, 0.0, 0.0
    for k, f, ph in harm:
        ff = f * g
        r += ff * math.sin(k * t + ph)
        rp += ff * k * math.cos(k * t + ph)
        rpp += -ff * k * k * math.sin(k * t + ph)
    return r, rp, rpp


def _props(harm, g, npts=6000):
    """Devuelve (rho=long/Rmin, cambios_de_signo, simple) a escala R0=1."""
    two = 2 * math.pi
    L = 0.0
    prev = None
    kap = []
    rpos = 9.0
    for i in range(npts):
        t = two * i / npts
        r, rp, rpp = _rd(harm, g, t)
        x, y = r * math.cos(t), r * math.sin(t)
        kap.append((r * r + 2 * rp * rp - r * rpp) / (r * r + rp * rp) ** 1.5)
        rpos = min(rpos, r)
        if prev:
            L += math.hypot(x - prev[0], y - prev[1])
        prev = (x, y)
    r, _, _ = _rd(harm, g, 0.0)
    L += math.hypot(r - prev[0], 0.0 - prev[1])
    kd = max(abs(v) for v in kap)
    signs = sum(1 for i in range(len(kap)) if kap[i] * kap[i - 1] < 0)
    return L * kd, signs, rpos > 0


def _solve_g(harm, rho_target):
    """Amplitud global g que da la relacion longitud/Rmin pedida."""
    lo, hi = 0.03, 0.98
    for _ in range(46):
        mid = (lo + hi) / 2
        rho, _, ok = _props(harm, mid)
        if not ok:
            hi = mid
        elif rho < rho_target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# 3. GENERAR UN TRAZADO
# ---------------------------------------------------------------------------
def _elevation(n, grade_max):
    L = n * SEG
    frac = [(1, 0.40), (2, 0.35), (3, 0.175), (5, 0.075)]
    amp = [(m, f * grade_max * L / (2.0 * math.pi * m)) for m, f in frac]
    y = [sum(Ak * math.sin(2.0 * math.pi * m * (i + 0.5) * SEG / L)
             for m, Ak in amp) for i in range(n)]
    return [v - y[0] for v in y]


def generate(t):
    d = TIPOS[t]
    harm = TMPL[t]
    rmin = d["rmin_uso"]
    rho_t = d["largo"] / rmin
    g = _solve_g(harm, rho_t)

    # muestreo denso: posicion, longitud acumulada y curvatura con signo
    two = 2 * math.pi
    dense = 60000
    ts = [two * i / dense for i in range(dense + 1)]
    xs, ys, kd = [], [], []
    for tt in ts:
        r, rp, rpp = _rd(harm, g, tt)
        xs.append(r * math.cos(tt))
        ys.append(r * math.sin(tt))
        kd.append((r * r + 2 * rp * rp - r * rpp) / (r * r + rp * rp) ** 1.5)
    s = [0.0]
    for i in range(1, dense + 1):
        s.append(s[-1] + math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))
    Ld = s[-1]                             # longitud a escala R0=1
    kmax = max(abs(v) for v in kd)         # curvatura maxima adimensional
    R0 = rmin * kmax                        # escala: radio minimo = rmin exacto
    L = Ld * R0                             # longitud real
    n = int(round(L / SEG))

    # remuestrear curvatura (real = adimensional / R0) a estaciones de 4 m
    kap, ban = [], []
    j = 0
    for seg in range(n):
        target = seg * SEG / R0            # estacion en la escala adimensional
        while j < dense and s[j + 1] < target:
            j += 1
        k_real = kd[j] / R0
        kap.append(k_real)
        R = 1.0 / abs(k_real) if abs(k_real) > 1e-9 else 1e9
        if R > 4000.0:                     # tramo (casi) recto: sin peralte
            ban.append(0.0)
        else:
            sgn = 1.0 if k_real >= 0 else -1.0
            ban.append(sgn * peralte(t, R))
    wid = [d["half_w"]] * n
    y = _elevation(n, d["grade_max"])

    # informe
    h = x = yy = 0.0
    for k in kap:
        x += math.cos(h) * SEG
        yy += math.sin(h) * SEG
        h += k * SEG
    Rs = [1.0 / abs(k) for k in kap if abs(k) > 1e-9]
    signs = sum(1 for i in range(1, n) if kap[i] * kap[i - 1] < 0)
    gmax = max(abs(y[i] - y[i - 1]) / SEG for i in range(1, n))
    pmax = max(peralte(t, R) for R in Rs if R <= 4000.0)

    fname = t.lower() + ".csv"
    path = os.path.join(os.path.dirname(__file__), "..",
                        "simulator", "tracks", fname)
    with open(path, "w") as f:
        f.write(f"# {t} generada por tools/make_carretera.py (Norma 3.1-IC)\n")
        f.write(f"# Vp={d['vp']} km/h, R_min norma={r_min_norma(t):.0f} m, "
                f"~{L/1000:.0f} km (~30 min a Vp)\n")
        f.write("# kappa_1_per_m, elev_m, piano, peralte_rad, semiancho_m\n")
        for k, e, b, w in zip(kap, y, ban, wid):
            f.write(f"{k:.6f},{e:.2f},0,{b:.4f},{w:.2f}\n")

    print(f"{fname}: {L/1000:.1f} km ({n} seg) | R_min norma {r_min_norma(t):.0f} "
          f"m, usado {min(Rs):.0f} m | curvas izq/dcha: {signs} cambios de sentido")
    print(f"    cierre: gap {math.hypot(x, yy):.1f} m, rumbo {math.degrees(h):.1f} deg"
          f" | peralte max {pmax*100:.1f}% (<= {d['pmax']*100:.0f}%)"
          f" | pendiente max {gmax*100:.1f}% (<= {d['grade_max']*100:.0f}%)")


def main():
    for t in TIPOS:
        generate(t)


if __name__ == "__main__":
    main()
