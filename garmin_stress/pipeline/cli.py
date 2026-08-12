"""Interfaz de línea de comandos.

    python -m pipeline synth   --days 5 --out data/raw
    python -m pipeline inspect data/raw
    python -m pipeline train   --data data/raw --model data/model.json
    python -m pipeline export  --model data/model.json
    python -m pipeline demo

`demo` hace el ciclo completo sobre datos sintéticos: sirve para
comprobar que la instalación está bien antes de salir a grabar de verdad.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW = ROOT / "data" / "raw"
DEFAULT_MODEL = ROOT / "data" / "model.json"
DEFAULT_MC = ROOT / "watch" / "source" / "ModelParams.mc"


def cmd_synth(args) -> int:
    from . import fitio, synth

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sessions = synth.make_days(n_days=args.days, seed=args.seed,
                               hours=args.hours)
    for i, s in enumerate(sessions):
        path = out / f"synth_{i:02d}.csv"
        fitio.write_csv(s, path)
        print(f"  {path}  ({len(s.samples)} s, {s.n_beats} latidos, "
              f"{len(s.markers())} marcas)")
    return 0


def cmd_inspect(args) -> int:
    from . import dataset as ds_mod
    from . import fitio, labels

    sessions = _load(args.data)
    if not sessions:
        return 1

    total_marks = 0
    for s in sessions:
        marks = s.markers()
        total_marks += len(marks)
        hrs = s.duration_s / 3600.0
        print(f"\n{Path(s.source).name}")
        print(f"  día         {s.day()}")
        print(f"  duración    {hrs:.2f} h")
        print(f"  latidos     {s.n_beats}  "
              f"({s.n_beats / max(s.duration_s, 1) * 60:.1f} ppm de media)")
        print(f"  marcas      {len(marks)}")
        for m in marks:
            kind = "pregunta" if m.is_prompt_reply else "manual"
            print(f"    t+{m.t - s.samples[0].t:7.0f}s  código {m.code:>2}  "
                  f"nivel {m.level}  inicio -{m.onset_s}s  ({kind})")

    print(f"\nTotal: {len(sessions)} sesiones, {total_marks} marcas")

    data = ds_mod.build(sessions, win_s=args.window, hop_s=args.hop)
    print(f"\nVentanas utilizables: {data.counts()}")

    windows = list(sessions[0].windows(args.window, args.hop))
    print("Reparto de la primera sesión:",
          labels.summary(labels.label_windows(sessions[0], windows)))
    return 0


def cmd_train(args) -> int:
    from . import dataset as ds_mod
    from . import train as train_mod

    sessions = _load(args.data)
    if not sessions:
        return 1

    data = ds_mod.build(sessions, win_s=args.window, hop_s=args.hop)
    print(f"Conjunto: {data.counts()}")
    if data.counts()["pos"] < 20:
        print("\nAVISO: menos de 20 ventanas positivas. Cualquier número que")
        print("salga de aquí es una anécdota, no una medida. Sigue grabando.")

    model = train_mod.train(data, max_false_alarms=args.max_false_alarms)
    Path(args.model).parent.mkdir(parents=True, exist_ok=True)
    model.save(args.model)
    print(f"\nModelo guardado en {args.model}")
    return 0


def cmd_export(args) -> int:
    from . import export_monkeyc
    from .train import Model

    model = Model.load(args.model)
    path = export_monkeyc.export(model, args.out)
    print(f"Escrito {path}")
    print("Recompila la app del reloj para que el cambio tenga efecto.")
    return 0


def cmd_demo(args) -> int:
    from . import dataset as ds_mod
    from . import export_monkeyc, synth
    from . import train as train_mod

    print("Generando 5 días sintéticos...")
    sessions = synth.make_days(n_days=5, seed=1, hours=4.0)
    data = ds_mod.build(sessions)
    print(f"Conjunto: {data.counts()}")

    model = train_mod.train(data)
    print()
    print(export_monkeyc.render(model)[:600] + "...")
    return 0


def _load(path):
    from . import fitio

    p = Path(path)
    if p.is_dir():
        sessions = fitio.load_dir(p)
    elif p.exists():
        sessions = [fitio.load(p)]
    else:
        print(f"No existe: {p}", file=sys.stderr)
        return []
    if not sessions:
        print(f"Sin ficheros .fit ni .csv en {p}", file=sys.stderr)
    return sessions


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pipeline", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("synth", help="genera sesiones sintéticas")
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--hours", type=float, default=4.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default=str(DEFAULT_RAW))
    p.set_defaults(func=cmd_synth)

    p = sub.add_parser("inspect", help="resumen de las sesiones grabadas")
    p.add_argument("data", nargs="?", default=str(DEFAULT_RAW))
    p.add_argument("--window", type=float, default=60.0)
    p.add_argument("--hop", type=float, default=15.0)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("train", help="entrena y valida el modelo")
    p.add_argument("--data", default=str(DEFAULT_RAW))
    p.add_argument("--model", default=str(DEFAULT_MODEL))
    p.add_argument("--window", type=float, default=60.0)
    p.add_argument("--hop", type=float, default=15.0)
    p.add_argument("--max-false-alarms", type=float, default=4.0)
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("export", help="escribe ModelParams.mc")
    p.add_argument("--model", default=str(DEFAULT_MODEL))
    p.add_argument("--out", default=str(DEFAULT_MC))
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("demo", help="ciclo completo sobre datos sintéticos")
    p.set_defaults(func=cmd_demo)

    args = ap.parse_args(argv)
    return args.func(args)
