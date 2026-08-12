"""Limpieza de artefactos en series de intervalos R-R.

Un latido mal detectado no es "ruido" que se promedie y desaparezca: es
veneno para el RMSSD. El RMSSD se calcula sobre diferencias entre latidos
consecutivos, así que un latido perdido convierte dos intervalos de 900 ms
en uno de 1800 ms y mete una diferencia de 900 ms donde no la había. Un
solo artefacto en una ventana de 60 s puede duplicar el RMSSD, y el modelo
lo leerá como "relajadísimo" justo cuando probablemente pasaba lo
contrario (el movimiento que despegó el electrodo).

De ahí las tres reglas, en este orden:

  1. Rango fisiológico: fuera de [300, 2000] ms no es un latido.
  2. Filtro de Malik: un intervalo que difiere más de un 20 % del último
     válido no es un latido, es un artefacto.
  3. Adyacencia: si se descarta un latido, la diferencia entre el
     anterior y el siguiente NO es una diferencia entre latidos
     consecutivos y no entra en el RMSSD. Este tercer punto es el que se
     olvida casi siempre y el que más daño hace.

Estas mismas reglas están implementadas en watch/source/Hrv.mc. Si tocas
una constante aquí, tócala allí (tests/test_parity.py lo comprueba).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Rango fisiológicamente posible, en ms (200 ppm .. 30 ppm).
RR_MIN_MS = 300
RR_MAX_MS = 2000

# Filtro de Malik: descarte por salto relativo al último latido válido.
MALIK_PCT = 0.20


@dataclass
class CleanSeries:
    """Resultado de limpiar una serie de intervalos R-R."""

    nn: list[float] = field(default_factory=list)
    """Intervalos aceptados, en ms."""

    diffs: list[float] = field(default_factory=list)
    """Diferencias entre latidos REALMENTE consecutivos, en ms."""

    n_total: int = 0
    """Latidos examinados."""

    @property
    def n_valid(self) -> int:
        return len(self.nn)

    @property
    def artifact_fraction(self) -> float:
        if self.n_total == 0:
            return 1.0
        return (self.n_total - self.n_valid) / self.n_total


def clean(rr_ms) -> CleanSeries:
    """Aplica las tres reglas a una serie de intervalos R-R ordenada.

    Recibe milisegundos y devuelve un CleanSeries. El orden importa: la
    serie tiene que venir en orden temporal.
    """
    out = CleanSeries()
    prev_valid: float | None = None
    prev_adjacent = False

    for raw in rr_ms:
        if raw is None:
            continue
        rr = float(raw)
        out.n_total += 1

        ok = RR_MIN_MS <= rr <= RR_MAX_MS
        if ok and prev_valid is not None:
            if abs(rr - prev_valid) > MALIK_PCT * prev_valid:
                ok = False

        if not ok:
            # Se rompe la cadena de adyacencia, pero prev_valid NO se
            # actualiza: el siguiente latido se compara con el último
            # bueno, no con el artefacto.
            prev_adjacent = False
            continue

        out.nn.append(rr)
        if prev_valid is not None and prev_adjacent:
            out.diffs.append(rr - prev_valid)
        prev_valid = rr
        prev_adjacent = True

    return out
