"""Definición del circuito.

Dos fuentes posibles:
  - El circuito de pruebas integrado, definido por tramos (longitud,
    radio, colina) en _sections().
  - Un circuito real importado con tools/import_track.py (CSV con
    curvatura/elevación/piano por segmento de 4 m), seleccionado con
    TRACK_FILE en config.py.
"""

import math
import os

from . import config as cfg


class Segment:
    __slots__ = ("index", "kappa", "y", "kerb", "bank", "half_w")

    def __init__(self, index, kappa, y, kerb, bank=0.0, half_w=None):
        self.index = index
        self.kappa = kappa    # curvatura 1/m (positiva = curva a la derecha)
        self.y = y            # altura del terreno (m)
        self.kerb = kerb      # True si el tramo tiene pianos
        self.bank = bank      # peralte (rad): >0 = borde izquierdo elevado
                              # (peralte correcto de una curva a la derecha)
        # semiancho de asfalto (m) del tramo; None -> el fijo de config
        self.half_w = cfg.ROAD_HALF_WIDTH if half_w is None else half_w


def _sections():
    """Tramos del circuito: (longitud_m, radio_m, desnivel_m[, peralte_deg]).

    radio > 0 curva a la derecha, < 0 a la izquierda, 0 recta.
    El desnivel se aplica como rampa suave a lo largo del tramo.
    peralte_deg (opcional) es la inclinación transversal hacia el
    interior de la curva, siempre positivo: el signo se toma del radio.
    """
    return [
        (400, 0, 0),        # recta de meta
        (250, 220, 0, 8),   # curva rápida derecha PERALTADA
        (150, 0, 4),        # subida corta
        (200, -140, 6),     # izquierda media en subida
        (180, 0, 0),        # recta corta
        (120, -60, -3),     # izquierda cerrada bajando
        (140, 60, -5),      # chicane: derecha cerrada
        (300, 0, -2),       # recta trasera
        (90, -35, 0),       # horquilla izquierda
        (260, 0, 8),        # recta en subida con rasante
        (220, 180, -8, 10), # derecha rápida bajando, PERALTADA
        (160, 0, 0),        # recta
        (110, 85, 0),       # derecha media
        (150, -120, 0),     # izquierda media que enlaza con meta
        (120, 0, 0),        # llegada
    ]


def build():
    segments = []
    y = 0.0
    idx = 0
    for sec in _sections():
        length, radius, climb = sec[0], sec[1], sec[2]
        bank_deg = sec[3] if len(sec) > 3 else 0.0
        n_segs = max(1, int(length / cfg.SEGMENT_LENGTH))
        kappa = (1.0 / radius) if radius else 0.0
        kerb = radius != 0
        bank_full = math.radians(bank_deg) * (1.0 if radius > 0 else -1.0) \
            if radius else 0.0
        for i in range(n_segs):
            # entrada/salida de curva suavizadas (curvatura Y peralte)
            t = i / n_segs
            ease = min(1.0, min(t, 1.0 - t) * 6.0 + 0.15) if kerb else 0.0
            k = kappa * (ease if kerb else 0.0)
            y += climb / n_segs
            # ondulación ligera del terreno para dar vida a la carretera
            wave = 0.35 * math.sin(idx * 0.05)
            segments.append(Segment(idx, k, y + wave, kerb,
                                    bank_full * ease))
            idx += 1
    return segments


def build_from_file(path):
    """Carga un circuito importado. Columnas por segmento de 4 m:
    kappa, elevación, piano[, peralte_rad con signo[, semiancho_m]]."""
    segments = []
    idx = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cols = line.split(",")
            bank = float(cols[3]) if len(cols) > 3 else 0.0
            half_w = float(cols[4]) if len(cols) > 4 and cols[4].strip() \
                else None
            segments.append(Segment(idx, float(cols[0]), float(cols[1]),
                                    cols[2].strip() == "1", bank, half_w))
            idx += 1
    if len(segments) < 10:
        raise ValueError(f"circuito invalido: {path}")
    return segments


class Track:
    def __init__(self):
        self.name = "CIRCUITO DE PRUEBAS"
        if cfg.TRACK_FILE:
            path = os.path.join(os.path.dirname(__file__), cfg.TRACK_FILE)
            self.segments = build_from_file(path)
            self.name = os.path.splitext(os.path.basename(path))[0].upper()
        else:
            self.segments = build()
        self.length = len(self.segments) * cfg.SEGMENT_LENGTH
        # semiancho representativo (mediana) para el render; la conducción usa
        # el de cada tramo (half_at)
        ws = sorted(s.half_w for s in self.segments)
        self.half_w = ws[len(ws) // 2]
        self._precompute_vertical()
        self._precompute_racing_line()

    def half_at(self, s: float) -> float:
        """Semiancho de asfalto (m) del tramo en la estación s."""
        return self.segment_at(s).half_w

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
        k_speed = smooth(ks, 5)     # ~20 m: velocidad de paso de la curva
                                    # (ventana corta: no diluye horquillas)

        max_off = cfg.ROAD_HALF_WIDTH - 1.3
        ay_max = cfg.TIRE_MU * 9.81 * 0.92   # apurar al 92 % del agarre
        self.line_n = []
        self.line_v = []
        for i in range(n):
            off = max(-max_off, min(max_off, k_offset[i] * 150.0))
            self.line_n.append(off)
            k = abs(k_speed[i])
            # el peralte bien orientado permite pasar más rápido: la
            # gravedad aporta parte de la aceleración centrípeta (con un
            # margen del 30 %, porque la ayuda real depende del coche)
            bank = self.segments[i].bank
            ay_i = ay_max
            if k > 1e-5 and abs(bank) > 1e-4:
                ay_i = max(ay_max * 0.3,
                           ay_max + 0.7 * 9.81 * math.tan(bank)
                           * (1.0 if k_speed[i] > 0 else -1.0))
            v = math.sqrt(ay_i / k) if k > 1e-5 else 70.0
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
                # la pendiente cambia la frenada: cuesta abajo la gravedad
                # resta capacidad de deceleración, cuesta arriba la suma
                a_eff = max(3.0, a_brake + 9.81 * self._grade[i])
                limit = math.sqrt(nxt * nxt + 2.0 * a_eff * L)
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

    def bank_at(self, s: float) -> float:
        """Peralte (rad) del tramo: >0 = borde izquierdo elevado."""
        return self.segment_at(s).bank

    def map_points(self):
        """Polilínea del circuito en planta, normalizada a [0..1]x[0..1]
        (manteniendo la proporción), para el minimapa. Se integra la
        curvatura y se reparte el error de cierre para que el plano
        quede perfectamente cerrado."""
        if hasattr(self, "_map_pts"):
            return self._map_pts
        n = len(self.segments)
        L = cfg.SEGMENT_LENGTH
        xs, ys = [0.0], [0.0]
        h = 0.0
        for seg in self.segments:
            xs.append(xs[-1] + math.sin(h) * L)
            ys.append(ys[-1] + math.cos(h) * L)
            h += seg.kappa * L
        # repartir el error de cierre linealmente
        ex, ey = xs[-1], ys[-1]
        pts = []
        for i in range(n):
            t = i / n
            pts.append((xs[i] - ex * t, ys[i] - ey * t))
        # normalizar manteniendo la proporción
        min_x = min(p[0] for p in pts)
        max_x = max(p[0] for p in pts)
        min_y = min(p[1] for p in pts)
        max_y = max(p[1] for p in pts)
        span = max(max_x - min_x, max_y - min_y, 1e-6)
        self._map_pts = [((p[0] - min_x) / span, (p[1] - min_y) / span)
                         for p in pts]
        self._map_aspect = ((max_x - min_x) / span, (max_y - min_y) / span)
        return self._map_pts

    def forward_plan(self, s0: float, largo: float = 1000.0,
                     paso: float = 6.0):
        """Planta del tramo que VIENE, en coordenadas locales del coche.

        Integra la curvatura hacia delante desde s0. El coche queda en el
        origen mirando hacia +y, así que el resultado se puede pintar tal
        cual en pantalla sin más que escalar: es un plano egocéntrico, como
        las notas de un copiloto.

        Devuelve [(x, y, kappa, s)] en metros. Convenio de curvatura:
        kappa > 0 = curva a la DERECHA, que aquí sale a +x.
        """
        pts = []
        x = y = h = 0.0
        s = s0
        n = max(1, int(largo / paso))
        for _ in range(n):
            k = self.kappa_at(s)
            pts.append((x, y, k, s))
            x += math.sin(h) * paso
            y += math.cos(h) * paso
            h += k * paso
            s += paso
        return pts

    def corners_ahead(self, s0: float, largo: float = 1000.0,
                      paso: float = 6.0, r_max: float = 600.0,
                      max_n: int = 6, suave_m: float = 18.0):
        """Curvas del tramo que viene, de la más cerrada a la más abierta.

        Una curva es un tramo CONTINUO con curvatura por encima del umbral
        (radio < r_max); su radio característico es el del punto de máxima
        curvatura, que es el ápice. Sin agrupar por tramos continuos, cada
        segmento de 4 m contaría como una curva distinta y saldrían decenas
        de etiquetas encima de la misma curva.

        Devuelve [(s_apice, radio, signo)] ordenado por estación, con signo
        +1 a derechas y −1 a izquierdas.
        """
        n = max(1, int(largo / paso))
        ks = [self.kappa_at(s0 + i * paso) for i in range(n)]
        # SUAVIZADO sobre una longitud FISICA (no un número de muestras):
        # los trazados importados vienen de un eje medido por GPS y su
        # curvatura tiene picos de ruido. Sin suavizar, un pico aislado se
        # confunde con una curva cerradísima: en Silverstone salía un radio
        # de 18 m donde no hay ninguna curva de menos de 25.
        # Con +-18 m los radios detectados coinciden con los reales del
        # circuito (24, 29, 30, 37, 44, 48 m frente a The Loop 25, Village
        # 30, Vale 40, Luffield 50).
        win = max(1, int(suave_m / max(1e-6, paso)))
        sm = []
        for i in range(n):
            a = max(0, i - win)
            b = min(n, i + win + 1)
            sm.append(sum(ks[a:b]) / (b - a))
        umbral = 1.0 / max(1.0, r_max)
        curvas = []
        i = 0
        while i < n:
            if abs(sm[i]) < umbral:
                i += 1
                continue
            j = i
            mejor = i
            signo = 1.0 if sm[i] > 0 else -1.0
            # el tramo dura mientras siga curvando EN EL MISMO SENTIDO
            while j < n and abs(sm[j]) >= umbral and \
                    (1.0 if sm[j] > 0 else -1.0) == signo:
                if abs(sm[j]) > abs(sm[mejor]):
                    mejor = j
                j += 1
            curvas.append((s0 + mejor * paso, 1.0 / abs(sm[mejor]), signo))
            i = j
        # se quedan las MAS CERRADAS (las que obligan a frenar), y luego se
        # devuelven en orden de recorrido
        curvas.sort(key=lambda c: c[1])
        return sorted(curvas[:max_n], key=lambda c: c[0])

    def heading_at(self, s: float) -> float:
        """Rumbo absoluto de la carretera (rad) integrado desde la meta;
        para el parallax del fondo."""
        if not hasattr(self, "_heading"):
            acc = 0.0
            self._heading = []
            for seg in self.segments:
                self._heading.append(acc)
                acc += seg.kappa * cfg.SEGMENT_LENGTH
        return self._heading[self._index_at(s)]

    def grade_at(self, s: float) -> float:
        return self._grade[self._index_at(s)]

    def vcurv_at(self, s: float) -> float:
        return self._vcurv[self._index_at(s)]

    def damage_at(self, s: float) -> float:
        """Cuánto está DAÑADO el asfalto en este tramo: 0 = firme sano,
        1 = parche muy roto. Determinista y de variación lenta con la
        posición (los baches malos vienen por zonas, no aislados), para que
        cada circuito tenga siempre sus mismos tramos rotos."""
        # ruido lento (dos senos incomensurables) umbralizado: la mayor parte
        # del firme está sano y de vez en cuando aparece una zona rota
        z = (math.sin(s * 0.0131) * math.sin(s * 0.0041 + 1.7)
             + 0.4 * math.sin(s * 0.0233 + 0.6))
        return max(0.0, (z - 0.30)) / 0.70

    def bump_at(self, s: float, n: float, surface: str) -> float:
        """Altura del microrrelieve bajo una rueda (m). Determinista en
        función de la posición: cada rueda ve su propio bache."""
        rough = cfg.ROAD_ROUGHNESS
        if surface == "kerb":
            # piano corrugado: dientes de ~40 cm
            return 0.028 * max(0.0, math.sin(s * (2 * math.pi / 0.4)))
        if surface == "grass":
            # hierba: irregular, con montículos y alta frecuencia -> zarandea
            base = (0.020 * math.sin(s * 3.7) + 0.016 * math.sin(s * 9.3 + n * 2.1)
                    + 0.012 * math.sin(s * 23.0 + n * 5.0))
            return base * rough
        # asfalto: rugosidad leve de base + ZONAS DAÑADAS (firme roto) que
        # añaden baches más grandes y de más frecuencia por tramos
        smooth = 0.004 * math.sin(s * 2.9) + 0.002 * math.sin(s * 7.1 + n * 0.8)
        dmg = self.damage_at(s)
        broken = dmg * (0.012 * math.sin(s * 17.0)
                        + 0.009 * math.sin(s * 41.0 + n * 3.0))
        return (smooth + broken) * rough

    def surface_at(self, n: float, s: float):
        """Devuelve (superficie, mu) según la posición lateral.

        superficie: 'road' | 'kerb' | 'grass'
        """
        an = abs(n)
        hw = self.segment_at(s).half_w
        if an <= hw:
            return "road", cfg.TIRE_MU
        if an <= hw + cfg.KERB_WIDTH and self.segment_at(s).kerb:
            return "kerb", cfg.TIRE_MU * 0.92
        return "grass", cfg.TIRE_MU_GRASS
