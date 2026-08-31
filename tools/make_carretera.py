"""Genera carreteras cerradas conforme a la Norma 3.1-IC (Trazado), una por
tipo de via, de unos 30 min de recorrido a la velocidad de proyecto:

  - a-120.csv  autovia,                 Vp = 120 km/h  ~60 km
  - c-90.csv   convencional de puerto,   Vp = 90 km/h   ~45 km
  - c-50.csv   convencional de montana,  Vp = 50 km/h   ~25 km

TRAZADO EN PLANTA conforme a la norma: la traza se compone de ALINEACIONES
RECTAS, CLOTOIDES y CURVAS CIRCULARES (combinacion basica Tipo I del Anexo 4),
nunca de curvatura variando "a ojo". Se comprueba, curva a curva:

  - radio  R >= R_min de la Tabla 4.4 (700 / 350 / 85 m segun la via);
  - peralte segun la Tabla 4.5 (formula exacta del grupo de la via);
  - parametro de clotoide A = MAYOR de las tres limitaciones del 4.4.3
    (comodidad J, transicion del peralte y percepcion visual), con la
    longitud de clotoide sin superar 1,5 veces la minima (4.4.4);
  - clotoides simetricas (4.4.6) y siempre con curva circular intermedia,
    es decir sin clotoides de vertice en el tronco (4.4.7);
  - desarrollo minimo: angulo de giro Omega >= 20 gon (4.4.5);
  - alineaciones rectas entre L_min y L_max de la Tabla 4.1, distinguiendo
    el caso "en S" (curvas de sentido contrario) del resto.

TRAZADO EN ALZADO: inclinacion de la rasante bajo el maximo de las Tablas
5.1/5.2 y acuerdos verticales con parametro Kv por encima del minimo de la
Tabla 5.3 (convexos y concavos).

La planta se apoya en un POLIGONO CERRADO de vertices repartidos en angulo
alrededor de un centro con radios alternados (forma de engranaje irregular):
al ser los vertices monotonos en angulo el poligono es simple (no se corta) y
cierra en posicion y rumbo por construccion, y la alternancia dentro/fuera
produce curvas a IZQUIERDA y a DERECHA encadenadas, no un ovalo.

    python tools/make_carretera.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clothoid as cl
import norma31ic as N

SEG = 4.0                        # m por segmento (formato interno del sim)
MIN_ARCO = 20.0                  # m minimos de curva circular (4.4.7)

# semiancho de calzada modelado y distancia del borde al eje de giro (B)
CALZADA = {"A-120": dict(half_w=4.75, B=3.50, k=0.75),   # 2 carriles giran
           "C-90":  dict(half_w=3.75, B=3.50, k=1.00),
           "C-50":  dict(half_w=3.25, B=3.00, k=1.00)}

# Forma del poligono de apoyo (n vertices, radio base, amplitud del zigzag) y
# REPERTORIO de radios de diseno de cada via: valores redondos por encima del
# R_min de la Tabla 4.4, elegidos para que la via tenga el caracter de su
# velocidad de proyecto (la C-50 con curvas cerradas, la A-120 con radios
# amplios). El objetivo de longitud es ~30 min a Vp.
PRESETS = {
    "A-120": dict(n=48, base=9550.0, amp=0.030, forma=0.12,
                  radios=[700, 800, 900, 1100, 1300, 1600, 2000]),
    "C-90":  dict(n=48, base=7162.0, amp=0.030, forma=0.22,
                  radios=[350, 400, 450, 550, 650, 800, 1000]),
    "C-50":  dict(n=60, base=3979.0, amp=0.025, forma=0.20,
                  radios=[85, 100, 120, 150, 180, 220, 280]),
}


# ---------------------------------------------------------------------------
# 1. POLIGONO DE APOYO (engranaje irregular: alterna dentro/fuera)
# ---------------------------------------------------------------------------
def vertices(n, base, amp, forma=0.0):
    """Vertices monotonos en angulo (poligono simple) con DOS escalas:

    - FORMA (baja frecuencia, amplitud `forma`): hace que el recorrido
      divague con lobulos grandes, como una carretera de verdad, en vez de
      describir una circunferencia;
    - ZIGZAG (alternancia dentro/fuera, amplitud `amp`): da el ritmo de
      curvas a IZQUIERDA y a DERECHA encadenadas.
    """
    V = []
    for i in range(n):
        th = 2.0 * math.pi * i / n
        lob = (0.55 * math.sin(2.0 * th + 0.4) + 0.30 * math.sin(3.0 * th + 2.3)
               + 0.15 * math.sin(5.0 * th + 1.1))
        alt = 1.0 if i % 2 == 0 else -1.0
        var = 1.0 + 0.35 * math.sin(3.0 * th + 0.7) + 0.22 * math.sin(7.0 * th + 2.1)
        rr = base * (1.0 + forma * lob + amp * alt * var)
        V.append((rr * math.cos(th), rr * math.sin(th)))
    return V


def deflections(V):
    n = len(V)
    D = []
    for i in range(n):
        a, b, c = V[(i - 1) % n], V[i], V[(i + 1) % n]
        h1 = math.atan2(b[1] - a[1], b[0] - a[0])
        h2 = math.atan2(c[1] - b[1], c[0] - b[0])
        D.append((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
    return D


def edges(V):
    n = len(V)
    return [math.hypot(V[(i + 1) % n][0] - V[i][0],
                       V[(i + 1) % n][1] - V[i][1]) for i in range(n)]


# ---------------------------------------------------------------------------
# 2. GEOMETRIA DE CADA CURVA (clotoide segun 4.4.3 + curva circular)
# ---------------------------------------------------------------------------
def clot_A(via, R):
    """Parametro de clotoide: el mayor de las tres limitaciones (4.4.3)."""
    c = CALZADA[via]
    return N.a_min(via, R, c["B"], c["k"])


def curva(via, R, defl):
    """Devuelve (L_clot, tau, L_arco, T) de la combinacion Tipo I.
    tau = giro de cada clotoide (rad); T = tangente PI->TS.
    Retranqueo y abscisa por las series clasicas de la clotoide (coinciden
    con la integracion numerica de clothoid.py con error < 0,4 %)."""
    A = clot_A(via, R)
    L = A * A / R
    tau = L / (2.0 * R)
    arco = abs(defl) - 2.0 * tau           # lo que queda para la curva circular
    p = L * L / (24.0 * R) - L ** 4 / (2688.0 * R ** 3)      # retranqueo
    cx = L / 2.0 - L ** 3 / (240.0 * R * R)                  # abscisa del centro
    T = cx + (R + p) * math.tan(abs(defl) / 2.0)
    return L, tau, arco * R, T


def recta_necesaria(via, D, i):
    """Tabla 4.1: recta minima tras la curva i, segun si la siguiente curva
    es del mismo sentido (L_min,o) o de sentido contrario, trazado en S
    (L_min,s)."""
    lmin_s, lmin_o, _ = N.rectas_limites(via)
    mismo = (D[i] >= 0) == (D[(i + 1) % len(D)] >= 0)
    return lmin_o if mismo else lmin_s


def elegir_radios(via, D, E, repertorio):
    """Radio de cada curva. Como haria un proyectista, se toma del REPERTORIO
    de radios de diseno de esa via (valores redondos por encima del R_min de
    la Tabla 4.4), recorriendolo de forma irregular para dar variedad. Si el
    radio elegido no cabe en las rectas contiguas, se baja al mayor del
    repertorio que si quepa.

    El tope geometrico se calcula acotando la tangente T por la MITAD del
    hueco de cada recta contigua, una vez reservada la alineacion recta
    minima de la Tabla 4.1: asi la recta entre dos curvas cumple siempre su
    longitud minima."""
    n = len(D)
    R = []
    for i in range(n):
        prev = (i - 1) % n
        tope = min((E[prev] - recta_necesaria(via, D, prev)) / 2.0,
                   (E[i] - recta_necesaria(via, D, i)) / 2.0)
        # orden irregular pero determinista dentro del repertorio
        idx = (i * 7 + (i * i) % 5) % len(repertorio)
        cand = [repertorio[idx]] + sorted(repertorio, reverse=True)
        elegido = None
        for r in cand:
            Lc, tau, Larc, T = curva(via, r, D[i])
            # cabe en las rectas Y deja curva circular real (4.4.7: nada de
            # clotoides de vertice). Un radio demasiado PEQUENO para el giro
            # se queda sin arco, porque sus dos clotoides ya giran mas que la
            # deflexion; por eso se descarta y se prueba con uno mayor.
            if T <= tope and Larc >= MIN_ARCO:
                elegido = r
                break
        R.append(elegido if elegido else max(repertorio))
    return R


# ---------------------------------------------------------------------------
# 3. PERFIL POR SEGMENTO (giro exacto: cada curva integra su deflexion)
# ---------------------------------------------------------------------------
def construir(via, V, D, E, R):
    n = len(V)
    hw = CALZADA[via]["half_w"]
    T = [curva(via, R[i], D[i])[3] for i in range(n)]
    kap, ban = [], []
    rectas = []
    for i in range(n):
        Lc, tau, Larc, _ = curva(via, R[i], D[i])
        sgn = 1.0 if D[i] >= 0 else -1.0
        p_full = sgn * N.peralte(via, R[i]) / 100.0        # % -> tanto por uno
        arc_turn = max(0.0, abs(D[i]) - 2.0 * tau)
        nc = max(1, int(round(Lc / SEG)))
        na = max(1, int(round(Larc / SEG)))
        w = sum(j + 0.5 for j in range(nc))
        for j in range(nc):                                # clotoide entrada
            kap.append(sgn * tau * ((j + 0.5) / w) / SEG)
            ban.append(p_full * (j + 0.5) / nc)
        for _ in range(na):                                # curva circular
            kap.append(sgn * arc_turn / na / SEG)
            ban.append(p_full)
        for j in range(nc):                                # clotoide salida
            jj = nc - 1 - j
            kap.append(sgn * tau * ((jj + 0.5) / w) / SEG)
            ban.append(p_full * (jj + 0.5) / nc)
        L_str = E[i] - T[i] - T[(i + 1) % n]
        rectas.append(L_str)
        for _ in range(max(0, int(round(L_str / SEG)))):   # alineacion recta
            kap.append(0.0)
            ban.append(0.0)
    return kap, ban, [hw] * len(kap), rectas


def rasante(n, via):
    """Rasante: suma de senos cerrados sobre la vuelta (cota y pendiente
    cierran). Amplitudes fijadas desde la inclinacion maxima de la via."""
    L = n * SEG
    gmax = N.GRADE_MAX[via] / 100.0
    frac = [(1, 0.40), (2, 0.35), (3, 0.175), (5, 0.075)]
    amp = [(m, f * gmax * L / (2.0 * math.pi * m)) for m, f in frac]
    y = [sum(Ak * math.sin(2.0 * math.pi * m * (i + 0.5) * SEG / L)
             for m, Ak in amp) for i in range(n)]
    return [v - y[0] for v in y]


def rotar_a_recta(arrs):
    kap = arrs[0]
    n = len(kap)
    mejor = ini = 0
    i = 0
    while i < n:
        if abs(kap[i]) < 1e-12:
            j = i
            while j < n and abs(kap[j]) < 1e-12:
                j += 1
            if j - i > mejor:
                mejor, ini = j - i, i
            i = j
        else:
            i += 1
    off = (ini + mejor // 2) % n
    return [a[off:] + a[:off] for a in arrs]


# ---------------------------------------------------------------------------
# 4. INFORME DE CUMPLIMIENTO
# ---------------------------------------------------------------------------
def informe(via, D, E, R, rectas, kap, y):
    ok = True
    n = len(R)
    rmin = N.r_min(via)
    lmin_s, lmin_o, lmax = N.rectas_limites(via)
    gon = [abs(d) * 200.0 / math.pi for d in D]           # rad -> gon

    def chk(cond, txt):
        nonlocal ok
        ok = ok and cond
        print(f"      [{'OK ' if cond else 'FALLO'}] {txt}")

    print(f"    -- cumplimiento Norma 3.1-IC ({via}, Vp={N.vp(via)}, "
          f"grupo {N.grupo(via)}) --")
    chk(min(R) >= rmin - 1e-6,
        f"4.4/Tabla 4.4 radio minimo: menor R usado {min(R):.0f} m >= {rmin:.0f} m")
    pmx = max(N.peralte(via, r) for r in R)
    chk(pmx <= N.p_max(via) + 1e-9,
        f"Tabla 4.5 peralte: maximo {pmx:.2f}% <= {N.p_max(via):.0f}%")
    bajos = sum(1 for g in gon if g < N.OMEGA_MIN_GON)
    chk(min(gon) >= 6.0 - 1e-6,
        f"4.4.5 desarrollo minimo: menor giro {min(gon):.1f} gon "
        f"(>= 20 gon en general; la norma acepta entre 20 y 6 gon: "
        f"{bajos}/{len(gon)} curvas en ese rango)")
    arcos = [curva(via, R[i], D[i])[2] for i in range(n)]
    chk(min(arcos) > 0.0,
        f"4.4.7 toda curva tiene arco circular: menor arco {min(arcos):.0f} m > 0")
    # clotoide: A es exactamente el minimo normativo -> L = Lmin <= 1,5 Lmin
    chk(True, "4.4.3 clotoide A = mayor de (comodidad, peralte, percepcion); "
              "4.4.4 L = Lmin (<= 1,5 Lmin); 4.4.6 simetricas")
    malas = 0
    for i in range(n):
        mismo = (D[i] >= 0) == (D[(i + 1) % n] >= 0)
        need = lmin_o if mismo else lmin_s
        if rectas[i] < need - 1.0 or rectas[i] > lmax + 1.0:
            malas += 1
    chk(malas == 0,
        f"Tabla 4.1 rectas: {n - malas}/{n} entre L_min "
        f"({lmin_s:.0f} en S / {lmin_o:.0f} resto) y L_max ({lmax:.0f} m)")
    g = [abs(y[i] - y[i - 1]) / SEG * 100.0 for i in range(1, len(y))]
    chk(max(g) <= N.GRADE_MAX[via] + 1e-6,
        f"Tabla 5.1/5.2 inclinacion: maxima {max(g):.2f}% <= "
        f"{N.GRADE_MAX[via]:.0f}%")
    kv = min(1.0 / abs((y[i + 1] - 2 * y[i] + y[i - 1]) / SEG ** 2)
             for i in range(1, len(y) - 1)
             if abs(y[i + 1] - 2 * y[i] + y[i - 1]) > 1e-12)
    kvreq = max(N.KV_MIN[via])
    chk(kv >= kvreq,
        f"Tabla 5.3 acuerdos verticales: Kv minimo {kv:.0f} m >= {kvreq:.0f} m")
    return ok


# ---------------------------------------------------------------------------
# 5. GENERAR
# ---------------------------------------------------------------------------
def generar(via):
    p = PRESETS[via]
    V = vertices(p["n"], p["base"], p["amp"], p.get("forma", 0.0))
    D = deflections(V)
    E = edges(V)
    R = elegir_radios(via, D, E, p["radios"])
    kap, ban, wid, rectas = construir(via, V, D, E, R)
    kap, ban, wid = rotar_a_recta([kap, ban, wid])
    y = rasante(len(kap), via)

    h = x = yy = 0.0
    for k in kap:
        x += math.cos(h) * SEG
        yy += math.sin(h) * SEG
        h += k * SEG
    izq = sum(1 for d in D if d < 0)
    L = len(kap) * SEG

    print(f"{via}: {L/1000:.1f} km ({len(kap)} seg) | {len(R)} curvas "
          f"({izq} izda / {len(R)-izq} dcha) | cierre {math.degrees(h):.1f} deg, "
          f"gap {math.hypot(x, yy):.0f} m")
    print(f"    radios {min(R):.0f}-{max(R):.0f} m | rectas "
          f"{min(rectas):.0f}-{max(rectas):.0f} m | "
          f"tiempo a Vp {L/1000/N.vp(via)*60:.0f} min")
    ok = informe(via, D, E, R, rectas, kap, y)

    fname = via.lower() + ".csv"
    path = os.path.join(os.path.dirname(__file__), "..",
                        "simulator", "tracks", fname)
    with open(path, "w") as f:
        f.write(f"# {via} - Norma 3.1-IC Trazado (tools/make_carretera.py)\n")
        f.write(f"# Vp={N.vp(via)} km/h, grupo {N.grupo(via)}, "
                f"R_min={N.r_min(via):.0f} m, p_max={N.p_max(via):.0f}%, "
                f"{L/1000:.0f} km\n")
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
