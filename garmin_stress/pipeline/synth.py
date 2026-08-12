"""Generador de sesiones sintéticas.

Sirve para dos cosas:

  1. Probar el pipeline entero (features, etiquetado, entrenamiento,
     exportación) sin haber puesto todavía un pie fuera con la banda.
     Todos los tests del proyecto corren sobre esto.

  2. Saber qué esperar. Aquí conocemos la verdad de cada segundo, así
     que el modelo entrenado sobre datos sintéticos marca un techo
     aproximado: si con datos limpios y episodios de libro no llega a un
     PR-AUC decente, el problema está en el código, no en tu fisiología.

Lo que simula, y por qué:

  - Arritmia sinusal respiratoria: el intervalo entre latidos oscila con
    la respiración (~0,25 Hz). Es el origen físico del RMSSD; sin ella
    los datos no se parecerían en nada a los reales.
  - Episodios de estrés: sube la frecuencia y, sobre todo, se APLANA la
    oscilación respiratoria (cae el tono vagal). Esa es la firma que
    buscamos.
  - Ratos de movimiento: sube la frecuencia y sube el acelerómetro. Son
    el confusor principal, y están puestos a propósito para comprobar
    que el modelo no los confunde con estrés.
  - Latencia de marcado: el usuario marca entre 30 s y 3 min DESPUÉS de
    que empiece el episodio, y a veces no lo marca. Es lo que obliga a
    que el etiquetado mire hacia atrás.
  - Artefactos: latidos perdidos, sobre todo durante el movimiento, que
    es cuando se despega el electrodo de verdad.

No pretende ser un modelo fisiológico serio. Pretende tener las mismas
trampas que los datos reales.
"""

from __future__ import annotations

import math
import random

from .session import (MARK_CALM, MARK_STRESS_1, ONSET_SECONDS, Sample, Session)


def make_session(seed: int = 0, hours: float = 4.0, t0: float = 1_760_000_000.0,
                 n_episodes: int | None = None,
                 mark_probability: float = 0.8) -> Session:
    """Genera una sesión sintética de `hours` horas.

    Por defecto los episodios escalan con la duración (~2 por hora): un
    número fijo no cabe en una sesión corta y sobra en una larga.
    """
    rng = random.Random(seed)
    total_s = int(hours * 3600)
    if n_episodes is None:
        n_episodes = max(3, int(round(hours * 2)))

    episodes = _plan(rng, total_s, n_episodes, dur=(180, 480), gap=600)
    moves = _plan(rng, total_s, n_episodes * 2, dur=(60, 300), gap=300,
                  avoid=episodes)

    # --- Serie de latidos ------------------------------------------
    beats: list[tuple[float, int]] = []   # (t relativo, rr en ms)
    hr_base = 58.0 + rng.uniform(-4, 6)
    f_resp = 0.25
    t = 0.0
    while t < total_s:
        stress = _intensity(t, episodes)
        move = _intensity(t, moves)

        # Deriva circadiana lenta: la frecuencia basal no es constante ni
        # siquiera en reposo.
        hr = (hr_base
              + 3.0 * math.sin(2 * math.pi * t / 5400.0)
              + 16.0 * stress
              + 22.0 * move)
        mean_nn = 60000.0 / hr

        # Amplitud de la arritmia respiratoria: se aplana con el estrés
        # (menos tono vagal) y con el esfuerzo.
        rsa = 0.075 * (1.0 - 0.75 * stress) * (1.0 - 0.6 * move)
        nn = mean_nn * (1.0 + rsa * math.sin(2 * math.pi * f_resp * t))
        nn += rng.gauss(0.0, mean_nn * 0.012 * (1.0 - 0.5 * stress))
        nn = max(300.0, min(2000.0, nn))

        t += nn / 1000.0
        if t >= total_s:
            break

        # Artefactos: más probables moviéndose.
        p_art = 0.0015 + 0.02 * move
        if rng.random() < p_art:
            if rng.random() < 0.5:
                continue                      # latido perdido
            beats.append((t, int(nn * 0.55))) # latido partido en dos
            beats.append((t, int(nn * 0.45)))
            continue
        beats.append((t, int(round(nn))))

    # --- Muestras a 1 Hz -------------------------------------------
    samples = [Sample(t=t0 + s, rr=[], act=0, ax=0, ay=980, az=0)
               for s in range(total_s)]
    for (bt, rr) in beats:
        idx = int(bt)
        if 0 <= idx < total_s:
            samples[idx].rr.append(rr)

    for s_i in range(total_s):
        move = _intensity(float(s_i), moves)
        act = int(abs(rng.gauss(8, 5)) + move * rng.uniform(120, 320))
        samples[s_i].act = min(act, 65535)
        if move > 0.5:
            # De pie / andando: cambia la dirección de la gravedad.
            samples[s_i].ax = int(rng.gauss(120, 40))
            samples[s_i].ay = int(rng.gauss(760, 60))
            samples[s_i].az = int(rng.gauss(560, 60))
        else:
            samples[s_i].ax = int(rng.gauss(30, 15))
            samples[s_i].ay = int(rng.gauss(970, 20))
            samples[s_i].az = int(rng.gauss(90, 25))

    # --- Marcas del usuario ----------------------------------------
    eventos: list[tuple[int, int, int]] = []      # (idx, código, onset)

    for (start, end) in episodes:
        if rng.random() > mark_probability:
            continue                              # episodio no marcado
        latency = rng.uniform(30, 180)
        mark_t = start + latency
        if mark_t >= end:
            mark_t = end - 5
        idx = int(mark_t)
        if not (0 <= idx < total_s):
            continue

        level = 1 + min(2, int((end - start) / 200))
        # El usuario elige la opción del menú más parecida a lo que cree
        # que ha pasado, no una al azar ni siempre la de más arriba.
        onset = min(ONSET_SECONDS, key=lambda k: abs(ONSET_SECONDS[k] - latency))
        eventos.append((idx, MARK_STRESS_1 - 1 + level, onset))

    # Alguna declaración explícita de calma, lejos de los episodios. Se
    # va relajando la distancia exigida para que también quepan en
    # sesiones cortas y muy pobladas de episodios.
    for _ in range(3):
        colocada = False
        for margen in (900, 600, 300):
            for _try in range(60):
                idx = rng.randrange(600, total_s - 60)
                if (_intensity(float(idx), episodes) == 0
                        and _intensity(float(idx), moves) == 0
                        and all(abs(idx - s) > margen for (s, _e) in episodes)):
                    eventos.append((idx, MARK_CALM, 0))
                    colocada = True
                    break
            if colocada:
                break

    # En orden cronológico, y esto NO es cosmético: _stamp rellena el
    # número de secuencia hasta el final de la sesión, así que sellar una
    # marca anterior después de una posterior le pisaría la secuencia a
    # la posterior y la haría desaparecer al deduplicar. Es exactamente
    # lo que pasa en el reloj también: las marcas solo pueden ir hacia
    # adelante en el tiempo.
    seq = 0
    for (idx, mark, onset) in sorted(eventos):
        seq = _stamp(samples, idx, mark, onset, seq, total_s)

    return Session(samples=samples, source=f"synth:{seed}")


def _stamp(samples, idx, mark, onset, seq, total_s) -> int:
    """Escribe una marca pegada varios segundos, como hace el reloj.

    Solo vale llamarla con índices crecientes: el relleno hacia adelante
    del número de secuencia machaca lo que hubiera después.
    """
    seq = (seq + 1) % 256
    for k in range(3):
        if idx + k < total_s:
            samples[idx + k].mark = mark
            samples[idx + k].mark_seq = seq
            samples[idx + k].onset = onset
    for j in range(idx + 3, total_s):
        samples[j].mark_seq = seq
    return seq


def _plan(rng, total_s, n, dur, gap, avoid=None):
    """Coloca n intervalos sin solaparse ni pegarse a los de `avoid`."""
    out: list[tuple[float, float]] = []
    avoid = avoid or []
    for _ in range(n):
        for _try in range(200):
            start = rng.uniform(300, total_s - dur[1] - 60)
            end = start + rng.uniform(*dur)
            if any(start < e + gap and s - gap < end for (s, e) in out):
                continue
            if any(start < e + gap and s - gap < end for (s, e) in avoid):
                continue
            out.append((start, end))
            break
    out.sort()
    return out


def _intensity(t: float, intervals) -> float:
    """Intensidad en 0..1 con subida rápida y bajada lenta.

    Los episodios no son escalones: la descarga simpática es rápida y la
    vuelta a la base es lenta. Importa porque el modelo va a ver sobre
    todo la parte de bajada.
    """
    for (s, e) in intervals:
        if s <= t <= e:
            rise = min(1.0, (t - s) / 45.0)
            fall = min(1.0, (e - t) / 120.0)
            return max(0.0, min(rise, 1.0) * (0.35 + 0.65 * fall))
    return 0.0


def make_days(n_days: int = 5, seed: int = 0, **kwargs) -> list[Session]:
    """Varias sesiones, una por día, para poder validar dejando un día fuera."""
    day = 86400.0
    return [make_session(seed=seed * 100 + i,
                         t0=1_760_000_000.0 + i * day, **kwargs)
            for i in range(n_days)]
