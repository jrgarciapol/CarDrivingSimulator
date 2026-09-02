"""LABORATORIO DE SONIDO: afinar el sintetizador oyéndolo en directo.

El motor y los neumáticos no son grabaciones: se sintetizan en cada
fotograma. Eso significa que su timbre son NÚMEROS, y que se pueden cambiar
mientras suenan. Esta pantalla es un banco de pruebas para hacerlo:

  - Todos los parámetros de sonido de ``config.py`` en una lista, con su
    explicación y su rango normal.
  - Un motor de mentira al que se le da gas para oír el cambio al momento,
    sin salir a la carretera ni tener que provocar un derrape.
  - Interruptores para oír AISLADO cada sonido de neumático: el chirrido
    lateral, el patinaje de tracción y el bloqueo de frenada suenan casi
    siempre a la vez conduciendo, y así no hay quien los afine.

Lo que se cambia aquí se guarda como el resto de la configuración: al
volver al menú ya está aplicado, y sigue estándolo la próxima vez.

Controles
  arriba/abajo   moverse            izquierda/derecha  ajustar
  MAYUS+flecha   paso grande        D                  valor por defecto
  ESPACIO        dar gas            F5                 todos por defecto
  1 2 3          chirrido / patinaje / bloqueo
  4              aviso ADAS         V                  viento
  ESC            volver
"""

import ctypes

import sdl2

from . import config as cfg
from . import font
from . import settings
from .tuning import _ascii, _fmt, _step, _wrap_text, get_entries

#: Secciones de config.py que se editan aquí.
_SECCIONES = ("SONIDO", "ADAS")

#: La frecuencia de muestreo no se puede cambiar en caliente: se fija al
#: abrir el dispositivo de audio y cambiarla a mitad de reproducción solo
#: haría que todo sonase a destiempo. Se edita en AJUSTES AVANZADOS.
_EXCLUIDOS = {"AUDIO_RATE"}

#: Régimen máximo del motor de pruebas.
_RPM_MAX = 7200.0
_RPM_RALENTI = 900.0


def _parametros():
    """Los parámetros de sonido, en el orden en que están en config.py,
    agrupados por su sección."""
    grupos = []
    for e in get_entries():
        sec = e["section"]
        if not any(sec.startswith(s) for s in _SECCIONES):
            continue
        if e["name"] in _EXCLUIDOS:
            continue
        if not grupos or grupos[-1][0] != sec:
            grupos.append((sec, []))
        grupos[-1][1].append(e)
    return grupos


def _filas(grupos):
    """Aplana los grupos en filas de pantalla. Una fila es ('sec', titulo)
    —no seleccionable— o ('par', entrada)."""
    filas = []
    for sec, ents in grupos:
        filas.append(("sec", sec))
        for e in ents:
            filas.append(("par", e))
    return filas


class _Banco:
    """El coche de mentira: un motor al que dar gas y unos neumáticos que se
    pueden hacer chirriar a voluntad, para oír lo que se está tocando."""

    def __init__(self):
        self.rpm = _RPM_RALENTI
        self.gas = 0.0
        self.velocidad = 0.0
        self.scrub = False
        self.spin = False
        self.lock = False
        self.adas = False
        self.viento = False

    def paso(self, gas, dt):
        self.gas = gas
        # inercia del motor: sube deprisa con gas y baja por rozamiento
        objetivo = _RPM_RALENTI + (_RPM_MAX - _RPM_RALENTI) * gas
        k = 3.2 if gas > 0.02 else 1.6
        self.rpm += (objetivo - self.rpm) * min(1.0, k * dt)
        # la velocidad solo alimenta al viento y a la transmisión
        v_obj = 60.0 if self.viento else 0.0
        self.velocidad += (v_obj - self.velocidad) * min(1.0, 1.2 * dt)

    def sonar(self, sonido):
        sonido.update(
            self.rpm, self.gas, engine_on=True, speed=self.velocidad,
            scrub=0.75 if self.scrub else 0.0,
            spin=0.75 if self.spin else 0.0,
            lock=0.75 if self.lock else 0.0,
            understeer=0.8 if self.adas else 0.0, oversteer=0.0)


def run_audio_lab(renderer, wheel=None, sonido=None):
    """Editor de sonido con escucha en directo.

    ``sonido`` es el EngineSound del juego; si no se pasa, se abre uno
    propio y se cierra al salir."""
    from .audio import EngineSound

    W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
    grupos = _parametros()
    filas = _filas(grupos)
    todas = [e for _s, ents in grupos for e in ents]
    if not todas:
        return
    #: valor de fábrica de cada parámetro, para poder volver a él
    fabrica = {e["name"]: e["default"] for e in todas}

    propio = sonido is None
    son = sonido if sonido is not None else EngineSound()
    if hasattr(son, "resume"):
        son.resume()

    banco = _Banco()
    sel = next(i for i, f in enumerate(filas) if f[0] == "par")
    top = 0
    n_rows = (H - 300) // 24
    rect = sdl2.SDL_Rect()
    event = sdl2.SDL_Event()
    aviso = ""
    aviso_t = 0

    def _fill(x, y, w, h, color):
        sdl2.SDL_SetRenderDrawColor(renderer, color[0], color[1], color[2],
                                    color[3] if len(color) > 3 else 255)
        rect.x, rect.y, rect.w, rect.h = int(x), int(y), int(w), int(h)
        sdl2.SDL_RenderFillRect(renderer, rect)

    def anota(e, v):
        if v == fabrica[e["name"]]:
            settings.forget(e["name"])
        else:
            settings.record(e["name"], v)

    def ajustar(e, direccion, big=False):
        cur = getattr(cfg, e["name"], e["default"])
        if e.get("is_enum"):
            opts = e["options"]
            v = opts[(opts.index(cur) % len(opts) + direccion) % len(opts)] \
                if cur in opts else opts[0]
        elif e["is_bool"]:
            v = not cur
        else:
            v = cur + _step(e, big) * direccion
            if e["is_int"]:
                v = int(round(v))
            # los valores de sonido negativos no significan nada y algunos
            # (longitudes de filtro, frecuencias) reventarian el sintetizador
            if e["lo"] is not None and e["lo"] >= 0.0:
                v = max(0.0 if not e["is_int"] else int(e["lo"] or 0), v)
        setattr(cfg, e["name"], v)
        anota(e, v)

    def por_defecto(e):
        setattr(cfg, e["name"], fabrica[e["name"]])
        anota(e, fabrica[e["name"]])

    def mover(paso):
        nonlocal sel
        i = sel
        for _ in range(len(filas)):
            i = (i + paso) % len(filas)
            if filas[i][0] == "par":
                sel = i
                return

    _TECLAS = {
        sdl2.SDLK_UP: "up", sdl2.SDLK_DOWN: "down",
        sdl2.SDLK_LEFT: "left", sdl2.SDLK_RIGHT: "right",
        sdl2.SDLK_ESCAPE: "back", sdl2.SDLK_RETURN: "back",
        sdl2.SDLK_d: "def", sdl2.SDLK_F5: "reset",
        sdl2.SDLK_1: "scrub", sdl2.SDLK_2: "spin", sdl2.SDLK_3: "lock",
        sdl2.SDLK_4: "adas", sdl2.SDLK_v: "viento",
    }

    reloj = sdl2.SDL_GetTicks()
    while True:
        ahora = sdl2.SDL_GetTicks()
        dt = max(0.001, min(0.1, (ahora - reloj) / 1000.0))
        reloj = ahora

        acciones = []
        big = bool(sdl2.SDL_GetModState() & sdl2.KMOD_SHIFT)
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            if event.type == sdl2.SDL_QUIT:
                if propio:
                    son.close()
                return
            if event.type == sdl2.SDL_KEYDOWN:
                a = _TECLAS.get(event.key.keysym.sym)
                if a and not (event.key.repeat
                              and a not in ("up", "down", "left", "right")):
                    acciones.append(a)
        if wheel is not None:
            acciones.extend(wheel.menu_nav(dt))

        e_sel = filas[sel][1]
        for a in acciones:
            if a == "back":
                if propio:
                    son.close()
                else:
                    son.pause()
                return
            if a == "up":
                mover(-1)
            elif a == "down":
                mover(1)
            elif a == "left":
                ajustar(e_sel, -1, big)
            elif a == "right":
                ajustar(e_sel, 1, big)
            elif a == "def":
                por_defecto(e_sel)
            elif a == "reset":
                for e in todas:
                    por_defecto(e)
                aviso, aviso_t = "TODO EL SONIDO POR DEFECTO", 150
            elif a == "scrub":
                banco.scrub = not banco.scrub
            elif a == "spin":
                banco.spin = not banco.spin
            elif a == "lock":
                banco.lock = not banco.lock
            elif a == "adas":
                banco.adas = not banco.adas
            elif a == "viento":
                banco.viento = not banco.viento

        # --- gas: la barra espaciadora o el pedal del volante -------------
        teclas = sdl2.SDL_GetKeyboardState(None)
        gas = 1.0 if teclas[sdl2.SDL_SCANCODE_SPACE] else 0.0
        if wheel is not None and getattr(wheel, "connected", False):
            wheel.update(teclas, banco.velocidad, dt)
            gas = max(gas, wheel.throttle)
        banco.paso(gas, dt)
        banco.sonar(son)

        if aviso_t > 0:
            aviso_t -= 1

        # ------------------------------------------------------- dibujo
        sdl2.SDL_SetRenderDrawColor(renderer, 14, 18, 26, 255)
        sdl2.SDL_RenderClear(renderer)
        font.draw_text(renderer, "LABORATORIO DE SONIDO", 60, 26, 3,
                       (255, 190, 60, 255))
        font.draw_text(renderer,
                       "ESPACIO O PEDAL = GAS   1 CHIRRIDO  2 PATINAJE  "
                       "3 BLOQUEO  4 AVISO  V VIENTO",
                       60, 64, 2, (150, 165, 185, 255))

        # --- banco de pruebas: régimen y fuentes activas ------------------
        bx, by, bw = 60, 92, W - 120
        _fill(bx, by, bw, 46, (24, 30, 42))
        frac = (banco.rpm - _RPM_RALENTI) / (_RPM_MAX - _RPM_RALENTI)
        frac = max(0.0, min(1.0, frac))
        col = (90, 210, 120) if frac < 0.78 else (
            (240, 190, 60) if frac < 0.93 else (235, 70, 60))
        _fill(bx + 10, by + 10, (bw - 20) * frac, 14, col)
        font.draw_text(renderer, f"{int(banco.rpm)} RPM", bx + 10, by + 30, 2,
                       (220, 228, 240, 255))
        etiquetas = [("CHIRRIDO", banco.scrub), ("PATINAJE", banco.spin),
                     ("BLOQUEO", banco.lock), ("AVISO", banco.adas),
                     ("VIENTO", banco.viento)]
        x = bx + 210
        for nombre, on in etiquetas:
            c = (120, 235, 140, 255) if on else (80, 90, 105, 255)
            font.draw_text(renderer, nombre, x, by + 30, 2, c)
            x += len(nombre) * 12 + 26

        # --- lista de parámetros ------------------------------------------
        if sel < top:
            top = sel
        elif sel >= top + n_rows:
            top = sel - n_rows + 1
        y0 = 156
        for i in range(top, min(len(filas), top + n_rows)):
            tipo, dato = filas[i]
            y = y0 + (i - top) * 24
            if tipo == "sec":
                font.draw_text(renderer, dato, 62, y + 4, 2,
                               (255, 150, 60, 255))
                continue
            e = dato
            cur = getattr(cfg, e["name"], e["default"])
            if i == sel:
                _fill(50, y - 4, W - 100, 24, (40, 55, 80))
            cambiado = cur != fabrica[e["name"]]
            nc = (255, 235, 180, 255) if i == sel else (
                (150, 220, 255, 255) if cambiado else (185, 195, 210, 255))
            font.draw_text(renderer, e["name"], 84, y, 2, nc)
            fuera = (not e["is_bool"] and e["lo"] is not None
                     and not (e["lo"] <= cur <= e["hi"]))
            vc = (255, 165, 60, 255) if fuera else (235, 240, 250, 255)
            font.draw_text(renderer, _fmt(cur), 560, y, 2, vc)
            if cambiado:
                font.draw_text(renderer, "DEF " + _fmt(fabrica[e["name"]]),
                               680, y, 2, (110, 125, 145, 255))

        # --- explicación del parámetro elegido ----------------------------
        e = filas[sel][1]
        _fill(50, H - 132, W - 100, 96, (24, 30, 42))
        font.draw_text(renderer, e["name"], 70, H - 122, 2,
                       (255, 200, 60, 255))
        for k, ln in enumerate(_wrap_text(e["desc"], 92)[:3]):
            font.draw_text(renderer, ln.upper(), 70, H - 98 + k * 18, 2,
                           (190, 200, 215, 255))
        font.draw_text(renderer,
                       "D = POR DEFECTO   F5 = TODO POR DEFECTO   "
                       "MAYUS+FLECHA = PASO GRANDE   ESC = VOLVER",
                       70, H - 44, 2, (120, 135, 155, 255))

        if aviso_t > 0:
            _fill(W // 2 - 260, 8, 520, 28, (20, 60, 30, 230))
            font.draw_text(renderer, _ascii(aviso), W // 2 - 240, 14, 2,
                           (150, 245, 160, 255))

        sdl2.SDL_RenderPresent(renderer)
