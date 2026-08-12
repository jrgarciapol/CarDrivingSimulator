"""Construcción de la matriz de entrenamiento.

La decisión de diseño importante está aquí: el modelo NO se entrena con
valores absolutos de HRV, sino con desviaciones respecto a tu propia
línea base móvil.

El motivo es que un umbral absoluto de RMSSD no significa nada. El RMSSD
en reposo de una persona sana puede ser 20 ms y el de otra 90 ms, y el
de la misma persona cambia entre la mañana y la tarde, con el café, con
la digestión y con lo que durmió. Lo que sí significa algo es "tu RMSSD
ha caído dos desviaciones típicas respecto a cómo estabas hace veinte
minutos, y no te has movido".

La línea base se calcula con la MISMA media/varianza móvil exponencial
que corre en el reloj (watch/source/Hrv.mc, clase RunningStat), y se
alimenta en el mismo orden temporal. Así lo que ve el modelo entrenando
es lo mismo que verá desplegado.

Queda una diferencia conocida, y prefiero dejarla escrita a fingir que
no existe: el reloj congela la línea base cuando su propia probabilidad
supera 0,5, mientras que aquí se congela en las ventanas etiquetadas
como estrés. Durante el entrenamiento no hay ninguna probabilidad que
consultar, y usar las etiquetas es lo más parecido. El desajuste solo
aparece cuando el modelo ya está desplegado y acierta, que es poco rato
al día.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import features as feat
from . import labels as lab
from .session import Session

# Iguales a watch/source/Config.mc.
BASELINE_TAU_S = 1800.0
BASELINE_WARMUP_S = 600
BASELINE_MIN_SAMPLES = 20
BASELINE_SD_FLOOR = 0.2
MOVE_THRESHOLD_MG = 60

# Punto de partida de la línea base. Se exportan a ModelParams.MU0/SD0.
BASELINE_MU0 = {
    "mean_hr": 70.0, "sdnn": 45.0, "log_rmssd": 3.5,
    "pnn50": 0.12, "act": 30.0,
}
BASELINE_SD0 = {
    "mean_hr": 10.0, "sdnn": 20.0, "log_rmssd": 0.5,
    "pnn50": 0.10, "act": 40.0,
}

# Recorte de los valores normalizados, igual que en el reloj.
Z_CLIP = 5.0

# ¿Se normaliza contra la línea base personal o contra la fija?
# El movimiento va en absoluto: quieto es quieto para cualquiera, y no
# queremos que "moverse menos de lo habitual" cuente como algo.
USE_Z = {name: name != "act" for name in feat.LIVE_FEATURES}


class RunningStat:
    """Línea base personal: lote de arranque y después media móvil.

    Réplica de la clase del mismo nombre en watch/source/Hrv.mc.

    Empezó siendo solo una media/varianza móviles exponenciales
    inicializadas con un valor a priori, y estaba mal. El problema es la
    varianza: con una constante de tiempo de 30 minutos, una varianza
    inicial equivocada tarda más de una hora en corregirse, y mientras
    tanto todos los z-scores salen mal escalados. Medido sobre datos
    sintéticos, la separación de log_rmssd caía de AUC 0,67 en crudo a
    0,48 normalizado: la normalización borraba justo la señal que
    queremos.

    Así que los primeros BASELINE_WARMUP_S segundos se acumulan y se
    calcula media y varianza por lotes, que es una estimación honesta
    con los datos que hay. A partir de ahí sí, media móvil exponencial
    para seguir la deriva del día.
    """

    def __init__(self, mean0: float, sd0: float):
        self.mean = float(mean0)
        self.var = float(sd0) ** 2
        self._sd0 = float(sd0)
        # Suelo permanente, no solo al terminar el lote de arranque: la
        # varianza exponencial DECAE si la entrada es muy estable, y sin
        # suelo acabaría en cero. Entonces cualquier fluctuación normal
        # daría un z-score enorme y el reloj vibraría sin motivo. Es un
        # fallo silencioso y de los que solo aparecen tras un rato largo
        # sentado y tranquilo, o sea, justo en el caso de uso.
        self._var_floor = (BASELINE_SD_FLOOR * float(sd0)) ** 2
        self.age = 0.0
        self._n = 0
        self._sum = 0.0
        self._sum2 = 0.0
        self._burned = False

    def update(self, x: float, dt: float) -> None:
        self.age += dt

        if not self._burned:
            self._n += 1
            self._sum += x
            self._sum2 += x * x
            # La media provisional ya es mejor que el valor a priori; la
            # varianza con cuatro muestras no, así que esa espera.
            self.mean = self._sum / self._n
            if self.age >= BASELINE_WARMUP_S and self._n >= BASELINE_MIN_SAMPLES:
                v = self._sum2 / self._n - self.mean * self.mean
                self.var = max(v, self._var_floor)
                self._burned = True
            return

        alpha = min(dt / BASELINE_TAU_S, 1.0)
        d = x - self.mean
        self.mean += alpha * d
        self.var += alpha * (d * d - self.var)

    @property
    def ready(self) -> bool:
        return self._burned

    def z(self, x: float) -> float:
        sd = math.sqrt(max(self.var, self._var_floor))
        if sd < 1e-9:
            return 0.0
        return max(-Z_CLIP, min(Z_CLIP, (x - self.mean) / sd))


@dataclass
class Dataset:
    X: list[list[float]] = field(default_factory=list)
    y: list[int] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    levels: list[int] = field(default_factory=list)
    times: list[float] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    feature_names: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.y)

    def counts(self) -> dict:
        return {
            "n": len(self.y),
            "pos": sum(self.y),
            "neg": len(self.y) - sum(self.y),
            "dias": len(set(self.groups)),
        }


def z_feature_names() -> list[str]:
    return [("z_" + n) if USE_Z[n] else n for n in feat.LIVE_FEATURES]


def build(sessions: list[Session], win_s: float = 60.0,
          hop_s: float = 15.0, warmup: bool = True) -> Dataset:
    """Monta la matriz de entrenamiento a partir de varias sesiones.

    Cada sesión arranca con su propia línea base: no tendría sentido
    arrastrar la de ayer a la de hoy, y además así el modelo aprende a
    funcionar desde el arranque de una sesión, que es como se va a usar.
    """
    ds = Dataset(feature_names=z_feature_names())

    for session in sessions:
        day = session.day()
        stats = {n: RunningStat(BASELINE_MU0[n], BASELINE_SD0[n])
                 for n in feat.LIVE_FEATURES}

        windows = list(session.windows(win_s=win_s, hop_s=hop_s))
        labeled = lab.label_windows(session, windows)

        prev_t = None
        for item in labeled:
            w = item.window
            td = feat.time_domain(w.rr)
            if td is None:
                continue                      # ventana sin garantías
            mv = feat.movement(w.samples)

            raw = {
                "mean_hr": td["mean_hr"],
                "sdnn": td["sdnn"],
                "log_rmssd": td["log_rmssd"],
                "pnn50": td["pnn50"],
                "act": mv["act"],
            }

            row = []
            ready = True
            for name in feat.LIVE_FEATURES:
                if USE_Z[name]:
                    row.append(stats[name].z(raw[name]))
                    ready = ready and stats[name].ready
                else:
                    v = (raw[name] - BASELINE_MU0[name]) / BASELINE_SD0[name]
                    row.append(max(-Z_CLIP, min(Z_CLIP, v)))

            # Actualización de la línea base. Va DESPUÉS de calcular la
            # fila: la ventana actual no debe influir en su propia
            # normalización.
            dt = hop_s if prev_t is None else max(w.t1 - prev_t, 0.0)
            prev_t = w.t1
            quiet = mv["act"] < MOVE_THRESHOLD_MG
            if quiet and item.label != 1:
                for name in feat.LIVE_FEATURES:
                    stats[name].update(raw[name], dt)

            if item.label is None:
                continue
            if warmup and not ready:
                # Los primeros minutos la línea base aún no vale: sus
                # z-scores son ruido contra unos valores por defecto.
                continue

            ds.X.append(row)
            ds.y.append(item.label)
            ds.groups.append(day)
            ds.weights.append(item.weight)
            ds.levels.append(item.level)
            ds.times.append(w.t0)
            ds.reasons.append(item.reason)

    return ds


def explore_table(session: Session, win_s: float = 300.0,
                  hop_s: float = 60.0) -> list[dict]:
    """Tabla con TODAS las features, también las que no corren en el reloj.

    Para mirar los datos, no para entrenar el modelo desplegable. La
    ventana por defecto es de 5 min porque las métricas frecuenciales no
    tienen sentido por debajo de 2.
    """
    rows = []
    windows = list(session.windows(win_s=win_s, hop_s=hop_s))
    labeled = lab.label_windows(session, windows)
    for item in labeled:
        w = item.window
        td = feat.time_domain(w.rr)
        if td is None:
            continue
        row = dict(td)
        row.update(feat.movement(w.samples))
        row.update(feat.poincare(w.rr))
        row.update(feat.frequency_domain(w.rr))
        row["t"] = w.t0
        row["label"] = item.label
        row["level"] = item.level
        row["reason"] = item.reason
        rows.append(row)
    return rows
