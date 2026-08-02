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
    def draw_road(self, track, car_state, show_line=True, cam_height=None):
        """Devuelve la altura del horizonte usada (para el fondo)."""
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        speed = abs(car_state.vx)
        if cam_height is None:
            cam_height = cfg.CAMERA_HEIGHT
        segs = track.segments
        n_segs = len(segs)
        seg_len = cfg.SEGMENT_LENGTH

        base_i = int(car_state.s / seg_len)
        frac = (car_state.s - base_i * seg_len) / seg_len
        base_seg = segs[base_i % n_segs]
        cam_y = base_seg.y + cam_height

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
        n_track = len(track.segments)
        clip_y = H
        poles = []
        for idx in range(len(rows) - 1):
            y1, x1, w1, si = rows[idx]
            y2, x2, w2, _ = rows[idx + 1]
            # las balizas se registran aunque su tramo de asfalto quede
            # oculto tras una cresta (la parte alta puede asomar); se
            # guarda el recorte del terreno vigente a su distancia. En la
            # lejanía se espacian al doble para no formar una "valla"
            if cfg.TRACK_POLES and w2 > 4.0 \
                    and si % (6 if w2 > 14.0 else 12) == 0:
                poles.append((y2, x2, w2, clip_y))
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

            # trazada ideal: color según la velocidad admisible en ese
            # punto (incluye la distancia de frenada a la curva siguiente)
            if show_line and cfg.RACING_LINE:
                line_n = track.line_n[si % n_track]
                line_v = track.line_v_allowed[si % n_track]
                if speed > line_v * 1.02:
                    line_c = (235, 45, 35)      # no llegas a frenar: FRENA
                elif speed > line_v * 0.88:
                    line_c = (250, 205, 60)     # al límite
                else:
                    line_c = (140, 235, 140)    # margen de sobra
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
                # trazada ideal
                if show_line and cfg.RACING_LINE and ww > 10:
                    lx = cxx + line_n * ww / cfg.ROAD_HALF_WIDTH
                    lw2 = max(2, ww * 0.05)
                    self._fill(lx - lw2 / 2, y, lw2, 1, line_c)
            clip_y = min(clip_y, y2)
            min_y = min(min_y, top)

        # postes de lejos a cerca para que los cercanos tapen a los lejanos.
        # Tienen tamaño mínimo en pantalla para verse desde lejos, y se
        # recortan contra el terreno (en una cresta asoma solo la punta)
        for y2, x2, w2, clip_at in reversed(poles):
            px_m = w2 / cfg.ROAD_HALF_WIDTH
            kerb_px = w2 * (cfg.KERB_WIDTH / cfg.ROAD_HALF_WIDTH)
            h = max(9.0, px_m * 2.2)
            pw = max(3, px_m * 0.22)
            top = y2 - h
            bottom = min(y2, clip_at)
            if bottom <= top:
                continue
            cap_h = max(2, h * 0.25)
            for side, color in ((-1, (255, 215, 30)), (1, (60, 145, 255))):
                px = x2 + side * (w2 + kerb_px + px_m * 0.5)
                self._fill(px - pw / 2, top, pw, bottom - top, color)
                self._fill(px - pw / 2, top, pw,
                           min(cap_h, bottom - top), (245, 245, 245))
        return min_y

    # ------------------------------------------------------------------
    def draw_car(self, car_state, steering):
        """Coche visto desde atrás con la carrocería VIVA: cabecea al
        acelerar/frenar, se balancea en las curvas y flota en las crestas
        (ángulos reales de la suspensión, exagerados para percibirlos).
        Las ruedas quedan fijas al suelo y están dibujadas A ESCALA: la vía
        real (CAR_TRACK_WIDTH) proyectada a la distancia del coche, de modo
        que cuando una rueda pisa el piano en la física, se ve pisándolo."""
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        ex = cfg.CAR_BODY_MOTION_EXAG
        # escala real: píxeles por metro a la distancia visual del coche
        z_car = 4.0
        ppm = cfg.CAMERA_DEPTH / z_car * (W / 2.0)
        track_px = cfg.CAR_TRACK_WIDTH * ppm
        car_w = int(1.78 * ppm)
        car_h = 116
        cx = W / 2 + steering * 18 - car_state.psi * 120
        cy = H - 108
        x = cx - car_w / 2

        # movimiento de la carrocería: + abajo. Frenar (pitch<0, morro
        # abajo) LEVANTA la cola que vemos; acelerar la hunde (squat,
        # amplificado porque la aceleración genera menos cabeceo que la
        # frenada y de serie apenas se percibía); las crestas la hacen flotar
        pitch_term = car_state.pitch * 250.0
        if pitch_term > 0.0:
            pitch_term *= 2.2
        body_dy = int((pitch_term - car_state.heave * 120.0) * ex) - 4
        body_dy = max(-26, min(26, body_dy))
        # balanceo: pendiente vertical por columna (roll + = derecha
        # elevada -> en pantalla el lado izquierdo baja)
        tilt = -car_state.roll * ex
        braking = car_state.ax < -2.0

        # sombra y ruedas, fijas al suelo y a escala con la vía real
        self._fill(x + 8, cy + car_h - 16, car_w - 16, 18, (20, 20, 20))
        wheel_w, wheel_h = int(0.31 * ppm), 32
        for side in (-1, 1):
            wx = cx + side * track_px / 2.0 - wheel_w / 2.0
            self._fill(wx, cy + car_h - wheel_h - 6, wheel_w, wheel_h,
                       (22, 22, 22))
            self._fill(wx + wheel_w * 0.3, cy + car_h - wheel_h + 4,
                       wheel_w * 0.4, 12, (75, 75, 75))

        # carrocería por columnas verticales inclinadas por el balanceo
        n_cols = 18
        col_w = car_w / n_cols
        light_zone = int(car_w * 0.21)
        for i in range(n_cols):
            dx = (i + 0.5) * col_w - car_w / 2
            dyc = body_dy + int(tilt * dx)
            colx = x + i * col_w
            cw = int(col_w) + 1
            # techo
            self._fill(colx, cy + 17 + dyc, cw, 7, (150, 18, 24))
            # luneta trasera (con margen a los lados)
            if abs(dx) < car_w / 2 - 34:
                self._fill(colx, cy + 24 + dyc, cw, 17, (35, 40, 60))
            else:
                self._fill(colx, cy + 24 + dyc, cw, 17, (150, 18, 24))
            # cuerpo principal
            self._fill(colx, cy + 41 + dyc, cw, 57, (178, 24, 30))
            # pilotos traseros (más brillantes al frenar)
            edge = car_w / 2 - abs(dx)
            if 10 < edge < light_zone:
                lc = (255, 170, 130) if braking else (225, 55, 40)
                self._fill(colx, cy + 53 + dyc, cw, 12, lc)

    def draw_car_chase(self, car_state, steering):
        """Vista de coche completo desde atrás y arriba: se ven las 4
        ruedas (las delanteras giran con el volante) y la carrocería
        cabecea y se balancea SOBRE ellas con los ángulos reales de la
        suspensión, como en las vistas chase de los simuladores."""
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        ex = cfg.CAR_BODY_MOTION_EXAG
        cx = W / 2 + steering * 14 - car_state.psi * 110
        y0 = H - 46
        tilt = -car_state.roll * ex
        pitch_raw = car_state.pitch * 250.0
        if pitch_raw > 0.0:
            pitch_raw *= 2.2   # squat al acelerar, amplificado
        pitch_off = max(-16.0, min(16.0, pitch_raw * ex))
        dy_h = int(max(-14.0, min(14.0, -car_state.heave * 120.0 * ex)))
        braking = car_state.ax < -2.0
        delta = steering * math.radians(cfg.WHEEL_ROTATION_DEG / 2.0) / cfg.STEER_RATIO
        shear = math.tan(max(-0.7, min(0.7, delta)))

        rear_half, front_half = 74, 59
        y_front_ax = y0 - 140      # eje delantero en pantalla
        # sombra
        self._fill(cx - rear_half - 4, y0 - 150, rear_half * 2 + 8, 152,
                   (38, 38, 42))

        # ruedas traseras (fijas al suelo)
        for side in (-1, 1):
            wx = cx + side * (rear_half + 16) - 13
            self._fill(wx, y0 - 30, 26, 30, (20, 20, 20))
            self._fill(wx + 8, y0 - 20, 10, 10, (70, 70, 70))
        # ruedas delanteras giradas con el volante (a rebanadas)
        for side in (-1, 1):
            wxc = cx + side * (front_half + 12)
            for r in range(0, 26, 3):
                off = shear * (13 - r)
                self._fill(wxc + off - 10, y_front_ax - 26 + r, 20, 3,
                           (20, 20, 20))

        # carrocería por bandas (morro, cabina, zaga), cada una con
        # columnas verticales inclinadas por el balanceo
        bands = (
            # (y_sup, alto, semiancho, factor_cabeceo, tipo)
            (y0 - 176, 46, front_half, -0.8, "nose"),
            (y0 - 130, 66, 67, 0.0, "cabin"),
            (y0 - 64, 60, rear_half, 0.8, "rear"),
        )
        n_cols = 16
        for y_top, h, half, pf, kind in bands:
            dy_band = int(pf * pitch_off) + dy_h
            colw = half * 2.0 / n_cols
            for i in range(n_cols):
                dx = (i + 0.5) * colw - half
                dyc = dy_band + int(tilt * dx)
                colx = cx - half + i * colw
                cw = int(colw) + 1
                yy = y_top + dyc
                if kind == "nose":
                    self._fill(colx, yy, cw, 8, (150, 18, 24))
                    self._fill(colx, yy + 8, cw, h - 8, (178, 24, 30))
                elif kind == "cabin":
                    # parabrisas delante, techo detrás
                    self._fill(colx, yy, cw, 14, (35, 40, 60))
                    self._fill(colx, yy + 14, cw, h - 14, (150, 18, 24))
                else:
                    # luneta trasera, maletero y pilotos
                    self._fill(colx, yy, cw, 16, (35, 40, 60))
                    self._fill(colx, yy + 16, cw, h - 26, (178, 24, 30))
                    edge = half - abs(dx)
                    if 4 < edge < 26:
                        lc = (255, 170, 130) if braking else (225, 55, 40)
                        self._fill(colx, yy + h - 10, cw, 8, lc)
                    else:
                        self._fill(colx, yy + h - 10, cw, 8, (150, 18, 24))


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

    def draw(self, car_state, lap_time, best_lap, lap_count, ffb_ok, wheel_name,
             auto_gear=False):
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        st = car_state

        # ------- cuentavueltas grande arriba, centrado, siempre a la vista
        bar_w, bar_h = 520, 30
        bx = (W - bar_w) // 2
        by = 18
        self._fill(bx - 104, by - 8, bar_w + 116, bar_h + 34, (0, 0, 0, 160))
        self._fill(bx, by, bar_w, bar_h, (52, 52, 52))
        rpm_frac = min(1.0, st.rpm / cfg.ENGINE_LIMITER_RPM)
        fill_w = int(bar_w * rpm_frac)
        # tramo verde, ámbar y rojo
        w_green = min(fill_w, int(bar_w * 0.62))
        w_amber = min(fill_w, int(bar_w * 0.85)) - int(bar_w * 0.62)
        w_red = fill_w - int(bar_w * 0.85)
        self._fill(bx, by, w_green, bar_h, (85, 215, 85))
        if w_amber > 0:
            self._fill(bx + int(bar_w * 0.62), by, w_amber, bar_h, (245, 205, 60))
        if w_red > 0:
            self._fill(bx + int(bar_w * 0.85), by, w_red, bar_h, (235, 55, 45))
        # marcas cada 1000 rpm y línea del corte
        for k in range(1, int(cfg.ENGINE_LIMITER_RPM // 1000) + 1):
            tx = bx + int(bar_w * k * 1000.0 / cfg.ENGINE_LIMITER_RPM)
            self._fill(tx, by, 2, bar_h, (25, 25, 25))
        red_x = bx + int(bar_w * cfg.ENGINE_REDLINE_RPM / cfg.ENGINE_LIMITER_RPM)
        self._fill(red_x, by - 4, 3, bar_h + 8, (255, 255, 255))
        font.draw_text(self.r, f"{int(st.rpm)}", bx, by + bar_h + 6, 2)
        # marcha en grande junto a la barra + modo de cambio
        gear_txt = "R" if st.gear < 0 else ("N" if st.gear == 0 else str(st.gear))
        gear_c = (235, 55, 45, 255) if rpm_frac > 0.85 else (255, 200, 60, 255)
        font.draw_text(self.r, gear_txt, bx - 68, by - 8, 6, gear_c)
        font.draw_text(self.r, "AUTO" if auto_gear else "MAN",
                       bx - 100, by + bar_h + 8, 2,
                       (140, 220, 255, 255) if auto_gear else (200, 200, 200, 255))

        # ------- panel inferior izquierdo: velocidad
        self._fill(20, H - 116, 260, 96, (0, 0, 0, 160))
        font.draw_text(self.r, f"{int(st.speed_kmh):3d}", 40, H - 100, 6)
        font.draw_text(self.r, "KM/H", 170, H - 84, 2)

        # tiempos
        self._fill(W - 320, 20, 300, 92, (0, 0, 0, 160))
        font.draw_text(self.r, f"VUELTA {lap_count}", W - 300, 32, 2)
        font.draw_text(self.r, f"TIEMPO {_fmt_time(lap_time)}", W - 300, 56, 2)
        best_txt = _fmt_time(best_lap) if best_lap else "--:--.-"
        font.draw_text(self.r, f"MEJOR  {best_txt}", W - 300, 80, 2, (255, 200, 60, 255))

        # estado del dispositivo (abajo, junto al velocímetro)
        dev = wheel_name if wheel_name else "TECLADO - FLECHAS"
        ffb = "FFB OK" if ffb_ok else "SIN FFB"
        font.draw_text(self.r, f"{dev[:30]}  {ffb}  {cfg.DRIVE_TYPE}", 20, H - 140, 2,
                       (180, 255, 180, 255) if ffb_ok else (255, 180, 140, 255))

        # motor parado: aviso grande en el centro
        if not st.engine_on:
            msg = "MOTOR PARADO"
            sub = "PULSA E O EL BOTON DE ARRANQUE"
            w1 = font.text_width(msg, 4)
            w2 = font.text_width(sub, 2)
            bxc = W // 2
            self._fill(bxc - w1 // 2 - 20, H // 2 - 120, w1 + 40, 78,
                       (90, 10, 10, 210))
            font.draw_text(self.r, msg, bxc - w1 // 2, H // 2 - 106, 4,
                           (255, 90, 70, 255))
            font.draw_text(self.r, sub, bxc - w2 // 2, H // 2 - 66, 2,
                           (255, 210, 200, 255))

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
        if st.front_grip_used > 0.88 and st.speed_kmh > 25:
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


    def draw_telemetry(self, car_state):
        """Superposición F2: círculo de fricción de cada rueda en vivo.
        Eje X = deriva normalizada (alfa/alfa_pico), eje Y = deslizamiento
        longitudinal normalizado (s/s_pico). El círculo marca rho = 1 (el
        pico de agarre); el punto fuera del círculo = neumático saturado."""
        W = cfg.WINDOW_WIDTH
        box_x, box_y, box_w, box_h = W - 320, 130, 300, 360
        self._fill(box_x, box_y, box_w, box_h, (0, 0, 0, 190))
        font.draw_text(self.r, "F2: CIRCULO DE FRICCION", box_x + 12, box_y + 10, 2)
        names = ("DI", "DD", "TI", "TD")
        radius = 52
        for i in range(4):
            cx = box_x + 80 + (i % 2) * 145
            cy = box_y + 90 + (i // 2) * 150
            # aro rho = 1
            sdl2.SDL_SetRenderDrawColor(self.r, 110, 110, 110, 255)
            for deg in range(0, 360, 5):
                a = math.radians(deg)
                self._fill(cx + radius * math.cos(a) - 1,
                           cy + radius * math.sin(a) - 1, 2, 2, (110, 110, 110))
            # ejes
            self._fill(cx - radius, cy, radius * 2, 1, (70, 70, 70))
            self._fill(cx, cy - radius, 1, radius * 2, (70, 70, 70))
            # punto de estado (saturado = rojo)
            a_n = car_state.slip_angle[i] / math.radians(cfg.TIRE_PEAK_SLIP_ANGLE_DEG)
            s_n = car_state.slip_ratio[i] / cfg.TIRE_PEAK_SLIP_RATIO
            rho = math.hypot(a_n, s_n)
            a_n = max(-1.5, min(1.5, a_n))
            s_n = max(-1.5, min(1.5, s_n))
            color = (255, 70, 50) if rho > 1.0 else (90, 230, 90)
            self._fill(cx + a_n * radius - 3, cy - s_n * radius - 3, 6, 6, color)
            # etiqueta y carga
            font.draw_text(self.r, names[i], cx - radius, cy - radius - 4, 2)
            load_frac = min(1.0, car_state.fz[i] / 8000.0)
            self._fill(cx - radius, cy + radius + 6, radius * 2, 6, (60, 60, 60))
            self._fill(cx - radius, cy + radius + 6,
                       int(radius * 2 * load_frac), 6, (120, 180, 255))



def _fmt_time(t):
    if t is None:
        return "--:--.-"
    mins = int(t // 60)
    secs = t - mins * 60
    return f"{mins:02d}:{secs:04.1f}"
