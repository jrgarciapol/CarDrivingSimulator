"""Editor gráfico del ALZADO (perfil longitudinal).

Segunda pantalla del diseño: sobre la COTA del terreno de nuestro trazado
resuelto (columna de elevación del CSV), defines las RASANTES (rectas de
pendiente) pinchando puntos; los HUECOS entre rasantes se rellenan solos con
ACUERDOS PARABÓLICOS tangentes a ambas (vértice = PIV, intersección de las
rasantes). GUARDAR guarda tus rasantes (.pfl.json) para reabrir; RESOLVER
ensambla el perfil z(s), lo cierra e INTEGRA en el track (escribe
'<csv>_alzado.csv' con la κ de la planta + la cota de diseño).

TODO por BOTONES (las teclas las usa matplotlib). Uso:
  python tools/profile_editor.py simulator/tracks/spa_resuelto.csv
"""

import math
import os
import sys

import matplotlib
for _k in [k for k in matplotlib.rcParams if k.startswith("keymap.")]:
    matplotlib.rcParams[_k] = []
import matplotlib.pyplot as plt
from matplotlib.widgets import Button

sys.path.insert(0, os.path.dirname(__file__))
import profile_geom as pg

SEGMENT_LENGTH = 4.0


def load_track(path):
    """Lee un CSV del simulador. Devuelve (kappa, elev, kerb, bank) por
    segmento."""
    kap, elev, kerb, bank = [], [], [], []
    for ln in open(path):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split(",")
        kap.append(float(parts[0]))
        elev.append(float(parts[1]) if len(parts) > 1 else 0.0)
        kerb.append(int(parts[2]) if len(parts) > 2 else 0)
        bank.append(float(parts[3]) if len(parts) > 3 else 0.0)
    return kap, elev, kerb, bank


class ProfileEditor:
    def __init__(self, csv_path, step=SEGMENT_LENGTH):
        self.csv_path = os.path.abspath(csv_path)
        self.kap, self.z_terrain, self.kerb, self.bank = load_track(csv_path)
        self.step = step
        self.n = len(self.z_terrain)
        self.L = self.n * step
        self.stations = [i * step for i in range(self.n)]
        self.pfl_path = os.path.splitext(self.csv_path)[0] + ".pfl.json"
        self.rasantes = []
        self.tool = None
        self.pending = []
        self.selected = None
        self._drag = None
        self._editing = False

        self.fig = plt.figure(figsize=(15.0, 7.5))
        self.ax = self.fig.add_axes([0.22, 0.10, 0.76, 0.84])
        self.ax.plot(self.stations, self.z_terrain, "-", color="0.6", lw=1.2,
                     label="terreno (DEM)")
        self.ax.set_xlabel("estación (m)")
        self.ax.set_ylabel("cota (m)")
        self.ax.grid(True, color="0.9")
        self._art = []
        self._buttons = []
        self._build_buttons()
        self.fig.canvas.mpl_connect("button_press_event", self.on_press)
        self.fig.canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.fig.canvas.mpl_connect("button_release_event", self.on_release)
        self.load_rasantes()
        self.set_tool(None)
        self.redraw()

    # ------------------------------------------------------------------
    def _build_buttons(self):
        specs = [
            ("RASANTE", lambda e: self.set_tool("rasante"), "rasante"),
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
            ("GUARDAR", lambda e: self.save(), None),
            ("RESOLVER", lambda e: self.resolver(), None),
        ]
        self._tool_buttons = {}
        y, h = 0.955, 0.05
        for label, cb, tool in specs:
            if label is None:
                y -= h * 0.5
                continue
            axb = self.fig.add_axes([0.02, y - h, 0.17, h])
            b = Button(axb, label)
            b.on_clicked(cb)
            self._buttons.append(b)
            if tool:
                self._tool_buttons[tool] = b
            y -= h + 0.006

    def _get_toolbar(self):
        tb = getattr(getattr(self.fig.canvas, "manager", None),
                     "toolbar", None)
        return tb or getattr(self.fig.canvas, "toolbar", None)

    def _nav_active(self):
        tb = self._get_toolbar()
        return tb.mode if (tb and getattr(tb, "mode", "")) else ""

    def _deactivate_nav(self):
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
            self.set_tool(None)
            getattr(tb, action)()
        elif action == "home":
            tb.home()
        self._refresh_button_marks()

    def _refresh_button_marks(self):
        nav = self._nav_active()
        for name, b in self._tool_buttons.items():
            on = (name == self.tool) or \
                 (name == "zoom" and "zoom" in nav) or \
                 (name == "pan" and "pan" in nav)
            b.ax.set_facecolor("#ffd27f" if on else "0.85")
        self.fig.canvas.draw_idle()

    # ------------------------------------------------------------------
    def set_tool(self, t):
        if t in ("rasante", "select"):
            self._deactivate_nav()
        if not self._editing:
            self.pending = []
        self.tool = t
        title = {None: "ninguna", "rasante": "RASANTE",
                 "select": "SELECCIONAR"}.get(t, "-")
        if self._editing:
            title += " (EDITANDO: arrastra los puntos, CONFIRMAR al acabar)"
        self.ax.set_title(f"Herramienta: {title}    |    "
                          f"{len(self.rasantes)} rasantes", color="black")
        self._refresh_button_marks()
        self.redraw()

    def _pick_pending(self, e):
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
        if self._nav_active():
            return
        if self.tool == "rasante":
            hit = self._pick_pending(e)
            if hit is not None:
                self._drag = hit
            else:
                self.pending.append((e.xdata, e.ydata))
                self.redraw()
        elif self.tool == "select":
            self.selected = self._nearest_rasante(e.xdata)
            self.redraw()

    def on_motion(self, e):
        if self._drag is None or e.inaxes != self.ax or e.xdata is None:
            return
        self.pending[self._drag] = (e.xdata, e.ydata)
        self.redraw()

    def on_release(self, e):
        self._drag = None

    def commit(self):
        if self.tool != "rasante":
            return
        if len(self.pending) < 2:
            self._flash("una rasante necesita al menos 2 puntos", "#c33")
            return
        self.rasantes.append(pg.build_rasante(self.pending))
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
        if self.selected is None or self.selected >= len(self.rasantes):
            self._flash("selecciona antes una rasante", "#c33")
            return
        r = self.rasantes.pop(self.selected)
        self.selected = None
        self.pending = [tuple(p) for p in r.get("pts", [])]
        self._editing = True
        self.set_tool("rasante")

    def delete_selected(self):
        if self.selected is not None and self.selected < len(self.rasantes):
            self.rasantes.pop(self.selected)
        elif self.rasantes:
            self.rasantes.pop()
        self.selected = None
        self.set_tool(self.tool)

    def _nearest_rasante(self, s):
        best_d, best_i = 1e30, None
        for i, r in enumerate(self.rasantes):
            if r["s0"] <= s <= r["s1"]:
                return i
            d = min(abs(s - r["s0"]), abs(s - r["s1"]))
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
        # rasantes: recta verde sobre su tramo (la seleccionada, naranja)
        for i, r in enumerate(self.rasantes):
            col, lw = ("#1a9641", 2.4)
            if i == self.selected:
                col, lw = ("#ff8c00", 4.0)
            xs = [r["s0"], r["s1"]]
            ys = [r["g"] * x + r["b"] for x in xs]
            self._art += self.ax.plot(xs, ys, "-", color=col, lw=lw)
            self._art += self.ax.plot(xs, ys, "o", color=col, ms=4)
        # perfil de diseño ENSAMBLADO (rasantes + acuerdos parabólicos)
        if len(self.rasantes) >= 1:
            _, z, pivs = pg.assemble_profile(self.rasantes, self.L, self.step,
                                             z_terrain=self.z_terrain)
            self._art += self.ax.plot(self.stations[:len(z)], z, "-",
                                      color="#7b2d8e", lw=1.6, alpha=0.9)
            # vértices (PIV): intersección de rasantes contiguas (azul), sobre
            # el perfil de diseño ensamblado
            for (s, zz) in pivs:
                if 0 <= s < self.L:
                    self._art += self.ax.plot([s], [z[int(s / self.step)]],
                                              "v", color="#2c7fb8", ms=8)
        # ajuste provisional de la rasante en curso
        if self.tool == "rasante" and len(self.pending) >= 2:
            g, b = pg.fit_grade(self.pending)
            xs = [min(p[0] for p in self.pending),
                  max(p[0] for p in self.pending)]
            self._art += self.ax.plot(xs, [g * x + b for x in xs], "-",
                                      color="#ff8c00", lw=2.0, alpha=0.9)
        if self.pending:
            self._art += self.ax.plot([p[0] for p in self.pending],
                                      [p[1] for p in self.pending], "o",
                                      color="orange", ms=8, mew=1.5,
                                      mec="black")
        self.fig.canvas.draw_idle()

    # ------------------------------------------------------------------
    def save(self):
        import json
        try:
            json.dump([{"pts": r["pts"]} for r in self.rasantes],
                      open(self.pfl_path, "w"))
        except OSError as ex:
            self._flash(f"no se pudo guardar: {ex}", "#c33")
            return
        print(f"GUARDADO {len(self.rasantes)} rasantes en {self.pfl_path}")
        self.ax.set_title(f"✓ GUARDADO: {self.pfl_path}", color="#1a7d1a")
        self.fig.canvas.draw_idle()

    def load_rasantes(self):
        if not os.path.exists(self.pfl_path):
            return
        try:
            import json
            for d in json.load(open(self.pfl_path)):
                self.rasantes.append(pg.build_rasante(d["pts"]))
            print(f"reanudadas {len(self.rasantes)} rasantes de "
                  f"{self.pfl_path}")
        except Exception as ex:
            print("no se pudieron cargar rasantes previas:", ex)

    def resolver(self):
        """Ensambla el perfil de diseño y lo integra en el track: escribe
        '<csv>_alzado.csv' con la κ de la planta + la cota de diseño."""
        if len(self.rasantes) < 1:
            self._flash("dibuja al menos una rasante", "#c33")
            return
        _, z, pivs = pg.assemble_profile(self.rasantes, self.L, self.step,
                                         z_terrain=self.z_terrain)
        out = os.path.splitext(self.csv_path)[0] + "_alzado.csv"
        try:
            with open(out, "w") as f:
                f.write("# Track con ALZADO de diseno (profile_editor):\n")
                f.write("# planta resuelta + rasantes y acuerdos parabolicos\n")
                f.write("# kappa_1pm,elev_m,kerb,peralte_rad (seg %.1f m)\n"
                        % self.step)
                for i in range(self.n):
                    zi = z[i] if i < len(z) else z[-1]
                    f.write("%.6f,%.2f,%d,%.4f\n"
                            % (self.kap[i], zi, self.kerb[i], self.bank[i]))
        except OSError as ex:
            self._flash(f"error al escribir: {ex}", "#c33")
            return
        gmax = max(abs((z[(i + 1) % len(z)] - z[i]) / self.step)
                   for i in range(len(z) - 1)) * 100
        print(f"RESUELTO alzado -> {out}: {len(self.rasantes)} rasantes, "
              f"{len(pivs)} acuerdos, pendiente max {gmax:.1f}%, "
              f"desnivel {max(z)-min(z):.0f} m")
        self.ax.set_title(f"✓ ALZADO integrado: {out}  (pend. max {gmax:.1f}%, "
                          f"desnivel {max(z)-min(z):.0f} m)", color="#7b2d8e")
        self.fig.canvas.draw_idle()

    def show(self):
        print(__doc__)
        plt.show()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        default = os.path.join(root, "simulator", "tracks", "spa_resuelto.csv")
        args = [default]
    ProfileEditor(args[0]).show()


if __name__ == "__main__":
    main()
