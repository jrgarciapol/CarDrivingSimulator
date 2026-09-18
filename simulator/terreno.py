"""Terreno de montana que la carretera corta: campo de alturas y secciones.

El circuito (kappa, cota, peralte por segmento) no sabe nada del terreno: la
carretera flotaba sobre una franja de hierba plana. Aqui el terreno es un
CAMPO DE ALTURAS h(x, y) en planta, con semilla fija, guardado junto al
circuito en ``<circuito>.terreno.npz`` (lo genera tools/make_terreno.py) y
leido por el juego para:

  - pintar la ladera a ambos lados de la calzada (malla del terreno), y
  - decidir la SECCION TIPO de cada segmento por la diferencia entre la
    rasante y el terreno bajo el eje, d = cota carretera - cota terreno:

        d >  10 m            PUENTE     (terraplen mas alto no se hace)
        0,5 < d <= 10 m      TERRAPLEN  (talud 3H:2V hasta el terreno)
        -30 <= d < -0,5 m    DESMONTE   (talud 1H:1V hasta el terreno)
        d < -30 m            TUNEL      (desmonte mas hondo no se hace)
        |d| <= 0,5 m         A NIVEL

    con longitudes minimas (un tunel de 20 m o un puente de 12 m no
    existen): los tramos cortos se alargan hasta el minimo y dos tuneles
    (o dos puentes) casi seguidos se unen.

El campo se construye ASI: la cota de la rasante se rasteriza en una
rejilla de planta y se difunde (ecuacion del calor con la carretera fija)
para tener una base suave que sigue a la carretera; encima va un ruido de
valor en varias octavas (laderas, lomas, barrancos) cuya amplitud se
calibra para que la carretera vaya casi siempre en desmonte o terraplen y
de vez en cuando en tunel o puente. Asi la carretera "esta en el terreno"
y el terreno tiene relieve propio.
"""

import math
import os

import numpy as np

from . import config as cfg

#: secciones tipo por segmento
A_NIVEL, TERRAPLEN, DESMONTE, PUENTE, TUNEL = 0, 1, 2, 3, 4
NOMBRES = {A_NIVEL: "a nivel", TERRAPLEN: "terraplen", DESMONTE: "desmonte",
           PUENTE: "puente", TUNEL: "tunel"}

#: reglas de seccion (m)
TERRAPLEN_MAX = 10.0        # por encima, puente
DESMONTE_MAX = 30.0         # por debajo, tunel
UMBRAL_NIVEL = 0.5          # |d| menor: a nivel
TUNEL_MIN = 60.0            # longitudes minimas
PUENTE_MIN = 40.0
UNIR_TUNELES = 40.0         # dos tuneles a menos de esto se unen
UNIR_PUENTES = 30.0

#: taludes (H:V) y seccion del tunel
TALUD_TERRAPLEN = 1.5       # 3H:2V
TALUD_DESMONTE = 1.0        # 1H:1V
TUNEL_ANCHO = 10.0          # m de anchura libre (7 de calzada + arcenes)
TUNEL_GALIBO = 6.5          # m de altura libre en el eje
#: puente
PUENTE_CANTO = 1.5          # m de canto del tablero
PUENTE_PILA_CADA = 30.0     # m entre pilas


# ---------------------------------------------------------------------------
# planta del circuito
# ---------------------------------------------------------------------------
def planta(track):
    """Eje del circuito en planta, en metros y CERRADO (el error de cierre
    se reparte a lo largo): arrays x, y (inicio de cada segmento) y el
    rumbo (rad) de cada segmento. x hacia el este, y hacia el norte, con el
    rumbo 0 hacia +y, como en Track.map_points."""
    L = cfg.SEGMENT_LENGTH
    kap = np.array([s.kappa for s in track.segments])
    n = len(kap)
    h = np.concatenate([[0.0], np.cumsum(kap * L)])[:-1]
    x = np.concatenate([[0.0], np.cumsum(np.sin(h) * L)])
    y = np.concatenate([[0.0], np.cumsum(np.cos(h) * L)])
    t = np.arange(n) / n
    return x[:-1] - x[-1] * t, y[:-1] - y[-1] * t, h


# ---------------------------------------------------------------------------
# ruido
# ---------------------------------------------------------------------------
def _hash(ix, iy, semilla):
    v = (ix.astype(np.int64) * 374761393 + iy.astype(np.int64) * 668265263
         + int(semilla) * 1442695041) & 0xFFFFFFFF
    v = (v ^ (v >> 13)) * 1274126177 & 0xFFFFFFFF
    v = (v ^ (v >> 16)) & 0xFFFFFFFF
    return v.astype(np.float64) / 4294967295.0


def ruido_valor(X, Y, longitud, semilla):
    """Ruido de valor suave (-1..1) con celdas de ``longitud`` metros."""
    px, py = X / longitud, Y / longitud
    ix, iy = np.floor(px), np.floor(py)
    fx, fy = px - ix, py - iy
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    ix, iy = ix.astype(np.int64), iy.astype(np.int64)
    a = _hash(ix, iy, semilla)
    b = _hash(ix + 1, iy, semilla)
    c = _hash(ix, iy + 1, semilla)
    d = _hash(ix + 1, iy + 1, semilla)
    v = (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy
    return v * 2.0 - 1.0


#: octavas del relieve: (longitud de onda m, amplitud m) para amplitud 1
OCTAVAS = [(2400.0, 0.36), (1200.0, 0.27), (600.0, 0.17), (300.0, 0.10),
           (150.0, 0.06), (75.0, 0.03)]


def relieve(X, Y, amplitud, semilla):
    """Suma de octavas: laderas largas y detalle fino, en metros."""
    z = np.zeros_like(X, dtype=np.float64)
    for k, (lam, amp) in enumerate(OCTAVAS):
        z += amp * ruido_valor(X, Y, lam, semilla + 101 * k)
    return z * amplitud


# ---------------------------------------------------------------------------
# generacion del campo
# ---------------------------------------------------------------------------
def _base_difusa(x, y, elev, x0, y0, paso, nx, ny, iteraciones=600,
                 inicial=None):
    """Rejilla con la cota de la carretera en las celdas que cruza (la MAS
    ALTA si pasa dos veces: en un cruce a distinto nivel el terreno esta a
    la altura de la carretera de arriba y la de abajo pasa en tunel; con
    la de abajo salian viaductos de 300 m de alto y 1,6 km) y, en
    el resto, la solucion de la ecuacion del calor (suave, sin extremos
    propios): la base que sigue a la carretera. ``inicial`` es un punto de
    partida (la solucion de una rejilla mas gruesa) para converger rapido."""
    # cada punto del eje fija los CUATRO nodos que lo rodean (los mismos
    # que usa la interpolacion bilineal): asi la cota interpolada bajo el
    # eje es exactamente la de la carretera, tambien en un cruce, donde el
    # nodo mas cercano podia estar fijado solo por la otra carretera
    fx = np.clip((x - x0) / paso, 0.0, nx - 1.001)
    fy = np.clip((y - y0) / paso, 0.0, ny - 1.001)
    maximo = np.full((ny, nx), -np.inf)
    for dx in (0, 1):
        for dy in (0, 1):
            np.maximum.at(maximo, (fy.astype(int) + dy, fx.astype(int) + dx), elev)
    fijo = np.isfinite(maximo)
    z = (np.array(inicial, dtype=float) if inicial is not None
         else np.full((ny, nx), float(elev.mean())))
    z[fijo] = maximo[fijo]
    for _ in range(iteraciones):
        zn = z.copy()
        zn[1:-1, 1:-1] = 0.25 * (z[:-2, 1:-1] + z[2:, 1:-1]
                                 + z[1:-1, :-2] + z[1:-1, 2:])
        zn[0, :], zn[-1, :] = zn[1, :], zn[-2, :]
        zn[:, 0], zn[:, -1] = zn[:, 1], zn[:, -2]
        zn[fijo] = z[fijo]
        z = zn
    return z


def generar(track, amplitud=50.0, semilla=1, paso=10.0, margen=400.0,
            desplazamiento=10.0):
    """El campo de alturas de un circuito: dict con x0, y0, paso y la
    rejilla ``alturas`` [ny, nx] (fila = y). ``amplitud`` (m) escala el
    relieve; ``margen`` (m) es lo que la rejilla sobresale del circuito;
    ``desplazamiento`` (m) sube el terreno respecto a la rasante (una
    carretera de montana va a media ladera, mas en desmonte que en
    terraplen, y con los umbrales 10/30 asi salen tantos tuneles como
    puentes)."""
    x, y, _ = planta(track)
    elev = np.array([s.y for s in track.segments])
    x0, y0 = x.min() - margen, y.min() - margen
    x1, y1 = x.max() + margen, y.max() + margen
    # base: primero en una rejilla gruesa (4 x paso) hasta converger, y de
    # ahi, interpolada, unas iteraciones en la fina para que la carretera
    # quede clavada a su cota tambien donde pasa cerca de si misma
    pg = paso * 4.0
    nxg, nyg = int((x1 - x0) / pg) + 2, int((y1 - y0) / pg) + 2
    base_g = _base_difusa(x, y, elev, x0, y0, pg, nxg, nyg)
    nx, ny = int((x1 - x0) / paso) + 2, int((y1 - y0) / paso) + 2
    X, Y = np.meshgrid(x0 + np.arange(nx) * paso, y0 + np.arange(ny) * paso)
    inicial = _bilineal(base_g, x0, y0, pg, X, Y)
    base = _base_difusa(x, y, elev, x0, y0, paso, nx, ny, iteraciones=120,
                        inicial=inicial)
    alturas = base + desplazamiento + relieve(X, Y, amplitud, semilla)
    return dict(x0=float(x0), y0=float(y0), paso=float(paso),
                alturas=alturas.astype(np.float32), amplitud=float(amplitud),
                semilla=int(semilla), desplazamiento=float(desplazamiento))


def _bilineal(z, x0, y0, paso, X, Y):
    ny, nx = z.shape
    fx = np.clip((np.asarray(X, dtype=float) - x0) / paso, 0.0, nx - 1.001)
    fy = np.clip((np.asarray(Y, dtype=float) - y0) / paso, 0.0, ny - 1.001)
    ix, iy = fx.astype(int), fy.astype(int)
    tx, ty = fx - ix, fy - iy
    return ((z[iy, ix] * (1 - tx) + z[iy, ix + 1] * tx) * (1 - ty)
            + (z[iy + 1, ix] * (1 - tx) + z[iy + 1, ix + 1] * tx) * ty)


def ruta_terreno(track_file):
    """<circuito>.terreno.npz junto al .csv del circuito."""
    base, _ = os.path.splitext(track_file)
    return base + ".terreno.npz"


def guardar(campo, ruta):
    np.savez_compressed(ruta, **campo)


# ---------------------------------------------------------------------------
# el terreno en el juego
# ---------------------------------------------------------------------------
class Terreno:
    """Campo de alturas cargado + secciones tipo del circuito."""

    def __init__(self, campo, track=None):
        self.x0, self.y0 = float(campo["x0"]), float(campo["y0"])
        self.paso = float(campo["paso"])
        self.alturas = np.asarray(campo["alturas"], dtype=np.float64)
        self.amplitud = float(campo.get("amplitud", 0.0))
        self.seccion = None
        self.d_eje = None
        if track is not None:
            self.clasificar(track)

    @classmethod
    def cargar(cls, ruta, track=None):
        if not os.path.exists(ruta):
            return None
        with np.load(ruta) as z:
            campo = {k: z[k] for k in z.files}
        return cls(campo, track)

    def altura(self, x, y):
        """Cota del terreno (m) en (x, y) de planta; acepta arrays."""
        return _bilineal(self.alturas, self.x0, self.y0, self.paso, x, y)

    def clasificar(self, track):
        """Seccion tipo de cada segmento (ver reglas arriba) y d_eje, la
        diferencia rasante - terreno bajo el eje."""
        x, y, _ = planta(track)
        elev = np.array([s.y for s in track.segments])
        d = elev - self.altura(x, y)
        self.d_eje = d
        L = cfg.SEGMENT_LENGTH
        n = len(d)
        sec = np.full(n, A_NIVEL, dtype=np.int8)
        sec[d > UMBRAL_NIVEL] = TERRAPLEN
        sec[d < -UMBRAL_NIVEL] = DESMONTE
        sec[d > TERRAPLEN_MAX] = PUENTE
        sec[d < -DESMONTE_MAX] = TUNEL
        # un tunel no puede alargarse sobre un valle (d > 10) ni un puente
        # meterse en la montana (d < -30): esas celdas bloquean
        for tipo, minimo, unir, bloqueo in (
                (TUNEL, TUNEL_MIN, UNIR_TUNELES, d > TERRAPLEN_MAX),
                (PUENTE, PUENTE_MIN, UNIR_PUENTES, d < -DESMONTE_MAX)):
            otro = PUENTE if tipo == TUNEL else TUNEL
            sec = _consolidar(sec, tipo, int(round(minimo / L)),
                              int(round(unir / L)), bloqueo | (sec == otro))
        self.seccion = sec
        return sec

    def resumen(self, track):
        """Texto con el reparto de secciones y la lista de tuneles y
        puentes (estacion inicial y longitud)."""
        if self.seccion is None:
            self.clasificar(track)
        L = cfg.SEGMENT_LENGTH
        n = len(self.seccion)
        out = []
        for t in (A_NIVEL, TERRAPLEN, DESMONTE, PUENTE, TUNEL):
            m = int((self.seccion == t).sum())
            out.append(f"  {NOMBRES[t]:10s} {m * L / 1000:6.2f} km  {100.0 * m / n:5.1f} %")
        for t in (TUNEL, PUENTE):
            tramos = self.tramos(t)
            out.append(f"  {NOMBRES[t]}es: {len(tramos)}  "
                       + ", ".join(f"pk {i * L / 1000:.2f} ({m * L:.0f} m)"
                                   for i, m in tramos[:12]))
        out.append(f"  d_eje: {self.d_eje.min():+.1f} .. {self.d_eje.max():+.1f} m")
        return "\n".join(out)

    def tramos(self, tipo):
        """[(indice inicial, n segmentos)] de cada tramo del tipo, en
        orden, tratando el circuito como cerrado."""
        sec = self.seccion
        n = len(sec)
        es = sec == tipo
        if es.all():
            return [(0, n)]
        if not es.any():
            return []
        # empezar en un segmento que NO sea del tipo para no partir un tramo
        k0 = int(np.nonzero(~es)[0][0])
        out = []
        i = 0
        while i < n:
            k = (k0 + i) % n
            if es[k]:
                m = 0
                while m < n and es[(k + m) % n]:
                    m += 1
                out.append((k, m))
                i += m
            else:
                i += 1
        return sorted(out)


def _tramos_de(es):
    """[(inicio, n)] de los tramos True de un array circular."""
    n = len(es)
    if not es.any():
        return []
    if es.all():
        return [(0, n)]
    k0 = int(np.nonzero(~es)[0][0])
    out, i = [], 0
    while i < n:
        k = (k0 + i) % n
        if es[k]:
            m = 0
            while m < n and es[(k + m) % n]:
                m += 1
            out.append((k, m))
            i += m
        else:
            i += 1
    return out


def _consolidar(sec, tipo, n_min, n_unir, bloqueo):
    """Los huecos menores que n_unir entre dos tramos del tipo se rellenan
    (si no hay celdas bloqueadas en medio) y los tramos mas cortos que
    n_min se alargan hasta n_min, repartiendo a los dos lados lo que haya
    libre (sin pisar celdas bloqueadas: la otra estructura o un terreno que
    no admite este tipo). Circuito cerrado."""
    sec = sec.copy()
    n = len(sec)
    if not (sec == tipo).any() or (sec == tipo).all():
        return sec
    # 1) unir huecos cortos
    tramos = _tramos_de(sec == tipo)
    for a, b in zip(tramos, tramos[1:] + tramos[:1]):
        fin_a = (a[0] + a[1]) % n
        hueco = (b[0] - fin_a) % n
        if 0 < hueco <= n_unir and not any(bloqueo[(fin_a + j) % n] for j in range(hueco)):
            for j in range(hueco):
                sec[(fin_a + j) % n] = tipo
    # 2) alargar los cortos
    for k, m in _tramos_de(sec == tipo):
        if m >= n_min:
            continue
        extra = n_min - m
        # sitio libre a cada lado hasta la primera celda bloqueada
        libre_tras, libre_del = 0, 0
        while libre_tras < n and not bloqueo[(k - 1 - libre_tras) % n] \
                and sec[(k - 1 - libre_tras) % n] != tipo:
            libre_tras += 1
        while libre_del < n and not bloqueo[(k + m + libre_del) % n] \
                and sec[(k + m + libre_del) % n] != tipo:
            libre_del += 1
        tras = min(extra // 2, libre_tras)
        delante = min(extra - tras, libre_del)
        tras = min(extra - delante, libre_tras)
        for j in range(1, tras + 1):
            sec[(k - j) % n] = tipo
        for j in range(delante):
            sec[(k + m + j) % n] = tipo
    return sec
