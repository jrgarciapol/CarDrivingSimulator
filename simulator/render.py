"""Renderizado pseudo-3D de la carretera (estilo clásico de segmentos).

Proyecta los segmentos del circuito desde la cámara situada detrás del coche
y dibuja franjas horizontales interpoladas: hierba, pianos, asfalto y líneas.
Las curvas se acumulan como desplazamiento lateral creciente con la distancia
y las colinas mueven el horizonte.
"""

import math

import sdl2

from . import config as cfg
from . import font

# Paleta
SKY_TOP = (78, 154, 219)
SKY_BOTTOM = (170, 210, 240)
GRASS = [(16, 122, 40), (12, 105, 34)]
ROAD = [(84, 84, 88), (78, 78, 82)]
KERB = [(214, 40, 40), (235, 235, 235)]
LINE = (235, 235, 235)
HORIZON_MOUNTAIN = (58, 108, 76)


class Renderer:
    def __init__(self, renderer):
        self.r = renderer
        self._rect = sdl2.SDL_Rect()

    def _fill(self, x, y, w, h, color):
        if w <= 0 or h <= 0:
            return
        sdl2.SDL_SetRenderDrawColor(self.r, color[0], color[1], color[2], 255)
        self._rect.x = int(x)
        self._rect.y = int(y)
        self._rect.w = int(w)
        self._rect.h = int(h)
        sdl2.SDL_RenderFillRect(self.r, self._rect)

    # ------------------------------------------------------------------
    def draw_background(self, horizon_y, road_heading):
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        # cielo degradado
        bands = 24
        for i in range(bands):
            t = i / bands
            c = tuple(int(SKY_TOP[j] + (SKY_BOTTOM[j] - SKY_TOP[j]) * t) for j in range(3))
            y0 = int(horizon_y * t)
            y1 = int(horizon_y * (i + 1) / bands)
            self._fill(0, y0, W, max(1, y1 - y0), c)
        # montañas lejanas con parallax según el rumbo
        off = int(-road_heading * 600) % W
        for base in (-W, 0, W):
            for k in range(5):
                mx = base + off + k * (W // 4)
                mw = W // 3
                mh = 40 + (k * 37) % 60
                self._draw_triangle(mx, horizon_y, mw, mh, HORIZON_MOUNTAIN)
        # suelo por defecto (por si la carretera no cubre todo)
        self._fill(0, horizon_y, W, H - horizon_y, GRASS[0])

    def _draw_triangle(self, x, base_y, w, h, color):
        sdl2.SDL_SetRenderDrawColor(self.r, color[0], color[1], color[2], 255)
        steps = max(1, h // 2)
        for i in range(steps):
            t = (i + 1) / steps
            row_w = int(w * t)
            self._rect.x = int(x + (w - row_w) / 2)
            self._rect.y = int(base_y - h + i * 2)
            self._rect.w = row_w
            self._rect.h = 2
            sdl2.SDL_RenderFillRect(self.r, self._rect)

    # ------------------------------------------------------------------
    def draw_road(self, track, car_state):
        """Devuelve la altura del horizonte usada (para el fondo)."""
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        segs = track.segments
        n_segs = len(segs)
        seg_len = cfg.SEGMENT_LENGTH

        base_i = int(car_state.s / seg_len)
        frac = (car_state.s - base_i * seg_len) / seg_len
        base_seg = segs[base_i % n_segs]
        cam_y = base_seg.y + cfg.CAMERA_HEIGHT

        # Proyección de cada segmento por delante de la cámara
        cam_d = cfg.CAMERA_DEPTH
        half_w = cfg.ROAD_HALF_WIDTH
        kerb_w = cfg.KERB_WIDTH

        x_offset = 0.0      # desplazamiento lateral acumulado por la curva
        dx = 0.0
        rows = []           # (screen_y, center_x, half_width_px, seg_index)
        min_y = H

        for i in range(cfg.DRAW_DISTANCE):
            seg = segs[(base_i + i) % n_segs]
            # el primer punto queda casi bajo la cámara para que la
            # carretera llegue al borde inferior de la pantalla
            z = (i - frac) * seg_len + 0.5
            if z < 0.3:
                if i > 0:
                    continue
                z = 0.3
            # curva: doble integración de la curvatura
            dx += seg.kappa * seg_len * seg_len
            x_offset += dx
            world_x = x_offset - car_state.n - car_state.psi * z
            world_y = seg.y - cam_y

            scale = cam_d / z
            sx = W / 2 + scale * world_x * (W / 2)
            sy = H / 2 - scale * world_y * (H / 2)
            sw = scale * half_w * (W / 2)
            rows.append((sy, sx, sw, (base_i + i)))

        # Dibujar de lejos a cerca no: de cerca a lejos con recorte por
        # elevación (solo se dibuja lo que asoma por encima de lo anterior)
        clip_y = H
        for idx in range(len(rows) - 1):
            y1, x1, w1, si = rows[idx]
            y2, x2, w2, _ = rows[idx + 1]
            if y2 >= clip_y:
                continue
            top = max(0, int(y2))
            bottom = min(int(clip_y), int(y1) + 1)
            if bottom <= top:
                clip_y = min(clip_y, y2)
                min_y = min(min_y, top)
                continue
            seg = segs[si % n_segs]
            grass_c = GRASS[(si // 3) % 2]
            road_c = ROAD[(si // 3) % 2]
            kerb_c = KERB[(si // 2) % 2] if seg.kerb else grass_c
            lane_mark = (si // 4) % 2 == 0

            span = max(1, int(y1) - int(y2))
            for y in range(top, bottom):
                t = (y - y2) / span if span else 0.0
                cxx = x1 * t + x2 * (1 - t)
                ww = w1 * t + w2 * (1 - t)
                kw = ww * (kerb_w / cfg.ROAD_HALF_WIDTH)
                # hierba a todo lo ancho
                self._fill(0, y, W, 1, grass_c)
                # pianos
                self._fill(cxx - ww - kw, y, kw, 1, kerb_c)
                self._fill(cxx + ww, y, kw, 1, kerb_c)
                # asfalto
                self._fill(cxx - ww, y, ww * 2, 1, road_c)
                # línea central discontinua
                if lane_mark and ww > 8:
                    lw = max(1, ww * 0.03)
                    self._fill(cxx - lw / 2, y, lw, 1, LINE)
                # bordes blancos
                ew = max(1, ww * 0.04)
                self._fill(cxx - ww, y, ew, 1, LINE)
                self._fill(cxx + ww - ew, y, ew, 1, LINE)
            clip_y = min(clip_y, y2)
            min_y = min(min_y, top)
        return min_y

    # ------------------------------------------------------------------
    def draw_car(self, car_state, steering):
        """Coche visto desde atrás, en la parte baja de la pantalla."""
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        cx = W / 2 + steering * 18 - car_state.psi * 120
        cy = H - 88
        lean = int(car_state.ay * 1.2)

        car_w, car_h = 190, 96
        x = cx - car_w / 2
        # sombra
        self._fill(x + 6, cy + car_h - 14, car_w - 12, 16, (20, 20, 20))
        # ruedas
        wheel_w, wheel_h = 34, 26
        self._fill(x - 8, cy + car_h - wheel_h - 6, wheel_w, wheel_h, (25, 25, 25))
        self._fill(x + car_w - wheel_w + 8, cy + car_h - wheel_h - 6, wheel_w, wheel_h, (25, 25, 25))
        # carrocería
        self._fill(x, cy + 30 + lean, car_w, car_h - 44, (178, 24, 30))
        self._fill(x + 18, cy + 14 + lean, car_w - 36, 26, (150, 18, 24))
        # luneta
        self._fill(x + 30, cy + 18 + lean, car_w - 60, 16, (35, 40, 60))
        # pilotos
        self._fill(x + 8, cy + 44 + lean, 26, 10, (255, 60, 40))
        self._fill(x + car_w - 34, cy + 44 + lean, 26, 10, (255, 60, 40))
        # luces de freno encendidas
        if car_state.ax < -2.0:
            self._fill(x + 8, cy + 44 + lean, 26, 10, (255, 160, 120))
            self._fill(x + car_w - 34, cy + 44 + lean, 26, 10, (255, 160, 120))


class Hud:
    def __init__(self, renderer):
        self.r = renderer
        self._rect = sdl2.SDL_Rect()

    def _fill(self, x, y, w, h, color):
        sdl2.SDL_SetRenderDrawColor(self.r, color[0], color[1], color[2],
                                    color[3] if len(color) > 3 else 255)
        self._rect.x, self._rect.y = int(x), int(y)
        self._rect.w, self._rect.h = int(w), int(h)
        sdl2.SDL_RenderFillRect(self.r, self._rect)

    def draw(self, car_state, lap_time, best_lap, lap_count, ffb_ok, wheel_name):
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        st = car_state

        # panel inferior izquierdo: velocidad y marcha
        self._fill(20, H - 150, 300, 130, (0, 0, 0, 160))
        font.draw_text(self.r, f"{int(st.speed_kmh):3d}", 40, H - 135, 6)
        font.draw_text(self.r, "KM/H", 160, H - 120, 2)
        gear_txt = "R" if st.gear < 0 else ("N" if st.gear == 0 else str(st.gear))
        font.draw_text(self.r, gear_txt, 250, H - 135, 7, (255, 200, 60, 255))

        # cuentavueltas RPM
        rpm_frac = min(1.0, st.rpm / cfg.ENGINE_LIMITER_RPM)
        bar_w = 260
        self._fill(40, H - 55, bar_w, 14, (60, 60, 60))
        color = (90, 220, 90) if rpm_frac < 0.85 else (235, 60, 50)
        self._fill(40, H - 55, int(bar_w * rpm_frac), 14, color)
        font.draw_text(self.r, f"{int(st.rpm)} RPM", 40, H - 38, 2)

        # tiempos
        self._fill(W - 320, 20, 300, 92, (0, 0, 0, 160))
        font.draw_text(self.r, f"VUELTA {lap_count}", W - 300, 32, 2)
        font.draw_text(self.r, f"TIEMPO {_fmt_time(lap_time)}", W - 300, 56, 2)
        best_txt = _fmt_time(best_lap) if best_lap else "--:--.-"
        font.draw_text(self.r, f"MEJOR  {best_txt}", W - 300, 80, 2, (255, 200, 60, 255))

        # estado del dispositivo
        dev = wheel_name if wheel_name else "TECLADO - FLECHAS"
        ffb = "FFB OK" if ffb_ok else "SIN FFB"
        font.draw_text(self.r, f"{dev[:30]}  {ffb}  {cfg.DRIVE_TYPE}", 20, 20, 2,
                       (180, 255, 180, 255) if ffb_ok else (255, 180, 140, 255))

        # avisos de conducción
        y_warn = H - 190
        if st.abs_active:
            font.draw_text(self.r, "ABS", W / 2 - 18, y_warn, 2, (255, 220, 60, 255))
            y_warn -= 24
        if st.front_locked or st.rear_locked:
            which = "DEL" if st.front_locked else "TRAS"
            font.draw_text(self.r, f"BLOQUEO {which}", W / 2 - 60, y_warn, 2,
                           (255, 90, 60, 255))
            y_warn -= 24
        if st.wheelspin:
            font.draw_text(self.r, "TRACCION", W / 2 - 48, y_warn, 2, (255, 120, 60, 255))
            y_warn -= 24
        if st.front_grip_used > 0.95 and st.speed_kmh > 30:
            font.draw_text(self.r, "SUBVIRAJE", W / 2 - 54, y_warn, 2, (255, 220, 80, 255))

    def draw_debug(self, wheel, car_state, surface):
        """Superposición F1: ejes y botones en crudo para configurar el mapeo,
        más telemetría por rueda."""
        self._fill(20, 60, 540, 330, (0, 0, 0, 190))
        font.draw_text(self.r, "F1: DIAGNOSTICO DE EJES/BOTONES", 32, 70, 2)
        axes = wheel.raw_axes()
        y = 96
        for i, v in enumerate(axes[:8]):
            font.draw_text(self.r, f"EJE {i}: {v:6d}", 32, y, 2)
            y += 20
        btns = wheel.pressed_buttons()
        font.draw_text(self.r, "BOTONES: " + " ".join(str(b) for b in btns[:10]), 32, y, 2)
        y += 24
        font.draw_text(self.r, f"SUPERFICIE: {surface}", 32, y, 2)
        y += 20
        font.draw_text(self.r, f"PAR COLUMNA: {car_state.steer_column_torque:5.1f} NM", 32, y, 2)
        y += 24
        names = ("DI", "DD", "TI", "TD")
        for i in range(4):
            font.draw_text(
                self.r,
                f"{names[i]} CARGA {int(car_state.fz[i]):5d} N  "
                f"DESL {car_state.slip_ratio[i]:5.2f}  "
                f"DERIVA {car_state.slip_angle[i] * 57.3:5.1f}", 32, y, 2)
            y += 20


def _fmt_time(t):
    if t is None:
        return "--:--.-"
    mins = int(t // 60)
    secs = t - mins * 60
    return f"{mins:02d}:{secs:04.1f}"
