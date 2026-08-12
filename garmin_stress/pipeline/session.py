"""Modelo de datos de una sesión: muestras a 1 Hz, marcas y ventanas."""

from __future__ import annotations

from dataclasses import dataclass, field

# Códigos de marca — iguales a watch/source/Config.mc.
MARK_NONE = 0
MARK_STRESS_1 = 1
MARK_STRESS_2 = 2
MARK_STRESS_3 = 3
MARK_CALM = 4
MARK_PROMPT_BASE = 10
MARK_PROMPT_YES_1 = 11
MARK_PROMPT_YES_2 = 12
MARK_PROMPT_YES_3 = 13
MARK_PROMPT_NO = 15
MARK_PROMPT_SKIP = 19

# Segundos hacia atrás de cada código de inicio.
ONSET_SECONDS = {0: 0, 1: 60, 2: 180, 3: 600}


@dataclass
class Sample:
    """Un registro FIT: un segundo de sesión."""

    t: float                       # epoch, segundos
    rr: list[int] = field(default_factory=list)
    act: int | None = None
    ax: int | None = None
    ay: int | None = None
    az: int | None = None
    mark: int = 0
    mark_seq: int = 0
    onset: int = 0
    p_stress: int | None = None
    rmssd_watch: int | None = None


@dataclass
class Marker:
    """Un evento de marcado, ya deduplicado."""

    t: float
    code: int
    onset_s: int

    @property
    def level(self) -> int:
        """Nivel de estrés declarado: 0 si dice calma o dice que no."""
        v = self.code % 10
        return v if 1 <= v <= 3 else 0

    @property
    def is_prompt_reply(self) -> bool:
        return self.code >= MARK_PROMPT_BASE

    @property
    def is_stress(self) -> bool:
        return self.level > 0

    @property
    def is_negative(self) -> bool:
        """Declaración explícita de que NO hay estrés."""
        return self.code in (MARK_CALM, MARK_PROMPT_NO)


@dataclass
class Window:
    t0: float
    t1: float
    samples: list[Sample]
    rr: list[int]


@dataclass
class Session:
    samples: list[Sample] = field(default_factory=list)
    source: str = ""

    def __post_init__(self):
        self.samples.sort(key=lambda s: s.t)

    @property
    def duration_s(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        return self.samples[-1].t - self.samples[0].t

    @property
    def n_beats(self) -> int:
        return sum(len(s.rr) for s in self.samples)

    def day(self) -> str:
        """Fecha de la sesión, para agrupar en la validación cruzada."""
        import datetime as dt
        if not self.samples:
            return "?"
        return dt.datetime.utcfromtimestamp(self.samples[0].t).strftime("%Y-%m-%d")

    # -----------------------------------------------------------------

    def markers(self) -> list[Marker]:
        """Marcas deduplicadas.

        Cada marca queda "pegada" varios registros para que no la pierda
        una carrera con el escritor de FIT, así que aparece repetida en
        3-4 muestras seguidas. El número de secuencia es lo que permite
        separar dos marcas distintas del mismo nivel: cambia el seq,
        cambia el evento.
        """
        out: list[Marker] = []
        last_seq = None
        for s in self.samples:
            if s.mark_seq != last_seq:
                last_seq = s.mark_seq
                if s.mark != MARK_NONE:
                    out.append(Marker(t=s.t, code=s.mark,
                                      onset_s=ONSET_SECONDS.get(s.onset, 0)))
        return out

    # -----------------------------------------------------------------

    def beat_times(self) -> list[tuple[float, int]]:
        """Empareja cada intervalo R-R con el instante en que terminó.

        El fichero FIT solo dice en qué SEGUNDO llegó cada tanda de
        intervalos, no el instante exacto de cada latido. Reconstruimos
        hacia atrás desde la marca de tiempo del registro: el último
        intervalo del segundo termina en t, el anterior en t menos su
        duración, y así. El error queda acotado por debajo de 1 s y no se
        acumula, que es lo que importa con ventanas de 60 s.
        """
        out: list[tuple[float, int]] = []
        for s in self.samples:
            tail = 0.0
            chunk = []
            for value in reversed(s.rr):
                chunk.append((s.t - tail / 1000.0, value))
                tail += value
            out.extend(reversed(chunk))
        out.sort(key=lambda p: p[0])
        return out

    def windows(self, win_s: float = 60.0, hop_s: float = 15.0):
        """Genera ventanas deslizantes con sus latidos y sus muestras."""
        if not self.samples:
            return
        beats = self.beat_times()
        t_start = self.samples[0].t
        t_end = self.samples[-1].t

        bi = 0
        si = 0
        t0 = t_start
        while t0 + win_s <= t_end:
            t1 = t0 + win_s
            while bi < len(beats) and beats[bi][0] < t0:
                bi += 1
            while si < len(self.samples) and self.samples[si].t < t0:
                si += 1

            j = bi
            rr = []
            while j < len(beats) and beats[j][0] < t1:
                rr.append(beats[j][1])
                j += 1
            k = si
            win_samples = []
            while k < len(self.samples) and self.samples[k].t < t1:
                win_samples.append(self.samples[k])
                k += 1

            yield Window(t0=t0, t1=t1, samples=win_samples, rr=rr)
            t0 += hop_s
