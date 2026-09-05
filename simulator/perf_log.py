"""Registro de RENDIMIENTO (tecla F3 o --registro): mide cuanto cuesta cada
parte del fotograma y anota, junto a cada medida, QUE hay en pantalla.

El problema que resuelve: los numeros del panel F1 saltan de fotograma en
fotograma y no se pueden apuntar a mano; y para comparar "con telemetria" y
"sin telemetria" hay que recordar que se tenia activado en cada momento.
Aqui lo hace el programa:

  - cada segundo escribe una fila en un CSV con la media, la mediana, el
    percentil 95 y el maximo del fotograma, el desglose por fases (entrada,
    fisica, sonido, escena, coche, HUD, presentar) y los tiempos de la GPU,
  - en la misma fila va la CONFIGURACION de pantalla en ese instante (vista,
    telemetria, velocimetro de aguja, minimapa, planta, trazada, particulas,
    fantasma, bruma, sombreado, GPU, MSAA, tamano de ventana, coche,
    circuito, asfalto, camara lenta): al pulsar F2 o cambiar de vista las
    filas siguientes ya lo reflejan, sin tocar nada,
  - al parar (F3 otra vez, ESC o cerrar) escribe un RESUMEN legible: los
    datos del equipo y una tabla con una linea por cada configuracion
    distinta que se ha tenido, con lo que cambia respecto a la primera y su
    coste. Asi se empieza con la pantalla limpia, se van anadiendo cosas y
    al final se lee cuanto cuesta cada una.

El tiempo de "presentar" incluye la espera del vsync: con la sincronia
vertical un fotograma no baja de 16,7 ms aunque el trabajo sean 4 ms. Por
eso se anota tambien el TRABAJO (todo menos presentar), que es lo que de
verdad mide el coste de lo que hay en pantalla.

Los archivos van a la carpeta del proyecto (rendimiento_FECHA_HORA.csv y
.txt) y estan en .gitignore: son de cada maquina.
"""

import csv
import datetime
import os
import platform
import statistics
import time

from . import config as cfg

# fases del fotograma, en el orden en que las marca el bucle principal
FASES = ("entrada", "fisica", "sonido", "escena", "coche", "hud",
         "presentar")

# claves de la configuracion en el orden en que se escriben; el valor es
# el rotulo que sale en el resumen
CLAVES = (
    ("ventana", "VENTANA"),
    ("completa", "PANTALLA COMPLETA"),
    ("gpu", "GPU"),
    ("msaa", "MSAA"),
    ("vista", "VISTA"),
    ("telemetria", "TELEMETRIA F2"),
    ("diagnostico", "PANEL F1"),
    ("aguja", "VELOCIMETRO AGUJA"),
    ("aguja_px", "TAMANO AGUJA"),
    ("minimapa", "MINIMAPA"),
    ("planta", "PLANTA"),
    ("trazada", "TRAZADA"),
    ("particulas", "PARTICULAS"),
    ("fantasma", "FANTASMA"),
    ("bruma_m", "BRUMA M"),
    ("sombreado", "SOMBREADO"),
    ("sol", "SOL"),
    ("camara_lenta", "CAMARA LENTA"),
    ("coche", "COCHE"),
    ("circuito", "CIRCUITO"),
    ("asfalto", "ASFALTO"),
)

VISTAS = ("INTERIOR", "TRASERA", "COCHE 3D")
INTERVALO_S = 1.0        # cada cuanto se escribe una fila del CSV


def _si(v):
    return "SI" if v else "NO"


def contexto(gpu, view_mode, show_telemetry, show_debug, show_minimap,
             show_plan, show_line, time_scale, car_name, track_name,
             condition):
    """Foto de lo que hay en pantalla ahora mismo. La construye el bucle
    principal con sus variables de estado y lo que diga config."""
    return {
        "ventana": f"{cfg.WINDOW_WIDTH}x{cfg.WINDOW_HEIGHT}",
        "completa": _si(getattr(cfg, "WINDOW_FULLSCREEN", False)),
        "gpu": _si(gpu is not None),
        "msaa": int(getattr(cfg, "GFX_MSAA", 0)) if gpu is not None else 0,
        "vista": VISTAS[view_mode % len(VISTAS)],
        "telemetria": _si(show_telemetry),
        "diagnostico": _si(show_debug),
        "aguja": _si(getattr(cfg, "SPEEDO_DIAL", False)),
        "aguja_px": int(getattr(cfg, "SPEEDO_SIZE", 0)),
        "minimapa": _si(show_minimap),
        "planta": _si(show_plan),
        "trazada": _si(show_line),
        "particulas": _si(getattr(cfg, "PARTICLES_ENABLED", False)),
        "fantasma": _si(getattr(cfg, "GHOST_ENABLED", False)),
        "bruma_m": int(getattr(cfg, "GFX_FOG_DIST", 0)),
        "sombreado": f"{getattr(cfg, 'GFX_SUN_SHADE', 0.0):.2f}",
        "sol": _si(getattr(cfg, "GFX_SUN", False)),
        "camara_lenta": f"{time_scale:g}",
        "coche": car_name,
        "circuito": track_name,
        "asfalto": condition,
    }


def _p(valores, q):
    """Percentil q (0..100) por interpolacion lineal, sin numpy."""
    if not valores:
        return 0.0
    v = sorted(valores)
    k = (len(v) - 1) * q / 100.0
    i = int(k)
    f = k - i
    if i + 1 < len(v):
        return v[i] + (v[i + 1] - v[i]) * f
    return v[i]


class _Bloque:
    """Una configuracion de pantalla y todos los fotogramas medidos con ella."""

    def __init__(self, ctx, t_inicio):
        self.ctx = dict(ctx)
        self.t_inicio = t_inicio
        self.t_fin = t_inicio
        self.total = []                       # ms por fotograma
        self.trabajo = []                     # ms sin la espera de presentar
        self.fases = {f: 0.0 for f in FASES}  # suma de ms por fase
        self.gpu = {"malla": 0.0, "gl": 0.0, "subida": 0.0}
        self.n = 0

    def anadir(self, total_ms, fases_ms, gpu_ms, t):
        self.total.append(total_ms)
        self.trabajo.append(total_ms - fases_ms.get("presentar", 0.0))
        for f, v in fases_ms.items():
            self.fases[f] = self.fases.get(f, 0.0) + v
        for k, v in gpu_ms.items():
            self.gpu[k] += v
        self.n += 1
        self.t_fin = t

    @property
    def duracion(self):
        return self.t_fin - self.t_inicio

    def media(self, f):
        return self.fases.get(f, 0.0) / self.n if self.n else 0.0

    def media_gpu(self, k):
        return self.gpu.get(k, 0.0) / self.n if self.n else 0.0

    def fps(self):
        return 1000.0 * self.n / sum(self.total) if self.total else 0.0


class RegistroRendimiento:
    """Acumula fotogramas mientras esta activo; escribe el CSV a medida y el
    resumen al parar. Cuando NO esta activo todas las llamadas vuelven de
    inmediato: no cuesta nada llevarlo en el bucle."""

    def __init__(self, carpeta=None, reloj=None):
        self.carpeta = carpeta or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..")
        self._reloj = reloj or time.perf_counter
        self.activo = False
        self.equipo = {}
        self.ruta_csv = self.ruta_txt = None
        self._csv = None
        self._escritor = None
        self._t0 = 0.0
        self._t_marca = 0.0
        self._t_fila = 0.0
        self._fases = {}
        self._bloques = []
        self._fila_total = []
        self._fila_fases = {f: 0.0 for f in FASES}
        self._fila_gpu = {"malla": 0.0, "gl": 0.0, "subida": 0.0}
        self._fila_n = 0
        self._fila_v = 0.0
        self._filas = 0

    # ---------------------------------------------------------------- equipo
    def describir_equipo(self, renderer_sdl="?", gpu=None):
        """Datos fijos de la maquina: van en la cabecera del resumen."""
        info = getattr(gpu, "info", {}) if gpu is not None else {}
        self.equipo = {
            "SISTEMA": f"{platform.system()} {platform.release()}",
            "PYTHON": platform.python_version(),
            "CPU": platform.processor() or platform.machine() or "?",
            "NUCLEOS": str(os.cpu_count() or "?"),
            "RENDER SDL": renderer_sdl,
            "RENDER GPU": (f"{info.get('GL_RENDERER', '?')} | "
                           f"{info.get('GL_VERSION', '?')}"
                           if gpu is not None else "no"),
            "VENTANA": f"{cfg.WINDOW_WIDTH}x{cfg.WINDOW_HEIGHT}",
        }
        return self.equipo

    # ---------------------------------------------------------- arrancar/parar
    def alternar(self):
        if self.activo:
            self.parar()
        else:
            self.arrancar()
        return self.activo

    def arrancar(self):
        if self.activo:
            return
        sello = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(self.carpeta, f"rendimiento_{sello}")
        k = 1
        while os.path.exists(base + ".csv"):     # dos en el mismo segundo
            k += 1
            base = os.path.join(self.carpeta, f"rendimiento_{sello}_{k}")
        self.ruta_csv = base + ".csv"
        self.ruta_txt = base + ".txt"
        self._csv = open(self.ruta_csv, "w", newline="", encoding="utf-8")
        self._escritor = csv.writer(self._csv, delimiter=";")
        self._escritor.writerow(
            ["t_s", "fps", "ms_media", "ms_mediana", "ms_p95", "ms_max",
             "ms_trabajo"] + [f"ms_{f}" for f in FASES]
            + ["ms_gpu_malla", "ms_gpu_gl", "ms_gpu_subida", "fotogramas",
               "velocidad_kmh"] + [k for k, _ in CLAVES])
        self._t0 = self._reloj()
        self._t_fila = self._t0
        self._bloques = []
        self._filas = 0
        self._vaciar_fila()
        self.activo = True
        print(f"Registro de rendimiento: GRABANDO en {self.ruta_csv}")

    def parar(self):
        if not self.activo:
            return
        self._volcar_fila(self._reloj())
        self.activo = False
        self._csv.close()
        self._csv = self._escritor = None
        self._escribir_resumen()
        print(f"Registro de rendimiento: parado. Resumen en {self.ruta_txt}")

    def cerrar(self):
        self.parar()

    # ---------------------------------------------------------------- medida
    def inicio(self):
        """Principio del fotograma."""
        if not self.activo:
            return
        self._t_marca = self._reloj()
        self._fases = {}

    def marca(self, fase):
        """Fin de una fase: apunta lo que ha pasado desde la marca anterior."""
        if not self.activo:
            return
        t = self._reloj()
        self._fases[fase] = self._fases.get(fase, 0.0) + (t - self._t_marca) * 1000.0
        self._t_marca = t

    def fotograma(self, ctx, gpu=None, velocidad_kmh=0.0):
        """Fin del fotograma: suma las fases y anota la configuracion."""
        if not self.activo:
            return
        t = self._reloj()
        total = sum(self._fases.values())
        gpu_ms = {"malla": getattr(gpu, "ms_malla", 0.0),
                  "gl": getattr(gpu, "ms_gl", 0.0),
                  "subida": getattr(gpu, "ms_subida", 0.0)}
        if not self._bloques or self._bloques[-1].ctx != ctx:
            # cambio de configuracion: la fila en curso se cierra para que
            # no mezcle dos situaciones
            if self._bloques:
                self._volcar_fila(t)
            self._bloques.append(_Bloque(ctx, t))
        self._bloques[-1].anadir(total, self._fases, gpu_ms, t)
        self._fila_total.append(total)
        for f, v in self._fases.items():
            self._fila_fases[f] = self._fila_fases.get(f, 0.0) + v
        for k, v in gpu_ms.items():
            self._fila_gpu[k] += v
        self._fila_n += 1
        self._fila_v += velocidad_kmh
        if t - self._t_fila >= INTERVALO_S:
            self._volcar_fila(t)

    def segundos(self):
        return self._reloj() - self._t0 if self.activo else 0.0

    # ------------------------------------------------------------------ CSV
    def _vaciar_fila(self):
        self._fila_total = []
        self._fila_fases = {f: 0.0 for f in FASES}
        self._fila_gpu = {"malla": 0.0, "gl": 0.0, "subida": 0.0}
        self._fila_n = 0
        self._fila_v = 0.0

    def _volcar_fila(self, t):
        n = self._fila_n
        if n == 0 or self._escritor is None:
            self._t_fila = t
            return
        tot = self._fila_total
        media = sum(tot) / n
        presentar = self._fila_fases.get("presentar", 0.0) / n
        ctx = self._bloques[-1].ctx if self._bloques else {}
        fila = [f"{t - self._t0:.1f}",
                f"{1000.0 * n / sum(tot):.1f}",
                f"{media:.2f}", f"{statistics.median(tot):.2f}",
                f"{_p(tot, 95):.2f}", f"{max(tot):.2f}",
                f"{media - presentar:.2f}"]
        fila += [f"{self._fila_fases.get(f, 0.0) / n:.2f}" for f in FASES]
        fila += [f"{self._fila_gpu[k] / n:.2f}" for k in ("malla", "gl", "subida")]
        fila += [str(n), f"{self._fila_v / n:.0f}"]
        fila += [str(ctx.get(k, "")) for k, _ in CLAVES]
        self._escritor.writerow(fila)
        self._csv.flush()
        self._filas += 1
        self._t_fila = t
        self._vaciar_fila()

    # -------------------------------------------------------------- resumen
    def _diferencias(self, ctx, base):
        return [f"{rot} {ctx[k]}" for k, rot in CLAVES
                if ctx.get(k) != base.get(k)]

    def resumen(self):
        """Texto del resumen (tambien lo devuelve para las pruebas)."""
        lineas = ["REGISTRO DE RENDIMIENTO - Car Driving Simulator "
                  f"{getattr(cfg, 'VERSION', '')}".rstrip(),
                  datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), ""]
        lineas.append("EQUIPO")
        for k, v in self.equipo.items():
            lineas.append(f"  {k:<11} {v}")
        lineas.append("")
        if not self._bloques:
            lineas.append("Sin fotogramas medidos.")
            return "\n".join(lineas) + "\n"
        base = self._bloques[0].ctx
        lineas.append("CONFIGURACION DE PARTIDA (bloque 1)")
        for k, rot in CLAVES:
            lineas.append(f"  {rot:<18} {base.get(k, '')}")
        lineas.append("")
        lineas.append("COSTE POR CONFIGURACION (ms por fotograma; 'trabajo' = "
                      "todo menos la espera del vsync)")
        cab = (f"  {'#':>2} {'seg':>5} {'fps':>5} {'media':>6} {'p95':>6} "
               f"{'max':>6} {'trabaj':>6} | {'escena':>6} {'coche':>5} "
               f"{'hud':>5} {'fisica':>6} | {'malla':>5} {'gl':>5} "
               f"{'subida':>6}  CAMBIOS RESPECTO AL BLOQUE 1")
        lineas.append(cab)
        lineas.append("  " + "-" * (len(cab) - 2))
        for i, b in enumerate(self._bloques, 1):
            if b.n == 0:
                continue
            difs = self._diferencias(b.ctx, base)
            lineas.append(
                f"  {i:>2} {b.duracion:5.1f} {b.fps():5.1f} "
                f"{sum(b.total) / b.n:6.2f} {_p(b.total, 95):6.2f} "
                f"{max(b.total):6.2f} {sum(b.trabajo) / b.n:6.2f} | "
                f"{b.media('escena'):6.2f} {b.media('coche'):5.2f} "
                f"{b.media('hud'):5.2f} {b.media('fisica'):6.2f} | "
                f"{b.media_gpu('malla'):5.2f} {b.media_gpu('gl'):5.2f} "
                f"{b.media_gpu('subida'):6.2f}  "
                + (", ".join(difs) if difs else "(igual que el bloque 1)"))
        lineas.append("")
        lineas.append("Como leerlo: compara 'trabaj' entre bloques. Si al activar "
                      "algo sube 3 ms, eso cuesta.")
        lineas.append("Con vsync la 'media' no baja de 16,7 ms (60 Hz) aunque el "
                      "trabajo sea mucho menor;")
        lineas.append("si 'trabaj' supera 16,7 ms el juego ya no llega a 60 fps y "
                      "se nota en la fluidez.")
        lineas.append(f"Detalle por segundos en {os.path.basename(self.ruta_csv)} "
                      "(separado por ';', se abre en una hoja de calculo).")
        return "\n".join(lineas) + "\n"

    def _escribir_resumen(self):
        with open(self.ruta_txt, "w", encoding="utf-8") as f:
            f.write(self.resumen())
