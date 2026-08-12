"""Extracción de features HRV sobre ventanas de tiempo.

Dos grupos bien separados, y la separación importa:

  LIVE_FEATURES  Las que el reloj sabe calcular en tiempo real. Son las
                 que puede usar el modelo que se despliega. El orden de
                 esta lista es el mismo que el de `module Features` en
                 watch/source/Hrv.mc y el mismo que el de ModelParams.W.

  OFFLINE_*      Las que solo se calculan en el PC (dominio frecuencial,
                 Poincaré). Sirven para ENTENDER tus datos y para saber
                 si merece la pena portarlas, pero no puedes meterlas en
                 el modelo del reloj sin implementarlas antes en Monkey C.

Sobre el dominio frecuencial, una advertencia que se repite poco: el
cociente LF/HF NO mide "balance simpático-vagal". Esa interpretación
lleva desacreditada desde hace años (la LF no es un marcador limpio de
actividad simpática; depende sobre todo de la respiración y del reflejo
barorreceptor). Lo calculamos porque a veces predice, no porque
signifique lo que se suele decir que significa. Si acaba entrando en el
modelo con un peso alto, sospecha de la respiración antes que del sistema
nervioso simpático.

Y sobre las ventanas: el RMSSD sobre 60 s ya está bien correlacionado con
el de 5 min, que es el estándar; por debajo de ~30 s deja de estarlo. Las
métricas frecuenciales necesitan más: con menos de 2 min la banda LF
(0,04-0,15 Hz) no tiene ni dos ciclos completos y el número que sale es
decorativo.
"""

from __future__ import annotations

import math

from . import rr as rrmod

# Orden canónico. NO reordenar sin regenerar ModelParams.mc.
#
# Ojo con la tentación de añadir aquí las variantes de lo mismo: mean_nn
# es 60000/mean_hr y rmssd es exp(log_rmssd). Meter las dos versiones no
# aporta información y destroza la interpretabilidad de los coeficientes,
# que es media razón de haber elegido una regresión logística.
LIVE_FEATURES = [
    "mean_hr",    # ppm
    "sdnn",       # ms
    "log_rmssd",  # ln(ms)
    "pnn50",      # 0..1
    "act",        # mg, índice de movimiento
]

OFFLINE_FEATURES = [
    "sd1", "sd2", "sd_ratio",
    "lf", "hf", "lf_hf", "total_power",
    "posture_change",
]

# Mínimos para dar por buena una ventana (iguales a Config.mc).
MIN_BEATS = 30
MAX_ARTIFACT = 0.15


def time_domain(rr_ms) -> dict | None:
    """Métricas de dominio temporal de una ventana de intervalos R-R.

    Devuelve None si la ventana no da garantías: pocos latidos válidos o
    demasiados artefactos. Devolver None es deliberado — un RMSSD
    calculado sobre 8 latidos con tres artefactos es peor que no tener
    dato, porque el modelo no puede distinguirlo de uno bueno.

    Réplica exacta de HrvWindow.features() en watch/source/Hrv.mc.
    """
    c = rrmod.clean(rr_ms)
    if c.n_valid < MIN_BEATS or len(c.diffs) < 2:
        return None
    if c.artifact_fraction > MAX_ARTIFACT:
        return None

    n = c.n_valid
    mean_nn = sum(c.nn) / n
    # Varianza poblacional (dividiendo por n, no por n-1) para que
    # coincida exactamente con el cálculo incremental del reloj. Con
    # n >= 30 la diferencia con la definición clásica de SDNN es < 2 %.
    var = sum(v * v for v in c.nn) / n - mean_nn * mean_nn
    var = max(var, 0.0)
    sdnn = math.sqrt(var)

    rmssd = math.sqrt(sum(d * d for d in c.diffs) / len(c.diffs))
    pnn50 = sum(1 for d in c.diffs if abs(d) > 50.0) / len(c.diffs)

    return {
        "mean_nn": mean_nn,
        "mean_hr": 60000.0 / mean_nn,
        "sdnn": sdnn,
        "rmssd": rmssd,
        "pnn50": pnn50,
        "log_rmssd": math.log(max(rmssd, 1.0)),
        "n_beats": float(n),
        "artifact_fraction": c.artifact_fraction,
    }


def poincare(rr_ms) -> dict:
    """SD1 / SD2 del diagrama de Poincaré.

    SD1 es la dispersión perpendicular a la identidad (variabilidad
    latido a latido, equivale a RMSSD/raíz de 2) y SD2 la dispersión a lo
    largo (variabilidad a largo plazo). El cociente SD2/SD1 suele subir
    con el estrés, y tiene la ventaja sobre LF/HF de no depender de una
    estimación espectral sobre una señal irregularmente muestreada.
    """
    c = rrmod.clean(rr_ms)
    if len(c.diffs) < 2:
        return {"sd1": float("nan"), "sd2": float("nan"), "sd_ratio": float("nan")}

    sdsd = _std(c.diffs)
    sd1 = math.sqrt(0.5) * sdsd
    sdnn = _std(c.nn)
    sd2sq = 2.0 * sdnn * sdnn - sd1 * sd1
    sd2 = math.sqrt(max(sd2sq, 0.0))
    return {
        "sd1": sd1,
        "sd2": sd2,
        "sd_ratio": (sd2 / sd1) if sd1 > 1e-9 else float("nan"),
    }


def frequency_domain(rr_ms, lf=(0.04, 0.15), hf=(0.15, 0.40)) -> dict:
    """Potencia en las bandas LF y HF por Lomb-Scargle.

    Se usa Lomb-Scargle en vez del clásico "interpolar a 4 Hz y hacer una
    FFT" porque la serie de intervalos R-R está muestreada de forma
    irregular por definición (un latido no llega cada X ms fijos), y la
    interpolación previa introduce potencia de baja frecuencia que no
    estaba en la señal. Lomb-Scargle trabaja directamente sobre muestras
    irregulares.

    Las unidades son ms^2 aproximadas: la normalización del periodograma
    de Lomb-Scargle no es la de una PSD calibrada. Como todas las
    features acaban normalizadas contra tu línea base, la escala absoluta
    da igual; lo que no daría igual es comparar estos valores con los de
    un artículo científico, así que no lo hagas.

    Devuelve NaN si no hay scipy o la ventana es demasiado corta.
    """
    nan = {"lf": float("nan"), "hf": float("nan"),
           "lf_hf": float("nan"), "total_power": float("nan")}
    try:
        import numpy as np
        from scipy.signal import lombscargle
    except ImportError:
        return nan

    c = rrmod.clean(rr_ms)
    if c.n_valid < 40:
        return nan

    nn = np.asarray(c.nn, dtype=float)
    t = np.cumsum(nn) / 1000.0          # tiempo del latido, en segundos
    t -= t[0]
    if t[-1] < 120.0:
        # Menos de dos minutos: la banda LF no tiene ni dos ciclos.
        return nan

    y = nn - nn.mean()
    freqs = np.linspace(lf[0], hf[1], 512)
    power = lombscargle(t, y, 2.0 * np.pi * freqs, normalize=False)
    power = power * 2.0 / len(nn)

    def band(lo, hi):
        m = (freqs >= lo) & (freqs < hi)
        if not m.any():
            return 0.0
        return float(np.trapezoid(power[m], freqs[m]))

    p_lf = band(*lf)
    p_hf = band(*hf)
    return {
        "lf": p_lf,
        "hf": p_hf,
        "lf_hf": (p_lf / p_hf) if p_hf > 1e-12 else float("nan"),
        "total_power": p_lf + p_hf,
    }


def movement(samples) -> dict:
    """Features del acelerómetro para una ventana.

    `act` es la desviación típica del módulo de la aceleración, o sea
    cuánto te has movido. `posture_change` compara la dirección media de
    la gravedad al principio y al final de la ventana: un cambio grande
    significa que te has levantado o te has tumbado.

    Esto último no es un adorno. Ponerse de pie hunde el RMSSD tanto como
    un disgusto serio (es el reflejo barorreceptor, no emoción). Sin esta
    feature, el modelo aprendería que levantarse de la silla es estrés.
    """
    acts = [s.act for s in samples if s.act is not None]
    act = sum(acts) / len(acts) if acts else 0.0
    act_max = max(acts) if acts else 0.0

    vecs = [(s.ax, s.ay, s.az) for s in samples
            if s.ax is not None and s.ay is not None and s.az is not None]
    change = 0.0
    if len(vecs) >= 4:
        k = max(1, len(vecs) // 4)
        change = _angle_between(_mean_vec(vecs[:k]), _mean_vec(vecs[-k:]))

    return {"act": act, "act_max": float(act_max), "posture_change": change}


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------

def _std(xs) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(max(sum((x - m) ** 2 for x in xs) / n, 0.0))


def _mean_vec(vs):
    n = len(vs)
    return (sum(v[0] for v in vs) / n,
            sum(v[1] for v in vs) / n,
            sum(v[2] for v in vs) / n)


def _angle_between(a, b) -> float:
    """Ángulo entre dos vectores, en grados."""
    na = math.sqrt(sum(c * c for c in a))
    nb = math.sqrt(sum(c * c for c in b))
    if na < 1e-6 or nb < 1e-6:
        return 0.0
    cos = sum(x * y for x, y in zip(a, b)) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))
