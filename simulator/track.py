"""Definición del circuito.

El circuito se define por tramos (longitud, radio, colina) y se discretiza en
segmentos cortos para el renderizado pseudo-3D y para consultar la curvatura
y el peralte en la posición del coche.
"""

import math

from . import config as cfg


class Segment:
    __slots__ = ("index", "kappa", "y", "kerb")

    def __init__(self, index, kappa, y, kerb):
        self.index = index
        self.kappa = kappa    # curvatura 1/m (positiva = curva a la derecha)
        self.y = y            # altura del terreno (m)
        self.kerb = kerb      # True si el tramo tiene pianos


def _sections():
    """Tramos del circuito: (longitud_m, radio_m, desnivel_m).

    radio > 0 curva a la derecha, < 0 a la izquierda, 0 recta.
    El desnivel se aplica como rampa suave a lo largo del tramo.
    """
    return [
        (400, 0, 0),        # recta de meta
        (250, 220, 0),      # curva rápida derecha
        (150, 0, 4),        # subida corta
        (200, -140, 6),     # izquierda media en subida
        (180, 0, 0),        # recta corta
        (120, -60, -3),     # izquierda cerrada bajando
        (140, 60, -5),      # chicane: derecha cerrada
        (300, 0, -2),       # recta trasera
        (90, -35, 0),       # horquilla izquierda
        (260, 0, 8),        # recta en subida con rasante
        (220, 180, -8),     # derecha rápida bajando
        (160, 0, 0),        # recta
        (110, 85, 0),       # derecha media
        (150, -120, 0),     # izquierda media que enlaza con meta
        (120, 0, 0),        # llegada
    ]


def build():
    segments = []
    y = 0.0
    idx = 0
    for length, radius, climb in _sections():
        n_segs = max(1, int(length / cfg.SEGMENT_LENGTH))
        kappa = (1.0 / radius) if radius else 0.0
        kerb = radius != 0
        for i in range(n_segs):
            # entrada/salida de curva suavizadas
            t = i / n_segs
            ease = min(1.0, min(t, 1.0 - t) * 6.0 + 0.15) if kerb else 0.0
            k = kappa * (ease if kerb else 0.0)
            y += climb / n_segs
            # ondulación ligera del terreno para dar vida a la carretera
            wave = 0.35 * math.sin(idx * 0.05)
            segments.append(Segment(idx, k, y + wave, kerb))
            idx += 1
    return segments


class Track:
    def __init__(self):
        self.segments = build()
        self.length = len(self.segments) * cfg.SEGMENT_LENGTH

    def segment_at(self, s: float) -> Segment:
        i = int(s / cfg.SEGMENT_LENGTH) % len(self.segments)
        return self.segments[i]

    def kappa_at(self, s: float) -> float:
        return self.segment_at(s).kappa

    def surface_at(self, n: float, s: float):
        """Devuelve (superficie, mu) según la posición lateral.

        superficie: 'road' | 'kerb' | 'grass'
        """
        an = abs(n)
        if an <= cfg.ROAD_HALF_WIDTH:
            return "road", cfg.TIRE_MU
        if an <= cfg.ROAD_HALF_WIDTH + cfg.KERB_WIDTH and self.segment_at(s).kerb:
            return "kerb", cfg.TIRE_MU * 0.92
        return "grass", cfg.TIRE_MU_GRASS
