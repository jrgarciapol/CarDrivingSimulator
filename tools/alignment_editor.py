"""Editor gráfico de alineaciones en planta.

Ajusta el trazado en planta de un circuito (línea del KML/KMZ) a
alineaciones de diseño de carreteras y lo exporta al formato del simulador.

Flujo (como en restitución de trazado):
  1. Elige una herramienta y pincha puntos sobre la traza:
       R = recta      (ajuste por mínimos cuadrados totales)
       C = círculo    (ajuste de Kåsa; curva de radio constante)
       P = punto      (curvatura en un punto: curva sin arco circular)
     ENTER confirma la alineación, ESC la cancela, RETROCESO quita el
     último punto.
  2. Repite con todas las curvas y rectas. No hace falta pinchar en las
     transiciones: los HUECOS entre alineaciones se rellenan solos con
     CLOTOIDES (rampa lineal de curvatura). Como la rampa es lineal, una
     recta↔círculo da una clotoide, y un círculo-derecha↔círculo-izquierda
     cruza κ=0 solo (el caso clotoide↔clotoide, curva de reversa).
  3. La línea azul es el resultado ensamblado en vivo sobre tu traza.
       D = borra la última alineación
       E = exporta a CSV (formato del simulador)
  Zoom y desplazamiento: barra de herramientas de matplotlib (lupa y mano).

Uso:
  python tools/alignment_editor.py entrada.kml [--linea=1] [--salida=ruta.csv]
  python tools/alignment_editor.py entrada.kmz
"""

import math
import os
import sys
import zipfile

import matplotlib
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
import alignment_geom as ag
from import_kml import parse_kml_lines

SEGMENT_LENGTH = 4.0
BANK_SCALE = 7.0
BANK_MAX_DEG = 6.0
KERB_KAPPA = 0.004


def load_plan(path, line_idx):
    """Devuelve la línea de planta como puntos XY locales (m)."""
    if path.lower().endswith(".kmz"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".kml"))
            tmp = os.path.join(os.path.dirname(path), "_tmp_doc.kml")
            with open(tmp, "wb") as f:
                f.write(z.read(name))
        lines = parse_kml_lines(tmp)
        os.remove(tmp)
    else:
        lines = parse_kml_lines(path)
    return ag.to_local_xy(lines[line_idx])


def load_elev_column(csv_path, n):
    """Toma la rasante real de un CSV existente, estirada a n segmentos
    (para conservar la elevación al reexportar solo la planta)."""
    try:
        col = []
        for ln in open(csv_path):
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                col.append(float(ln.split(",")[1]))
        if not col:
            return [0.0] * n
        return [col[min(len(col) - 1, int(i * len(col) / n))] for i in range(n)]
    except (OSError, ValueError, IndexError):
        return [0.0] * n


class PlanEditor:
    TOOLS = {"r": "recta", "c": "circulo", "p": "punto"}

    def __init__(self, xy, out_path, elev_csv=None, step=SEGMENT_LENGTH):
        self.xy = xy
        self.stations = ag.polyline_stations(xy)
        self.L = self.stations[-1]
        self.step = step
        self.out_path = out_path
        self.elev_csv = elev_csv
        self.elements = []
        self.tool = None
        self.pending = []

        self.fig, self.ax = plt.subplots(figsize=(12.5, 8.5))
        self.ax.set_aspect("equal")
        tx = [p[0] for p in xy] + [xy[0][0]]
        ty = [p[1] for p in xy] + [xy[0][1]]
        self.ax.plot(tx, ty, "-", color="0.6", lw=1.0, label="traza (KML)")
        self._art = []
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        self.fig.canvas.mpl_connect("button_press_event", self.on_click)
        self._status = self.ax.set_title("")
        self.set_tool(None)
        self.redraw()

    # ------------------------------------------------------------------
    def set_tool(self, t):
        self.tool = t
        self.pending = []
        name = self.TOOLS.get(t, "ninguna")
        self.ax.set_title(
            f"Herramienta: {name.upper()}   |   R recta  C circulo  P punto  "
            f"ENTER ok  ESC cancela  D borra  E exporta   |   "
            f"{len(self.elements)} alineaciones")
        self.fig.canvas.draw_idle()

    def on_key(self, e):
        k = (e.key or "").lower()
        if k in self.TOOLS:
            self.set_tool(k)
        elif k == "enter":
            self.commit()
        elif k == "escape":
            self.set_tool(self.tool)
        elif k == "backspace":
            if self.pending:
                self.pending.pop()
                self.redraw()
        elif k == "d":
            if self.elements:
                self.elements.pop()
                self.redraw()
        elif k == "e":
            self.export()

    def on_click(self, e):
        # no capturar clics cuando la barra está en modo zoom/desplazar
        tb = getattr(self.fig.canvas, "toolbar", None)
        if tb is not None and getattr(tb, "mode", ""):
            return
        if self.tool is None or e.inaxes != self.ax or e.button != 1:
            return
        if e.xdata is None:
            return
        self.pending.append((e.xdata, e.ydata))
        self.redraw()

    def commit(self):
        need = 2 if self.tool == "line" or self.tool == "r" else 3
        kind = {"r": "line", "c": "arc", "p": "point"}.get(self.tool)
        if kind is None or len(self.pending) < (2 if kind == "line" else 3):
            return
        try:
            el = ag.build_element(kind, self.pending, self.xy, self.stations)
        except Exception as ex:               # ajuste degenerado
            print("no se pudo ajustar:", ex)
            return
        self.elements.append(el)
        self.pending = []
        self.set_tool(self.tool)
        self.redraw()

    # ------------------------------------------------------------------
    def redraw(self):
        for a in self._art:
            a.remove()
        self._art = []
        # primitivas ajustadas, dibujadas ANCLADAS a la traza (sin deriva
        # de integración): recta verde, círculo rojo, punto morado
        els = sorted(self.elements, key=lambda e: e["s0"])
        for el in els:
            col = {"line": "#1a9641", "arc": "#d7191c",
                   "point": "#b03fb0"}[el["kind"]]
            poly = ag.element_polyline(el, self.xy, self.stations)
            self._art += self.ax.plot([p[0] for p in poly],
                                      [p[1] for p in poly], "-",
                                      color=col, lw=2.4)
            self._art += self.ax.plot([poly[0][0], poly[-1][0]],
                                      [poly[0][1], poly[-1][1]], "o",
                                      color=col, ms=4)
        # clotoides: conectan el fin de una alineación con el inicio de la
        # siguiente (línea discontinua azul = la transición que se rellena)
        for i in range(len(els)):
            e0 = els[i]
            e1 = els[(i + 1) % len(els)]
            p0 = ag.element_polyline(e0, self.xy, self.stations)[-1]
            p1 = ag.element_polyline(e1, self.xy, self.stations)[0]
            self._art += self.ax.plot([p0[0], p1[0]], [p0[1], p1[1]], "--",
                                      color="#2c7fb8", lw=1.3)
        # puntos en curso
        if self.pending:
            xs = [p[0] for p in self.pending]
            ys = [p[1] for p in self.pending]
            self._art += self.ax.plot(xs, ys, "x", color="orange", ms=9,
                                      mew=2)
        self.fig.canvas.draw_idle()

    def _trace_point(self, s):
        s = max(0.0, min(self.L, s))
        i = 0
        while i < len(self.stations) - 2 and self.stations[i + 1] < s:
            i += 1
        return self.xy[i]

    # ------------------------------------------------------------------
    def export(self):
        if len(self.elements) < 2:
            print("hacen falta al menos 2 alineaciones para exportar")
            return
        n = int(round(self.L / self.step))
        ks = ag.assemble_kappa(self.elements, self.L, self.step, close=True)
        elev = (load_elev_column(self.elev_csv, n) if self.elev_csv
                else [0.0] * n)
        cap = math.radians(BANK_MAX_DEG)
        win = max(1, int(15.0 / self.step))
        banks = []
        for i in range(n):
            k = sum(ks[(i + j) % n] for j in range(-win, win + 1)) \
                / (2 * win + 1)
            b = max(-cap, min(cap, k * BANK_SCALE))
            banks.append(b if abs(b) > 0.004 else 0.0)
        with open(self.out_path, "w") as f:
            f.write("# Trazado en planta EDITADO a mano (alignment_editor):\n")
            f.write("# rectas + circulos + clotoides; rasante conservada\n")
            f.write("# kappa_1pm,elev_m,kerb,peralte_rad (seg %.1f m)\n"
                    % self.step)
            for i, k in enumerate(ks):
                kerb = 1 if abs(k) > KERB_KAPPA else 0
                f.write("%.6f,%.2f,%d,%.4f\n" % (k, elev[i], kerb, banks[i]))
        r_min = 1.0 / max(1e-9, max(abs(k) for k in ks))
        print(f"exportado {self.out_path}: {n} seg, {self.L:.0f} m, "
              f"radio min {r_min:.0f} m, {len(self.elements)} alineaciones")

    def show(self):
        print(__doc__)
        plt.show()


def main():
    argv = sys.argv[1:]
    args = [a for a in argv if not a.startswith("--")]
    line_idx = 1
    out = None
    for a in argv:
        if a.startswith("--linea="):
            line_idx = int(a.split("=")[1])
        if a.startswith("--salida="):
            out = a.split("=", 1)[1]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    src = args[0]
    out = out or os.path.join("simulator", "tracks", "editado.csv")
    elev_csv = os.path.join("simulator", "tracks", "spa.csv")
    xy = load_plan(src, line_idx)
    ed = PlanEditor(xy, out, elev_csv if os.path.exists(elev_csv) else None)
    ed.show()


if __name__ == "__main__":
    main()
