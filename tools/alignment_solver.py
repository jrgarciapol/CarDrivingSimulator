"""Solver de cierre del trazado en planta a partir de las DIRECTRICES.

Entrada: las alineaciones dibujadas a mano (rectas infinitas y círculos
completos), en orden de estación sobre la traza. Salida: un trazado de diseño
que ENLAZA esas directrices con clotoides (tangencia C1 y C2) y CIERRA el
anillo a ±360°, manteniendo EXACTOS los radios y las direcciones de recta y
moviendo los círculos su retranqueo.

Trabaja en dos etapas:

  Etapa 1 (curvatura/rumbo — lo que consume el simulador):
    Incógnitas = longitudes de cada segmento (arcos, rectas y clotoides).
    Restricción = entre dos rectas consecutivas, el giro total (Σ de los
    giros de clotoides y arcos intermedios) debe igualar la diferencia EXACTA
    de rumbo entre esas dos rectas, desambiguada con el giro real de la traza
    (necesario en horquillas). Objetivo = quedarse cerca del reparto que
    dibujó el usuario (longitudes ≈ las de su traza). Se resuelve por mínimos
    cuadrados con restricciones lineales (sistema KKT), con conjunto activo
    para longitudes no negativas y clotoide mínima.

  Etapa 2 (planta 2D — retranqueo y verificación):
    Se integra κ(s) para obtener la planta; se ajustan las longitudes de
    recta (no cambian el rumbo) para cerrar posición; se comparan los centros
    de círculo resultantes con los dibujados -> retranqueo de cada uno.

La convención de curvatura es la del simulador: κ = −dφ/ds (κ>0 = derecha).
"""

import math

import numpy as np

import alignment_geom as ag


TWO_PI = 2.0 * math.pi


def _wrap(a):
    return (a + math.pi) % TWO_PI - math.pi


# ------------------------------------------------------- anillo de directrices
def build_ring(elements, xy, stations, merge_kink_deg=2.0):
    """Ordena las directrices por estación y fusiona rectas consecutivas casi
    colineales (quiebro < merge_kink_deg). Devuelve (ring, avisos)."""
    els = sorted(elements, key=lambda e: e["s0"])
    # fit_line da una dirección SIN orientar (autovector). Orientarla según el
    # sentido de marcha (tangente de la traza) para que los rumbos sean
    # coherentes; si no, algunas rectas apuntan "hacia atrás" (180°).
    for e in els:
        if e["kind"] == "line":
            smid = 0.5 * (e["s0"] + e["s1"])
            tx, ty = ag.tangent_at(smid, xy, stations)
            if e["dir"][0] * tx + e["dir"][1] * ty < 0:
                e["dir"] = (-e["dir"][0], -e["dir"][1])
    ring = []
    avisos = []
    for e in els:
        if (e["kind"] == "line" and ring and ring[-1]["kind"] == "line"):
            b0 = math.atan2(ring[-1]["dir"][1], ring[-1]["dir"][0])
            b1 = math.atan2(e["dir"][1], e["dir"][0])
            dk = math.degrees(abs(_wrap(b1 - b0)))
            # dos rectas seguidas no pueden enlazarse sin curva: se fusionan
            # (el quiebro se absorbe). Si es apreciable, se avisa para que el
            # usuario dibuje un círculo ahí.
            if dk >= merge_kink_deg:
                avisos.append(
                    f"quiebro recta-recta de {dk:.1f}° en s≈{e['s0']:.0f} m "
                    f"(sin círculo): fusiono las rectas; dibuja un círculo ahí "
                    f"si quieres esa curva")
            ring[-1] = dict(ring[-1], s1=e["s1"])
            continue
        ring.append(dict(e))
    return ring, avisos


def _kappa_ends(d):
    """(κ_inicio, κ_fin) de una directriz."""
    if d["kind"] == "line":
        return 0.0, 0.0
    k = d["kappa"]
    return k, k


def build_segments(ring, L):
    """Construye la secuencia de segmentos: directriz, clotoide, directriz,
    clotoide, ... (la última clotoide cierra con la primera directriz).
    Cada segmento: {tipo, ks, ke, tgt} con tgt = longitud dibujada objetivo.
    tipo ∈ {'line','arc','clo'}. L = longitud total de la traza (para el
    hueco de cierre con módulo)."""
    m = len(ring)
    segs = []
    for i, d in enumerate(ring):
        ks, ke = _kappa_ends(d)
        tgt = max(1.0, d["s1"] - d["s0"]) if d["kind"] != "point" else 4.0
        segs.append({"tipo": ("line" if d["kind"] == "line" else "arc"),
                     "ks": ks, "ke": ke, "tgt": tgt, "dir_idx": i})
        # clotoide hacia la siguiente directriz
        nxt = ring[(i + 1) % m]
        gap = (nxt["s0"] - d["s1"]) % L
        segs.append({"tipo": "clo", "ks": ke, "ke": _kappa_ends(nxt)[0],
                     "tgt": max(8.0, gap), "dir_idx": None,
                     "between": (i, (i + 1) % m)})
    return segs


# ------------------------------------------------------------------- objetivos
def trace_heading_cumulative(xy, stations):
    """Rumbo CONTINUO (desenrollado) de la traza en cada vértice. Fiable en
    conjunto (da la vuelta completa ±2π); se usa solo para elegir la rama de
    2π de los rumbos EXACTOS del usuario, no como objetivo en sí."""
    hs = [0.0]
    prev = None
    for i in range(len(xy) - 1):
        dx = xy[i + 1][0] - xy[i][0]
        dy = xy[i + 1][1] - xy[i][1]
        if dx == 0 and dy == 0:
            hs.append(hs[-1])
            continue
        h = math.atan2(dy, dx)
        if prev is None:
            hs[0] = h
            hs.append(h)
        else:
            hs.append(hs[-1] + _wrap(h - prev))
        prev = h
    hs.append(hs[-1])
    return hs


def _interp_heading(s, stations, hc):
    i = 0
    while i < len(stations) - 2 and stations[i + 1] < s:
        i += 1
    return hc[i]


def span_targets(ring, xy, stations):
    """Giro objetivo de cada tramo entre rectas consecutivas = diferencia de
    los rumbos EXACTOS del usuario, con la rama de 2π elegida por el rumbo
    CONTINUO de la traza (robusto, recupera bien la vuelta completa)."""
    L = stations[-1]
    lines = [i for i, d in enumerate(ring) if d["kind"] == "line"]
    hc = trace_heading_cumulative(xy, stations)

    def cont_bearing(i):
        """Rumbo exacto del usuario, en la rama continua de la traza."""
        smid = 0.5 * (ring[i]["s0"] + ring[i]["s1"])
        htr = _interp_heading(smid, stations, hc)
        b = math.atan2(ring[i]["dir"][1], ring[i]["dir"][0])
        return b + TWO_PI * round((htr - b) / TWO_PI)

    total_wind = hc[-1] - hc[0]        # vuelta completa de la traza (~±2π)
    conts = {i: cont_bearing(i) for i in lines}
    out = []
    for a, b in zip(lines, lines[1:] + [lines[0]]):
        ca = conts[a]
        cb = conts[b]
        if b == lines[0]:              # tramo que cruza la meta
            cb += total_wind
        out.append((a, b, cb - ca))
    return out


# ----------------------------------------------------- etapa 1: curvatura/rumbo
def solve_lengths(segs, targets, ring, lmin_clo=8.0):
    """Resuelve las longitudes de los segmentos por MC con restricciones de
    giro por tramo (KKT), con conjunto activo para respetar longitudes ≥ 0 y
    clotoides ≥ lmin_clo. Devuelve el vector de longitudes."""
    n = len(segs)
    turn_coef = np.array([0.5 * (s["ks"] + s["ke"]) for s in segs])
    tgt = np.array([s["tgt"] for s in segs])
    # pesos: arcos y rectas pegados a lo dibujado; clotoides más libres
    w = np.array([1.0 if s["tipo"] != "clo" else 0.15 for s in segs])

    # índice de segmentos por tramo entre rectas (para la matriz de giro)
    dir_of_seg = [s.get("dir_idx") for s in segs]
    # posición de cada directriz-recta en la secuencia de segmentos
    seg_of_dir = {}
    for si, s in enumerate(segs):
        if s["dir_idx"] is not None:
            seg_of_dir[s["dir_idx"]] = si

    rows = []
    bvec = []
    for (a, b, target) in targets:
        sa = seg_of_dir[a]
        sb = seg_of_dir[b]
        row = np.zeros(n)
        si = (sa + 1) % n
        while si != sb:
            row[si] = turn_coef[si]
            si = (si + 1) % n
        rows.append(row)
        # Σκ·L = −Δrumbo (κ>0 = derecha = el rumbo decrece)
        bvec.append(-target)
    Aeq = np.array(rows)
    beq = np.array(bvec)

    # conjunto activo: variables fijadas a su cota
    lo = np.array([lmin_clo if s["tipo"] == "clo" else
                   (2.0 if s["tipo"] == "line" else 4.0) for s in segs])
    fixed = np.zeros(n, bool)
    x = tgt.copy()
    for _ in range(30):
        free = ~fixed
        idx = np.where(free)[0]
        W = np.diag(w[idx])
        Af = Aeq[:, idx]
        # término independiente ajustado por las variables fijadas
        bb = beq - Aeq[:, fixed] @ x[fixed]
        # KKT: min (x-t)ᵀW(x-t) s.a. Af x = bb
        nf = len(idx)
        K = np.zeros((nf + len(bb), nf + len(bb)))
        K[:nf, :nf] = 2 * W
        K[:nf, nf:] = Af.T
        K[nf:, :nf] = Af
        rhs = np.concatenate([2 * W @ tgt[idx], bb])
        try:
            sol = np.linalg.solve(K, rhs)
        except np.linalg.LinAlgError:
            sol = np.linalg.lstsq(K, rhs, rcond=None)[0]
        xf = sol[:nf]
        xnew = x.copy()
        xnew[idx] = xf
        # ¿alguna variable libre por debajo de su cota? fijarla y repetir
        viol = free & (xnew < lo - 1e-6)
        if not viol.any():
            x = xnew
            break
        x[viol] = lo[viol]
        fixed |= viol
        x[fixed] = np.maximum(x[fixed], lo[fixed])
    else:
        x = xnew
    x = np.maximum(x, lo)
    return x


# --------------------------------------------------------- κ(s) y planta
def kappa_profile(segs, lengths, step=4.0):
    """Muestrea κ(s) a paso `step` recorriendo los segmentos (arco κ cte,
    recta κ=0, clotoide rampa lineal)."""
    ks = []
    for s, L in zip(segs, lengths):
        nseg = max(1, int(round(L / step)))
        for j in range(nseg):
            t = (j + 0.5) / nseg
            ks.append(s["ks"] + (s["ke"] - s["ks"]) * t)
    return ks


def march_segments(segs, lengths, h0=0.0, sub=6.0):
    """Recorre los segmentos analíticamente (recta, arco, clotoide) con la
    convención κ=−dφ/ds. Devuelve:
      pts   posición al inicio de cada segmento y el cierre final (world)
      hs    rumbo al inicio de cada segmento
      cens  centro de círculo de cada segmento 'arc' (world), o None
    """
    x = y = 0.0
    h = h0
    pts = [(x, y)]
    hs = [h]
    cens = []
    for s, Ln in zip(segs, lengths):
        ks, ke = s["ks"], s["ke"]
        if s["tipo"] == "arc" and abs(ks) > 1e-12:
            # centro a la derecha/izquierda según signo (κ>0 -> centro a la
            # derecha del sentido de marcha)
            side = -1.0 if ks > 0 else 1.0     # normal izq * side -> centro
            nx, ny = -math.sin(h), math.cos(h)
            R = 1.0 / abs(ks)
            cens.append((x + side * R * nx, y + side * R * ny))
        else:
            cens.append(None)
        # subintegración (arco y clotoide exactos; recta trivial)
        nsub = max(1, int(round(Ln / sub)))
        ds = Ln / nsub
        for j in range(nsub):
            t = (j + 0.5) / nsub
            k = ks + (ke - ks) * t
            h -= k * ds
            x += math.cos(h) * ds
            y += math.sin(h) * ds
        pts.append((x, y))
        hs.append(h)
    return pts, hs, cens


def close_position(segs, lengths, h0=0.0):
    """Cierra la posición del anillo ajustando SOLO las longitudes de recta
    (no cambian el rumbo). Solución de norma mínima (una pasada, lineal).
    Devuelve las longitudes ajustadas."""
    pts, hs, _ = march_segments(segs, lengths, h0)
    err = np.array(pts[-1])            # cierre = P_final − P_inicial(=0)
    line_ids = [i for i, s in enumerate(segs) if s["tipo"] == "line"]
    if not line_ids:
        return lengths
    U = np.array([[math.cos(hs[i]), math.sin(hs[i])] for i in line_ids]).T
    # min ||δ||  s.a.  U δ = −err   ->  δ = Uᵀ (U Uᵀ)⁻¹ (−err)
    try:
        d = U.T @ np.linalg.solve(U @ U.T, -err)
    except np.linalg.LinAlgError:
        return lengths
    out = list(lengths)
    for k, i in enumerate(line_ids):
        out[i] = max(2.0, lengths[i] + d[k])
    return out


def integrate_plan(ks, step, h0=0.0):
    """Planta (x,y) integrando κ(s) con la convención del simulador."""
    x = y = 0.0
    h = h0
    pts = [(0.0, 0.0)]
    hs = [h0]
    for k in ks:
        h -= k * step
        x += math.cos(h) * step
        y += math.sin(h) * step
        pts.append((x, y))
        hs.append(h)
    return pts, hs


def _trace_xy_at(s, xy, stations):
    i = 0
    while i < len(stations) - 2 and stations[i + 1] < s:
        i += 1
    return xy[i]


def solve(elements, xy, stations, step=4.0):
    """Resuelve el trazado completo a partir de las directrices. Devuelve un
    dict con: ks (κ(s) para el simulador), ring, segs, lengths, plan (planta
    world alineada a la traza), retranqueos [(centro_dibujado, centro_resuelto,
    R, dist)], avisos, y métricas (giro, radio_min, longitud)."""
    L = stations[-1]
    ring, avisos = build_ring(elements, xy, stations)
    segs = build_segments(ring, L)
    targets = span_targets(ring, xy, stations)
    lengths_pre = solve_lengths(segs, targets, ring)

    # rumbo inicial = tangente de la traza al inicio de la 1ª directriz, para
    # que la planta resuelta quede orientada como la traza
    s0 = ring[0]["s0"]
    tx, ty = ag.tangent_at(s0, xy, stations)
    h0 = math.atan2(ty, tx)
    lengths = close_position(segs, lengths_pre, h0)

    ks = kappa_profile(segs, lengths, step)
    pts, hs, cens = march_segments(segs, lengths, h0)
    # trasladar la planta al punto de la traza correspondiente
    P0 = np.asarray(_trace_xy_at(s0, xy, stations), float)
    plan = [(P0[0] + p[0], P0[1] + p[1]) for p in pts]
    cens_w = [None if c is None else (P0[0] + c[0], P0[1] + c[1])
              for c in cens]

    # RETRANQUEO LOCAL de cada círculo: desplazamiento p que introduce su
    # clotoide de entrada/salida (clásico, pocos metros). L de cada clotoide
    # sale del solver (segmentos vecinos).
    import clothoid as cl
    nseg = len(segs)
    retr_local = []
    for i, s in enumerate(segs):
        if s["tipo"] != "arc":
            continue
        R = 1.0 / abs(s["ks"])
        sign = 1.0 if s["ks"] > 0 else -1.0
        L_in = lengths[(i - 1) % nseg]
        L_out = lengths[(i + 1) % nseg]
        p_in = cl.clothoid_shift(L_in, R, sign)[0] if L_in > 1e-6 else 0.0
        p_out = cl.clothoid_shift(L_out, R, sign)[0] if L_out > 1e-6 else 0.0
        retr_local.append({"R": R, "L_in": L_in, "L_out": L_out,
                           "p_in": p_in, "p_out": p_out})

    # desviación de la planta resuelta respecto a la traza (coste de exigir
    # radios Y rectas exactos en un dibujo a mano que no cierra por sí solo)
    drift = 0.0
    for p in plan:
        dmin = min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in xy[::4])
        drift = max(drift, dmin)

    # error de cierre ANTES de forzar el cierre (lo que absorbió el ajuste de
    # longitudes de recta): mide cuánto NO cierran por sí solos radios+rectas
    pts_raw, _, _ = march_segments(segs, lengths_pre, h0)
    misclose = math.hypot(pts_raw[-1][0] - pts_raw[0][0],
                          pts_raw[-1][1] - pts_raw[0][1])

    turn = sum(ks) * step
    rmin = 1.0 / max(abs(k) for k in ks) if ks else float("inf")
    return {
        "ks": ks, "ring": ring, "segs": segs, "lengths": lengths,
        "plan": plan, "centers": cens_w, "retranqueos_local": retr_local,
        "avisos": avisos, "h0": h0, "P0": (float(P0[0]), float(P0[1])),
        "turn": turn, "rmin": rmin, "length": sum(lengths),
        "trace_drift": drift, "misclose": misclose,
    }
