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
        self._precompute_vertical()
        self._precompute_racing_line()

    def _precompute_racing_line(self):
        """Trazada ideal simplificada: desplazamiento lateral hacia el
        interior de cada curva (suavizado para que la aproximación sea
        gradual) y velocidad máxima de paso según el agarre disponible."""
        n = len(self.segments)
        ks = [seg.kappa for seg in self.segments]

        def smooth(vals, half_win):
            out = []
            for i in range(n):
                acc = 0.0
                for j in range(-half_win, half_win + 1):
                    acc += vals[(i + j) % n]
                out.append(acc / (2 * half_win + 1))
            return out

        k_offset = smooth(ks, 25)   # ~100 m: aproximación gradual al vértice
        k_speed = smooth(ks, 8)     # ~32 m: velocidad de paso de la curva

        max_off = cfg.ROAD_HALF_WIDTH - 1.3
        ay_max = cfg.TIRE_MU * 9.81 * 0.92   # apurar al 92 % del agarre
        self.line_n = []
        self.line_v = []
        for i in range(n):
            off = max(-max_off, min(max_off, k_offset[i] * 150.0))
            self.line_n.append(off)
            k = abs(k_speed[i])
            v = math.sqrt(ay_max / k) if k > 1e-5 else 70.0
            self.line_v.append(min(70.0, v))

        # velocidad ADMISIBLE en cada punto teniendo en cuenta la distancia
        # de frenada hasta la curva siguiente (inducción hacia atrás): si
        # vas más rápido que esto, ya no llegas a frenar -> línea roja
        a_brake = 8.5
        L = cfg.SEGMENT_LENGTH
        self.line_v_allowed = list(self.line_v)
        for _ in range(2):  # dos pasadas para cerrar el circuito circular
            for i in range(n - 1, -1, -1):
                nxt = self.line_v_allowed[(i + 1) % n]
                limit = math.sqrt(nxt * nxt + 2.0 * a_brake * L)
                self.line_v_allowed[i] = min(self.line_v_allowed[i], limit)

    def _precompute_vertical(self):
        """Pendiente (dy/ds) y curvatura vertical (d²y/ds²) suavizadas,
        para que la gravedad y las rasantes actúen sobre la física."""
        n = len(self.segments)
        L = cfg.SEGMENT_LENGTH
        ys = [seg.y for seg in self.segments]
        self._grade = []
        self._vcurv = []
        span = 3  # suavizado sobre ±3 segmentos
        for i in range(n):
            y_prev = ys[(i - span) % n]
            y_next = ys[(i + span) % n]
            y_here = ys[i]
            self._grade.append((y_next - y_prev) / (2 * span * L))
            self._vcurv.append((y_next - 2 * y_here + y_prev) / (span * L) ** 2)

    def segment_at(self, s: float) -> Segment:
        i = int(s / cfg.SEGMENT_LENGTH) % len(self.segments)
        return self.segments[i]

    def _index_at(self, s: float) -> int:
        return int(s / cfg.SEGMENT_LENGTH) % len(self.segments)

    def kappa_at(self, s: float) -> float:
        return self.segment_at(s).kappa

    def grade_at(self, s: float) -> float:
        return self._grade[self._index_at(s)]

    def vcurv_at(self, s: float) -> float:
        return self._vcurv[self._index_at(s)]

    def bump_at(self, s: float, n: float, surface: str) -> float:
        """Altura del microrrelieve bajo una rueda (m). Determinista en
        función de la posición: cada rueda ve su propio bache."""
        if surface == "kerb":
            # piano corrugado: dientes de ~40 cm
            return 0.028 * max(0.0, math.sin(s * (2 * math.pi / 0.4)))
        if surface == "grass":
            return 0.020 * math.sin(s * 3.7) + 0.016 * math.sin(s * 9.3 + n * 2.1)
        # asfalto: rugosidad leve
        return 0.005 * math.sin(s * 2.9) + 0.003 * math.sin(s * 7.1 + n * 0.8)

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
