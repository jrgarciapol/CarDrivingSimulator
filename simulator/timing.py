"""Cronometraje de vueltas.

Vive aparte del bucle principal para poder probarlo: la lógica de "¿esto
ha sido una vuelta de verdad?" es sutil y ya dio un fallo serio.

REGLAS. Una vuelta cuenta solo si:

  1. Se cruza la línea de meta **hacia delante** (avanzando por el trazado,
     no retrocediendo).
  2. Se ha recorrido hacia delante casi todo el circuito desde el cruce
     anterior (LAP_MIN_FRACTION).
  3. La vuelta estaba marcada como válida: no es la primera (parcial, desde
     donde se arrancó hasta la meta) ni se ha recolocado el coche.

El fallo que motivó esto: la condición original era simplemente

    (s_anterior % L) > (s_actual % L)

que detecta el salto del módulo al cruzar la meta... pero también se cumple
en CADA paso de física si se recorre el circuito en sentido contrario,
porque entonces s decrece siempre. El resultado era una "vuelta" cada 2 ms
y récords guardados de centésimas de segundo.
"""

import math

from . import config as cfg


class LapTimer:
    """Estado del cronómetro de una sesión."""

    def __init__(self, length: float, best: float = None):
        self.length = max(1.0, length)
        self.best = best
        self.lap_time = 0.0
        self.lap_count = 1
        self.valid = False        # la primera vuelta es parcial: no cuenta
        self.wrong_way = False
        self.last_was_best = False
        self._dist = 0.0          # metros recorridos HACIA DELANTE

    # ------------------------------------------------------------------
    def invalidate(self):
        """Anula la vuelta en curso (recolocar el coche, salirse...)."""
        self.valid = False
        self._dist = 0.0

    def _update_direction(self, vx: float, psi: float):
        """psi es el rumbo del coche respecto al eje de la carretera; pasado
        el través va del revés. Con histéresis para no parpadear en un
        trompo ni con el coche casi parado."""
        psi_n = abs(math.atan2(math.sin(psi), math.cos(psi)))
        umbral = math.radians(getattr(cfg, "WRONG_WAY_DEG", 105.0))
        if abs(vx) > 3.0 and psi_n > umbral:
            self.wrong_way = True
        elif psi_n < umbral - math.radians(30.0) or abs(vx) < 1.0:
            self.wrong_way = False

    def update(self, dt: float, prev_s: float, s: float, vx: float,
               psi: float):
        """Avanza el cronómetro un paso de física.

        Devuelve el tiempo de la vuelta recién COMPLETADA Y VALIDA, o None.
        El llamante decide qué hacer con él (récord, fantasma...)."""
        self.lap_time += dt
        self._update_direction(vx, psi)

        # distancia recorrida hacia delante (restando lo que se retroceda)
        ds = s - prev_s
        if abs(ds) < self.length * 0.5:      # descarta el salto del módulo
            self._dist += ds

        # CRUCE DE META, solo en el sentido bueno
        cruza = (ds > 0.0 and vx > 1.0
                 and prev_s % self.length > s % self.length)
        if not cruza:
            return None

        frac = getattr(cfg, "LAP_MIN_FRACTION", 0.9)
        completa = self._dist > self.length * frac
        tiempo = self.lap_time if (self.valid and completa) else None
        self.last_was_best = False
        if tiempo is not None and (self.best is None or tiempo < self.best):
            self.best = tiempo
            self.last_was_best = True

        # a partir de aquí se cronometra de verdad
        self.valid = True
        self._dist = 0.0
        self.lap_time = 0.0
        self.lap_count += 1
        return tiempo

    # ------------------------------------------------------------------
    @property
    def progress(self) -> float:
        """Fracción del circuito recorrida en la vuelta actual (0..1+)."""
        return self._dist / self.length
