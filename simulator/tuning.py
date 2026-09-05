"""Pantalla de AJUSTES AVANZADOS: editar la configuración desde el juego.

Los parámetros, sus descripciones y sus rangos normales se extraen
AUTOMÁTICAMENTE de simulator/config.py, que ya documenta cada valor con un
comentario y su rango razonable ``[min .. max]``. Así hay una sola fuente de
verdad: documentar un parámetro nuevo en config.py lo hace aparecer aquí.

Se permiten valores FUERA del rango normal (se avisan en naranja); el rango
es una guía, no un límite. Cada parámetro (o todos) puede volver a su valor
POR DEFECTO (el de config.py).

Controles: flechas arriba/abajo (mantener para correr), izquierda/derecha
ajustan (con MAYÚS, paso grande), D = valor por defecto del seleccionado,
F5 = TODOS por defecto, ESC/ENTER = volver.
"""

import ast
import ctypes
import os
import re

import sdl2

from . import config as cfg
from . import font

# parámetros que no tiene sentido tocar en caliente
_EXCLUDE = {"WINDOW_WIDTH", "WINDOW_HEIGHT", "PHYSICS_HZ"}

_RANGE_RE = re.compile(r"\[\s*(-?\d+\.?\d*)\s*\.\.\s*(-?\d+\.?\d*)\s*\]")
#: opciones de un parametro de TEXTO, p.ej.  {legacy | inertia}
_ENUM_RE = re.compile(r"\{([^}]+)\}")

_TRANS = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")


def _ascii(s):
    """La fuente del juego solo tiene ASCII: transliterar acentos y símbolos."""
    return (s.translate(_TRANS).replace("·", ".").replace("°", "o")
            .replace("²", "2").replace("³", "3").replace("½", "1/2")
            .replace("—", "-").replace("≈", "~").replace("μ", "mu")
            .replace("κ", "k").replace("→", "->").replace("↑", "+")
            .replace("↓", "-"))


def _parse_config():
    """Lee config.py y devuelve la lista de parámetros editables:
    [{name, default, lo, hi, desc, section}] en orden de aparición."""
    path = os.path.join(os.path.dirname(__file__), "config.py")
    entries = []
    section = "GENERAL"
    lines = open(path, encoding="utf-8").read().splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        # sección: bloque "# ====" / "# TITULO" / ... / "# ====" — el título
        # es la primera línea de comentario tras la primera raya
        if ln.startswith("# =="):
            if i + 1 < len(lines) and lines[i + 1].startswith("#") \
                    and not lines[i + 1].startswith("# =="):
                section = lines[i + 1][1:].strip()
            i += 1
            while i < len(lines) and lines[i].startswith("#"):
                i += 1
            continue
        m = re.match(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.+?)(#.*)?$", ln)
        if m:
            name, val_s, com = m.group(1), m.group(2).strip(), m.group(3) or ""
            # comentario: el de la línea + las líneas-comentario siguientes
            desc = com.lstrip("# ").strip()
            j = i + 1
            while j < len(lines) and re.match(r"^\s+#", lines[j]):
                desc += " " + lines[j].strip().lstrip("# ").strip()
                j += 1
            try:
                val = ast.literal_eval(val_s)
            except (ValueError, SyntaxError):
                i = j
                continue
            if isinstance(val, bool) or isinstance(val, (int, float)):
                if name not in _EXCLUDE:
                    rng = _RANGE_RE.search(desc)
                    lo = hi = None
                    if rng:
                        lo, hi = float(rng.group(1)), float(rng.group(2))
                        desc = _RANGE_RE.sub("", desc)
                    entries.append({
                        "name": name, "default": val,
                        "lo": lo, "hi": hi,
                        "desc": _ascii(" ".join(desc.split())),
                        "section": _ascii(section),
                        "is_int": isinstance(val, int)
                        and not isinstance(val, bool),
                        "is_bool": isinstance(val, bool),
                    })
            elif isinstance(val, str):
                # parametro de OPCIONES: se edita si el comentario lista sus
                # valores entre llaves, p.ej.  {legacy | inertia}
                enum = _ENUM_RE.search(desc)
                if enum and name not in _EXCLUDE:
                    opts = [o.strip() for o in enum.group(1).split("|")
                            if o.strip()]
                    desc = _ENUM_RE.sub("", desc)
                    entries.append({
                        "name": name, "default": val, "lo": None, "hi": None,
                        "desc": _ascii(" ".join(desc.split())),
                        "section": _ascii(section),
                        "is_int": False, "is_bool": False,
                        "is_enum": True, "options": opts,
                    })
            i = j
            continue
        i += 1
    return entries


_ENTRIES = None


def get_entries():
    global _ENTRIES
    if _ENTRIES is None:
        _ENTRIES = _parse_config()
    return _ENTRIES


def _step(e, big):
    if e["is_bool"]:
        return 1
    if e["lo"] is not None and e["hi"] is not None and e["hi"] > e["lo"]:
        s = (e["hi"] - e["lo"]) / (8.0 if big else 40.0)
    else:
        base = abs(e["default"]) or 1.0
        s = base * (0.25 if big else 0.05)
    if e["is_int"]:
        s = max(1, round(s))
    return s


def _fmt(v):
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "SI" if v else "NO"
    if isinstance(v, int):
        return str(v)
    a = abs(v)
    if a >= 1000:
        return f"{v:.0f}"
    if a >= 10:
        return f"{v:.1f}"
    return f"{v:.3f}".rstrip("0").rstrip(".") or "0"


def _wrap_text(txt, width):
    out, cur = [], ""
    for w in txt.split():
        if len(cur) + len(w) + 1 > width:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(cur)
    return out


def _recompute_derived():
    cfg.CAR_CG_TO_FRONT = cfg.WHEELBASE * (1.0 - cfg.WEIGHT_DIST_FRONT)
    cfg.CAR_CG_TO_REAR = cfg.WHEELBASE * cfg.WEIGHT_DIST_FRONT



# ===========================================================================
# Pantalla de AJUSTES con navegación en DOS niveles: primero se elige una
# CATEGORIA (pantalla, mando, coche...) y dentro se editan sus parámetros.
# Así la lista no es un muro de 170 valores. Los cambios se anotan en
# settings (para persistir la configuración y reaplicar el reglaje del coche
# tras load_car), y el reglaje se puede GUARDAR COMO COCHE NUEVO.
# ===========================================================================
from . import garage        # noqa: E402
from . import settings      # noqa: E402


def _pedir_texto(renderer, wheel, titulo, inicial=""):
    """Cuadro para escribir texto (el nombre del coche). Devuelve el texto o
    None si se cancela. Funciona con teclado y con el teclado en pantalla de
    Steam (STEAM+X en la Deck), porque lee eventos de texto de SDL."""
    W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
    rect = sdl2.SDL_Rect()
    event = sdl2.SDL_Event()
    texto = str(inicial)
    sdl2.SDL_StartTextInput()
    try:
        while True:
            while sdl2.SDL_PollEvent(ctypes.byref(event)):
                if event.type == sdl2.SDL_QUIT:
                    return None
                if event.type == sdl2.SDL_TEXTINPUT:
                    frag = bytes(event.text.text).split(b"\x00", 1)[0]
                    texto += frag.decode("utf-8", "ignore")
                elif event.type == sdl2.SDL_KEYDOWN:
                    s = event.key.keysym.sym
                    if s == sdl2.SDLK_ESCAPE:
                        return None
                    if s in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                        return texto.strip() or None
                    if s == sdl2.SDLK_BACKSPACE:
                        texto = texto[:-1]
            if wheel is not None:
                for a in wheel.menu_nav(0.016):
                    if a == "back":
                        return None
                    if a == "ok" and texto.strip():
                        return texto.strip()

            sdl2.SDL_SetRenderDrawColor(renderer, 10, 12, 18, 235)
            sdl2.SDL_RenderClear(renderer)
            bx, by, bw, bh = W // 2 - 380, H // 2 - 90, 760, 180
            sdl2.SDL_SetRenderDrawColor(renderer, 30, 40, 60, 255)
            rect.x, rect.y, rect.w, rect.h = bx, by, bw, bh
            sdl2.SDL_RenderFillRect(renderer, rect)
            font.draw_text(renderer, _ascii(titulo), bx + 24, by + 20, 2,
                           (255, 200, 60, 255))
            font.draw_text(renderer, (texto or "_") + "_", bx + 24, by + 70, 3,
                           (255, 255, 255, 255))
            font.draw_text(renderer,
                           "ESCRIBE EL NOMBRE   ENTER/A: GUARDAR   ESC/B: CANCELAR",
                           bx + 24, by + bh - 34, 2, (150, 150, 150, 255))
            font.draw_text(renderer,
                           "(EN LA STEAM DECK, TECLADO EN PANTALLA: STEAM + X)",
                           bx + 24, by + bh - 12, 2, (110, 130, 160, 255))
            sdl2.SDL_RenderPresent(renderer)
            sdl2.SDL_Delay(16)
    finally:
        sdl2.SDL_StopTextInput()


def _baselines():
    """Valor de REFERENCIA de cada parámetro (el que restaura 'POR DEFECTO' y
    contra el que se decide si algo está 'CAMBIADO').

    - CONFIG: el valor de fábrica de config.py. Restaurarlo = valores de
      fábrica de la aplicación.
    - COCHE: el valor PROPIO del coche elegido (no el de config.py). Cada
      coche redefine muchos parámetros; si la referencia fuese config.py, un
      coche recién cargado saldría 'cambiado' sin haberlo tocado y restaurar
      le borraría su carácter (p.ej. la carga aerodinámica del fórmula).

    Para las referencias del coche se recarga el coche LIMPIO (sin el reglaje
    del usuario), se fotografía y se vuelve a aplicar el reglaje, dejando cfg
    como estaba."""
    base = {}
    for e in get_entries():                       # 1) config -> fábrica
        if e["name"] not in garage.CAR_KEYS:
            base[e["name"]] = e["default"]
    path = getattr(settings, "_car_path", None)
    if path:                                       # 2) coche -> valor limpio
        try:
            garage.load_car(path)                  # cfg del coche, sin reglaje
        except (OSError, ValueError):
            path = None
    for e in get_entries():
        if e["name"] in garage.CAR_KEYS:
            base[e["name"]] = getattr(cfg, e["name"], e["default"])
    if path:
        settings.apply_car()                       # devolver el reglaje a cfg
    return base


def _categorias():
    """Agrupa los parámetros por sección, en orden, y marca cada categoría
    como de COCHE (reglaje) o de CONFIG según lo que predomine."""
    orden, por = [], {}
    for e in get_entries():
        if e["section"] not in por:
            por[e["section"]] = []
            orden.append(e["section"])
        por[e["section"]].append(e)
    cats = []
    for s in orden:
        ents = por[s]
        de_coche = sum(1 for e in ents
                       if e["name"] in garage.CAR_KEYS) > len(ents) / 2
        cats.append((s, ents, de_coche))
    return cats


def run_tuning(renderer, wheel=None):
    """Editor de configuración en DOS niveles (categoría -> parámetros).

    - Los cambios se ANOTAN: los de coche son reglaje (se reaplican tras
      cargar el coche y se pueden guardar como coche nuevo); los de config
      se guardan y valen para siempre.
    - Se navega con teclado o mando (cruceta/stick, mantener = rápido).
    - GUARDAR COCHE COMO... crea un .car con el reglaje actual.
    """
    W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
    cats = _categorias()
    base = _baselines()                 # valor de referencia de cada parámetro
    n_cat = len(cats)
    ACC_GUARDAR_AQUI, ACC_GUARDAR, ACC_RESET = n_cat, n_cat + 1, n_cat + 2
    n_items = n_cat + 3                 # + guardar en este coche + guardar
                                        #   como nuevo + restaurar todo

    modo = "cats"                       # "cats" o "params"
    sel_cat = 0
    sel = 0
    top = 0
    n_rows = (H - 210) // 26
    rect = sdl2.SDL_Rect()
    event = sdl2.SDL_Event()
    mensaje = ""
    mensaje_t = 0

    def _fill(x, y, w, h, color):
        sdl2.SDL_SetRenderDrawColor(renderer, color[0], color[1], color[2],
                                    color[3] if len(color) > 3 else 255)
        rect.x, rect.y, rect.w, rect.h = int(x), int(y), int(w), int(h)
        sdl2.SDL_RenderFillRect(renderer, rect)

    def ref(e):
        """Valor de referencia (fábrica para config, propio del coche para
        el reglaje)."""
        return base.get(e["name"], e["default"])

    def anota(e, v):
        # se anota solo si difiere de SU referencia; si vuelve a ella, se
        # olvida (un parámetro de coche igual al del coche no necesita
        # reaplicarse tras load_car).
        if v == ref(e):
            settings.forget(e["name"])
        else:
            settings.record(e["name"], v)

    def ajustar(e, direccion, big=False):
        cur = getattr(cfg, e["name"], e["default"])
        if e.get("is_enum"):
            opts = e["options"]
            idx = opts.index(cur) if cur in opts else 0
            v = opts[(idx + direccion) % len(opts)]
        elif e["is_bool"]:
            v = not cur
        else:
            paso = _step(e, big)
            v = cur + paso * direccion
            if e["is_int"]:
                v = int(round(v))
            else:
                # ENCAJAR en la rejilla del paso: si el valor de partida no
                # es multiplo del paso, con las flechas nunca se pasaba por
                # 0 (que en muchos parametros es "apagado") ni por 1
                v = round(round(v / paso) * paso, 6)
                if e["lo"] is not None:
                    v = max(e["lo"], v)
                if e["hi"] is not None:
                    v = min(e["hi"], v)
        setattr(cfg, e["name"], v)
        anota(e, v)

    def por_defecto(e):
        setattr(cfg, e["name"], ref(e))
        anota(e, ref(e))

    _TECLAS = {
        sdl2.SDLK_UP: "up", sdl2.SDLK_DOWN: "down",
        sdl2.SDLK_LEFT: "left", sdl2.SDLK_RIGHT: "right",
        sdl2.SDLK_RETURN: "ok", sdl2.SDLK_KP_ENTER: "ok",
        sdl2.SDLK_ESCAPE: "back", sdl2.SDLK_d: "def", sdl2.SDLK_F5: "reset",
    }

    while True:
        acciones = []
        big = bool(sdl2.SDL_GetModState() & sdl2.KMOD_SHIFT)
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            if event.type == sdl2.SDL_QUIT:
                _recompute_derived()
                return
            if event.type == sdl2.SDL_KEYDOWN:
                a = _TECLAS.get(event.key.keysym.sym)
                # direcciones admiten repeticion del teclado; el resto no
                if a and not (event.key.repeat
                              and a not in ("up", "down", "left", "right")):
                    acciones.append(a)
        if wheel is not None:
            acciones.extend(wheel.menu_nav(0.016))

        for a in acciones:
            if modo == "cats":
                if a == "back":
                    _recompute_derived()
                    return
                if a == "up":
                    sel_cat = (sel_cat - 1) % n_items
                elif a == "down":
                    sel_cat = (sel_cat + 1) % n_items
                elif a == "ok":
                    if sel_cat < n_cat:
                        modo, sel, top = "params", 0, 0
                    elif sel_cat == ACC_GUARDAR_AQUI:
                        ruta = settings.guardar_en_este_coche()
                        mensaje = ("GUARDADO EN " + ruta if ruta
                                   else "NADA QUE GUARDAR EN ESTE COCHE")
                        mensaje_t = 180
                        base = _baselines()      # el coche ya lleva el reglaje
                    elif sel_cat == ACC_GUARDAR:
                        nombre = _pedir_texto(renderer, wheel,
                                              "NOMBRE DEL COCHE", "MI COCHE")
                        if nombre:
                            ruta = settings.guardar_coche(nombre)
                            mensaje = "GUARDADO EN " + ruta
                            mensaje_t = 180
                    elif sel_cat == ACC_RESET:
                        for _, ents, _c in cats:
                            for e in ents:
                                por_defecto(e)
                        mensaje = "TODOS LOS VALORES POR DEFECTO"
                        mensaje_t = 180
            else:                       # modo params
                ents = cats[sel_cat][1]
                if a in ("back", "ok"):
                    modo = "cats"
                elif a == "up":
                    sel = (sel - 1) % len(ents)
                elif a == "down":
                    sel = (sel + 1) % len(ents)
                elif a == "left":
                    ajustar(ents[sel], -1, big)
                elif a == "right":
                    ajustar(ents[sel], 1, big)
                elif a == "def":
                    por_defecto(ents[sel])
                elif a == "reset":
                    for e in ents:
                        por_defecto(e)

        if mensaje_t > 0:
            mensaje_t -= 1

        # ----------------------------------------------------- dibujo
        sdl2.SDL_SetRenderDrawColor(renderer, 14, 18, 26, 255)
        sdl2.SDL_RenderClear(renderer)

        if modo == "cats":
            font.draw_text(renderer, "AJUSTES", 60, 28, 3, (235, 60, 50, 255))
            font.draw_text(renderer,
                           "ELIGE UNA CATEGORIA   ENTER/A: ENTRAR   ESC/B: VOLVER",
                           60, 66, 2, (150, 150, 150, 255))
            y = 116
            for i in range(n_items):
                is_sel = (i == sel_cat)
                if is_sel:
                    _fill(50, y - 4, W - 100, 26, (40, 55, 80))
                if i < n_cat:
                    nombre, ents, de_coche = cats[i]
                    n_ch = sum(1 for e in ents
                               if getattr(cfg, e["name"], base[e["name"]])
                               != base[e["name"]])
                    tag = "COCHE " if de_coche else "CONFIG"
                    tag_c = (255, 190, 90, 255) if de_coche else (120, 190, 235, 255)
                    font.draw_text(renderer, tag, 70, y, 2, tag_c)
                    font.draw_text(renderer, nombre[:52], 190, y, 2,
                                   (255, 220, 120, 255) if is_sel
                                   else (210, 210, 210, 255))
                    if n_ch:
                        font.draw_text(renderer, f"({n_ch} CAMBIADOS)",
                                       W - 320, y, 2, (140, 230, 140, 255))
                else:
                    txt = ("GUARDAR EN ESTE COCHE" if i == ACC_GUARDAR_AQUI
                           else "GUARDAR COCHE COMO..." if i == ACC_GUARDAR
                           else "RESTAURAR TODO POR DEFECTO")
                    col = (140, 235, 170, 255) if i in (ACC_GUARDAR, ACC_GUARDAR_AQUI) \
                        else (235, 150, 90, 255)
                    font.draw_text(renderer, txt, 190, y, 2, col)
                y += 30
            font.draw_text(renderer,
                           "LOS CAMBIOS DE 'CONFIG' SE GUARDAN SOLOS. LOS DE "
                           "'COCHE' SON REGLAJE: GUARDALO EN ESTE COCHE O COMO NUEVO.",
                           60, H - 60, 2, (150, 160, 175, 255))

        else:                           # modo params
            nombre, ents, de_coche = cats[sel_cat]
            if sel < top:
                top = sel
            if sel >= top + n_rows:
                top = sel - n_rows + 1
            font.draw_text(renderer, _ascii(nombre)[:46], 60, 28, 3,
                           (235, 60, 50, 255))
            font.draw_text(renderer,
                           "ARR/ABA: MOVER  IZQ/DER: AJUSTAR  MAYUS: PASO GRANDE"
                           "  D/X: DEFECTO  ESC/B: VOLVER",
                           60, 66, 2, (150, 150, 150, 255))
            y = 104
            for i in range(top, min(len(ents), top + n_rows)):
                e = ents[i]
                cur = getattr(cfg, e["name"], e["default"])
                is_sel = (i == sel)
                if is_sel:
                    _fill(50, y - 4, W - 100, 24, (40, 55, 80))
                out = (not e["is_bool"] and e["lo"] is not None
                       and not (e["lo"] <= cur <= e["hi"]))
                changed = cur != base[e["name"]]
                name_c = (255, 200, 60, 255) if is_sel else (185, 185, 185, 255)
                val_c = (255, 150, 60, 255) if out else (
                    (140, 230, 140, 255) if changed else (235, 235, 235, 255))
                font.draw_text(renderer, e["name"], 84, y, 2, name_c)
                font.draw_text(renderer, _fmt(cur), 620, y, 2, val_c)
                if e["lo"] is not None:
                    font.draw_text(renderer,
                                   f"[{_fmt(e['lo'])} .. {_fmt(e['hi'])}]",
                                   800, y, 2, (120, 120, 130, 255))
                font.draw_text(renderer, f"DEF {_fmt(base[e['name']])}",
                               1040, y, 2, (110, 110, 120, 255))
                y += 26

            e = ents[sel]
            _fill(50, H - 150, W - 100, 110, (24, 30, 42))
            font.draw_text(renderer, e["name"], 70, H - 138, 2, (255, 200, 60, 255))
            yy = H - 112
            for ln in _wrap_text(e["desc"], 96)[:3]:
                font.draw_text(renderer, ln.upper(), 70, yy, 2, (190, 200, 215, 255))
                yy += 24
            cur = getattr(cfg, e["name"], e["default"])
            if (not e["is_bool"] and e["lo"] is not None
                    and not (e["lo"] <= cur <= e["hi"])):
                font.draw_text(renderer, "FUERA DEL RANGO NORMAL (PERMITIDO)",
                               W - 520, H - 138, 2, (255, 150, 60, 255))

        if mensaje_t > 0:
            _fill(W // 2 - 320, 8, 640, 30, (20, 60, 30, 230))
            font.draw_text(renderer, mensaje[:70],
                           W // 2 - font.text_width(mensaje[:70], 2) // 2, 14,
                           2, (150, 240, 170, 255))

        sdl2.SDL_RenderPresent(renderer)
        sdl2.SDL_Delay(16)
