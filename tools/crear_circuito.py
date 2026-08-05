"""Lanzador del flujo completo de creación de circuitos (TUMFTM -> track).

Encadena las fases en orden, sin ir de comando en comando:

  1. Elige el CSV del eje central de TUMFTM (x_m,y_m,w_tr_right_m,w_tr_left_m)
     con un diálogo de archivo (empieza en tools/ejemplos/).
  2. GEORREFERENCIAR: colocas el trazado sobre la ortofoto (2 puntos + ajuste)
     y EXPORTAS. Al cerrar la ventana,
  3. se baja SOLA la altimetría del DEM y se construye el track (llevando los
     ANCHOS reales de TUMFTM a una 5ª columna), y
  4. ALZADO: dibujas las rasantes y RESUELVES; se escribe el track final
     (planta + alzado + anchos), listo para conducir.

Uso:
  python tools/crear_circuito.py            (abre el diálogo de archivo)
  python tools/crear_circuito.py Spa.csv    (salta el diálogo)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import georef as gr
import import_kml as ik
from georef_tool import GeorefTool
from profile_editor import ProfileEditor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EJEMPLOS = os.path.join(os.path.dirname(__file__), "ejemplos")
TRACKS = os.path.join(ROOT, "simulator", "tracks")


def load_halfwidths(csv_path):
    """Semiancho de calzada por punto (m) del CSV de TUMFTM, con el MISMO
    filtrado que georef.load_xy (para que casen 1:1 con los puntos del KML).
    (w_tr_right + w_tr_left) / 2. Devuelve None si el CSV no trae anchos."""
    ws = []
    any_w = False
    for ln in open(csv_path):
        ln = ln.strip()
        if not ln or ln.startswith("#") or ln.lower().startswith("x_m"):
            continue
        p = ln.replace(";", ",").split(",")
        if len(p) >= 4:
            try:
                ws.append((float(p[2]) + float(p[3])) / 2.0)
                any_w = True
                continue
            except ValueError:
                pass
        ws.append(None)
    if not any_w:
        return None
    med = sorted(w for w in ws if w is not None)[sum(w is not None
                                                     for w in ws) // 2]
    return [med if w is None else w for w in ws]


def pick_file():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title="Elige el eje de TUMFTM (x_m,y_m,...)",
            initialdir=EJEMPLOS if os.path.isdir(EJEMPLOS) else ROOT,
            filetypes=[("CSV de TUMFTM", "*.csv"), ("Todos", "*.*")])
        root.destroy()
        return path
    except Exception as ex:
        print("no se pudo abrir el diálogo de archivo:", ex)
        return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = args[0] if args else pick_file()
    if not src:
        print("no se eligió ningún archivo.")
        return
    src = os.path.abspath(src)
    name = os.path.splitext(os.path.basename(src))[0]
    name = name.replace("_TUMFTM", "").replace("_tumftm", "").lower()
    os.makedirs(TRACKS, exist_ok=True)
    kml = os.path.join(TRACKS, name + ".kml")
    track_csv = os.path.join(TRACKS, name + ".csv")

    # anchos por punto (para llevarlos hasta el track)
    try:
        widths = load_halfwidths(src)
    except Exception:
        widths = None

    # ---- fase 1: georreferenciar (bloquea hasta cerrar la ventana) -------
    reuse = False
    if os.path.exists(kml):
        ans = input(f"\nYa existe {os.path.basename(kml)}. ¿Reutilizar esa "
                    f"georreferencia y saltar a la altimetría? (s/n): ")
        reuse = ans.strip().lower().startswith("s")
    if not reuse:
        if os.path.exists(kml):
            os.remove(kml)
        print("\n[1/3] GEORREFERENCIA: coloca el trazado y pulsa EXPORTAR KML.")
        try:
            GeorefTool(src, kml).show()
        except ValueError as ex:
            print("ERROR:", ex)
            return
        if not os.path.exists(kml):
            print("no exportaste el KML; se cancela el flujo.")
            return

    # ---- fase 2: altimetría + anchos -> track ----------------------------
    print("[2/3] Bajando altimetría del DEM y construyendo el track…")
    lines = ik.parse_kml_lines(kml)
    pts = max(lines, key=len)
    w = widths if (widths and len(widths) == len(pts)) else None
    if widths and w is None:
        print(f"  aviso: {len(widths)} anchos vs {len(pts)} puntos del KML; "
              "no cuadran, sigo sin anchos")
    n, total = ik.build_track(pts, track_csv, widths=w)
    print(f"  {track_csv}: {n} segmentos, {total:.0f} m"
          + ("  (con anchos reales)" if w else ""))

    # ---- fase 3: alzado (bloquea) ----------------------------------------
    print("[3/3] ALZADO: dibuja las rasantes y pulsa RESOLVER.")
    ProfileEditor(track_csv).show()
    final = os.path.splitext(track_csv)[0] + "_alzado.csv"
    if os.path.exists(final):
        print(f"\n✓ LISTO: {final}\n  Ponlo en config.py TRACK_FILE para "
              f"conducirlo (ruta relativa a simulator/): "
              f"tracks/{os.path.basename(final)}")
    else:
        print(f"\nTrack sin alzado en {track_csv} (no resolviste el alzado).")


if __name__ == "__main__":
    main()
