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
     Los puntos en curso son círculos ARRASTRABLES: pincha encima y muévelos
     para afinar el ajuste (se reajusta en vivo, naranja).
  3. Las primitivas ajustadas se dibujan ancladas a la traza (recta verde,
     círculo rojo, punto morado; clotoides discontinuas azules). SELECCIONAR
     + pinchar elige una alineación (resaltada); EDITAR la reabre para mover
     sus puntos; BORRAR la elimina.
  4. ZOOM / MOVER / VISTA COMPLETA para navegar (al elegir una herramienta de
     dibujo se apagan solos); GUARDAR exporta el CSV para el simulador Y las
     alineaciones (.aln.json) para poder reabrir y corregir el trabajo.

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
        self.aln_path = os.path.splitext(out_path)[0] + ".aln.json"
        self.elements = []
        self.tool = None
        self.pending = []
        self.selected = None          # índice de alineación seleccionada
        self._drag = None             # índice del punto que se arrastra
        self._editing = False         # True mientras se edita una alineación

        self.fig = plt.figure(figsize=(14.0, 8.5))
        self.ax = self.fig.add_axes([0.24, 0.06, 0.74, 0.90])
        self.ax.set_aspect("equal")
        tx = [p[0] for p in xy] + [xy[0][0]]
        ty = [p[1] for p in xy] + [xy[0][1]]
        self.ax.plot(tx, ty, "-", color="0.6", lw=1.0)
        self._art = []
        self._buttons = []
        self._build_buttons()
        self.fig.canvas.mpl_connect("button_press_event", self.on_press)
        self.fig.canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.fig.canvas.mpl_connect("button_release_event", self.on_release)
        self.load_alignments()        # reanuda trabajo previo si existe
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
            ("EDITAR", lambda e: self.edit_selected(), None),
            ("BORRAR", lambda e: self.delete_selected(), None),
            (None, None, None),
            ("ZOOM", lambda e: self._toolbar("zoom"), "zoom"),
            ("MOVER", lambda e: self._toolbar("pan"), "pan"),
            ("VISTA COMPLETA", lambda e: self._toolbar("home"), None),
            (None, None, None),
            ("GUARDAR", lambda e: self.export(), None),
        ]
        self._tool_buttons = {}
        y = 0.955
        h = 0.043
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
            y -= h + 0.005

    def _get_toolbar(self):
        tb = getattr(getattr(self.fig.canvas, "manager", None),
                     "toolbar", None)
        return tb or getattr(self.fig.canvas, "toolbar", None)

    def _nav_active(self):
        tb = self._get_toolbar()
        return tb.mode if (tb and getattr(tb, "mode", "")) else ""

    def _deactivate_nav(self):
        """Apaga zoom/mover del backend (para no dejarlos 'pegados')."""
        tb = self._get_toolbar()
        if tb and getattr(tb, "mode", ""):
            if "zoom" in tb.mode:
                tb.zoom()
            elif "pan" in tb.mode:
                tb.pan()

    def _toolbar(self, action):
        tb = self._get_toolbar()
        if tb is None:
            return
        if action in ("zoom", "pan"):
            # activar zoom/mover DESACTIVA la herramienta de dibujo
            self.set_tool(None)
            getattr(tb, action)()
        elif action == "home":
            tb.home()
        self._refresh_button_marks()

    def _refresh_button_marks(self):
        """Resalta el botón de la herramienta/navegación activa."""
        nav = self._nav_active()
        for name, b in self._tool_buttons.items():
            on = (name == self.tool) or \
                 (name == "zoom" and "zoom" in nav) or \
                 (name == "pan" and "pan" in nav)
            b.ax.set_facecolor("#ffd27f" if on else "0.85")
        self.fig.canvas.draw_idle()

    # ------------------------------------------------------------------
    def set_tool(self, t):
        # activar una herramienta de dibujo/selección apaga zoom/mover, para
        # no tener que despincharlos desde la barra inferior de matplotlib
        if t in ("line", "arc", "point", "select"):
            self._deactivate_nav()
        if not self._editing:
            self.pending = []
        self.tool = t
        title = {None: "ninguna", "line": "RECTA", "arc": "CIRCULO",
                 "point": "PUNTO", "select": "SELECCIONAR"}.get(t, "-")
        if self._editing:
            title += " (EDITANDO: arrastra los puntos, CONFIRMAR al acabar)"
        self.ax.set_title(f"Herramienta: {title}    |    "
                          f"{len(self.elements)} alineaciones", color="black")
        self._refresh_button_marks()
        self.redraw()

    # ---- ratón: pinchar añade punto, arrastrar mueve un punto ---------
    def _pick_pending(self, e):
        """Índice del punto en curso más cercano al cursor (en píxeles),
        o None si no hay ninguno lo bastante cerca (umbral ~12 px)."""
        best_d, best_i = 12.0 ** 2, None
        for i, p in enumerate(self.pending):
            px, py = self.ax.transData.transform(p)
            d = (px - e.x) ** 2 + (py - e.y) ** 2
            if d < best_d:
                best_d, best_i = d, i
        return best_i

    def on_press(self, e):
        if e.inaxes != self.ax or e.button != 1 or e.xdata is None:
            return
        if self._nav_active():           # zoom/mover manda: no dibujar
            return
        if self.tool in ("line", "arc", "point"):
            hit = self._pick_pending(e)
            if hit is not None:          # empezar a arrastrar ese punto
                self._drag = hit
            else:                        # o añadir un punto nuevo
                self.pending.append((e.xdata, e.ydata))
                self.redraw()
        elif self.tool == "select":
            self.selected = self._nearest_element((e.xdata, e.ydata))
            self.redraw()

    def on_motion(self, e):
        if self._drag is None or e.inaxes != self.ax or e.xdata is None:
            return
        self.pending[self._drag] = (e.xdata, e.ydata)
        self.redraw()

    def on_release(self, e):
        self._drag = None

    def commit(self):
        if self.tool not in ("line", "arc", "point"):
            return
        if len(self.pending) < (2 if self.tool == "line" else 3):
            self._flash("faltan puntos (2 recta, 3 circulo/punto)", "#c33")
            return
        try:
            el = ag.build_element(self.tool, self.pending, self.xy,
                                  self.stations)
        except Exception as ex:               # ajuste degenerado
            self._flash(f"no se pudo ajustar: {ex}", "#c33")
            return
        self.elements.append(el)
        self.pending = []
        self._editing = False
        self.set_tool(self.tool)

    def undo_point(self):
        if self.pending:
            self.pending.pop()
            self.redraw()

    def cancel(self):
        self.pending = []
        self._editing = False
        self.redraw()

    def edit_selected(self):
        """Edita la alineación seleccionada: la saca de la lista y pone sus
        puntos como 'en curso' para poder arrastrarlos y reajustar."""
        if self.selected is None or self.selected >= len(self.elements):
            self._flash("selecciona antes una alineacion", "#c33")
            return
        el = self.elements.pop(self.selected)
        self.selected = None
        self.pending = [tuple(p) for p in el.get("pts", [])]
        self._editing = True
        self.set_tool(el["kind"])

    def delete_selected(self):
        if self.selected is not None and self.selected < len(self.elements):
            self.elements.pop(self.selected)
        elif self.elements:
            self.elements.pop()
        self.selected = None
        self.set_tool(self.tool)

    def _nearest_element(self, pt):
        best_d, best_i = 1e30, None
        for i, el in enumerate(self.elements):
            for q in ag.element_polyline(el, self.xy, self.stations, 20):
                d = (q[0] - pt[0]) ** 2 + (q[1] - pt[1]) ** 2
                if d < best_d:
                    best_d, best_i = d, i
        return best_i

    def _flash(self, msg, color="#1a7"):
        print(msg)
        self.ax.set_title(msg, color=color)
        self.fig.canvas.draw_idle()

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
        # ajuste PROVISIONAL en vivo de la alineación en curso (si hay
        # puntos suficientes): se ve cómo encaja mientras colocas/arrastras
        if self.tool in ("line", "arc", "point") and \
                len(self.pending) >= (2 if self.tool == "line" else 3):
            try:
                prov = ag.build_element(self.tool, self.pending, self.xy,
                                        self.stations)
                poly = ag.element_polyline(prov, self.xy, self.stations)
                self._art += self.ax.plot([p[0] for p in poly],
                                          [p[1] for p in poly], "-",
                                          color="#ff8c00", lw=2.0, alpha=0.9)
            except Exception:
                pass
        # puntos en curso: círculos ARRASTRABLES (pincha encima y mueve)
        if self.pending:
            self._art += self.ax.plot([p[0] for p in self.pending],
                                      [p[1] for p in self.pending], "o",
                                      color="orange", ms=8, mew=1.5,
                                      mec="black")
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
        # NO se fuerza el cierre geométrico (close=False): el simulador conduce
        # sobre el campo de curvatura κ(s) —estación + desplazamiento lateral—
        # y NO necesita que el bucle cierre en x/y (el minimapa ya reparte el
        # error de cierre él solo). Forzar el cierre escalaba TODA la curvatura
        # y apretaba los radios que el usuario eligió a mano (p.ej. 18→13.5 m),
        # dejando el trazado inconducible. Con close=False se respetan los
        # radios REALES dibujados y el error de cierre se informa abajo.
        ks = ag.assemble_kappa(self.elements, self.L, self.step, close=False)
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
        # guardar de forma ROBUSTA: crear la carpeta si no existe y avisar
        # con la ruta ABSOLUTA (en pantalla y por consola). Si por lo que sea
        # el destino no se puede escribir, se cae a la carpeta actual para
        # NUNCA perder el trabajo.
        path = os.path.abspath(self.out_path)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fh = open(path, "w")
        except OSError:
            path = os.path.abspath("editado.csv")
            fh = open(path, "w")
        with fh as f:
            f.write("# Trazado en planta EDITADO a mano (alignment_editor):\n")
            f.write("# rectas + circulos + clotoides; rasante conservada\n")
            f.write("# kappa_1pm,elev_m,kerb,peralte_rad (seg %.1f m)\n"
                    % self.step)
            for i, k in enumerate(ks):
                kerb = 1 if abs(k) > KERB_KAPPA else 0
                f.write("%.6f,%.2f,%d,%.4f\n" % (k, elev[i], kerb, banks[i]))
        # guardar TAMBIÉN las alineaciones (tipo + puntos) para poder
        # reabrir y corregir el trabajo, no solo el κ resultante
        aln = os.path.splitext(path)[0] + ".aln.json"
        try:
            import json
            json.dump([{"kind": e["kind"], "pts": e["pts"]}
                       for e in self.elements], open(aln, "w"))
        except OSError:
            aln = None
        r_min = 1.0 / max(1e-9, max(abs(k) for k in ks))
        # diagnóstico de CIERRE: cuánto gira el dibujo frente a los ±360° que
        # tiene todo circuito cerrado, y en qué curvas se queda corto. No se
        # corrige solo (respeta el diseño); es información para afinar a mano.
        turn = ag.total_turn(ks, self.step)
        miss = math.degrees(turn) - math.copysign(360.0, turn)
        worst = ag.turn_deficit(ks, self.xy, self.stations, self.step)
        print(f"GUARDADO en {path}  ({n} seg, {self.L:.0f} m, "
              f"radio min {r_min:.0f} m, {len(self.elements)} alineaciones)"
              + (f"  + alineaciones en {aln}" if aln else ""))
        print(f"  cierre: el dibujo gira {math.degrees(turn):+.0f}° "
              f"(un circuito cerrado gira ±360°) -> descuadre {miss:+.0f}°")
        if worst and worst[0][3] > 8.0:
            print("  curvas que se quedan CORTAS de giro (afínalas en el editor):")
            for s0, tra, asm, dfc in worst[:4]:
                if dfc > 8.0:
                    print(f"    s≈{s0:.0f} m: traza {tra:+.0f}°, dibujo "
                          f"{asm:+.0f}°  (faltan {dfc:.0f}°)")
        # confirmación bien visible en la ventana (verde)
        self.ax.set_title(f"✓ GUARDADO: {path}   (cierre {miss:+.0f}°, "
                          f"radio mín {r_min:.0f} m)", color="#1a7d1a")
        self.fig.canvas.draw_idle()

    def load_alignments(self):
        """Reanuda el trabajo previo: si existe el .aln.json junto a la
        salida, reconstruye las alineaciones (reajustando desde sus puntos)."""
        if not os.path.exists(self.aln_path):
            return
        try:
            import json
            data = json.load(open(self.aln_path))
            for d in data:
                self.elements.append(
                    ag.build_element(d["kind"], d["pts"], self.xy,
                                     self.stations))
            print(f"reanudadas {len(self.elements)} alineaciones de "
                  f"{self.aln_path}")
        except Exception as ex:
            print("no se pudieron cargar alineaciones previas:", ex)

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
    # rutas por defecto RELATIVAS AL REPOSITORIO (la carpeta padre de
    # tools/), no al directorio desde el que se ejecuta: así GUARDAR
    # siempre escribe en simulator/tracks/ del proyecto, exista o no el cwd
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out = out or os.path.join(root, "simulator", "tracks", "editado.csv")
    elev_csv = os.path.join(root, "simulator", "tracks", "spa.csv")
    xy = load_plan(src, line_idx)
    ed = PlanEditor(xy, out, elev_csv if os.path.exists(elev_csv) else None)
    ed.show()


if __name__ == "__main__":
    main()
