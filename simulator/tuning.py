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


def run_tuning(renderer):
    """Editor de configuración. Vuelve con ESC/ENTER (los cambios quedan
    aplicados sobre cfg; el coche/circuito los recogen al REempezar)."""
    W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
    entries = get_entries()
    sel = 0
    top = 0
    n_rows = (H - 260) // 26
    rect = sdl2.SDL_Rect()
    event = sdl2.SDL_Event()

    def _fill(x, y, w, h, color):
        sdl2.SDL_SetRenderDrawColor(renderer, color[0], color[1], color[2],
                                    color[3] if len(color) > 3 else 255)
        rect.x, rect.y, rect.w, rect.h = int(x), int(y), int(w), int(h)
        sdl2.SDL_RenderFillRect(renderer, rect)

    while True:
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            if event.type == sdl2.SDL_QUIT:
                return
            if event.type != sdl2.SDL_KEYDOWN:
                continue
            sym = event.key.keysym.sym
            mods = sdl2.SDL_GetModState()
            big = bool(mods & sdl2.KMOD_SHIFT)
            if sym in (sdl2.SDLK_ESCAPE, sdl2.SDLK_RETURN,
                       sdl2.SDLK_KP_ENTER):
                _recompute_derived()
                return
            if sym == sdl2.SDLK_UP:
                sel = (sel - 1) % len(entries)
            elif sym == sdl2.SDLK_DOWN:
                sel = (sel + 1) % len(entries)
            elif sym == sdl2.SDLK_PAGEUP:
                sel = max(0, sel - n_rows)
            elif sym == sdl2.SDLK_PAGEDOWN:
                sel = min(len(entries) - 1, sel + n_rows)
            elif sym in (sdl2.SDLK_LEFT, sdl2.SDLK_RIGHT):
                e = entries[sel]
                cur = getattr(cfg, e["name"], e["default"])
                if e["is_bool"]:
                    setattr(cfg, e["name"], not cur)
                else:
                    s = _step(e, big) * (1 if sym == sdl2.SDLK_RIGHT else -1)
                    v = cur + s
                    if e["is_int"]:
                        v = int(round(v))
                    setattr(cfg, e["name"], v)
            elif sym == sdl2.SDLK_d:
                e = entries[sel]
                setattr(cfg, e["name"], e["default"])
            elif sym == sdl2.SDLK_F5:
                for e in entries:
                    setattr(cfg, e["name"], e["default"])

        # mantener la selección a la vista (con margen para las cabeceras
        # de sección, que también consumen filas)
        if sel < top:
            top = sel
        if sel >= top + n_rows - 6:
            top = sel - (n_rows - 6) + 1

        # ------------------------------------------------------ dibujo
        sdl2.SDL_SetRenderDrawColor(renderer, 14, 18, 26, 255)
        sdl2.SDL_RenderClear(renderer)
        font.draw_text(renderer, "AJUSTES AVANZADOS", 60, 28, 3,
                       (235, 60, 50, 255))
        font.draw_text(renderer,
                       "FLECHAS: MOVER/AJUSTAR  MAYUS: PASO GRANDE  "
                       "D: POR DEFECTO  F5: TODO POR DEFECTO  ESC: VOLVER",
                       60, 64, 2, (150, 150, 150, 255))

        y = 100
        last_section = None
        i = top
        shown = 0
        while i < len(entries) and shown < n_rows:
            e = entries[i]
            if e["section"] != last_section:
                last_section = e["section"]
                font.draw_text(renderer, e["section"][:60], 60, y, 2,
                               (120, 170, 230, 255))
                y += 26
                shown += 1
                if shown >= n_rows:
                    break
            cur = getattr(cfg, e["name"], e["default"])
            is_sel = (i == sel)
            if is_sel:
                _fill(50, y - 4, W - 100, 24, (40, 55, 80))
            out = (not e["is_bool"] and e["lo"] is not None
                   and not (e["lo"] <= cur <= e["hi"]))
            changed = cur != e["default"]
            name_c = (255, 200, 60, 255) if is_sel else (185, 185, 185, 255)
            val_c = (255, 150, 60, 255) if out else (
                (140, 230, 140, 255) if changed else (235, 235, 235, 255))
            font.draw_text(renderer, e["name"], 84, y, 2, name_c)
            font.draw_text(renderer, _fmt(cur), 620, y, 2, val_c)
            if e["lo"] is not None:
                font.draw_text(renderer,
                               f"[{_fmt(e['lo'])} .. {_fmt(e['hi'])}]",
                               800, y, 2, (120, 120, 130, 255))
            font.draw_text(renderer, f"DEF {_fmt(e['default'])}",
                           1040, y, 2, (110, 110, 120, 255))
            y += 26
            shown += 1
            i += 1

        # pie: descripción del seleccionado
        e = entries[sel]
        _fill(50, H - 150, W - 100, 110, (24, 30, 42))
        font.draw_text(renderer, e["name"], 70, H - 138, 2,
                       (255, 200, 60, 255))
        yy = H - 112
        for ln in _wrap_text(e["desc"], 96)[:3]:
            font.draw_text(renderer, ln.upper(), 70, yy, 2,
                           (190, 200, 215, 255))
            yy += 24
        cur = getattr(cfg, e["name"], e["default"])
        if (not e["is_bool"] and e["lo"] is not None
                and not (e["lo"] <= cur <= e["hi"])):
            font.draw_text(renderer, "FUERA DEL RANGO NORMAL (PERMITIDO)",
                           W - 520, H - 138, 2, (255, 150, 60, 255))

        sdl2.SDL_RenderPresent(renderer)
        sdl2.SDL_Delay(16)
