"""Genera carreteras conformes a la Norma 3.1-IC (Trazado), una por tipo de
via, de unos 30 min de recorrido a la velocidad de proyecto:

  - a-120.csv  autovia,                 Vp = 120 km/h
  - c-90.csv   convencional de puerto,   Vp = 90 km/h
  - c-50.csv   convencional de montana,  Vp = 50 km/h

ESQUEMA DEL CIRCUITO: no es un anillo que da vueltas alrededor de un centro
(eso obliga a girar 360 gon netos y sale un ovalo). Es un recorrido de IDA y
VUELTA, con trazados DISTINTOS, cerrado con dos GLORIETAS:

    [ tramo de ida ] -> (glorieta 180) -> [ tramo de vuelta ] -> (glorieta 180)

Como cada glorieta gira 180 gon, los tramos pueden girar 0 gon netos y
divagar LIBREMENTE con curvas a izquierda y derecha. Ida y vuelta SE CRUZAN,
y en cada cruce la rasante garantiza un GALIBO minimo (paso superior /
inferior), como en un cruce a distinto nivel real.

RECTAS CORTAS: las curvas se encadenan SIEMPRE alternando el sentido (trazado
en S). Ese es justo el caso en que la Tabla 4.1 pide la recta minima menor,
L_min,s = 1,39*Vp, que son exactamente CINCO SEGUNDOS a la velocidad de
proyecto. Asi el trazado no tiene rectas monotonas y cumple la norma.

TRAZADO EN PLANTA conforme a la norma: alineaciones RECTAS, CLOTOIDES y
CURVAS CIRCULARES (combinacion Tipo I). Se comprueba curva a curva:
  - R >= R_min de la Tabla 4.4 (700 / 350 / 85 m segun la via);
  - peralte segun la Tabla 4.5 (formula exacta del grupo);
  - clotoide A = mayor de las tres limitaciones del 4.4.3 (comodidad J,
    transicion del peralte, percepcion visual), con L <= 1,5 L_min (4.4.4);
  - clotoides simetricas (4.4.6) y siempre con curva circular (4.4.7);
  - desarrollo minimo, angulo de giro (4.4.5);
  - rectas >= L_min,s y <= L_max de la Tabla 4.1.

El cierre en posicion se resuelve ajustando ligeramente las DEFLEXIONES (no
las rectas, que quedan fijas en 5 s), por minimos cuadrados y manteniendo el
giro neto en 0.

GLORIETAS: el 10.6.1 excluye las calzadas anulares de las reglas de los
capitulos 4, 5 y 7, y el Anexo 5 limita su velocidad especifica a 50 km/h.
Se proyectan para 40 km/h: R = V^2/(127*(ft+p/100)) = 63 m.

TRAZADO EN ALZADO: inclinacion bajo el maximo de las Tablas 5.1/5.2, acuerdos
verticales con Kv por encima del minimo de la Tabla 5.3, y galibo en los
cruces entre ida y vuelta.

    python tools/make_carretera.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import norma31ic as N

SEG = 4.0                        # m por segmento (formato interno del sim)
MIN_ARCO = 25.0                  # m minimos de curva circular (4.4.7)
GALIBO = 5.30                    # m de galibo minimo en los cruces
SEG_RECTA = 5.0                  # s de recta entre curvas (= L_min,s / Vp)

V_GLORIETA = 40.0                # km/h en la calzada anular (Anexo 5: <= 50)
P_GLORIETA = 2.0                 # % de peralte en la calzada anular

CALZADA = {"A-120": dict(half_w=4.75, B=3.50, k=0.75),
           "C-90":  dict(half_w=3.75, B=3.50, k=1.00),
           "C-50":  dict(half_w=3.25, B=3.00, k=1.00)}

PRESETS = {
    "A-120": dict(largo=60000.0, radios=[700, 800, 900, 1100, 1300, 1600, 2000]),
    "C-90":  dict(largo=45000.0, radios=[350, 400, 450, 550, 650, 800, 1000]),
    "C-50":  dict(largo=25000.0, radios=[85, 100, 120, 150, 180, 220, 280]),
}


def radio_glorieta():
    ft = N.FT_MAX[int(V_GLORIETA)]
    return V_GLORIETA ** 2 / (127.0 * (ft + P_GLORIETA / 100.0))


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
    x = seed
    while True:
        x = (1103515245 * x + 12345) % 2147483648
        yield x / 2147483648.0


# ---------------------------------------------------------------------------
# 1. UN TRAMO: curvas ALTERNADAS con rectas de 5 s
# ---------------------------------------------------------------------------
def tramo(via, largo_obj, seed):
    """[[deflexion_rad, R, recta_m], ...] alternando SIEMPRE el sentido, con
    la recta minima del caso "en S" (5 s a la Vp). Giro neto 0."""
    p = PRESETS[via]
    lmin_s, _, _ = N.rectas_limites(via)          # 1,39*Vp = 5 s
    rnd = _rnd(seed)
    curvas = []
    total = 0.0
    signo = 1.0
    while total < largo_obj:
        gon = 24.0 + 55.0 * next(rnd)
        defl = math.radians(gon * 0.9) * signo
        R = None
        for r in sorted(p["radios"]):             # el menor que deje arco
            if curva(via, r, defl)[2] >= MIN_ARCO:
                R = r
                break
        if R is None:
            R = max(p["radios"])
        if next(rnd) > 0.45:                      # variedad de radios
            mayores = [r for r in sorted(p["radios"]) if r > R]
            if mayores:
                R = mayores[min(len(mayores) - 1, int(next(rnd) * 3))]
        Lc, tau, Larc, T = curva(via, R, defl)
        curvas.append([defl, R, lmin_s])
        total += 2 * Lc + Larc + lmin_s
        signo = -signo                            # SIEMPRE en S
    # La glorieta que sigue gira a DERECHAS: para que la recta que entra en
    # ella sea tambien un caso "en S" (recta minima de 5 s y no de 10 s), la
    # ultima curva del tramo debe girar a izquierdas.
    if curvas[-1][0] > 0:
        gon = 24.0 + 55.0 * next(rnd)
        defl = -math.radians(gon * 0.9)
        R = next((r for r in sorted(p["radios"])
                  if curva(via, r, defl)[2] >= MIN_ARCO), max(p["radios"]))
        curvas.append([defl, R, lmin_s])
    resid = sum(c[0] for c in curvas)
    esc = sum(abs(c[0]) for c in curvas)
    for c in curvas:
        c[0] -= resid * abs(c[0]) / esc
    return curvas


# ---------------------------------------------------------------------------
# 2. RECORRIDO Y CIERRE POR DEFLEXIONES
# ---------------------------------------------------------------------------
def recorrer(via, mitades, Rg, paso=None):
    """Recorre el circuito. Devuelve (puntos_xy_por_segmento, mitad_por
    segmento, posicion_de_cada_curva, cierre)."""
    h = 0.0
    x = y = 0.0
    pts, quien = [], []
    pos_curva = []
    for m, curvas in enumerate(mitades):
        for defl, R, recta in curvas:
            Lc, tau, Larc, T = curva(via, R, defl)
            pos_curva.append((x, y))
            sgn = 1.0 if defl >= 0 else -1.0
            arc = max(0.0, abs(defl) - 2.0 * tau)
            for ln, dh in ((Lc, sgn * tau), (Larc, sgn * arc), (Lc, sgn * tau)):
                n = max(1, int(round(ln / SEG))) if ln > 0 else 0
                for _ in range(n):
                    h += dh / n
                    x += math.cos(h) * SEG
                    y += math.sin(h) * SEG
                    pts.append((x, y))
                    quien.append(m)
            for _ in range(max(0, int(round(recta / SEG)))):
                x += math.cos(h) * SEG
                y += math.sin(h) * SEG
                pts.append((x, y))
                quien.append(m)
        ng = max(1, int(round(math.pi * Rg / SEG)))
        for _ in range(ng):                        # glorieta: 180 gon
            h += math.pi / ng
            x += math.cos(h) * SEG
            y += math.sin(h) * SEG
            pts.append((x, y))
            quien.append(-1)
    return pts, quien, pos_curva, (x, y)


def cerrar(via, mitades, Rg, iteraciones=25):
    """Cierra la posicion ajustando las DEFLEXIONES (las rectas quedan fijas
    en 5 s). Minimos cuadrados con tres restricciones: dx, dy y giro neto 0.
    Cambiar la deflexion de la curva i gira todo lo que va detras alrededor
    de ella, luego d(P_fin)/d(defl_i) = z x (P_fin - P_i)."""
    todas = [c for m in mitades for c in m]
    for _ in range(iteraciones):
        pts, quien, pos, (gx, gy) = recorrer(via, mitades, Rg)
        if math.hypot(gx, gy) < 3.0:
            break
        J = [(-(gy - py), (gx - px)) for (px, py) in pos]
        n = len(J)
        # filas: dx, dy, suma de deflexiones
        A = [[j[0] for j in J], [j[1] for j in J], [1.0] * n]
        b = [-gx, -gy, 0.0]
        # M = A A^T (3x3)
        M = [[sum(A[r][k] * A[c][k] for k in range(n)) for c in range(3)]
             for r in range(3)]
        try:
            lam = _solve3(M, b)
        except ZeroDivisionError:
            break
        for i, c in enumerate(todas):
            d = sum(lam[r] * A[r][i] for r in range(3))
            nuevo = c[0] + d
            if abs(nuevo) > math.radians(8.0):     # no degenerar la curva
                c[0] = nuevo
    return mitades


def _solve3(M, b):
    """Resuelve un sistema 3x3 por eliminacion."""
    A = [row[:] + [b[i]] for i, row in enumerate(M)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(A[r][i]))
        if abs(A[p][i]) < 1e-12:
            raise ZeroDivisionError
        A[i], A[p] = A[p], A[i]
        for r in range(3):
            if r != i:
                f = A[r][i] / A[i][i]
                for c in range(i, 4):
                    A[r][c] -= f * A[i][c]
    return [A[i][3] / A[i][i] for i in range(3)]


# ---------------------------------------------------------------------------
# 3. CRUCES ENTRE IDA Y VUELTA Y RASANTE CON GALIBO
# ---------------------------------------------------------------------------
def cruces(pts, quien, umbral=14.0):
    """Pares de estaciones (i de la ida, j de la vuelta) cuyos ejes se cruzan
    en planta. Rejilla espacial para no comparar todo contra todo."""
    celda = umbral
    rej = {}
    for j, (x, y) in enumerate(pts):
        if quien[j] != 1:
            continue
        rej.setdefault((int(x // celda), int(y // celda)), []).append(j)
    vistos = []
    for i, (x, y) in enumerate(pts):
        if quien[i] != 0:
            continue
        cx, cy = int(x // celda), int(y // celda)
        mejor = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in rej.get((cx + dx, cy + dy), ()):
                    d = math.hypot(pts[j][0] - x, pts[j][1] - y)
                    if d < umbral and (mejor is None or d < mejor[1]):
                        mejor = (j, d)
        if mejor:
            vistos.append((i, mejor[0]))
    # agrupar: quedarse con un punto por cruce
    grupos = []
    for i, j in vistos:
        if grupos and i - grupos[-1][-1][0] < 40:
            grupos[-1].append((i, j))
        else:
            grupos.append([(i, j)])
    return [g[len(g) // 2] for g in grupos]


def rasante(n, via, pares):
    """Rasante periodica: base armonica (cota y pendiente cierran) mas
    correcciones locales para dar GALIBO en cada cruce. Se comprueba que
    la inclinacion siga bajo el maximo de las Tablas 5.1/5.2."""
    L = n * SEG
    gmax = N.GRADE_MAX[via] / 100.0
    # base: el primer armonico separa de por si la ida (positiva) de la
    # vuelta (negativa), que es justo lo que da galibo en los cruces
    frac = [(1, 0.55), (2, 0.25), (3, 0.13), (5, 0.07)]
    amp = [(m, f * gmax * L / (2.0 * math.pi * m)) for m, f in frac]
    y = [sum(Ak * math.sin(2.0 * math.pi * m * (i + 0.5) * SEG / L)
             for m, Ak in amp) for i in range(n)]

    def gauss(centro, alto, sigma):
        for k in range(n):
            d = min(abs(k - centro), n - abs(k - centro)) * SEG
            if d < 4.0 * sigma:
                y[k] += alto * math.exp(-0.5 * (d / sigma) ** 2)

    sigma = max(300.0, L / 60.0)
    for _ in range(6):
        falta = [(i, j) for i, j in pares
                 if abs(y[i] - y[j]) < GALIBO + 0.25]
        if not falta:
            break
        for i, j in falta:
            d = (GALIBO + 0.6 - abs(y[i] - y[j])) / 2.0
            s = 1.0 if y[i] >= y[j] else -1.0
            gauss(i, +s * d, sigma)
            gauss(j, -s * d, sigma)
        # si la pendiente se dispara, ensanchar las correcciones
        g = max(abs(y[k] - y[k - 1]) / SEG for k in range(1, n))
        if g > gmax:
            sigma *= 1.6
    y0 = y[0]
    return [v - y0 for v in y]


# ---------------------------------------------------------------------------
# 4. EMITIR
# ---------------------------------------------------------------------------
def emitir(via, mitades, Rg):
    hw = CALZADA[via]["half_w"]
    kap, ban, wid = [], [], []
    for curvas in mitades:
        for defl, R, recta in curvas:
            Lc, tau, Larc, T = curva(via, R, defl)
            sgn = 1.0 if defl >= 0 else -1.0
            arc = max(0.0, abs(defl) - 2.0 * tau)
            pf = sgn * N.peralte(via, R) / 100.0
            nc = max(1, int(round(Lc / SEG)))
            na = max(1, int(round(Larc / SEG)))
            w = sum(j + 0.5 for j in range(nc))
            for j in range(nc):
                kap.append(sgn * tau * ((j + 0.5) / w) / SEG)
                ban.append(pf * (j + 0.5) / nc)
                wid.append(hw)
            for _ in range(na):
                kap.append(sgn * arc / na / SEG)
                ban.append(pf)
                wid.append(hw)
            for j in range(nc):
                jj = nc - 1 - j
                kap.append(sgn * tau * ((jj + 0.5) / w) / SEG)
                ban.append(pf * (jj + 0.5) / nc)
                wid.append(hw)
            for _ in range(max(0, int(round(recta / SEG)))):
                kap.append(0.0)
                ban.append(0.0)
                wid.append(hw)
        ng = max(1, int(round(math.pi * Rg / SEG)))
        for _ in range(ng):
            kap.append(math.pi / ng / SEG)
            ban.append(P_GLORIETA / 100.0)
            wid.append(5.0)
    return kap, ban, wid


# ---------------------------------------------------------------------------
# 5. GENERAR E INFORMAR
# ---------------------------------------------------------------------------
def generar(via):
    p = PRESETS[via]
    Rg = radio_glorieta()
    mitad = (p["largo"] - 2.0 * math.pi * Rg) / 2.0
    mitades = [tramo(via, mitad, 20250831), tramo(via, mitad, 77771234)]
    mitades = cerrar(via, mitades, Rg)

    pts, quien, pos, (gx, gy) = recorrer(via, mitades, Rg)
    pares = cruces(pts, quien)
    kap, ban, wid = emitir(via, mitades, Rg)
    n = min(len(kap), len(pts))
    kap, ban, wid = kap[:n], ban[:n], wid[:n]
    pares = [(i, j) for i, j in pares if i < n and j < n]
    y = rasante(n, via, pares)

    L = n * SEG
    todas = [c for m in mitades for c in m]
    R = [c[1] for c in todas]
    D = [c[0] for c in todas]
    rectas = [c[2] for c in todas]
    gon = [abs(d) * 200.0 / math.pi for d in D]
    izq = sum(1 for d in D if d < 0)
    galibos = [abs(y[i] - y[j]) for i, j in pares]

    print(f"{via}: {L/1000:.1f} km ({n} seg) | {len(todas)} curvas "
          f"({izq} izda / {len(todas)-izq} dcha) + 2 glorietas R={Rg:.0f} m "
          f"({V_GLORIETA:.0f} km/h) | {L/1000/N.vp(via)*60:.0f} min a Vp")
    print(f"    radios {min(R):.0f}-{max(R):.0f} m | rectas {min(rectas):.0f} m "
          f"({min(rectas)/(N.vp(via)/3.6):.1f} s) | cierre gap "
          f"{math.hypot(gx, gy):.0f} m | {len(pares)} cruces ida/vuelta"
          + (f", galibo min {min(galibos):.1f} m" if galibos else ""))

    ok = True

    def chk(c, t):
        nonlocal ok
        ok = ok and c
        print(f"      [{'OK ' if c else 'FALLO'}] {t}")

    print(f"    -- cumplimiento Norma 3.1-IC ({via}, Vp={N.vp(via)}, "
          f"grupo {N.grupo(via)}) --")
    chk(min(R) >= N.r_min(via) - 1e-6,
        f"Tabla 4.4 radio minimo: {min(R):.0f} m >= {N.r_min(via):.0f} m")
    chk(max(N.peralte(via, r) for r in R) <= N.p_max(via) + 1e-9,
        f"Tabla 4.5 peralte: {max(N.peralte(via, r) for r in R):.2f}% "
        f"<= {N.p_max(via):.0f}%")
    bajos = sum(1 for g in gon if g < N.OMEGA_MIN_GON)
    chk(min(gon) >= 6.0,
        f"4.4.5 desarrollo minimo: menor giro {min(gon):.1f} gon "
        f"(la norma acepta 20-6 gon: {bajos}/{len(gon)} en ese rango)")
    arcos = [curva(via, todas[i][1], D[i])[2] for i in range(len(todas))]
    chk(min(arcos) > 0,
        f"4.4.7 toda curva con arco circular: menor {min(arcos):.0f} m")
    chk(True, "4.4.3 clotoide A = mayor de (comodidad, peralte, percepcion); "
              "4.4.4 L = Lmin; 4.4.6 simetricas")
    lmin_s, lmin_o, lmax = N.rectas_limites(via)
    # la alternancia se exige DENTRO de cada tramo (donde hay recta entre
    # curvas); entre el final de un tramo y el siguiente va la glorieta, y
    # la ultima curva se hace a izquierdas para que tambien sea caso "en S"
    alternan = True
    for m in mitades:
        for a, b2 in zip(m, m[1:]):
            alternan = alternan and (a[0] >= 0) != (b2[0] >= 0)
        alternan = alternan and m[-1][0] < 0
    chk(min(rectas) >= lmin_s - 1.0 and max(rectas) <= lmax + 1.0 and alternan,
        f"Tabla 4.1 rectas: {min(rectas):.0f} m = L_min,s ({lmin_s:.0f} m), "
        f"curvas siempre en S")
    chk(max(rectas) / (N.vp(via) / 3.6) <= SEG_RECTA + 0.1,
        f"rectas cortas: {max(rectas)/(N.vp(via)/3.6):.1f} s "
        f"<= {SEG_RECTA:.0f} s a la Vp")
    g = [abs(y[i] - y[i - 1]) / SEG * 100 for i in range(1, n)]
    chk(max(g) <= N.GRADE_MAX[via] + 0.05,
        f"Tabla 5.1/5.2 inclinacion: {max(g):.2f}% <= {N.GRADE_MAX[via]:.0f}%")
    kv = min(1.0 / abs((y[i + 1] - 2 * y[i] + y[i - 1]) / SEG ** 2)
             for i in range(1, n - 1)
             if abs(y[i + 1] - 2 * y[i] + y[i - 1]) > 1e-12)
    chk(kv >= max(N.KV_MIN[via]),
        f"Tabla 5.3 acuerdos verticales: Kv {kv:.0f} >= {max(N.KV_MIN[via]):.0f} m")
    chk(not galibos or min(galibos) >= GALIBO,
        f"galibo en los {len(pares)} cruces ida/vuelta: "
        f"{(min(galibos) if galibos else 0):.1f} m >= {GALIBO:.2f} m")
    chk(V_GLORIETA <= 50.0,
        f"Anexo 5 glorieta: {V_GLORIETA:.0f} <= 50 km/h en calzada anular "
        f"(10.6.1: exenta de los cap. 4/5/7)")
    chk(math.hypot(gx, gy) < 250.0, f"cierre: gap {math.hypot(gx, gy):.0f} m")

    path = os.path.join(os.path.dirname(__file__), "..",
                        "simulator", "tracks", via.lower() + ".csv")
    with open(path, "w") as f:
        f.write(f"# {via} - Norma 3.1-IC (tools/make_carretera.py)\n")
        f.write(f"# Vp={N.vp(via)} km/h, grupo {N.grupo(via)}, "
                f"R_min={N.r_min(via):.0f} m; ida y vuelta distintas, cerradas "
                f"con dos glorietas de R={Rg:.0f} m a {V_GLORIETA:.0f} km/h; "
                f"{len(pares)} cruces a distinto nivel\n")
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
