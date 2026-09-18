"""Genera el TERRENO de un circuito: el campo de alturas que la carretera
corta (ver simulator/terreno.py) y su reparto de secciones.

    python tools/make_terreno.py simulator/tracks/m-50.csv [--amplitud=50] [--semilla=1] [--desplazamiento=10]

Deja <circuito>.terreno.npz junto al .csv e imprime cuanto circuito va a
nivel, en terraplen, en desmonte, en puente y en tunel, y donde estan los
tuneles y los puentes. La amplitud (m) del relieve es lo que decide ese
reparto: mas amplitud, mas tuneles y puentes.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from simulator import config as cfg              # noqa: E402
from simulator import terreno                    # noqa: E402
from simulator.track import Track                # noqa: E402


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    ops = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    if not args:
        print(__doc__)
        return 2
    ruta = os.path.abspath(args[0])
    cfg.TRACK_FILE = ruta
    track = Track()
    campo = terreno.generar(track, amplitud=float(ops.get("amplitud", 50.0)),
                            semilla=int(ops.get("semilla", 1)),
                            desplazamiento=float(ops.get("desplazamiento", 10.0)))
    salida = terreno.ruta_terreno(ruta)
    terreno.guardar(campo, salida)
    t = terreno.Terreno(campo, track)
    print(f"Guardado {os.path.relpath(salida)}: rejilla {campo['alturas'].shape[1]} x "
          f"{campo['alturas'].shape[0]} a {campo['paso']:.0f} m, amplitud "
          f"{campo['amplitud']:.0f} m, semilla {campo['semilla']}")
    print(t.resumen(track))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
