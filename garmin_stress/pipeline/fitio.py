"""Lectura de los ficheros que produce el reloj.

Dos formatos:

  .fit  Lo que saca el Epix Pro. Se lee con `fitparse`. Los campos que
        crea la app (rr, mark, act...) son *developer fields*: fitparse
        los expone por el nombre con el que se crearon en Monkey C, así
        que los nombres de watch/source/Recorder.mc y los de aquí tienen
        que coincidir.

  .csv  Formato propio de depuración. Lo usa el generador sintético
        (pipeline/synth.py) para poder probar todo el pipeline sin
        reloj, y sirve también para inspeccionar a mano una sesión.

Como red de seguridad se leen también los mensajes `hrv` nativos del
FIT: muchos Garmin escriben ahí los intervalos R-R por su cuenta cuando
hay una banda conectada. Si por lo que sea el campo `rr` de la app
saliera vacío, esos mensajes salvan la sesión.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from .session import Sample, Session

RECORD_FIELDS = ("rr", "rr_n", "rr_lost", "act", "mark", "mark_seq",
                 "onset", "p_stress", "rmssd", "ax", "ay", "az")


def load(path) -> Session:
    """Carga una sesión, deduciendo el formato por la extensión."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return read_csv(path)
    return read_fit(path)


def load_dir(path, pattern="*") -> list[Session]:
    """Carga todas las sesiones de un directorio, ordenadas por nombre."""
    path = Path(path)
    files = sorted(p for p in path.glob(pattern)
                   if p.suffix.lower() in (".fit", ".csv"))
    return [load(p) for p in files]


# ---------------------------------------------------------------------
# FIT
# ---------------------------------------------------------------------

def read_fit(path) -> Session:
    from fitparse import FitFile

    path = Path(path)
    ff = FitFile(str(path))
    samples: list[Sample] = []

    for msg in ff.get_messages("record"):
        d = {}
        for f in msg.fields:
            # Un mismo nombre puede venir del campo nativo y del de la
            # app; nos quedamos con el primero que traiga valor.
            if f.name not in d or d[f.name] is None:
                d[f.name] = f.value

        ts = d.get("timestamp")
        if ts is None:
            continue
        if isinstance(ts, dt.datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            t = ts.timestamp()
        else:
            t = float(ts)

        samples.append(Sample(
            t=t,
            rr=_extract_rr(d),
            act=_as_int(d.get("act")),
            ax=_as_int(d.get("ax")),
            ay=_as_int(d.get("ay")),
            az=_as_int(d.get("az")),
            mark=_as_int(d.get("mark")) or 0,
            mark_seq=_as_int(d.get("mark_seq")) or 0,
            onset=_as_int(d.get("onset")) or 0,
            p_stress=_as_int(d.get("p_stress")),
            rmssd_watch=_as_int(d.get("rmssd")),
        ))

    session = Session(samples=samples, source=str(path))

    if session.n_beats == 0:
        _fill_from_native_hrv(ff, session)

    return session


def _extract_rr(d) -> list[int]:
    """Saca los intervalos R-R de un registro, en los dos formatos.

    Formato array (Config.RR_ARRAY_FIELD = true): un campo `rr` con
    RR_SLOTS valores, los huecos sin usar a 0.
    Formato escalar (plan B): campos rr0, rr1, rr2, rr3.
    """
    out: list[int] = []
    raw = d.get("rr")
    if raw is not None:
        if isinstance(raw, (list, tuple)):
            out = [int(v) for v in raw if v]
        elif raw:
            out = [int(raw)]
    else:
        i = 0
        while f"rr{i}" in d:
            v = d.get(f"rr{i}")
            if v:
                out.append(int(v))
            i += 1

    n = _as_int(d.get("rr_n"))
    if n is not None and 0 <= n < len(out):
        out = out[:n]
    return out


def _fill_from_native_hrv(ff, session: Session) -> None:
    """Rescata los R-R de los mensajes `hrv` nativos del FIT.

    Estos mensajes no llevan marca de tiempo propia: van intercalados
    entre los registros, así que se asignan al último registro visto. Es
    menos preciso que el campo de la app pero para ventanas de 60 s da
    igual.
    """
    by_t = {s.t: s for s in session.samples}
    times = sorted(by_t)
    if not times:
        return

    idx = 0
    for msg in ff.get_messages("hrv"):
        for f in msg.fields:
            if f.name != "time":
                continue
            values = f.value if isinstance(f.value, (list, tuple)) else [f.value]
            for v in values:
                if v is None:
                    continue
                ms = int(round(float(v) * 1000.0))
                if ms <= 0:
                    continue
                by_t[times[min(idx, len(times) - 1)]].rr.append(ms)
        idx = min(idx + 1, len(times) - 1)


def _as_int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------

CSV_HEADER = ["t", "rr", "act", "ax", "ay", "az",
              "mark", "mark_seq", "onset", "p_stress"]


def read_csv(path) -> Session:
    samples = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rr = [int(v) for v in row["rr"].split(";") if v]
            samples.append(Sample(
                t=float(row["t"]),
                rr=rr,
                act=int(row["act"]),
                ax=int(row["ax"]), ay=int(row["ay"]), az=int(row["az"]),
                mark=int(row["mark"]),
                mark_seq=int(row["mark_seq"]),
                onset=int(row["onset"]),
                p_stress=int(row["p_stress"]) if row.get("p_stress") else None,
            ))
    return Session(samples=samples, source=str(path))


def write_csv(session: Session, path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for s in session.samples:
            w.writerow([
                f"{s.t:.0f}",
                ";".join(str(v) for v in s.rr),
                s.act if s.act is not None else 0,
                s.ax or 0, s.ay or 0, s.az or 0,
                s.mark, s.mark_seq, s.onset,
                s.p_stress if s.p_stress is not None else 0,
            ])
