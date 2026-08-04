"""Visor de georreferenciación (planta métrica de TUMFTM -> lat/lon).

Flujo, todo en la ventana:
  1. Se dibuja la planta del CSV con índices marcados.
  2. Pulsa PUNTO 1 y pincha en la planta un sitio reconocible (meta, una
     curva); abajo pega su coordenada de Google Earth en el cuadro (formato
     50°26'29.58"N 5°57'59.57"E o decimal). Igual con PUNTO 2.
  3. VER SATÉLITE calcula la georreferencia y superpone la planta sobre la
     ortofoto (Esri World Imagery, servidor público) para que veas si calza.
  4. EXPORTAR KML guarda el trazado georreferenciado (lat/lon); luego
     import_kml le baja la altimetría y profile_editor ajusta el alzado.

IMPORTANTE: la entrada es el eje central MÉTRICO de TUMFTM (columnas
x_m,y_m,...), que bajas de github.com/TUMFTM/racetrack-database. NO es el
track ya convertido de simulator/tracks/ (ese es kappa,elev,... y no vale).
Hay un ejemplo listo en tools/ejemplos/Silverstone_TUMFTM.csv.

Uso:
  python tools/georef_tool.py tools/ejemplos/Silverstone_TUMFTM.csv
  python tools/georef_tool.py Spa.csv --salida=spa.kml
"""

import io
import math
import os
import sys
import urllib.request

import matplotlib
for _k in [k for k in matplotlib.rcParams if k.startswith("keymap.")]:
    matplotlib.rcParams[_k] = []
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, TextBox

sys.path.insert(0, os.path.dirname(__file__))
import georef as gr

R_EARTH = 6378137.0
C_MERC = math.pi * R_EARTH


def read_clipboard(fig=None):
    """Lee texto del portapapeles del sistema (la caja de texto de matplotlib
    no admite pegar). Prueba Tk y, si no, órdenes del sistema operativo."""
    if fig is not None:
        try:
            return fig.canvas.get_tk_widget().clipboard_get()
        except Exception:
            pass
    try:
        import tkinter as tk
        r = tk._default_root or tk.Tk()
        return r.clipboard_get()
    except Exception:
        pass
    import subprocess
    try:
        if sys.platform.startswith("win"):
            return subprocess.check_output(
                ["powershell", "-command", "Get-Clipboard"], text=True)
        if sys.platform == "darwin":
            return subprocess.check_output(["pbpaste"], text=True)
        for cmd in (["xclip", "-selection", "clipboard", "-o"],
                    ["xsel", "--clipboard", "--output"]):
            try:
                return subprocess.check_output(cmd, text=True)
            except Exception:
                continue
    except Exception:
        pass
    return None


def mercator(lat, lon):
    x = math.radians(lon) * R_EARTH
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R_EARTH
    return x, y


def deg2tile(lat, lon, z):
    n = 2 ** z
    xt = (lon + 180.0) / 360.0 * n
    latr = math.radians(lat)
    yt = (1 - math.log(math.tan(latr) + 1 / math.cos(latr)) / math.pi) / 2 * n
    return xt, yt


def tile_merc_extent(xt, yt, z):
    n = 2 ** z
    x0 = xt / n * 2 * C_MERC - C_MERC
    x1 = (xt + 1) / n * 2 * C_MERC - C_MERC
    y1 = C_MERC - yt / n * 2 * C_MERC
    y0 = C_MERC - (yt + 1) / n * 2 * C_MERC
    return x0, x1, y0, y1


def fetch_esri_mosaic(latlon, pad=0.25, max_tiles=7):
    """Descarga un mosaico de ortofoto (Esri World Imagery) que cubre el
    trazado. Devuelve (imagen_np, extent_merc) o None si no hay red."""
    import numpy as np
    from PIL import Image
    lats = [p[0] for p in latlon]
    lons = [p[1] for p in latlon]
    dlat = (max(lats) - min(lats)) * pad
    dlon = (max(lons) - min(lons)) * pad
    la0, la1 = min(lats) - dlat, max(lats) + dlat
    lo0, lo1 = min(lons) - dlon, max(lons) + dlon
    z = 17
    while z > 10:
        x0, y1 = deg2tile(la0, lo0, z)
        x1, y0 = deg2tile(la1, lo1, z)
        xa, xb = int(min(x0, x1)), int(max(x0, x1))
        ya, yb = int(min(y0, y1)), int(max(y0, y1))
        if (xb - xa + 1) <= max_tiles and (yb - ya + 1) <= max_tiles:
            break
        z -= 1
    cols, rows = xb - xa + 1, yb - ya + 1
    mosaic = Image.new("RGB", (cols * 256, rows * 256))
    url = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
           "World_Imagery/MapServer/tile/{z}/{y}/{x}")
    try:
        for j, yt in enumerate(range(ya, yb + 1)):
            for i, xt in enumerate(range(xa, xb + 1)):
                req = urllib.request.Request(
                    url.format(z=z, y=yt, x=xt),
                    headers={"User-Agent": "cardrivingsim-georef"})
                data = urllib.request.urlopen(req, timeout=20).read()
                tile = Image.open(io.BytesIO(data)).convert("RGB")
                mosaic.paste(tile, (i * 256, j * 256))
    except Exception as ex:
        print("sin ortofoto (¿sin red?):", ex)
        return None
    ex0, _, _, ey1 = tile_merc_extent(xa, ya, z)
    _, ex1, ey0, _ = tile_merc_extent(xb, yb, z)
    return np.asarray(mosaic), (ex0, ex1, ey0, ey1)


class GeorefTool:
    def __init__(self, csv_path, out_path):
        self.csv_path = os.path.abspath(csv_path)
        self.out_path = out_path
        self.pts = gr.load_xy(csv_path)
        self.ctrl = {1: {"idx": None, "ll": None},
                     2: {"idx": None, "ll": None}}
        self.picking = None

        self.fig = plt.figure(figsize=(13.5, 8.5))
        self.ax = self.fig.add_axes([0.30, 0.08, 0.68, 0.88])
        self.ax.set_aspect("equal")
        xs = [p[0] for p in self.pts] + [self.pts[0][0]]
        ys = [p[1] for p in self.pts] + [self.pts[0][1]]
        self.ax.plot(xs, ys, "-", color="#333", lw=1.4)
        # índices de referencia (dispersos) para orientarse
        stepi = max(1, len(self.pts) // 36)
        for i in range(0, len(self.pts), stepi):
            self.ax.annotate(str(i), self.pts[i], fontsize=7, color="#c33")
            self.ax.plot(*self.pts[i], ".", color="#c33", ms=3)
        self.ax.set_title("Pulsa PUNTO 1 / PUNTO 2 y pincha un sitio "
                          "reconocible; pega su coordenada de Google Earth")
        self._marks = []
        self._build_widgets()
        self.fig.canvas.mpl_connect("button_press_event", self.on_click)

    def _build_widgets(self):
        self._w = []
        def btn(x, y, w, h, label, cb):
            axb = self.fig.add_axes([x, y, w, h])
            b = Button(axb, label)
            b.on_clicked(cb)
            self._w.append(b)
            return b
        def txt(x, y, w, h, label, cb):
            axb = self.fig.add_axes([x, y, w, h])
            t = TextBox(axb, label, textalignment="left")
            t.on_submit(cb)
            self._w.append(t)
            return t

        self.b1 = btn(0.02, 0.86, 0.115, 0.06, "PUNTO 1",
                      lambda e: self._start_pick(1))
        btn(0.145, 0.86, 0.115, 0.06, "PEGAR 1",
            lambda e: self._paste_coord(1))
        self.t1 = txt(0.02, 0.79, 0.24, 0.05, "coord 1: ",
                      lambda s: self._set_coord(1, s))
        self.b2 = btn(0.02, 0.70, 0.115, 0.06, "PUNTO 2",
                      lambda e: self._start_pick(2))
        btn(0.145, 0.70, 0.115, 0.06, "PEGAR 2",
            lambda e: self._paste_coord(2))
        self.t2 = txt(0.02, 0.63, 0.24, 0.05, "coord 2: ",
                      lambda s: self._set_coord(2, s))
        btn(0.02, 0.52, 0.24, 0.07, "VER SATÉLITE",
            lambda e: self.ver_satelite())
        btn(0.02, 0.42, 0.24, 0.07, "EXPORTAR KML",
            lambda e: self.exportar())
        self._nav_buttons = {
            "zoom": btn(0.02, 0.33, 0.075, 0.055, "ZOOM",
                        lambda e: self._toolbar("zoom")),
            "pan": btn(0.105, 0.33, 0.075, 0.055, "MOVER",
                       lambda e: self._toolbar("pan")),
        }
        btn(0.19, 0.33, 0.075, 0.055, "VISTA",
            lambda e: self._toolbar("home"))
        self.status = self.fig.text(0.02, 0.10, "", fontsize=9, wrap=True)
        self._refresh_status()

    # ---- navegación (zoom/mover del backend, sin dejarlos pegados) -----
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
            self.picking = None
            getattr(tb, action)()
        elif action == "home":
            tb.home()
        self._refresh_nav_marks()

    def _refresh_nav_marks(self):
        nav = self._nav_active()
        for name, b in self._nav_buttons.items():
            b.ax.set_facecolor("#ffd27f" if name in nav else "0.85")
        self.fig.canvas.draw_idle()

    def _start_pick(self, n):
        self._deactivate_nav()          # al elegir punto, soltar zoom/mover
        self._refresh_nav_marks()
        self.picking = n
        self.ax.set_title(f"PUNTO {n}: pincha en la planta el sitio "
                          f"reconocible", color="#1a7")
        self.fig.canvas.draw_idle()

    def on_click(self, e):
        if self.picking is None or e.inaxes != self.ax or e.xdata is None:
            return
        if self._nav_active():          # zoom/mover manda: no elegir punto
            return
        # índice del punto del CSV más cercano al clic
        i = min(range(len(self.pts)),
                key=lambda k: (self.pts[k][0] - e.xdata) ** 2
                + (self.pts[k][1] - e.ydata) ** 2)
        self.ctrl[self.picking]["idx"] = i
        self.picking = None
        self._draw_marks()
        self._refresh_status()

    def _set_coord(self, n, s):
        if not s.strip():
            return
        try:
            self.ctrl[n]["ll"] = gr.parse_coord(s)
        except ValueError as ex:
            self.status.set_text(str(ex))
            self.fig.canvas.draw_idle()
            return
        self._refresh_status()

    def _paste_coord(self, n):
        """Pega la coordenada del portapapeles (copiada en Google Earth) en el
        punto n, sin teclear."""
        txt = read_clipboard(self.fig)
        if not txt or not txt.strip():
            self.status.set_text("portapapeles vacío: copia antes la "
                                 "coordenada en Google Earth")
            self.fig.canvas.draw_idle()
            return
        txt = txt.strip().splitlines()[0]
        try:
            self.ctrl[n]["ll"] = gr.parse_coord(txt)
        except ValueError:
            self.status.set_text(f"no se pudo interpretar del portapapeles: "
                                 f"{txt!r}")
            self.fig.canvas.draw_idle()
            return
        tb = self.t1 if n == 1 else self.t2
        try:
            tb.set_val(txt)
        except Exception:
            pass
        self._refresh_status()

    def _draw_marks(self):
        for m in self._marks:
            m.remove()
        self._marks = []
        for n, c in self.ctrl.items():
            if c["idx"] is not None:
                p = self.pts[c["idx"]]
                self._marks += self.ax.plot(*p, "o", color="#1a7", ms=12,
                                            mfc="none", mew=2.5)
                self._marks.append(self.ax.annotate(
                    f"P{n} (i={c['idx']})", p, color="#1a7",
                    fontsize=10, fontweight="bold"))
        self.fig.canvas.draw_idle()

    def _refresh_status(self):
        def one(n):
            c = self.ctrl[n]
            i = "—" if c["idx"] is None else str(c["idx"])
            ll = "—" if c["ll"] is None else \
                f"{c['ll'][0]:.5f}, {c['ll'][1]:.5f}"
            return f"P{n}: índice={i}  lat/lon={ll}"
        self.status.set_text(one(1) + "\n" + one(2))
        self.fig.canvas.draw_idle()

    def _ready(self):
        return all(self.ctrl[n]["idx"] is not None and
                   self.ctrl[n]["ll"] is not None for n in (1, 2))

    def _georef(self):
        A = self.ctrl[1]
        B = self.ctrl[2]
        return gr.georef_points(self.pts, self.pts[A["idx"]], A["ll"],
                                self.pts[B["idx"]], B["ll"])

    def ver_satelite(self):
        if not self._ready():
            self.status.set_text("faltan los 2 puntos (índice + coordenada)")
            self.fig.canvas.draw_idle()
            return
        latlon = self._georef()
        self.status.set_text("descargando ortofoto…")
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()
        moza = fetch_esri_mosaic(latlon)
        fig2, ax2 = plt.subplots(figsize=(9, 9))
        mx = [mercator(la, lo)[0] for la, lo in latlon]
        my = [mercator(la, lo)[1] for la, lo in latlon]
        if moza is not None:
            img, ext = moza
            ax2.imshow(img, extent=ext, origin="upper")
        ax2.plot(mx + [mx[0]], my + [my[0]], "-", color="#ffcc00", lw=2.0)
        for n in (1, 2):
            la, lo = self.ctrl[n]["ll"]
            x, y = mercator(la, lo)
            ax2.plot(x, y, "o", color="#1a7", ms=10, mfc="none", mew=2.5)
        ax2.set_aspect("equal")
        ax2.set_title("Planta georreferenciada sobre ortofoto (amarillo). "
                      "Si calza, EXPORTA en la otra ventana.")
        ax2.set_xticks([])
        ax2.set_yticks([])
        fig2.tight_layout()
        plt.show(block=False)

    def exportar(self):
        if not self._ready():
            self.status.set_text("faltan los 2 puntos (índice + coordenada)")
            self.fig.canvas.draw_idle()
            return
        latlon = self._georef()
        name = os.path.splitext(os.path.basename(self.out_path))[0]
        gr.write_kml(latlon, os.path.abspath(self.out_path), name)
        _, _, _, scale, _ = gr.similarity(
            self.pts[self.ctrl[1]["idx"]], self.ctrl[1]["ll"],
            self.pts[self.ctrl[2]["idx"]], self.ctrl[2]["ll"])
        msg = (f"✓ EXPORTADO {os.path.abspath(self.out_path)}  "
               f"(escala CSV→m = {scale:.4f}). "
               f"Ahora: import_kml.py para bajar la altimetría.")
        print(msg)
        self.status.set_text(msg)
        self.ax.set_title("✓ KML georreferenciado exportado", color="#1a7d1a")
        self.fig.canvas.draw_idle()

    def show(self):
        print(__doc__)
        plt.show()


def main():
    argv = sys.argv[1:]
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    out = os.path.splitext(args[0])[0] + ".kml"
    for a in argv:
        if a.startswith("--salida="):
            out = a.split("=", 1)[1]
    try:
        tool = GeorefTool(args[0], out)
    except ValueError as ex:
        print("\nERROR:", ex, "\n")
        raise SystemExit(1)
    tool.show()


if __name__ == "__main__":
    main()
