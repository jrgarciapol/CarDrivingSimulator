"""De marcas a etiquetas: la parte más delicada de todo el proyecto.

El problema es que una marca NO ocurre cuando ocurre el episodio.
Ocurre cuando te das cuenta de que estás estresado, decides marcarlo,
levantas la muñeca y pulsas. Entre el pico fisiológico y el botón pueden
pasar de diez segundos a varios minutos. Si etiquetamos ingenuamente "la
ventana que contiene la pulsación", pasan dos cosas malas:

  1. Etiquetamos como estrés el gesto de levantar el brazo y pulsar, que
     es movimiento y va a ensuciar el acelerómetro. Con suficientes
     ejemplos, el modelo aprende a detectar pulsaciones de botón, no
     estrés. Y funcionará estupendamente en validación.
  2. Nos perdemos el comienzo del episodio, que es justo el trozo con la
     firma más limpia (la descarga simpática inicial).

De ahí las dos correcciones:

  LAG  Se descartan los últimos LABEL_LAG_S segundos antes de la marca:
       ahí está el gesto de pulsar.
  PRE  Se etiqueta hacia atrás desde el inicio declarado (el menú
       "¿desde cuándo?"), más un margen, porque el episodio ya venía
       calentando antes de que te dieras cuenta.

Y una tercera decisión, la zona gris: las ventanas cercanas a una marca
pero fuera del episodio no se etiquetan como negativas. No sabemos si
ahí había estrés o no, y meterlas como "calma" sería enseñarle al modelo
que el estado justo anterior a un episodio es tranquilidad.

El resto de la sesión sí entra como negativo, con una salvedad honesta:
son negativos DÉBILES. Que no marcaras nada no prueba que estuvieras
tranquilo, solo que no lo marcaste. Por eso existe el botón "estoy
tranquilo" y por eso las respuestas "no" a las preguntas del reloj valen
más: esos sí son negativos declarados.
"""

from __future__ import annotations

from dataclasses import dataclass

from .session import Marker, Session, Window

# Segundos anteriores a la marca que se descartan (gesto de pulsar).
LABEL_LAG_S = 15

# Margen hacia atrás desde el inicio declarado del episodio.
LABEL_PRE_S = 60

# Ventana que cubre una declaración explícita de calma.
CALM_BEFORE_S = 120
CALM_AFTER_S = 30

# Zona gris alrededor de un episodio: ni positivo ni negativo.
GUARD_S = 600

# Solapamiento mínimo entre ventana e intervalo para heredar su etiqueta.
MIN_OVERLAP = 0.5


@dataclass
class Labeled:
    window: Window
    label: int | None        # 1 estrés, 0 calma, None excluida
    level: int               # 0..3
    weight: float            # 1.0 negativo declarado, menor si es débil
    reason: str


def _intervals(session: Session):
    """Intervalos positivos, negativos y de zona gris de una sesión."""
    pos, neg, guard = [], [], []

    for m in session.markers():
        if m.code == 19:              # preguntó y no contestaste
            guard.append((m.t - GUARD_S, m.t + GUARD_S))
            continue

        if m.is_stress:
            start = m.t - m.onset_s - LABEL_PRE_S
            end = m.t - LABEL_LAG_S
            if end <= start:
                end = start + 30.0
            pos.append((start, end, m.level))
            guard.append((start - GUARD_S, m.t + GUARD_S))
        elif m.is_negative:
            neg.append((m.t - CALM_BEFORE_S, m.t + CALM_AFTER_S))

    return pos, neg, guard


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def label_windows(session: Session, windows) -> list[Labeled]:
    """Asigna etiqueta a cada ventana de la sesión."""
    pos, neg, guard = _intervals(session)
    out: list[Labeled] = []

    for w in windows:
        span = w.t1 - w.t0
        need = MIN_OVERLAP * span

        best_level = 0
        hit_pos = False
        for (s, e, lvl) in pos:
            # Dos condiciones, y la segunda no es redundante: exigir solo
            # un 50 % de solape dejaría pasar ventanas que se extienden
            # más allá del final del intervalo, o sea, que contienen la
            # pulsación del botón. Exigiendo además que la ventana TERMINE
            # antes del corte, ninguna ventana positiva puede contener el
            # gesto de marcar.
            if _overlap(w.t0, w.t1, s, e) >= need and w.t1 <= e:
                hit_pos = True
                best_level = max(best_level, lvl)
        if hit_pos:
            out.append(Labeled(w, 1, best_level, 1.0, "marca"))
            continue

        if any(_overlap(w.t0, w.t1, s, e) >= need for (s, e) in neg):
            out.append(Labeled(w, 0, 0, 1.0, "calma declarada"))
            continue

        if any(_overlap(w.t0, w.t1, s, e) > 0 for (s, e, *_) in pos):
            out.append(Labeled(w, None, 0, 0.0, "solape parcial"))
            continue

        if any(_overlap(w.t0, w.t1, s, e) > 0 for (s, e) in guard):
            out.append(Labeled(w, None, 0, 0.0, "zona gris"))
            continue

        # Negativo débil: no marcaste nada, pero eso no es una prueba.
        # El peso menor evita que decenas de miles de estos aplasten a la
        # media docena de negativos declarados que sí valen.
        out.append(Labeled(w, 0, 0, 0.3, "sin marca"))

    return out


def summary(labeled: list[Labeled]) -> dict:
    """Recuento por etiqueta y motivo, para no entrenar a ciegas."""
    out = {"total": len(labeled), "pos": 0, "neg": 0, "excluidas": 0,
           "por_motivo": {}, "por_nivel": {1: 0, 2: 0, 3: 0}}
    for item in labeled:
        if item.label == 1:
            out["pos"] += 1
            out["por_nivel"][item.level] = out["por_nivel"].get(item.level, 0) + 1
        elif item.label == 0:
            out["neg"] += 1
        else:
            out["excluidas"] += 1
        out["por_motivo"][item.reason] = out["por_motivo"].get(item.reason, 0) + 1
    return out
