"""Editor gráfico de alineaciones en planta.

Ajusta el trazado en planta de un circuito (línea del KML/KMZ) a
alineaciones de diseño de carreteras y lo exporta al formato del simulador.

TODO se maneja con BOTONES del panel izquierdo (las teclas están reservadas
por matplotlib). Flujo, como en restitución de trazado:

  1. Pulsa RECTA / CIRCULO / PUNTO y pincha puntos sobre la traza; pulsa
     CONFIRMAR para fijar la alineación (QUITAR PUNTO / CANCELAR corrigen).
       - RECTA: mínimos cuadrados totales
       - CIRCULO: ajuste de Kåsa (curva de radio constante)
       - PUNTO: una curvatura en un punto (curva sin arco circular)
  2. Repite con todas las curvas y rectas. No hace falta pinchar en las
     transiciones: los HUECOS entre alineaciones se rellenan solos con
     CLOTOIDES (rampa lineal de curvatura). Como la rampa es lineal, una
     recta↔círculo da una clotoide, y un círculo-derecha↔círculo-izquierda
     cruza κ=0 solo (el caso clotoide↔clotoide, curva de reversa).
  3. Las primitivas ajustadas se dibujan ancladas a la traza (recta verde,
     círculo rojo, punto morado; clotoides discontinuas azules). SELECCIONAR
     + pinchar elige una alineación (queda resaltada); BORRAR la elimina.
  4. ZOOM / MOVER / VISTA COMPLETA para navegar; GUARDAR exporta el CSV.

Uso:
  python tools/alignment_editor.py entrada.kml [--linea=1] [--salida=ruta.csv]
  python tools/alignment_editor.py entrada.kmz
"""

import math
import os
import sys
import zipfile

import matplotlib
# anular los atajos de teclado por defecto de matplotlib: aquí todo va por
# botones y no queremos que una tecla dispare guardar/zoom/pan del backend
for _k in [k for k in matplotlib.rcParams if k.startswith("keymap.")]:
    matplotlib.rcParams[_k] = []
import matplotlib.pyplot as plt
from matplotlib.widgets import Button

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
        self.selected = None          # índice de alineación seleccionada

        self.fig = plt.figure(figsize=(14.0, 8.5))
        self.ax = self.fig.add_axes([0.24, 0.06, 0.74, 0.90])
        self.ax.set_aspect("equal")
        tx = [p[0] for p in xy] + [xy[0][0]]
        ty = [p[1] for p in xy] + [xy[0][1]]
        self.ax.plot(tx, ty, "-", color="0.6", lw=1.0)
        self._art = []
        self._buttons = []
        self._build_buttons()
        self.fig.canvas.mpl_connect("button_press_event", self.on_click)
        self.set_tool(None)
        self.redraw()

    # ------------------------------------------------------------------
    def _build_buttons(self):
        # (etiqueta, callback, herramienta-que-activa|None)
        specs = [
            ("RECTA", lambda e: self.set_tool("line"), "line"),
            ("CIRCULO", lambda e: self.set_tool("arc"), "arc"),
            ("PUNTO", lambda e: self.set_tool("point"), "point"),
            (None, None, None),
            ("CONFIRMAR", lambda e: self.commit(), None),
            ("QUITAR PUNTO", lambda e: self.undo_point(), None),
            ("CANCELAR", lambda e: self.cancel(), None),
            (None, None, None),
            ("SELECCIONAR", lambda e: self.set_tool("select"), "select"),
            ("BORRAR", lambda e: self.delete_selected(), None),
            (None, None, None),
            ("ZOOM", lambda e: self._toolbar("zoom"), None),
            ("MOVER", lambda e: self._toolbar("pan"), None),
            ("VISTA COMPLETA", lambda e: self._toolbar("home"), None),
            (None, None, None),
            ("GUARDAR", lambda e: self.export(), None),
        ]
        self._tool_buttons = {}
        y = 0.94
        h = 0.045
        for label, cb, tool in specs:
            if label is None:
                y -= h * 0.5            # separador
                continue
            axb = self.fig.add_axes([0.02, y - h, 0.19, h])
            b = Button(axb, label)
            b.on_clicked(cb)
            self._buttons.append(b)
            if tool:
                self._tool_buttons[tool] = b
            y -= h + 0.006

    def _toolbar(self, action):
        tb = getattr(self.fig.canvas, "manager", None)
        tb = getattr(tb, "toolbar", None) or \
            getattr(self.fig.canvas, "toolbar", None)
        if tb is None:
            return
        # al usar zoom/mover se desactiva la herramienta de dibujo
        if action in ("zoom", "pan"):
            self.set_tool(None)
            getattr(tb, action)()
        elif action == "home":
            tb.home()

    # ------------------------------------------------------------------
    def set_tool(self, t):
        self.tool = t
        self.pending = []
        for name, b in self._tool_buttons.items():
            b.ax.set_facecolor("#ffd27f" if name == t else "0.85")
        title = {None: "ninguna", "line": "RECTA", "arc": "CIRCULO",
                 "point": "PUNTO", "select": "SELECCIONAR"}.get(t, "-")
        self.ax.set_title(f"Herramienta activa: {title}    |    "
                          f"{len(self.elements)} alineaciones")
        self.fig.canvas.draw_idle()

    def on_click(self, e):
        # ignorar clics en el panel de botones o con zoom/mover activos
        if e.inaxes != self.ax or e.button != 1 or e.xdata is None:
            return
        tb = getattr(self.fig.canvas, "toolbar", None)
        if tb is not None and getattr(tb, "mode", ""):
            return
        if self.tool in ("line", "arc", "point"):
            self.pending.append((e.xdata, e.ydata))
            self.redraw()
        elif self.tool == "select":
            self.selected = self._nearest_element((e.xdata, e.ydata))
            self.redraw()

    def commit(self):
        if self.tool not in ("line", "arc", "point"):
            return
        if len(self.pending) < (2 if self.tool == "line" else 3):
            print("faltan puntos para ajustar la alineación")
            return
        try:
            el = ag.build_element(self.tool, self.pending, self.xy,
                                  self.stations)
        except Exception as ex:               # ajuste degenerado
            print("no se pudo ajustar:", ex)
            return
        self.elements.append(el)
        self.pending = []
        self.set_tool(self.tool)
        self.redraw()

    def undo_point(self):
        if self.pending:
            self.pending.pop()
            self.redraw()

    def cancel(self):
        self.pending = []
        self.redraw()

    def delete_selected(self):
        if self.selected is not None and self.selected < len(self.elements):
            self.elements.pop(self.selected)
        elif self.elements:
            self.elements.pop()
        self.selected = None
        self.set_tool(self.tool)
        self.redraw()

    def _nearest_element(self, pt):
        best_d, best_i = 1e30, None
        for i, el in enumerate(self.elements):
            for q in ag.element_polyline(el, self.xy, self.stations, 20):
                d = (q[0] - pt[0]) ** 2 + (q[1] - pt[1]) ** 2
                if d < best_d:
                    best_d, best_i = d, i
        return best_i

    # ------------------------------------------------------------------
    def redraw(self):
        for a in self._art:
            a.remove()
        self._art = []
        # primitivas ajustadas, ANCLADAS a la traza (sin deriva): recta
        # verde, círculo rojo, punto morado; la seleccionada, gruesa/naranja
        for i, el in enumerate(self.elements):
            col = {"line": "#1a9641", "arc": "#d7191c",
                   "point": "#b03fb0"}[el["kind"]]
            lw = 2.4
            if i == self.selected:
                col, lw = "#ff8c00", 4.0
            poly = ag.element_polyline(el, self.xy, self.stations)
            self._art += self.ax.plot([p[0] for p in poly],
                                      [p[1] for p in poly], "-",
                                      color=col, lw=lw)
            self._art += self.ax.plot([poly[0][0], poly[-1][0]],
                                      [poly[0][1], poly[-1][1]], "o",
                                      color=col, ms=4)
        # clotoides: conectan alineaciones consecutivas (discontinua azul)
        els = sorted(self.elements, key=lambda e: e["s0"])
        for i in range(len(els)):
            p0 = ag.element_polyline(els[i], self.xy, self.stations)[-1]
            p1 = ag.element_polyline(els[(i + 1) % len(els)], self.xy,
                                     self.stations)[0]
            self._art += self.ax.plot([p0[0], p1[0]], [p0[1], p1[1]], "--",
                                      color="#2c7fb8", lw=1.3)
        # puntos en curso
        if self.pending:
            self._art += self.ax.plot([p[0] for p in self.pending],
                                      [p[1] for p in self.pending], "x",
                                      color="orange", ms=9, mew=2)
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
