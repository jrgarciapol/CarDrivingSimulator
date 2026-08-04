"""Núcleo de geometría de clotoides para el trazado en planta.

Modelo de diseño de carreteras: las DIRECTRICES son rectas infinitas y
círculos completos (centro + radio + sentido). El script GENERA las clotoides
(espirales de Euler) que las enlazan con tangencia en 1ª derivada (rumbo, C1) y
2ª derivada (curvatura, C2), retranqueando el círculo lo necesario para que la
transición quepa.

Clotoide de Euler:  R·L = A²  (curvatura lineal con la longitud de arco).
  - ángulo recorrido por la clotoide:  τ = L / (2R)
  - retranqueo (desplazamiento del círculo hacia el interior de la recta):
        p = Y_c − R(1 − cos τ)         (exacto; aprox. de manual  p ≈ L²/24R)
  - retroceso de la tangente (abscisa del centro sobre la recta):  x_c ≈ L/2

Convención de curvatura del simulador: κ = −dφ/ds  (κ>0 = curva a la DERECHA).
Aquí el signo de la clotoide/círculo (`sign`) es +1 a la derecha, −1 a la
izquierda, coherente con esa convención.

Sin dependencias externas (solo numpy): las integrales de Fresnel se resuelven
por serie/cuadratura, y el endpoint de la clotoide integrando κ(s) directo.
"""

import math

import numpy as np


# --------------------------------------------------------------- Fresnel
def fresnel(t, n=600):
    """Integrales de Fresnel  C(t)=∫₀ᵗcos(πu²/2)du ,  S(t)=∫₀ᵗsin(πu²/2)du
    por cuadratura de Simpson. `t` puede ser escalar o array. Precisión
    holgada en el rango que usamos (|t|≲1.5)."""
    t = np.asarray(t, float)
    scalar = t.ndim == 0
    tt = np.atleast_1d(t)
    out_c = np.empty_like(tt)
    out_s = np.empty_like(tt)
    for k, tv in enumerate(tt):
        m = n if n % 2 == 0 else n + 1
        u = np.linspace(0.0, tv, m + 1)
        fc = np.cos(0.5 * math.pi * u * u)
        fs = np.sin(0.5 * math.pi * u * u)
        h = (tv) / m if m else 0.0
        w = np.ones(m + 1)
        w[1:-1:2] = 4.0
        w[2:-1:2] = 2.0
        out_c[k] = h / 3.0 * np.dot(w, fc)
        out_s[k] = h / 3.0 * np.dot(w, fs)
    if scalar:
        return float(out_c[0]), float(out_s[0])
    return out_c, out_s


# ---------------------------------------------------- clotoide (local)
def clothoid_endpoint(L, R, sign=1.0, steps=2000):
    """Extremo de una clotoide que arranca en el origen con rumbo 0 y κ=0 y
    llega a κ = sign/R en s=L. Devuelve (x, y, theta): posición y rumbo del
    extremo en el marco local (integrando κ(s)=sign·s/(L·R))."""
    ds = L / steps
    x = y = th = 0.0
    for i in range(steps):
        s = (i + 0.5) * ds
        k = sign * s / (L * R)
        x += math.cos(th) * ds
        y += math.sin(th) * ds
        th += k * ds
    return x, y, th


def clothoid_endpoint_fresnel(L, R, sign=1.0):
    """Igual que clothoid_endpoint pero por Fresnel (forma cerrada). Sirve de
    verificación cruzada. A²=R·L, s=A√π·t, extremo en t_L=√(L/(πR))."""
    A = math.sqrt(R * L)
    tL = math.sqrt(L / (math.pi * R))
    C, S = fresnel(tL)
    x = A * math.sqrt(math.pi) * C
    y = sign * A * math.sqrt(math.pi) * S
    th = sign * L / (2.0 * R)
    return x, y, th


def clothoid_shift(L, R, sign=1.0):
    """Retranqueo de la clotoide recta→círculo. Devuelve (p, xc, tau):
      p   = retranqueo (desplazamiento perpendicular del círculo respecto a
            la recta de entrada; siempre ≥0 hacia el interior)
      xc  = abscisa del centro del círculo sobre la recta (retroceso ≈ L/2)
      tau = ángulo de la clotoide L/(2R)
    El círculo tangente al final de la clotoide tiene su centro, en el marco
    local (recta = eje x, entrada en el origen), en (xc, sign·(R+p))."""
    x, y, th = clothoid_endpoint(L, R, sign)
    tau = L / (2.0 * R)
    # centro = extremo + R en la normal (lado cóncavo)
    cx = x - sign * R * math.sin(th)
    cy = y + sign * R * math.cos(th)
    p = abs(cy) - R          # |cy| = R + p
    return p, cx, tau


def link_line_arc(P, d, C_drawn, R, sign, L):
    """Enlaza una RECTA (punto P, dirección unitaria d = sentido de marcha) con
    un CÍRCULO de radio R y sentido `sign` mediante una clotoide de longitud L,
    manteniendo EXACTOS R y la dirección de la recta. Desliza el punto de
    tangencia sobre la recta para que el círculo, ya RETRANQUEADO a su posición
    geométrica correcta, quede a la misma abscisa (sobre la recta) que el
    círculo que dibujó el usuario; el retranqueo es entonces el desplazamiento
    perpendicular necesario.

    Devuelve dict con:
      TS        punto de tangencia recta→clotoide (world)
      SC        punto de tangencia clotoide→círculo (world)
      C_fixed   centro del círculo retranqueado (world)
      shift     vector de retranqueo (C_fixed − C_drawn)
      p, tau, L parámetros de la clotoide
      poly      polilínea de la clotoide (world)
    """
    P = np.asarray(P, float)
    d = np.asarray(d, float)
    d = d / np.hypot(*d)
    nrm = np.array([-d[1], d[0]])          # normal a la IZQUIERDA de la marcha
    C_drawn = np.asarray(C_drawn, float)

    p, xc, tau = clothoid_shift(L, R, sign)
    rel = C_drawn - P
    a_center = float(rel @ d)              # abscisa del centro dibujado
    a_TS = a_center - xc                   # el centro cae xc por delante de TS
    TS = P + a_TS * d
    C_fixed = TS + xc * d + sign * (R + p) * nrm
    poly_local = clothoid_polyline(L, R, sign)
    poly = [TS + xl * d + yl * nrm for (xl, yl) in poly_local]
    SC = poly[-1]
    return {
        "TS": TS, "SC": np.asarray(SC), "C_fixed": C_fixed,
        "shift": C_fixed - C_drawn, "p": p, "tau": tau, "L": L,
        "poly": [np.asarray(q) for q in poly],
    }


def clothoid_polyline(L, R, sign=1.0, npts=60):
    """Polilínea local de la clotoide (origen, rumbo 0, κ 0→sign/R)."""
    pts = [(0.0, 0.0)]
    ds = L / npts
    x = y = th = 0.0
    for i in range(npts):
        s = (i + 0.5) * ds
        k = sign * s / (L * R)
        x += math.cos(th) * ds
        y += math.sin(th) * ds
        th += k * ds
        pts.append((x, y))
    return pts
