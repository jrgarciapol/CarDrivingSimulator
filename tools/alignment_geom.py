"""Geometría del editor de alineaciones en planta (núcleo sin GUI).

Modelo de datos: un trazado en planta es una secuencia de ALINEACIONES
definidas por el usuario sobre su traza (la línea del KML):

  - recta   (line)  : curvatura κ = 0
  - círculo (arc)   : curvatura κ = ±1/R constante
  - punto   (point) : una curvatura objetivo en una estación (círculo
                      degenerado; sirve para curvas sin arco circular)

El usuario ajusta cada alineación a unos puntos que pincha (mínimos
cuadrados: círculo de Kåsa, recta por PCA). Las alineaciones cubren tramos
de la traza; los HUECOS entre alineaciones consecutivas son las CLOTOIDES.

Ensamblado (assemble_kappa): se trabaja en el diagrama de curvatura, que es
justo el formato interno del simulador. Un trazado correcto es ahí una
poligonal continua: tramos planos (recta κ=0, círculo κ=cte) unidos por
rampas (clotoides, κ lineal). Así la tangencia y la continuidad de curvatura
salen solas, y solo hay que fijar las estaciones de cada elemento (ajustadas
a la traza) y forzar el cierre del bucle (Σκ·ds = ±2π). No se resuelve la
geometría 2D con puntos de tangencia y retranqueo ΔR explícitos —no hace
falta, porque el simulador solo consume κ(s)— pero la intención de diseño
del usuario (qué radios, qué rectas, dónde van las clotoides) se respeta
exactamente.
"""

import math

import numpy as np


# --------------------------------------------------------------- proyección
def to_local_xy(lonlat):
    """lon/lat -> metros locales (equirectangular alrededor del 1er punto)."""
    lat0 = sum(p[1] for p in lonlat) / len(lonlat)
    mlat = 111320.0
    mlon = 111320.0 * math.cos(math.radians(lat0))
    x0, y0 = lonlat[0]
    return [((lon - x0) * mlon, (lat - y0) * mlat) for lon, lat in lonlat]


def polyline_stations(xy):
    """Estación acumulada (longitud de arco) de cada vértice de la traza."""
    s = [0.0]
    for i in range(1, len(xy)):
        s.append(s[-1] + math.dist(xy[i], xy[i - 1]))
    return s


def project_station(pt, xy, stations):
    """Estación del punto de la traza más cercano a pt (proyección al eje)."""
    px, py = pt
    best_d, best_s = 1e30, 0.0
    for i in range(len(xy) - 1):
        ax, ay = xy[i]
        bx, by = xy[i + 1]
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy or 1e-9
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
        qx, qy = ax + t * dx, ay + t * dy
        d = (px - qx) ** 2 + (py - qy) ** 2
        if d < best_d:
            best_d = d
            best_s = stations[i] + t * math.dist((ax, ay), (bx, by))
    return best_s


def tangent_at(s, xy, stations):
    """Vector tangente unitario de la traza en la estación s."""
    i = 0
    while i < len(stations) - 2 and stations[i + 1] < s:
        i += 1
    dx = xy[i + 1][0] - xy[i][0]
    dy = xy[i + 1][1] - xy[i][1]
    n = math.hypot(dx, dy) or 1e-9
    return dx / n, dy / n


# ------------------------------------------------------------------- ajustes
def fit_circle(pts):
    """Círculo de mejor ajuste (Kåsa, mínimos cuadrados algebraicos).
    Devuelve (centro, radio)."""
    P = np.asarray(pts, float)
    x, y = P[:, 0], P[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(P))]
    b = x * x + y * y
    (a, bb, c), *_ = np.linalg.lstsq(A, b, rcond=None)
    R = math.sqrt(max(1e-9, c + a * a + bb * bb))
    return (float(a), float(bb)), R


def fit_line(pts):
    """Recta de mejor ajuste (PCA / mínimos cuadrados totales).
    Devuelve (punto_medio, direccion_unitaria)."""
    P = np.asarray(pts, float)
    c = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P - c)
    d = vt[0]
    return (float(c[0]), float(c[1])), (float(d[0]), float(d[1]))


def arc_signed_kappa(center, R, pts, xy, stations):
    """Signo de la curvatura del arco según de qué lado del sentido de la
    marcha queda el centro (+κ = curva a la derecha, centro a la derecha)."""
    smid = project_station(pts[len(pts) // 2], xy, stations)
    tx, ty = tangent_at(smid, xy, stations)
    mx, my = pts[len(pts) // 2]
    nx, ny = center[0] - mx, center[1] - my
    cross = tx * ny - ty * nx          # >0: centro a la izquierda
    sign = -1.0 if cross > 0 else 1.0  # centro a la derecha -> +κ (derecha)
    return sign / R


# --------------------------------------------------------------- ensamblado
def build_element(kind, pts, xy, stations):
    """Crea un elemento {kind, kappa, s0, s1, ...} a partir de los puntos
    pinchados y la traza (para situarlo por estación)."""
    ss = sorted(project_station(p, xy, stations) for p in pts)
    s0, s1 = ss[0], ss[-1]
    if kind == "line":
        pt, d = fit_line(pts)
        return {"kind": "line", "kappa": 0.0, "s0": s0, "s1": s1,
                "point": pt, "dir": d}
    if kind == "arc":
        center, R = fit_circle(pts)
        k = arc_signed_kappa(center, R, pts, xy, stations)
        return {"kind": "arc", "kappa": k, "s0": s0, "s1": s1,
                "center": center, "R": R}
    if kind == "point":
        center, R = fit_circle(pts)
        k = arc_signed_kappa(center, R, pts, xy, stations)
        smid = 0.5 * (s0 + s1)
        return {"kind": "point", "kappa": k, "s0": smid, "s1": smid,
                "R": R}
    raise ValueError(kind)


def assemble_kappa(elements, total_len, step, close=True):
    """Compone κ(s) a partir de los elementos: cada elemento aporta su κ
    constante en su tramo, y los huecos entre elementos consecutivos son
    clotoides (rampa lineal de κ). Devuelve la lista de κ por segmento.

    Los elementos se ordenan por estación y se cierra el bucle (el hueco
    entre el último y el primero cruza la meta). Con close, se escala κ para
    que la vuelta gire exactamente ±2π."""
    n = int(round(total_len / step))
    if len(elements) < 2:
        # con 0 o 1 alineación no hay trazado que cerrar; se devuelve la
        # curvatura del único elemento solo en su tramo (evita el caso
        # degenerado del "hueco de cierre del elemento consigo mismo")
        ks = [0.0] * n
        for e in elements:
            for i in range(n):
                if e["s0"] <= (i + 0.5) * step <= e["s1"]:
                    ks[i] = e["kappa"]
        return ks
    els = sorted(elements, key=lambda e: e["s0"])

    def kappa_at(s):
        s %= total_len
        # ¿dentro de algún elemento?
        for e in els:
            if e["s1"] >= e["s0"]:
                if e["s0"] <= s <= e["s1"]:
                    return e["kappa"]
        # si no, estamos en una clotoide entre el elemento previo y el sig.
        prev = els[-1]
        prev_end = prev["s1"] - total_len       # su fin "antes" de la meta
        nxt = els[0]
        for i in range(len(els)):
            if els[i]["s0"] > s:
                nxt = els[i]
                prev = els[i - 1]
                prev_end = prev["s1"]
                break
        else:
            nxt = els[0]
            prev = els[-1]
            prev_end = prev["s1"]
        start = prev_end
        end = nxt["s0"]
        if end <= start:
            end += total_len
        ss = s if s >= start else s + total_len
        t = (ss - start) / (end - start) if end > start else 0.0
        t = max(0.0, min(1.0, t))
        return prev["kappa"] + (nxt["kappa"] - prev["kappa"]) * t

    ks = [kappa_at((i + 0.5) * step) for i in range(n)]
    if close:
        turn = sum(ks) * step
        if abs(turn) > 1e-6:
            f = math.copysign(2 * math.pi, turn) / turn
            ks = [k * f for k in ks]
    return ks


def element_polyline(el, xy, stations, npts=40):
    """Puntos XY de la primitiva ajustada (para dibujarla anclada a la
    traza, sin deriva de integración). Recta: segmento sobre la línea
    ajustada; arco: arco del círculo entre sus extremos."""
    def trace_pt(s):
        i = 0
        while i < len(stations) - 2 and stations[i + 1] < s:
            i += 1
        return xy[i]

    a = trace_pt(el["s0"])
    b = trace_pt(el["s1"])
    if el["kind"] == "line":
        px, py = el["point"]
        dx, dy = el["dir"]
        ta = (a[0] - px) * dx + (a[1] - py) * dy
        tb = (b[0] - px) * dx + (b[1] - py) * dy
        return [(px + dx * (ta + (tb - ta) * k / (npts - 1)),
                 py + dy * (ta + (tb - ta) * k / (npts - 1)))
                for k in range(npts)]
    if el["kind"] == "arc":
        cx, cy = el["center"]
        R = el["R"]
        a0 = math.atan2(a[1] - cy, a[0] - cx)
        a1 = math.atan2(b[1] - cy, b[0] - cx)
        # ir por el arco corto en el sentido de la marcha
        while a1 - a0 > math.pi:
            a1 -= 2 * math.pi
        while a1 - a0 < -math.pi:
            a1 += 2 * math.pi
        return [(cx + R * math.cos(a0 + (a1 - a0) * k / (npts - 1)),
                 cy + R * math.sin(a0 + (a1 - a0) * k / (npts - 1)))
                for k in range(npts)]
    return [a]        # punto


def integrate_xy(ks, step, h0=0.0):
    """Integra κ(s) a una polilínea (para dibujar el resultado). Convención
    del simulador: κ = -dφ/ds (κ>0 = curva a la derecha), así que el rumbo
    DECRECE con κ positiva."""
    x = y = 0.0
    h = h0
    out = [(0.0, 0.0)]
    for k in ks:
        h -= k * step
        x += math.cos(h) * step
        y += math.sin(h) * step
        out.append((x, y))
    return out
