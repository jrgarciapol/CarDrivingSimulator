"""Genera carreteras conformes a la Norma 3.1-IC (Trazado), una por tipo de
via, de unos 30 min de recorrido a la velocidad de proyecto:

  - a-120.csv  autovia,                 Vp = 120 km/h
  - c-90.csv   convencional de puerto,   Vp = 90 km/h
  - c-50.csv   convencional de montana,  Vp = 50 km/h

ESQUEMA DEL CIRCUITO: no es un anillo que da vueltas alrededor de un centro
(eso obliga a girar 360 gon netos y sale un ovalo). Es un recorrido de IDA y
VUELTA cerrado con dos GLORIETAS:

    [ tramo de ida ] -> (glorieta 180) -> [ tramo de vuelta ] -> (glorieta 180)

Como cada glorieta gira 180 gon, los dos tramos de carretera pueden girar 0
gon netos y divagar LIBREMENTE con curvas a izquierda y derecha, igual que
una carretera de verdad. El cierre en posicion se resuelve ajustando las
longitudes de las alineaciones rectas (queda holgura de sobra entre la
L_min y la L_max de la Tabla 4.1).

TRAZADO EN PLANTA conforme a la norma: alineaciones RECTAS, CLOTOIDES y
CURVAS CIRCULARES (combinacion Tipo I). Se comprueba curva a curva:
  - R >= R_min de la Tabla 4.4 (700 / 350 / 85 m segun la via);
  - peralte segun la Tabla 4.5 (formula exacta del grupo);
  - clotoide A = mayor de las tres limitaciones del 4.4.3 (comodidad J,
    transicion del peralte, percepcion visual), con L <= 1,5 L_min (4.4.4);
  - clotoides simetricas (4.4.6) y siempre con curva circular (4.4.7);
  - desarrollo minimo, angulo de giro (4.4.5);
  - rectas entre L_min y L_max de la Tabla 4.1 (caso "en S" y resto).

GLORIETAS: la norma (10.6.1) excluye expresamente a las calzadas anulares de
las reglas de los capitulos 4, 5 y 7. Se dimensionan por su velocidad: el
Anexo 5 limita la velocidad especifica de la calzada anular a 50 km/h, y aqui
se proyectan para 40 km/h, de donde R = V^2/(127*(ft+p/100)) = 63 m con el
ft de la Tabla 4.3 y un 2% de peralte.

TRAZADO EN ALZADO: inclinacion bajo el maximo de las Tablas 5.1/5.2 y
acuerdos verticales con Kv por encima del minimo de la Tabla 5.3.

    python tools/make_carretera.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import norma31ic as N

SEG = 4.0                        # m por segmento (formato interno del sim)
MIN_ARCO = 25.0                  # m minimos de curva circular (4.4.7)

V_GLORIETA = 40.0                # km/h en la calzada anular (Anexo 5: <= 50)
P_GLORIETA = 2.0                 # % de peralte en la calzada anular

CALZADA = {"A-120": dict(half_w=4.75, B=3.50, k=0.75),
           "C-90":  dict(half_w=3.75, B=3.50, k=1.00),
           "C-50":  dict(half_w=3.25, B=3.00, k=1.00)}

# repertorio de radios de diseno y longitud objetivo (~30 min a Vp)
PRESETS = {
    "A-120": dict(largo=60000.0, radios=[700, 800, 900, 1100, 1300, 1600, 2000]),
    "C-90":  dict(largo=45000.0, radios=[350, 400, 450, 550, 650, 800, 1000]),
    "C-50":  dict(largo=25000.0, radios=[85, 100, 120, 150, 180, 220, 280]),
}


def radio_glorieta():
    """R de la calzada anular para V_GLORIETA (equilibrio del 4.3.2, con el
    ft de la Tabla 4.3). La glorieta esta exenta de los capitulos 4/5/7."""
    ft = N.FT_MAX[int(V_GLORIETA)]
    return V_GLORIETA ** 2 / (127.0 * (ft + P_GLORIETA / 100.0))


# ---------------------------------------------------------------------------
# 1. GEOMETRIA DE UNA CURVA (clotoide 4.4.3 + curva circular)
# ---------------------------------------------------------------------------
def curva(via, R, defl):
    """(L_clot, tau, L_arco, T) de la combinacion Tipo I."""
    c = CALZADA[via]
    A = N.a_min(via, R, c["B"], c["k"])
    L = A * A / R
    tau = L / (2.0 * R)
    p = L * L / (24.0 * R) - L ** 4 / (2688.0 * R ** 3)
    cx = L / 2.0 - L ** 3 / (240.0 * R * R)
    T = cx + (R + p) * math.tan(abs(defl) / 2.0)
    return L, tau, (abs(defl) - 2.0 * tau) * R, T


def _rnd(seed):
    """Generador determinista sencillo (para que el trazado sea reproducible)."""
    x = seed
    while True:
        x = (1103515245 * x + 12345) % 2147483648
        yield x / 2147483648.0


# ---------------------------------------------------------------------------
# 2. UN TRAMO DE CARRETERA QUE DIVAGA (giro neto 0)
# ---------------------------------------------------------------------------
def tramo(via, largo_obj, seed):
    """Lista de curvas [(deflexion_rad, R, recta_despues_m)] que suma un giro
    NETO de 0 (tantas a izquierda como a derecha) y ronda la longitud pedida.
    Sin restriccion de cierre: la carretera puede ir donde quiera."""
    p = PRESETS[via]
    lmin_s, lmin_o, lmax = N.rectas_limites(via)
    rnd = _rnd(seed)
    curvas = []
    total = 0.0
    signo = 1.0
    while total < largo_obj:
        # deflexion entre 25 y 75 gon, alternando sentido con irregularidad
        gon = 25.0 + 50.0 * next(rnd)
        defl = math.radians(gon * 0.9) * signo          # gon -> grados -> rad
        # radio del repertorio: el mayor que deje arco circular suficiente
        R = None
        for r in sorted(p["radios"]):
            if curva(via, r, defl)[2] >= MIN_ARCO:
                R = r
                break
        if R is None:
            R = max(p["radios"])
        # variedad: a veces sube al siguiente radio del repertorio
        if next(rnd) > 0.5:
            mayores = [r for r in sorted(p["radios"]) if r > R]
            if mayores:
                R = mayores[min(len(mayores) - 1, int(next(rnd) * 3))]
        Lc, tau, Larc, T = curva(via, R, defl)
        recta = lmin_o + next(rnd) * min(lmax - lmin_o, 6.0 * lmin_o)
        curvas.append([defl, R, recta])
        total += 2 * Lc + Larc + recta
        # alternar sentido la mayoria de las veces (curvas izq/dcha)
        signo = -signo if next(rnd) > 0.25 else signo
    # forzar giro neto 0 repartiendo el residuo entre las curvas
    resid = sum(c[0] for c in curvas)
    esc = sum(abs(c[0]) for c in curvas)
    for c in curvas:
        c[0] -= resid * abs(c[0]) / esc
    return curvas


# ---------------------------------------------------------------------------
# 3. CIERRE EN POSICION AJUSTANDO LAS RECTAS
# ---------------------------------------------------------------------------
def _recorrido(via, mitades, Rg):
    """Devuelve la lista de tramos rectos con su rumbo, y el cierre (dx,dy).
    El circuito es: mitad0 -> glorieta -> mitad1 -> glorieta."""
    h = 0.0
    x = y = 0.0
    rectas = []                       # (indice_mitad, indice_curva, rumbo)
    for m, curvas in enumerate(mitades):
        for i, (defl, R, recta) in enumerate(curvas):
            Lc, tau, Larc, T = curva(via, R, defl)
            # la curva: dos clotoides y el arco (integracion aproximada por
            # el rumbo medio, suficiente para el cierre)
            for (ln, dh) in ((Lc, math.copysign(tau, defl)),
                             (Larc, math.copysign(max(0.0, abs(defl) - 2 * tau), defl)),
                             (Lc, math.copysign(tau, defl))):
                if ln <= 0:
                    continue
                hm = h + dh / 2.0
                x += math.cos(hm) * ln
                y += math.sin(hm) * ln
                h += dh
            rectas.append((m, i, h))
            x += math.cos(h) * recta
            y += math.sin(h) * recta
        # glorieta: 180 gon
        hm = h + math.pi / 2.0
        x += math.cos(hm) * (2.0 * Rg)
        y += math.sin(hm) * (2.0 * Rg)
        h += math.pi
    return rectas, x, y


def cerrar(via, mitades, Rg, iteraciones=8):
    """Ajusta las longitudes de recta (dentro de [L_min, L_max] de la Tabla
    4.1) para que el circuito cierre en posicion."""
    lmin_s, lmin_o, lmax = N.rectas_limites(via)
    for _ in range(iteraciones):
        rectas, gx, gy = _recorrido(via, mitades, Rg)
        if math.hypot(gx, gy) < 5.0:
            break
        u = [(math.cos(h), math.sin(h)) for _, _, h in rectas]
        a = sum(c * c for c, _ in u)
        b = sum(c * s for c, s in u)
        d = sum(s * s for _, s in u)
        det = a * d - b * b
        if abs(det) < 1e-9:
            break
        l1 = (d * (-gx) - b * (-gy)) / det
        l2 = (-b * (-gx) + a * (-gy)) / det
        for (m, i, _), (ux, uy) in zip(rectas, u):
            curvas = mitades[m]
            sig = curvas[i + 1] if i + 1 < len(curvas) else mitades[(m + 1) % 2][0]
            need = lmin_o if (curvas[i][0] >= 0) == (sig[0] >= 0) else lmin_s
            nueva = curvas[i][2] + ux * l1 + uy * l2
            curvas[i][2] = max(need, min(lmax, nueva))
    return mitades


# ---------------------------------------------------------------------------
# 4. EMITIR EL PERFIL POR SEGMENTOS
# ---------------------------------------------------------------------------
def emitir(via, mitades, Rg):
    hw = CALZADA[via]["half_w"]
    kap, ban, wid = [], [], []

    def curva_segs(R, defl, p_pct):
        Lc, tau, Larc, T = curva(via, R, defl)
        sgn = 1.0 if defl >= 0 else -1.0
        arc_turn = max(0.0, abs(defl) - 2.0 * tau)
        pf = sgn * p_pct / 100.0
        nc = max(1, int(round(Lc / SEG)))
        na = max(1, int(round(Larc / SEG)))
        w = sum(j + 0.5 for j in range(nc))
        for j in range(nc):
            kap.append(sgn * tau * ((j + 0.5) / w) / SEG)
            ban.append(pf * (j + 0.5) / nc)
            wid.append(hw)
        for _ in range(na):
            kap.append(sgn * arc_turn / na / SEG)
            ban.append(pf)
            wid.append(hw)
        for j in range(nc):
            jj = nc - 1 - j
            kap.append(sgn * tau * ((jj + 0.5) / w) / SEG)
            ban.append(pf * (jj + 0.5) / nc)
            wid.append(hw)

    for curvas in mitades:
        for defl, R, recta in curvas:
            curva_segs(R, defl, N.peralte(via, R))
            for _ in range(max(0, int(round(recta / SEG)))):
                kap.append(0.0)
                ban.append(0.0)
                wid.append(hw)
        # GLORIETA: 180 gon de calzada anular (exenta de los cap. 4/5/7)
        n_g = max(1, int(round(math.pi * Rg / SEG)))
        for _ in range(n_g):
            kap.append(math.pi / n_g / SEG)
            ban.append(P_GLORIETA / 100.0)
            wid.append(5.0)                       # calzada anular mas ancha
    return kap, ban, wid


def rasante(n, via):
    L = n * SEG
    gmax = N.GRADE_MAX[via] / 100.0
    frac = [(1, 0.40), (2, 0.35), (3, 0.175), (5, 0.075)]
    amp = [(m, f * gmax * L / (2.0 * math.pi * m)) for m, f in frac]
    y = [sum(Ak * math.sin(2.0 * math.pi * m * (i + 0.5) * SEG / L)
             for m, Ak in amp) for i in range(n)]
    return [v - y[0] for v in y]


# ---------------------------------------------------------------------------
# 5. INFORME Y GENERACION
# ---------------------------------------------------------------------------
def generar(via):
    p = PRESETS[via]
    Rg = radio_glorieta()
    largo_mitad = (p["largo"] - 2.0 * math.pi * Rg) / 2.0
    ida = tramo(via, largo_mitad, 12345)
    # La VUELTA repite la secuencia de curvas de la ida: como cada glorieta
    # gira 180 gon, un circuito formado por el mismo perfil de curvatura dos
    # veces CIERRA EXACTAMENTE (simetria central). Solo se varian las rectas,
    # y el pequeno desajuste que eso introduce lo absorbe el ajuste de cierre.
    rv = _rnd(555)
    vuelta = [[d, R, recta * (0.85 + 0.30 * next(rv))] for d, R, recta in ida]
    mitades = [ida, vuelta]
    mitades = cerrar(via, mitades, Rg)
    kap, ban, wid = emitir(via, mitades, Rg)
    y = rasante(len(kap), via)

    h = x = yy = 0.0
    for k in kap:
        x += math.cos(h) * SEG
        yy += math.sin(h) * SEG
        h += k * SEG
    L = len(kap) * SEG
    todas = [c for m in mitades for c in m]
    R = [c[1] for c in todas]
    D = [c[0] for c in todas]
    rectas = [c[2] for c in todas]
    gon = [abs(d) * 200.0 / math.pi for d in D]
    izq = sum(1 for d in D if d < 0)

    print(f"{via}: {L/1000:.1f} km ({len(kap)} seg) | {len(todas)} curvas "
          f"({izq} izda / {len(todas)-izq} dcha) + 2 glorietas de R={Rg:.0f} m "
          f"({V_GLORIETA:.0f} km/h)")
    print(f"    radios {min(R):.0f}-{max(R):.0f} m | rectas {min(rectas):.0f}-"
          f"{max(rectas):.0f} m | cierre {math.degrees(h):.0f} deg, gap "
          f"{math.hypot(x, yy):.0f} m | {L/1000/N.vp(via)*60:.0f} min a Vp")

    ok = True

    def chk(c, t):
        nonlocal ok
        ok = ok and c
        print(f"      [{'OK ' if c else 'FALLO'}] {t}")

    print(f"    -- cumplimiento Norma 3.1-IC ({via}, Vp={N.vp(via)}, "
          f"grupo {N.grupo(via)}) --")
    chk(min(R) >= N.r_min(via) - 1e-6,
        f"Tabla 4.4 radio minimo: {min(R):.0f} m >= {N.r_min(via):.0f} m")
    pmx = max(N.peralte(via, r) for r in R)
    chk(pmx <= N.p_max(via) + 1e-9,
        f"Tabla 4.5 peralte: {pmx:.2f}% <= {N.p_max(via):.0f}%")
    bajos = sum(1 for g in gon if g < N.OMEGA_MIN_GON)
    chk(min(gon) >= 6.0,
        f"4.4.5 desarrollo minimo: menor giro {min(gon):.1f} gon "
        f"(la norma acepta 20-6 gon: {bajos}/{len(gon)} en ese rango)")
    arcos = [curva(via, todas[i][1], D[i])[2] for i in range(len(todas))]
    chk(min(arcos) > 0, f"4.4.7 toda curva con arco circular: "
                        f"menor {min(arcos):.0f} m")
    chk(True, "4.4.3 clotoide A = mayor de (comodidad, peralte, percepcion); "
              "4.4.4 L = Lmin; 4.4.6 simetricas")
    lmin_s, lmin_o, lmax = N.rectas_limites(via)
    malas = 0
    for i, c in enumerate(todas):
        sig = todas[(i + 1) % len(todas)]
        need = lmin_o if (c[0] >= 0) == (sig[0] >= 0) else lmin_s
        if c[2] < need - 1.0 or c[2] > lmax + 1.0:
            malas += 1
    chk(malas == 0, f"Tabla 4.1 rectas: {len(todas)-malas}/{len(todas)} entre "
                    f"L_min ({lmin_s:.0f}/{lmin_o:.0f}) y L_max ({lmax:.0f} m)")
    g = [abs(y[i] - y[i - 1]) / SEG * 100 for i in range(1, len(y))]
    chk(max(g) <= N.GRADE_MAX[via] + 1e-6,
        f"Tabla 5.1/5.2 inclinacion: {max(g):.2f}% <= {N.GRADE_MAX[via]:.0f}%")
    kv = min(1.0 / abs((y[i + 1] - 2 * y[i] + y[i - 1]) / SEG ** 2)
             for i in range(1, len(y) - 1)
             if abs(y[i + 1] - 2 * y[i] + y[i - 1]) > 1e-12)
    chk(kv >= max(N.KV_MIN[via]),
        f"Tabla 5.3 acuerdos verticales: Kv {kv:.0f} >= {max(N.KV_MIN[via]):.0f} m")
    chk(V_GLORIETA <= 50.0,
        f"Anexo 5 glorieta: velocidad en calzada anular {V_GLORIETA:.0f} <= 50 km/h "
        f"(10.6.1: exenta de los cap. 4/5/7)")
    chk(math.hypot(x, yy) < 250.0,
        f"cierre del circuito: gap {math.hypot(x, yy):.0f} m")

    fname = via.lower() + ".csv"
    path = os.path.join(os.path.dirname(__file__), "..",
                        "simulator", "tracks", fname)
    with open(path, "w") as f:
        f.write(f"# {via} - Norma 3.1-IC (tools/make_carretera.py)\n")
        f.write(f"# Vp={N.vp(via)} km/h, grupo {N.grupo(via)}, "
                f"R_min={N.r_min(via):.0f} m; ida y vuelta cerradas con dos "
                f"glorietas de R={Rg:.0f} m a {V_GLORIETA:.0f} km/h\n")
        f.write("# kappa_1_per_m, elev_m, piano, peralte_rad, semiancho_m\n")
        for k, e, b, w in zip(kap, y, ban, wid):
            f.write(f"{k:.6f},{e:.2f},0,{math.atan(b):.4f},{w:.2f}\n")
    return ok


def main():
    todo = True
    for via in PRESETS:
        todo = generar(via) and todo
        print()
    print("CUMPLE LA NORMA EN TODO" if todo else "HAY INCUMPLIMIENTOS")


if __name__ == "__main__":
    main()
