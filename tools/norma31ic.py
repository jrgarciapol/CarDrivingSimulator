"""Norma 3.1-IC Trazado (Instruccion de Carreteras): tablas y formulas.

Extraidas de docs/instruccion_trazado.pdf. Este modulo es la UNICA fuente de
los criterios normativos; el generador de trazados los consume.

  Tabla 4.1  longitudes minima/maxima de alineacion recta
  Tabla 4.3  coeficiente de rozamiento transversal maximo movilizado (ft max)
  Tabla 4.4  velocidad de proyecto -> radio minimo y peralte maximo
  Tabla 4.5  peralte en funcion del radio (para radios > minimo)
  Tabla 4.6  variacion de la aceleracion centrifuga J
  4.4.3      parametro minimo de la clotoide (3 limitaciones)
  4.4.5      desarrollo minimo de la curva (angulo de giro)
  Tabla 5.1/5.2 inclinacion maxima de la rasante
  Tabla 5.3  parametros minimos Kv de los acuerdos verticales
"""

import math

# --- Tabla 4.3: coeficiente de rozamiento transversal maximo movilizado -----
FT_MAX = {40: 0.180, 50: 0.166, 60: 0.151, 70: 0.137, 80: 0.122, 90: 0.113,
          100: 0.104, 110: 0.096, 120: 0.087, 130: 0.078, 140: 0.069}

# --- Tabla 4.4: radio minimo y peralte maximo por velocidad de proyecto -----
# clave: denominacion -> (grupo, Vp, R_min m, p_max %)
VIAS = {
    "A-120": (2, 120, 700.0, 8.0),
    "C-90":  (3, 90,  350.0, 7.0),
    "C-50":  (3, 50,   85.0, 7.0),
}

# --- Tabla 5.1 / 5.2: inclinacion maxima de la rasante (%) -----------------
# autopistas y autovias: Vp>=100 -> 4 ; Vp 90 y 80 -> 5
# convencionales: Vp100 -> 4 ; 90 y 80 -> 5 ; 70 y 60 -> 6 ; 50 y 40 -> 7
GRADE_MAX = {"A-120": 4.0, "C-90": 5.0, "C-50": 7.0}
GRADE_MIN = 0.5                      # % minimo por drenaje

# --- Tabla 5.3: parametros minimos Kv (visibilidad de parada) --------------
# denominacion -> (Kv convexo, Kv concavo) en m
KV_MIN = {"A-120": (11000.0, 7100.0),
          "C-90":  (3500.0, 3800.0),
          "C-50":  (450.0, 1160.0)}


def grupo(via):
    return VIAS[via][0]


def vp(via):
    return VIAS[via][1]


def r_min(via):
    """Tabla 4.4: radio minimo (m)."""
    return VIAS[via][2]


def p_max(via):
    """Tabla 4.4: peralte maximo (%)."""
    return VIAS[via][3]


def peralte(via, R):
    """Tabla 4.5: peralte (%) en funcion del radio. Devuelve 0 para radios
    tan grandes que corresponde bombeo (no es peralte de curva)."""
    g = grupo(via)
    if g in (1,):                       # A-140 / A-130
        if R <= 1050.0:
            return 8.0
        if R <= 5000.0:
            return 8.0 - 7.96 * (1.0 - 1050.0 / R) ** 1.2
        if R < 7500.0:
            return 2.0
        return 0.0
    if g == 2:                          # A-120..A-80, C-100
        if R <= 700.0:
            return 8.0
        if R <= 5000.0:
            return 8.0 - 7.3 * (1.0 - 700.0 / R) ** 1.3
        if R < 7500.0:
            return 2.0
        return 0.0
    # grupo 3: C-90..C-40
    if R <= 350.0:
        return 7.0
    if R <= 2500.0:
        return 7.0 - 6.65 * (1.0 - 350.0 / R) ** 1.9
    if R < 3500.0:
        return 2.0
    return 0.0


def j_comodidad(ve):
    """Tabla 4.6: variacion de la aceleracion centrifuga J (m/s3)."""
    return 0.5 if ve < 80 else 0.4


def grad_ip(via):
    """4.4.3.2: gradiente maximo de la pendiente transversal (%)."""
    return 0.86 - 0.004 * vp(via)


def a_min_comodidad(via, R):
    """4.4.3.1: parametro minimo por variacion de la aceleracion centrifuga
    (caso recta -> curva circular: R1=inf, p1=0)."""
    ve = vp(via)
    p = peralte(via, R)
    j = j_comodidad(ve)
    val = (ve * ve / R) - 1.27 * p
    if val <= 0:
        return 0.0
    return math.sqrt(R * ve / (46.656 * j) * val)


def a_min_peralte(via, R, B, k=1.0):
    """4.4.3.2: parametro minimo por transicion del peralte.
    B = distancia del borde de calzada al eje de giro (m); k factor de carriles."""
    p = peralte(via, R)
    return math.sqrt(R * B * k * p / grad_ip(via))


def a_min_percepcion(R):
    """4.4.3.3: parametro minimo por percepcion visual.
    R >= 972 m -> A = R/3 (acimut >= 1/18 rad)
    R <  972 m -> A = (12 R^3)^(1/4)  (retranqueo >= 0,50 m)"""
    if R >= 972.0:
        return R / 3.0
    return (12.0 * R ** 3) ** 0.25


def a_min(via, R, B, k=1.0):
    """4.4.3: el parametro de la clotoide es el MAYOR de las tres
    limitaciones."""
    return max(a_min_comodidad(via, R),
               a_min_peralte(via, R, B, k),
               a_min_percepcion(R))


OMEGA_MIN_GON = 20.0     # 4.4.5 desarrollo minimo (aceptable hasta 6 gon)
L_CLOT_MAX_FACTOR = 1.5  # 4.4.4 la clotoide no superara 1,5 veces su L minima


def rectas_limites(via):
    """Tabla 4.1: (Lmin_s, Lmin_o, Lmax) en m.
    Lmin_s = recta entre curvas de sentido CONTRARIO (trazado en S)
    Lmin_o = recta entre curvas del MISMO sentido
    Lmax   = longitud maxima recomendable"""
    v = vp(via)
    return 1.39 * v, 2.78 * v, 16.70 * v
