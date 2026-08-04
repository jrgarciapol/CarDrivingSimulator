"""Geometría del editor de ALZADO (perfil longitudinal), núcleo sin GUI.

El alzado es el mismo problema que la planta, una dimensión más simple. Se
trabaja sobre el DIAGRAMA DE PENDIENTES g(s):

  - rasante (grade)  : pendiente g = cte (recta de alzado)
  - acuerdo (gap)    : entre dos rasantes, g varía LINEALMENTE -> una PARÁBOLA
                       (curva de acuerdo vertical), tangente a las dos
                       rasantes por construcción (pendiente continua = C1).

El usuario define las RASANTES sobre el perfil del terreno z(s) (la cota
obtenida del modelo del terreno para nuestro trazado resuelto); los HUECOS
entre rasantes consecutivas son los acuerdos parabólicos. El VÉRTICE (PIV) de
cada parábola es la intersección de las dos rasantes contiguas.

Ensamblado: g(s) es una poligonal continua (tramos planos = rasantes, rampas =
acuerdos). Se integra a la cota z(s) = z0 + Σ g·ds. Como el circuito es un
bucle, la cota debe cerrar (z_fin = z_ini): se reparte el pequeño descuadre
linealmente (detrend), igual que el minimapa cierra la planta.
"""

import numpy as np


def fit_grade(pts):
    """Ajusta una recta z = g·s + b a los puntos (s, z) pinchados (mínimos
    cuadrados). Devuelve (g, b): pendiente e ordenada en el origen."""
    P = np.asarray(pts, float)
    s, z = P[:, 0], P[:, 1]
    A = np.c_[s, np.ones(len(P))]
    (g, b), *_ = np.linalg.lstsq(A, z, rcond=None)
    return float(g), float(b)


def build_rasante(pts):
    """Crea una rasante {g, b, s0, s1, pts} a partir de puntos (estación,
    cota) pinchados sobre el perfil."""
    pts = [(float(p[0]), float(p[1])) for p in pts]
    ss = sorted(p[0] for p in pts)
    g, b = fit_grade(pts)
    return {"kind": "rasante", "g": g, "b": b,
            "s0": ss[0], "s1": ss[-1], "pts": pts}


def piv(r0, r1):
    """Vértice (PIV): intersección de dos rasantes consecutivas. Devuelve
    (s, z) o None si son paralelas."""
    if abs(r0["g"] - r1["g"]) < 1e-9:
        return None
    s = (r1["b"] - r0["b"]) / (r0["g"] - r1["g"])
    z = r0["g"] * s + r0["b"]
    return (s, z)


def assemble_grade(rasantes, total_len, step):
    """Compone g(s) a paso `step`: pendiente constante en cada rasante, rampa
    lineal (parábola) en los huecos entre rasantes consecutivas. El hueco de
    cierre cruza la meta. Devuelve la lista de pendientes por segmento."""
    n = int(round(total_len / step))
    if not rasantes:
        return [0.0] * n
    rs = sorted(rasantes, key=lambda r: r["s0"])
    if len(rs) == 1:
        return [rs[0]["g"]] * n

    def grade_at(s):
        s %= total_len
        for r in rs:
            if r["s0"] <= s <= r["s1"]:
                return r["g"]
        # en un acuerdo: rampa lineal entre la rasante previa y la siguiente
        prev, nxt = rs[-1], rs[0]
        for i in range(len(rs)):
            if rs[i]["s0"] > s:
                nxt = rs[i]
                prev = rs[i - 1]
                break
        start = prev["s1"]
        end = nxt["s0"]
        if end <= start:
            end += total_len
        ss = s if s >= start else s + total_len
        t = (ss - start) / (end - start) if end > start else 0.0
        t = max(0.0, min(1.0, t))
        return prev["g"] + (nxt["g"] - prev["g"]) * t

    return [grade_at((i + 0.5) * step) for i in range(n)]


def integrate_elevation(grades, step, z0=0.0, close=True):
    """Integra g(s) a la cota z(s) = z0 + Σ g·ds. Con close, reparte el
    descuadre de cierre (z_fin - z_ini) linealmente para que el bucle cierre."""
    n = len(grades)
    z = z0
    out = [z0]
    for g in grades:
        z += g * step
        out.append(z)
    if close and n > 0:
        drift = out[-1] - out[0]
        out = [out[i] - drift * (i / n) for i in range(n + 1)]
    return out          # n+1 puntos: el último (out[n]) cierra con out[0]


def fit_offset(z_design, z_terrain):
    """Desplazamiento vertical constante que mejor acerca el perfil de diseño
    al del terreno (mínimos cuadrados: media de la diferencia)."""
    if not z_design or not z_terrain:
        return 0.0
    m = min(len(z_design), len(z_terrain))
    return float(np.mean([z_terrain[i] - z_design[i] for i in range(m)]))


def assemble_profile(rasantes, total_len, step, z_terrain=None):
    """Perfil de diseño completo: g(s) -> z(s) cerrado, ajustado en cota al
    terreno. Devuelve (grades, z, pivots)."""
    grades = assemble_grade(rasantes, total_len, step)
    z = integrate_elevation(grades, step, z0=0.0, close=True)[:len(grades)]
    if z_terrain is not None:
        off = fit_offset(z, z_terrain)
        z = [zi + off for zi in z]
    rs = sorted(rasantes, key=lambda r: r["s0"])
    pivots = [p for p in (piv(rs[i], rs[(i + 1) % len(rs)])
                          for i in range(len(rs))) if p] if len(rs) > 1 else []
    return grades, z, pivots
