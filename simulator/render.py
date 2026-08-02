"""Renderizado pseudo-3D de la carretera (estilo clásico de segmentos).

Proyecta los segmentos del circuito desde la cámara situada detrás del coche
y dibuja franjas horizontales interpoladas: hierba, pianos, asfalto y líneas.
Las curvas se acumulan como desplazamiento lateral creciente con la distancia
y las colinas mueven el horizonte.
"""

import ctypes
import math

import numpy as np
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
    def draw_road(self, track, car_state, show_line=True, cam_height=None,
                  cam_back=0.0, yaw_gain=None):
        """Renderizador 3D real: proyección en perspectiva de la malla de
        la carretera con la cámara anclada al coche (posición, rumbo y
        altura reales). La geometría se construye por secciones
        transversales y se dibuja por triángulos (SDL_RenderGeometryRaw)
        ordenados de lejos a cerca (algoritmo del pintor)."""
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        speed = abs(car_state.vx)
        if cam_height is None:
            cam_height = cfg.CAMERA_HEIGHT
        segs = track.segments
        n_segs = len(segs)
        L = cfg.SEGMENT_LENGTH
        f = cfg.CAMERA_DEPTH
        half_w = cfg.ROAD_HALF_WIDTH
        kerb_w = cfg.KERB_WIDTH

        base_i = int(car_state.s / L)
        frac = (car_state.s - base_i * L) / L
        cam_y = segs[base_i % n_segs].y + cam_height
        if yaw_gain is None:
            yaw_gain = cfg.CAMERA_YAW_GAIN
        psi_c = car_state.psi * yaw_gain
        cp, sp = math.cos(psi_c), math.sin(psi_c)

        # --- centro de la carretera en el plano local del coche ---------
        N_BACK = 3
        N = cfg.DRAW_DISTANCE
        n_sec = N_BACK + N + 1
        cx = np.empty(n_sec)
        cz = np.empty(n_sec)
        hx = np.empty(n_sec)   # componentes del vector "derecha"
        hz = np.empty(n_sec)
        elev = np.empty(n_sec)
        seg_idx = np.empty(n_sec, dtype=np.int64)

        # retroceder N_BACK secciones desde la sección base
        x = 0.0
        z = -frac * L
        h = 0.0
        for j in range(N_BACK):
            k = (base_i - j - 1) % n_segs
            h -= segs[k].kappa * L
            x -= math.sin(h) * L
            z -= math.cos(h) * L
        # avanzar registrando secciones
        for j in range(n_sec):
            k = (base_i - N_BACK + j) % n_segs
            seg = segs[k]
            cx[j] = x
            cz[j] = z
            hx[j] = math.cos(h)      # "derecha" = (cos h, -sin h)
            hz[j] = -math.sin(h)
            elev[j] = seg.y
            seg_idx[j] = base_i - N_BACK + j
            x += math.sin(h) * L
            z += math.cos(h) * L
            h += seg.kappa * L

        # desplazar al coche (está a +n del centro) y girar por el rumbo
        cx = cx - car_state.n
        xr = cx * cp - cz * sp
        zr = cx * sp + cz * cp + cam_back
        rxr = hx * cp - hz * sp
        rzr = hx * sp + hz * cp

        # recorte del plano cercano: la sección que queda justo detrás de
        # la cámara se interpola exactamente sobre el plano z=0.3 para que
        # el asfalto llegue hasta el borde inferior de la pantalla
        Z_NEAR = 0.3
        for j in range(min(N_BACK + 3, n_sec - 1)):
            if zr[j] <= Z_NEAR < zr[j + 1]:
                t = (Z_NEAR - zr[j]) / (zr[j + 1] - zr[j])
                xr[j] += (xr[j + 1] - xr[j]) * t
                zr[j] = Z_NEAR + 1e-4
                rxr[j] += (rxr[j + 1] - rxr[j]) * t
                rzr[j] += (rzr[j + 1] - rzr[j]) * t
                elev[j] += (elev[j + 1] - elev[j]) * t

        # --- offsets transversales de la malla --------------------------
        li = np.array([track.line_n[s % n_segs] for s in seg_idx])
        GW = 38.0
        offs = [
            (-GW, -half_w - kerb_w),          # hierba izquierda
            (-half_w - kerb_w, -half_w),      # piano izquierdo
            (-half_w, half_w),                # asfalto
            (-half_w + 0.06, -half_w + 0.42), # línea blanca izquierda
            (half_w - 0.42, half_w - 0.06),   # línea blanca derecha
            (-0.14, 0.14),                    # línea central discontinua
            (half_w, half_w + kerb_w),        # piano derecho
            (half_w + kerb_w, GW),            # hierba derecha
        ]
        if show_line and cfg.RACING_LINE:
            offs.append(None)                 # trazada (offset por sección)

        # --- proyección de todos los puntos ------------------------------
        dy = elev - cam_y
        z_ok = zr > 0.25
        inv_z = np.where(z_ok, 1.0 / np.maximum(zr, 0.25), 0.0)

        def clip_col(xc, zc):
            """Recorta una columna de puntos contra el plano cercano
            interpolando el punto de cruce: el quad que atraviesa la
            cámara no desaparece (evita el parpadeo del borde inferior)."""
            crossings = np.nonzero((zc[:-1] <= 0.28) & (zc[1:] > 0.28))[0]
            for j in crossings:
                t = (0.28 - zc[j]) / (zc[j + 1] - zc[j])
                xc[j] += (xc[j + 1] - xc[j]) * t
                zc[j] = 0.2801

        def project(o_left, o_right, per_section=None):
            """Devuelve (P0x,P0y,P1x,P1y) proyectados por sección para un
            par de offsets (o el offset de la trazada por sección)."""
            if per_section is not None:
                oL = per_section - 0.30
                oR = per_section + 0.30
            else:
                oL = np.full(n_sec, o_left)
                oR = np.full(n_sec, o_right)
            xl = xr + rxr * oL
            zl = zr + rzr * oL
            xrg = xr + rxr * oR
            zrg = zr + rzr * oR
            clip_col(xl, zl)
            clip_col(xrg, zrg)
            izl = np.where(zl > 0.25, 1.0 / np.maximum(zl, 0.25), 0.0)
            izr = np.where(zrg > 0.25, 1.0 / np.maximum(zrg, 0.25), 0.0)
            sxl = W / 2 + f * xl * izl * (W / 2)
            syl = H / 2 - f * dy * izl * (H / 2)
            sxr = W / 2 + f * xrg * izr * (W / 2)
            syr = H / 2 - f * dy * izr * (H / 2)
            valid = (zl > 0.25) & (zrg > 0.25)
            return sxl, syl, sxr, syr, valid

        # --- colores por segmento ----------------------------------------
        par3 = (seg_idx // 3) % 2
        par2 = (seg_idx // 2) % 2
        par4 = (seg_idx // 4) % 2
        kerb_flag = np.array([segs[s % n_segs].kerb for s in seg_idx])
        grass_c = np.where(par3[:, None].astype(bool),
                           np.array(GRASS[0]), np.array(GRASS[1]))
        road_c = np.where(par3[:, None].astype(bool),
                          np.array(ROAD[0]), np.array(ROAD[1]))
        kerb_c = np.where(par2[:, None].astype(bool),
                          np.array(KERB[0]), np.array(KERB[1]))
        kerb_c = np.where(kerb_flag[:, None], kerb_c, grass_c)
        line_white = np.tile(np.array(LINE), (n_sec, 1))
        cline_c = np.where(par4[:, None].astype(bool), line_white, road_c)
        if show_line and cfg.RACING_LINE:
            v_allow = np.array([track.line_v_allowed[s % n_segs] for s in seg_idx])
            rl_c = np.empty((n_sec, 3))
            rl_c[:] = (140, 235, 140)
            rl_c[speed > v_allow * 0.88] = (250, 205, 60)
            rl_c[speed > v_allow * 1.02] = (235, 45, 35)

        band_colors = [grass_c, kerb_c, road_c, line_white, line_white,
                       cline_c, kerb_c, grass_c]
        if show_line and cfg.RACING_LINE:
            band_colors.append(rl_c)

        # --- construir vértices e índices (lejos -> cerca) ---------------
        n_quads = n_sec - 1
        all_xy = []
        all_col = []
        index_blocks = []
        v_base = 0
        for b, spec in enumerate(offs):
            if spec is None:
                sxl, syl, sxr, syr, valid = project(0, 0, per_section=li)
            else:
                sxl, syl, sxr, syr, valid = project(spec[0], spec[1])
            # cuatro esquinas por quad: (j izq, j der, j+1 izq, j+1 der)
            xy = np.empty((n_quads, 4, 2), dtype=np.float32)
            xy[:, 0, 0] = sxl[:-1]; xy[:, 0, 1] = syl[:-1]
            xy[:, 1, 0] = sxr[:-1]; xy[:, 1, 1] = syr[:-1]
            xy[:, 2, 0] = sxl[1:];  xy[:, 2, 1] = syl[1:]
            xy[:, 3, 0] = sxr[1:];  xy[:, 3, 1] = syr[1:]
            col = np.empty((n_quads, 4, 4), dtype=np.uint8)
            col[:, :, :3] = band_colors[b][:-1][:, None, :]
            col[:, :, 3] = 255
            qv = valid[:-1] & valid[1:]
            base = v_base + np.arange(n_quads, dtype=np.int32) * 4
            idx = np.empty((n_quads, 6), dtype=np.int32)
            idx[:, 0] = base;     idx[:, 1] = base + 1; idx[:, 2] = base + 2
            idx[:, 3] = base + 1; idx[:, 4] = base + 3; idx[:, 5] = base + 2
            idx[~qv] = -1
            all_xy.append(xy.reshape(-1, 2))
            all_col.append(col.reshape(-1, 4))
            index_blocks.append(idx)
            v_base += n_quads * 4

        xy_v = np.concatenate(all_xy)
        col_v = np.concatenate(all_col)
        # orden del pintor: quads de la sección más lejana primero,
        # intercalando todas las bandas de cada sección
        idx_stack = np.stack(index_blocks, axis=1)      # (n_quads, bandas, 6)
        idx_sorted = idx_stack[::-1].reshape(-1, 6)
        idx_flat = idx_sorted[idx_sorted[:, 0] >= 0].reshape(-1).astype(np.int32)
        uv_v = np.zeros_like(xy_v)

        if len(idx_flat) > 0:
            sdl2.SDL_RenderGeometryRaw(
                self.r, None,
                xy_v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), 8,
                col_v.ctypes.data_as(ctypes.POINTER(sdl2.SDL_Color)), 4,
                uv_v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), 8,
                len(xy_v),
                idx_flat.ctypes.data_as(ctypes.c_void_p), len(idx_flat), 4)

        # --- balizas (billboards) de lejos a cerca -----------------------
        if cfg.TRACK_POLES:
            for j in range(n_sec - 1, N_BACK, -1):
                if seg_idx[j] % (6 if inv_z[j] * f * (W / 2) > 3.0 else 12):
                    continue
                if not z_ok[j] or zr[j] > 700.0:
                    continue
                ppm = f * inv_z[j] * (W / 2)
                if ppm < 0.8:
                    continue
                h_px = max(9.0, ppm * 2.2)
                pw = max(3.0, ppm * 0.22)
                cap = max(2.0, h_px * 0.25)
                for side, color in ((-1, (255, 215, 30)), (1, (60, 145, 255))):
                    o = side * (half_w + kerb_w + 0.5)
                    px_w = xr[j] + rxr[j] * o
                    pz_w = zr[j] + rzr[j] * o
                    if pz_w < 0.3:
                        continue
                    sx = W / 2 + f * px_w / pz_w * (W / 2)
                    sy = H / 2 - f * dy[j] / pz_w * (H / 2)
                    self._fill(sx - pw / 2, sy - h_px, pw, h_px, color)
                    self._fill(sx - pw / 2, sy - h_px, pw, cap, (245, 245, 245))
        return H // 2

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
        # la cámara va anclada al coche: el coche queda fijo en pantalla
        # (solo un matiz con el volante) y es el mundo el que gira
        cx = W / 2 + steering * 18
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

    def draw_car_3d(self, car_state, steering, cam_height, cam_back,
                    yaw_gain):
        """Coche 3D real para la vista de coche completo: cajas en
        perspectiva orientadas con el RUMBO del coche (la parte de psi que
        la cámara no sigue), con las ruedas delanteras giradas por la
        dirección y la carrocería cabeceando/balanceando en 3D."""
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        f = cfg.CAMERA_DEPTH
        ex = cfg.CAR_BODY_MOTION_EXAG * 0.55
        dpsi = car_state.psi * (1.0 - yaw_gain)
        cyaw, syaw = math.cos(dpsi), math.sin(dpsi)
        delta = steering * math.radians(cfg.WHEEL_ROTATION_DEG / 2.0) / cfg.STEER_RATIO
        delta = max(-0.6, min(0.6, delta))
        heave = max(-0.12, min(0.12, car_state.heave * ex))
        pitch = max(-0.10, min(0.10, car_state.pitch * ex))
        roll = max(-0.12, min(0.12, car_state.roll * ex))
        braking = car_state.ax < -2.0

        quads = []   # (z_medio, [(x,y) x4], color)

        def to_cam(px, py, pz, yaw_c=cyaw, yaw_s=syaw, ox=0.0, oz=0.0):
            # coche: x derecha, y arriba (desde el suelo), z adelante
            x = (px * yaw_c + pz * yaw_s) + ox
            z = (-px * yaw_s + pz * yaw_c) + oz + cam_back
            return x, py - cam_height, z

        def add_quad(p0, p1, p2, p3, color):
            zs = []
            scr = []
            for (x, y, z) in (p0, p1, p2, p3):
                if z < 0.3:
                    return
                zs.append(z)
                scr.append((W / 2 + f * x / z * (W / 2),
                            H / 2 - f * y / z * (H / 2)))
            quads.append((sum(zs) / 4.0, scr, color))

        def add_box(x0, x1, y0, y1, z0, z1, cs, ct, body=False,
                    yaw2=0.0, cx0=0.0, cz0=0.0):
            """Caja [x0..x1]x[y0..y1]x[z0..z1]; si body, aplica cabeceo/
            balanceo/altura; yaw2 rota la caja sobre su centro (ruedas
            directrices)."""
            c2, s2 = math.cos(yaw2), math.sin(yaw2)
            corners = {}
            for ix, xx in enumerate((x0, x1)):
                for iy, yy in enumerate((y0, y1)):
                    for iz, zz in enumerate((z0, z1)):
                        px, pz = xx, zz
                        if yaw2:
                            rx, rz = px - cx0, pz - cz0
                            px = cx0 + rx * c2 + rz * s2
                            pz = cz0 - rx * s2 + rz * c2
                        py = yy
                        if body:
                            py += heave + pitch * pz + roll * px
                        corners[(ix, iy, iz)] = to_cam(px, py, pz)
            # caras: trasera (z0), superior (y1), izquierda, derecha, frontal
            add_quad(corners[(0, 0, 0)], corners[(1, 0, 0)],
                     corners[(1, 1, 0)], corners[(0, 1, 0)], cs)
            add_quad(corners[(0, 0, 1)], corners[(1, 0, 1)],
                     corners[(1, 1, 1)], corners[(0, 1, 1)], cs)
            add_quad(corners[(0, 0, 0)], corners[(0, 0, 1)],
                     corners[(0, 1, 1)], corners[(0, 1, 0)], cs)
            add_quad(corners[(1, 0, 0)], corners[(1, 0, 1)],
                     corners[(1, 1, 1)], corners[(1, 1, 0)], cs)
            add_quad(corners[(0, 1, 0)], corners[(1, 1, 0)],
                     corners[(1, 1, 1)], corners[(0, 1, 1)], ct)

        # sombra en el suelo
        sh = [to_cam(px, 0.02, pz) for (px, pz) in
              ((-1.0, -2.3), (1.0, -2.3), (1.0, 2.3), (-1.0, 2.3))]
        add_quad(sh[0], sh[1], sh[2], sh[3], (30, 30, 34))

        # ruedas (las delanteras giran con la dirección)
        for sx_ in (-1, 1):
            add_box(sx_ * 0.86 - 0.13, sx_ * 0.86 + 0.13, 0.0, 0.62,
                    -1.62, -0.96, (22, 22, 22), (40, 40, 40))
            add_box(sx_ * 0.83 - 0.12, sx_ * 0.83 + 0.12, 0.0, 0.58,
                    0.98, 1.58, (22, 22, 22), (40, 40, 40),
                    yaw2=delta, cx0=sx_ * 0.83, cz0=1.28)

        # carrocería y cabina (con dinámica)
        add_box(-0.89, 0.89, 0.34, 0.95, -2.08, 2.08,
                (152, 20, 26), (196, 40, 44), body=True)
        add_box(-0.72, 0.72, 0.95, 1.40, -0.85, 0.95,
                (38, 44, 66), (170, 24, 30), body=True)

        # pilotos traseros
        lc = (255, 170, 130) if braking else (228, 58, 42)
        for sx_ in (-1, 1):
            p0 = to_cam(sx_ * 0.78 - 0.16, 0.62, -2.09)
            p1 = to_cam(sx_ * 0.78 + 0.16, 0.62, -2.09)
            p2 = to_cam(sx_ * 0.78 + 0.16, 0.80, -2.09)
            p3 = to_cam(sx_ * 0.78 - 0.16, 0.80, -2.09)
            add_quad(p0, p1, p2, p3, lc)
            quads[-1] = (quads[-1][0] - 0.05, quads[-1][1], quads[-1][2])

        # pintor: de lejos a cerca, en una sola llamada de geometría
        quads.sort(key=lambda q: -q[0])
        n_q = len(quads)
        if not n_q:
            return
        xy = np.empty((n_q * 4, 2), dtype=np.float32)
        col = np.empty((n_q * 4, 4), dtype=np.uint8)
        idx = np.empty((n_q, 6), dtype=np.int32)
        for i, (_, scr, color) in enumerate(quads):
            for k in range(4):
                xy[i * 4 + k] = scr[k]
                col[i * 4 + k, :3] = color
                col[i * 4 + k, 3] = 255
            b = i * 4
            idx[i] = (b, b + 1, b + 2, b, b + 2, b + 3)
        uv = np.zeros_like(xy)
        sdl2.SDL_RenderGeometryRaw(
            self.r, None,
            xy.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), 8,
            col.ctypes.data_as(ctypes.POINTER(sdl2.SDL_Color)), 4,
            uv.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), 8,
            len(xy), idx.reshape(-1).ctypes.data_as(ctypes.c_void_p),
            n_q * 6, 4)

    def draw_car_chase(self, car_state, steering):
        """Vista de coche completo desde atrás y arriba: se ven las 4
        ruedas (las delanteras giran con el volante) y la carrocería
        cabecea y se balancea SOBRE ellas con los ángulos reales de la
        suspensión, como en las vistas chase de los simuladores."""
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        ex = cfg.CAR_BODY_MOTION_EXAG
        # cámara anclada al coche: el coche no se desplaza con psi
        cx = W / 2 + steering * 14
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
             auto_gear=False, time_scale=1.0):
        W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
        st = car_state

        # indicador de cámara lenta
        if time_scale < 0.999:
            txt = f"CAMARA LENTA X{time_scale:.2f}".replace("0.", ".")
            font.draw_text(self.r, txt, W // 2 - font.text_width(txt, 2) // 2,
                           92, 2, (120, 220, 255, 255))

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

        # estado del dispositivo (abajo, junto al velocímetro) y versión
        dev = wheel_name if wheel_name else "TECLADO - FLECHAS"
        ffb = "FFB OK" if ffb_ok else "SIN FFB"
        font.draw_text(self.r, f"{dev[:30]}  {ffb}  {cfg.DRIVE_TYPE}", 20, H - 140, 2,
                       (180, 255, 180, 255) if ffb_ok else (255, 180, 140, 255))
        font.draw_text(self.r, cfg.VERSION, W - font.text_width(cfg.VERSION, 2) - 14,
                       H - 24, 2, (150, 150, 150, 255))

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
        self._draw_susp_car(cfg.WINDOW_WIDTH - 270, 130, car_state)

    def _draw_susp_car(self, x0, y0, car_state):
        """Esquema cenital del coche con sus 4 ruedas y muelles que se
        comprimen (cortos, rojos) o extienden (largos, azules) con la
        suspensión real. Complemento visual del panel F1."""
        self._fill(x0, y0, 250, 210, (0, 0, 0, 190))
        font.draw_text(self.r, "SUSPENSION", x0 + 12, y0 + 10, 2)
        body_w, body_h = 56, 130
        bx = x0 + 125 - body_w // 2
        by = y0 + 46
        # carrocería (morro arriba)
        self._fill(bx, by, body_w, body_h, (178, 24, 30))
        self._fill(bx + 10, by + 26, body_w - 20, 22, (35, 40, 60))
        static = (cfg.CAR_MASS * 9.81 / 4.0)
        wheel_w, wheel_h = 14, 34
        for i in range(4):
            side = -1 if i % 2 == 0 else 1        # 0,2 izquierda
            front = i < 2
            wy = by + (6 if front else body_h - wheel_h - 6)
            d = car_state.susp_def[i]
            # longitud del muelle: nominal 26 px; comprimido = corto
            ln = int(max(8, min(46, 26 - d * 350)))
            ratio = car_state.fz[i] / max(1.0, static)
            if ratio > 1.25:
                sc = (255, 80, 60)      # muy cargado
            elif ratio < 0.55:
                sc = (110, 170, 255)    # descargado (casi en el aire)
            else:
                sc = (120, 230, 120)
            if side < 0:
                sx0 = bx - ln
                wx = sx0 - wheel_w
            else:
                sx0 = bx + body_w
                wx = sx0 + ln
            # muelle en zigzag (5 tramos alternando arriba/abajo)
            segw = ln / 5.0
            for k in range(5):
                off = -4 if k % 2 else 4
                self._fill(sx0 + k * segw, wy + wheel_h / 2 + off - 2,
                           segw + 1, 4, sc)
            # rueda
            self._fill(wx, wy, wheel_w, wheel_h, (25, 25, 25))
            self._fill(wx + 4, wy + 12, wheel_w - 8, 10, (80, 80, 80))


    def draw_minimap(self, track, car_state):
        """Plano del circuito arriba a la izquierda: trazado completo, el
        tramo que viene resaltado en ámbar, la meta y el coche como punto
        rojo — para leer la siguiente curva y preparar la velocidad."""
        pts = track.map_points()
        n = len(pts)
        box_w, box_h = 236, 176
        x0, y0 = 16, 16
        pad = 14
        aw, ah = track._map_aspect
        scale = min((box_w - 2 * pad) / max(aw, 1e-6),
                    (box_h - 2 * pad) / max(ah, 1e-6))
        ox = x0 + (box_w - aw * scale) / 2
        oy = y0 + (box_h - ah * scale) / 2

        self._fill(x0, y0, box_w, box_h, (0, 0, 0, 165))

        def to_px(p):
            return ox + p[0] * scale, oy + (ah - p[1]) * scale

        # trazado completo
        for i in range(0, n, 2):
            px, py = to_px(pts[i])
            self._fill(px, py, 2, 2, (210, 210, 210))
        # tramo inmediato por delante (600 m) en ámbar, más grueso
        i_car = track._index_at(car_state.s)
        for k in range(0, 150, 1):
            px, py = to_px(pts[(i_car + k) % n])
            self._fill(px - 1, py - 1, 3, 3, (250, 200, 60))
        # línea de meta
        mx, my = to_px(pts[0])
        self._fill(mx - 2, my - 2, 6, 6, (255, 255, 255))
        # el coche
        cx_, cy_ = to_px(pts[i_car])
        self._fill(cx_ - 3, cy_ - 3, 7, 7, (235, 45, 35))

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
