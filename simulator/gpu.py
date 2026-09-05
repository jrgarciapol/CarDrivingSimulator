"""Escena 3D en la GPU con moderngl: cielo, carretera y balizas.

Qué cambia respecto al renderizador de SDL (``render.draw_road``)
-------------------------------------------------------------------
Aquel ya mandaba triángulos a la GPU por ``SDL_RenderGeometryRaw``, pero
sin búfer de profundidad ni sombreadores: había que ordenar los cuadriláteros
de lejos a cerca (algoritmo del pintor), recortarlos a mano contra el plano
cercano, y la niebla y la luz se calculaban por vértice en numpy. Aquí:

  - La malla se manda con sus coordenadas 3D y la GPU proyecta, recorta y
    resuelve la oclusión con el búfer de profundidad: sin ordenar, sin
    recortes a mano, y las balizas quedan tapadas por las crestas.
  - Antialiasing multimuestra (``GFX_MSAA``): bordes de pianos y líneas sin
    dientes de sierra.
  - Bruma por píxel en el sombreador: no cuesta CPU, así que el preset de
    rendimiento de la Deck ya no necesita apagarla.
  - El cielo, el sol, los montes lejanos y el suelo hasta el horizonte son un
    sombreador de pantalla completa fijo al MUNDO: al girar la cámara se
    mueven como deben, y en una curva peraltada el horizonte se inclina.

Qué NO cambia: la geometría. La carretera se sigue construyendo cada
fotograma en el sistema local del coche, integrando la curvatura desde su
posición, exactamente como antes pero vectorizado en numpy. Se hace así a
propósito: varios circuitos no cierran en coordenadas de mundo (Spa desvía
33 m; el óvalo, 78° de rumbo), y una malla global integrada desde la meta
tendría una costura en cada vuelta y, peor, dibujaría una curvatura distinta
de la que siente la física. Relativo al coche, lo que se ve es lo que se
conduce.

Cómo convive con SDL
--------------------
El resto del juego (HUD, menús, coche, partículas) sigue dibujándose con el
renderizador de SDL, y en Linux ese renderizador también es OpenGL, con su
propio contexto y una caché de estado que no perdona que otro le cambie
nada. Por eso esta escena usa un contexto PROPIO e independiente (standalone),
pinta en un framebuffer fuera de pantalla, lee los píxeles y se los entrega a
SDL como una textura que se copia al fondo del fotograma. Cuesta una lectura
de W×H×4 bytes por fotograma (4 MB a 1280×800), y a cambio ninguno de los dos
puede pisar el estado del otro. Tras cada fotograma se le devuelve a SDL su
contexto, que en Linux es imprescindible.

Si falta ``moderngl`` o no hay OpenGL 3.3, ``GpuScene.ok`` es False y el
juego sigue con el renderizador de SDL como si nada.
"""

import contextlib
import ctypes
import math
import time

import numpy as np
import sdl2

from . import config as cfg

try:
    import moderngl
except ImportError:                       # pragma: no cover
    moderngl = None

#: metros de hierba a cada lado del asfalto (igual que en el render de SDL)
ANCHO_HIERBA = 38.0
#: planos de recorte de la proyección (m). El cercano coincide con el umbral
#: que usaba el render de SDL para descartar puntos.
Z_CERCA, Z_LEJOS = 0.25, 4000.0
#: elevación de la trazada ideal sobre el asfalto: con búfer de profundidad,
#: dos cuadriláteros coplanares parpadean (z-fighting); un centímetro basta
LEVANTE_TRAZADA = 0.012
#: azimut y elevación del sol en el mundo (rad). Equivalen a la posición que
#: tenía en el fondo 2D con rumbo cero: al 68 % del ancho y a un tercio de la
#: altura del cielo.
SOL_AZIMUT, SOL_ELEVACION = 0.29, 0.50

# --------------------------------------------------------------------------
# Sombreadores
# --------------------------------------------------------------------------
_VS_ESCENA = """#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
in vec3 in_pos;
in vec4 in_col;
out vec4 v_col;
out vec3 v_view;
void main() {
    vec4 p = u_view * vec4(in_pos, 1.0);
    v_view = p.xyz;
    v_col = in_col;
    gl_Position = u_proj * p;
}
"""

_FS_ESCENA = """#version 330
uniform vec3 u_bruma_col;
uniform float u_bruma_d;            // 0 = sin bruma
in vec4 v_col;
in vec3 v_view;
out vec4 f_col;
void main() {
    vec3 c = v_col.rgb;
    if (u_bruma_d > 1.0) {
        // misma ley que tenia el render de SDL, pero por pixel y con la
        // distancia real a la camara en vez de la estacion sobre el eje
        float d = length(v_view);
        float bruma = 0.92 * (1.0 - exp(-pow(d / u_bruma_d, 1.6)));
        c = mix(c, u_bruma_col, bruma);
    }
    f_col = vec4(c, v_col.a);
}
"""

_VS_CIELO = """#version 330
// un solo triangulo que cubre la pantalla entera
const vec2 P[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
void main() { gl_Position = vec4(P[gl_VertexID], 0.0, 1.0); }
"""

_FS_CIELO = """#version 330
uniform vec2 u_tam;          // ancho y alto del framebuffer en pixeles
uniform float u_f;           // CAMERA_DEPTH efectivo (1/tan(fov/2))
uniform float u_pitch;       // cabeceo como desplazamiento vertical en NDC
uniform float u_roll;        // balanceo de la camara = peralte bajo el coche
uniform float u_rumbo;       // rumbo absoluto de la camara en el mundo
uniform float u_alt_cam;     // altura de la camara sobre el suelo (m)
uniform vec3 u_cielo_alto;
uniform vec3 u_cielo_bajo;
uniform vec3 u_calima;
uniform vec3 u_hierba;
uniform vec3 u_monte;
uniform vec3 u_bruma_col;
uniform float u_bruma_d;
uniform float u_sol;         // 1 = dibujar el sol (la lluvia lo tapa)
uniform vec2 u_sol_px;       // centro del sol en pixeles del framebuffer
out vec4 f_col;

float hash(float n) { return fract(sin(n * 12.9898) * 43758.5453); }

// Silueta de montes lejanos: altura angular (rad) segun el azimut. Picos
// triangulares mas anchos que su separacion, como los del fondo 2D, que se
// solapaban; al ser funcion del azimut ABSOLUTO se quedan quietos en el
// mundo y es la camara la que gira.
float cresta(float az) {
    float u = az / 6.2831853 * 14.0;
    float i = floor(u);
    float h = 0.0;
    for (int k = -1; k <= 1; k++) {
        float c = i + float(k) + 0.5;
        float alt = 0.07 + 0.12 * hash(c);
        h = max(h, alt * max(0.0, 1.0 - abs(u - c) / 0.85));
    }
    return h;
}

void main() {
    // NDC con "arriba" hacia la primera fila de la imagen (el framebuffer
    // se lee tal cual, sin darle la vuelta, gracias al signo de la proyeccion)
    float nx = 2.0 * gl_FragCoord.x / u_tam.x - 1.0;
    float ny = 1.0 - 2.0 * gl_FragCoord.y / u_tam.y;
    // rayo de vista, invirtiendo la misma proyeccion que usa la carretera
    vec3 d = normalize(vec3(nx / u_f, (ny + u_pitch) / u_f, 1.0));
    // deshacer el balanceo de la camara: el horizonte se inclina con el peralte
    float cr = cos(u_roll), sr = sin(u_roll);
    d = vec3(d.x * cr + d.y * sr, -d.x * sr + d.y * cr, d.z);
    float az = atan(d.x, d.z) + u_rumbo;
    float el = asin(clamp(d.y, -1.0, 1.0));
    vec3 col;
    if (el >= 0.0) {
        // cielo degradado con CALIMA junto al horizonte (perspectiva aerea)
        float t = clamp(el / 0.62, 0.0, 1.0);
        col = mix(u_cielo_bajo, u_cielo_alto, t);
        col = mix(col, u_calima, 0.55 * pow(1.0 - t, 5.0));
        if (el < cresta(az))
            col = mix(u_monte, u_calima, 0.48);
        if (u_sol > 0.5) {
            // disco y halos en PIXELES (redondos en pantalla, como el fondo
            // 2D): la proyeccion no es isotropa y un disco angular saldria
            // eliptico. Radios referidos a una pantalla de 800 px de alto.
            float r = length(gl_FragCoord.xy - u_sol_px) * (800.0 / u_tam.y);
            col = mix(col, vec3(1.0, 0.98, 0.88), 0.10 * (1.0 - smoothstep(90.0, 120.0, r)));
            col = mix(col, vec3(1.0, 0.98, 0.90), 0.24 * (1.0 - smoothstep(50.0, 70.0, r)));
            col = mix(col, vec3(1.0, 0.99, 0.94), 1.0 - smoothstep(31.0, 35.0, r));
        }
    } else {
        // suelo hasta el horizonte: un plano a la altura de la camara que
        // se funde con la bruma en la distancia
        float dist = u_alt_cam / max(-d.y, 1e-4);
        col = u_hierba;
        if (u_bruma_d > 1.0) {
            float bruma = 0.92 * (1.0 - exp(-pow(dist / u_bruma_d, 1.6)));
            col = mix(col, u_bruma_col, bruma);
        }
    }
    f_col = vec4(col, 1.0);
}
"""

_VERTICE = np.dtype([("pos", "f4", 3), ("col", "u1", 4)])


def _mat_traslacion(x, y, z):
    m = np.eye(4)
    m[0, 3], m[1, 3], m[2, 3] = x, y, z
    return m


def _mat_guinada(psi):
    """Misma rotación que usaba el render de SDL: xr = x·cos − z·sin."""
    c, s = math.cos(psi), math.sin(psi)
    m = np.eye(4)
    m[0, 0], m[0, 2] = c, -s
    m[2, 0], m[2, 2] = s, c
    return m


def _mat_balanceo(theta):
    """Giro sobre el eje de vista: la cámara rueda con el peralte."""
    c, s = math.cos(theta), math.sin(theta)
    m = np.eye(4)
    m[0, 0], m[0, 1] = c, -s
    m[1, 0], m[1, 1] = s, c
    return m


def _mat_proyeccion(f, pitch_ndc):
    """Reproduce EXACTAMENTE la proyección del render de SDL:

        sx = W/2 + f·x/z·W/2        sy = H/2 − f·y/z·H/2 + pitch_px

    o sea, en coordenadas normalizadas ndc_x = f·x/z y ndc_y = f·y/z − pitch,
    con el cabeceo como desplazamiento de pantalla. La fila de y va NEGADA:
    OpenGL guarda el framebuffer de abajo arriba y así la lectura sale ya con
    la primera fila arriba, sin darle la vuelta a 4 MB por fotograma."""
    n, fa = Z_CERCA, Z_LEJOS
    m = np.zeros((4, 4))
    m[0, 0] = f
    m[1, 1] = -f
    m[1, 2] = pitch_ndc
    m[2, 2] = (fa + n) / (fa - n)
    m[2, 3] = -2.0 * fa * n / (fa - n)
    m[3, 2] = 1.0
    return m


class GpuScene:
    """La escena 3D en la GPU. Un objeto por ventana (ver ``obtener``)."""

    def __init__(self, sdl_renderer, ancho, alto, msaa=4, sin_gl=False):
        self.r = sdl_renderer
        self.W, self.H = int(ancho), int(alto)
        self.ok = False
        self.motivo = ""
        self.ctx = None
        self.tex = None
        self._frame = None          # caché del fotograma para world_to_screen
        self._track_id = None
        self._rels_key = None
        self._idx_key = None
        self.ms_malla = self.ms_gl = self.ms_lectura = self.ms_subida = 0.0
        # lectura ASINCRONA del fotograma (ver dibujar): dos PBO que se
        # alternan y el fotograma pendiente de mostrar (indice, cache)
        self.pbo = None
        self._pbo_i = 0
        self._pendiente = None
        self.asincrono = False      # (informativo) si el ultimo fue asincrono
        if sin_gl:
            # solo la geometria (pruebas): ni contexto ni textura
            self.motivo = "sin GL a proposito"
            return
        if moderngl is None:
            self.motivo = "falta moderngl (pip install moderngl)"
            return
        prev = self._contexto_sdl()
        try:
            self.ctx = self._crear_contexto()
            self._montar(msaa)
            self.ok = True
        except Exception as e:                       # noqa: BLE001
            self.motivo = f"{type(e).__name__}: {str(e)[:120]}"
            self.ctx = None
        finally:
            self._devolver_contexto_sdl(prev)
        if self.ok:
            self.tex = sdl2.SDL_CreateTexture(
                sdl_renderer, sdl2.SDL_PIXELFORMAT_ABGR8888,
                sdl2.SDL_TEXTUREACCESS_STREAMING, self.W, self.H)
            if not self.tex:
                self.ok = False
                self.motivo = "SDL no pudo crear la textura de la escena"
            else:
                sdl2.SDL_SetTextureBlendMode(self.tex, sdl2.SDL_BLENDMODE_NONE)

    # -- contexto ---------------------------------------------------------
    @staticmethod
    def _crear_contexto():
        """Contexto OpenGL propio. En Linux con escritorio se abre por X11
        (GLX); sin pantalla, por EGL (también sirve para las pruebas con
        Mesa por software)."""
        errores = []
        for kw in ({}, {"backend": "egl"}):
            try:
                return moderngl.create_standalone_context(require=330, **kw)
            except Exception as e:                   # noqa: BLE001
                errores.append(f"{kw or 'auto'}: {str(e)[:60]}")
        raise RuntimeError("sin OpenGL 3.3 (" + "; ".join(errores) + ")")

    @staticmethod
    def _contexto_sdl():
        """El contexto GL que SDL cree tener activo, para devolvérselo.

        SDL lleva su propia cuenta de qué contexto está activo y no la
        comprueba contra el driver: si otro contexto se activa a sus
        espaldas, sus siguientes llamadas van a parar a ese otro. En Windows
        el renderizador de SDL es Direct3D y esto devuelve nulo: no hay nada
        que devolver."""
        return (sdl2.SDL_GL_GetCurrentWindow(), sdl2.SDL_GL_GetCurrentContext())

    @staticmethod
    def _devolver_contexto_sdl(prev):
        win, ctx = prev
        if ctx:
            sdl2.SDL_GL_MakeCurrent(win, ctx)

    @contextlib.contextmanager
    def _gl(self):
        prev = self._contexto_sdl()
        self.ctx.__enter__()
        try:
            yield self.ctx
        finally:
            self.ctx.__exit__(None, None, None)
            self._devolver_contexto_sdl(prev)

    def _montar(self, msaa):
        ctx = self.ctx
        self.prog = ctx.program(vertex_shader=_VS_ESCENA,
                                fragment_shader=_FS_ESCENA)
        self.prog_cielo = ctx.program(vertex_shader=_VS_CIELO,
                                      fragment_shader=_FS_CIELO)
        self.vao_cielo = ctx.vertex_array(self.prog_cielo, [])
        # búferes generosos; se redimensionan si hiciera falta
        self.vbo = ctx.buffer(reserve=64 * 1024 * _VERTICE.itemsize)
        self.ibo = ctx.buffer(reserve=96 * 1024 * 4)
        self.vao = ctx.vertex_array(
            self.prog, [(self.vbo, "3f 4f1", "in_pos", "in_col")],
            index_buffer=self.ibo, index_element_size=4)
        tam = (self.W, self.H)
        m = max(0, min(8, int(msaa)))
        m = m if m in (0, 2, 4, 8) else 4
        try:
            self.fbo_ms = ctx.framebuffer(
                [ctx.renderbuffer(tam, 4, samples=m)],
                ctx.depth_renderbuffer(tam, samples=m))
        except Exception:                            # noqa: BLE001
            m = 0
            self.fbo_ms = None
        self.msaa = m
        self.fbo = ctx.framebuffer([ctx.renderbuffer(tam, 4)],
                                   ctx.depth_renderbuffer(tam))
        # dos PBO (pixel buffer objects) para leer el fotograma sin esperar
        # a la GPU: se pide la lectura de este fotograma y se recoge el del
        # anterior, que ya esta listo. Si no se pueden crear, lectura directa.
        try:
            self.pbo = [ctx.buffer(reserve=self.W * self.H * 4)
                        for _ in range(2)]
        except Exception:                            # noqa: BLE001
            self.pbo = None
        ctx.disable(moderngl.CULL_FACE)
        self.info = dict(ctx.info)

    # -- datos por circuito ------------------------------------------------
    def _preparar(self, track):
        """Vectores por segmento del circuito, calculados una vez."""
        if self._track_id == id(track):
            return
        segs = track.segments
        N = len(segs)
        L = cfg.SEGMENT_LENGTH
        self.N = N
        self.kap = np.array([s.kappa for s in segs])
        self.ely = np.array([s.y for s in segs])
        self.bnk = np.array([s.bank for s in segs])
        self.hw = np.array([s.half_w for s in segs])
        self.kerb = np.array([s.kerb for s in segs], dtype=bool)
        self.line_n = np.asarray(track.line_n, dtype=float)
        self.v_allow = np.asarray(track.line_v_allowed, dtype=float)
        dmg_fn = getattr(track, "damage_at", None)
        self.dmg = (np.array([dmg_fn(i * L) for i in range(N)])
                    if dmg_fn is not None else np.zeros(N))
        # rumbo absoluto con el error de cierre REPARTIDO: solo lo usa el
        # cielo (sol y montes). Sin repartirlo, en un circuito que no cierra
        # el sol daría un salto al cruzar la meta.
        h = np.concatenate([[0.0], np.cumsum(self.kap * L)[:-1]])
        total = self.kap.sum() * L
        desvio = (total + math.pi) % (2.0 * math.pi) - math.pi
        self.rumbo = h - desvio * np.arange(N) / N
        self._track_id = id(track)
        # cambio de circuito: el fotograma pendiente era del anterior
        self._pendiente = None

    def _rels(self):
        """Estaciones de las secciones relativas al coche: malla adaptativa
        idéntica a la del render de SDL (1 m cerca, 2 m a media distancia,
        4 m lejos, y 40 m por detrás)."""
        clave = (cfg.DRAW_DISTANCE, cfg.SEGMENT_LENGTH)
        if self._rels_key != clave:
            rels = []
            d = -40.0
            while d < cfg.DRAW_DISTANCE * cfg.SEGMENT_LENGTH:
                rels.append(d)
                if d < -24.0:
                    d += 2.0
                elif d < 24.0:
                    d += 1.0
                elif d < 80.0:
                    d += 2.0
                else:
                    d += 4.0
            self._rels_arr = np.array(rels)
            self._j0 = int(np.argmin(np.abs(self._rels_arr)))
            self._rels_key = clave
        return self._rels_arr, self._j0

    def _interp(self, arr, sa):
        """Interpolación lineal entre centros de segmento (como k_interp)."""
        pos = sa / cfg.SEGMENT_LENGTH - 0.5
        i0 = np.floor(pos).astype(np.int64)
        t = pos - i0
        return arr[i0 % self.N] * (1.0 - t) + arr[(i0 + 1) % self.N] * t

    def _indices(self, n_bandas, n_quads):
        """Índices de triángulos para n_bandas×n_quads cuadriláteros de 4
        vértices: constantes mientras no cambie el tamaño, se cachean."""
        clave = (n_bandas, n_quads)
        if self._idx_key != clave:
            base = np.arange(n_bandas * n_quads, dtype=np.int32) * 4
            idx = np.empty((n_bandas * n_quads, 6), dtype=np.int32)
            idx[:, 0] = base
            idx[:, 1] = base + 1
            idx[:, 2] = base + 2
            idx[:, 3] = base + 1
            idx[:, 4] = base + 3
            idx[:, 5] = base + 2
            self._idx = idx.reshape(-1)
            self._idx_key = clave
        return self._idx

    # -- el fotograma -------------------------------------------------------
    def eje(self, track, s0):
        """Eje de la carretera en el sistema local del coche, por secciones.

        Integración por punto medio, vectorizada, anclada en el coche (que
        queda en el origen mirando a +z). Mismo esquema que el bucle del
        render de SDL; solo que aquí lo hace numpy de una vez. Devuelve un
        diccionario con, por sección: estación relativa (rels), posición
        (x, z), vector derecha (hx, hz), elevación, seno y coseno del
        peralte, trazada, semiancho e índice de segmento."""
        self._preparar(track)
        L = cfg.SEGMENT_LENGTH
        rels, j0 = self._rels()
        sa = s0 + rels
        paso = np.diff(rels)
        kmid = self._interp(self.kap, s0 + (rels[:-1] + rels[1:]) * 0.5)
        dh = kmid * paso
        h = np.concatenate([[0.0], np.cumsum(dh)])
        h -= h[j0]
        h_medio = h[:-1] + dh * 0.5
        x = np.concatenate([[0.0], np.cumsum(np.sin(h_medio) * paso)])
        z = np.concatenate([[0.0], np.cumsum(np.cos(h_medio) * paso)])
        x -= x[j0]
        z -= z[j0]
        bank = self._interp(self.bnk, sa)
        seg_idx = np.floor(sa / L).astype(np.int64)
        return dict(rels=rels, x=x, z=z, hx=np.cos(h), hz=-np.sin(h),
                    elev=self._interp(self.ely, sa),
                    cb=np.cos(bank), sb=np.sin(bank),
                    li=self._interp(self.line_n, sa),
                    hw=self._interp(self.hw, sa),
                    seg_idx=seg_idx, sm=seg_idx % self.N)

    def dibujar(self, track, car_state, cam, show_line, pal):
        """Construye la malla del fotograma, la pinta y la copia al fondo del
        renderizador de SDL. ``cam`` es el estado de cámara que calcula
        ``Renderer._camara``; ``pal`` la paleta (ver ``render.paleta``)."""
        t0 = time.perf_counter()
        L = cfg.SEGMENT_LENGTH
        W, H = self.W, self.H
        s0 = car_state.s
        e = self.eje(track, s0)
        rels, x, z, hx, hz = e["rels"], e["x"], e["z"], e["hx"], e["hz"]
        elev, cb, sb, li, hw = e["elev"], e["cb"], e["sb"], e["li"], e["hw"]
        seg_idx, sm = e["seg_idx"], e["sm"]
        N = self.N
        n_sec = len(rels)

        # --- cámara ------------------------------------------------------
        elev_cam = float(self._interp(self.ely, np.array([s0]))[0])
        bank_cam = float(self._interp(self.bnk, np.array([s0]))[0])
        cam_y = elev_cam + cam.extra_y
        cam_x = -cam.mesh_dx
        vista = (_mat_traslacion(0.0, 0.0, cam.cam_back)
                 @ _mat_balanceo(bank_cam)
                 @ _mat_guinada(cam.psi_c)
                 @ _mat_traslacion(-cam_x, -cam_y, -cam.cam_forward))
        pitch_ndc = cam.pitch_px / (H / 2.0)
        proy = _mat_proyeccion(cam.f, pitch_ndc)
        rumbo = float(self.rumbo[int(s0 / L) % N]) + cam.psi_c
        sol_px = self._sol_en_pantalla(rumbo, bank_cam, cam.f, cam.pitch_px)
        self._sol_px = sol_px               # (pruebas) donde se pinto el sol

        # --- colores por sección (misma receta que el render de SDL) --------
        par3 = ((seg_idx // 3) % 2).astype(bool)[:, None]
        par2 = ((seg_idx // 2) % 2).astype(bool)[:, None]
        kerb_flag = self.kerb[sm][:, None]
        grass_c = np.where(par3, pal["grass"][0], pal["grass"][1]).astype(float)
        road_c = np.where(par3, pal["road"][0], pal["road"][1]).astype(float)
        tex = 0.94 + 0.12 * (((seg_idx * 2654435761) % 977) / 977.0)
        road_c *= tex[:, None]
        dmg = self.dmg[sm]
        mottle = 1.0 + 0.22 * dmg * (((seg_idx * 40503) % 331) / 331.0 - 0.5)
        road_c *= ((1.0 - 0.36 * dmg) * mottle)[:, None]
        kerb_c = np.where(par2, pal["kerb"][0], pal["kerb"][1]).astype(float)
        kerb_c = np.where(kerb_flag, kerb_c, grass_c)
        dash = ((seg_idx % 2) == 0)[:, None]
        edge_c = np.where(kerb_flag | dash, pal["line"], road_c)
        rl_c = None
        if show_line and cfg.RACING_LINE:
            speed = abs(car_state.vx)
            v_allow = self.v_allow[sm]
            rl_c = np.empty((n_sec, 3))
            rl_c[:] = (140, 235, 140)
            rl_c[speed > v_allow * 0.88] = (250, 205, 60)
            rl_c[speed > v_allow * 1.02] = (235, 45, 35)
            rl_c = np.where(dash, rl_c, road_c)
        # línea de meta en damero (dos segmentos)
        meta_a = (sm == 0)[:, None]
        meta_b = (sm == 1)[:, None]
        meta = meta_a | meta_b
        if meta.any():
            blanco = np.array((240.0, 240.0, 240.0))
            negro = np.array((22.0, 22.0, 22.0))
            road_c = np.where(meta, blanco, road_c)
            edge_c = np.where(meta, blanco, edge_c)
            kerb_c = np.where(meta_a, negro, kerb_c)
            kerb_c = np.where(meta_b, blanco, kerb_c)
            grass_c = np.where(meta_a, blanco, grass_c)
            grass_c = np.where(meta_b, negro, grass_c)
        # sombreado solar del relieve (estático: se hornea en el vértice)
        shade = getattr(cfg, "GFX_SUN_SHADE", 0.0)
        if shade > 0.0:
            g_slope = np.gradient(elev, rels)
            light = (1.0 + shade * np.clip(-g_slope * 5.0, -1.0, 1.0)
                     + shade * 0.7 * sb)[:, None]
            grass_c *= light
            road_c *= light
            kerb_c *= light

        # --- bandas: particionan la sección, sin solapes ---------------------
        # (las líneas de borde son bandas PROPIAS y no se superponen al
        # asfalto: con búfer de profundidad, dos polígonos en el mismo plano
        # parpadean)
        kw = cfg.KERB_WIDTH
        GW = ANCHO_HIERBA
        borde = np.full(n_sec, GW)
        bandas = [
            (-borde, -hw - kw, grass_c, 0.0),
            (-hw - kw, -hw, kerb_c, 0.0),
            (-hw, -hw + 0.06, road_c, 0.0),
            (-hw + 0.06, -hw + 0.42, edge_c, 0.0),
            (-hw + 0.42, hw - 0.42, road_c, 0.0),
            (hw - 0.42, hw - 0.06, edge_c, 0.0),
            (hw - 0.06, hw, road_c, 0.0),
            (hw, hw + kw, kerb_c, 0.0),
            (hw + kw, borde, grass_c, 0.0),
        ]
        if rl_c is not None:
            bandas.append((li - 0.30, li + 0.30, rl_c, LEVANTE_TRAZADA))
        n_q = n_sec - 1
        vertices = np.empty((len(bandas), n_q, 4), dtype=_VERTICE)
        for b, (oL, oR, col, lev) in enumerate(bandas):
            oL = np.broadcast_to(oL, (n_sec,))
            oR = np.broadcast_to(oR, (n_sec,))
            pl = np.stack([x + hx * oL * cb, elev - oL * sb + lev,
                           z + hz * oL * cb], axis=1)
            pr = np.stack([x + hx * oR * cb, elev - oR * sb + lev,
                           z + hz * oR * cb], axis=1)
            v = vertices[b]
            v["pos"][:, 0] = pl[:-1]
            v["pos"][:, 1] = pr[:-1]
            v["pos"][:, 2] = pl[1:]
            v["pos"][:, 3] = pr[1:]
            c = np.clip(col[:-1], 0, 255).astype(np.uint8)
            v["col"][:, :, :3] = c[:, None, :]
            v["col"][:, :, 3] = 255
        idx = self._indices(len(bandas), n_q)

        # --- balizas y paneles: cuadriláteros orientados a la cámara ----------
        # Se construyen ya en el espacio de la cámara, de frente por
        # construcción, y se dibujan con la profundidad de la carretera: una
        # cresta los tapa, como debe ser.
        bill = self._balizas(vista, x, z, hx, hz, elev, cb, sb, hw, rels,
                             seg_idx, sm, kw)

        # caché para world_to_screen (fantasma, partículas)
        self._frame = (s0, rels, x, z, hx, hz, elev, cb, sb, vista[:3],
                       cam.f, cam.pitch_px, track.length)
        self.ms_malla = (time.perf_counter() - t0) * 1000.0
        frame_actual = self._frame

        # --- pintar -------------------------------------------------------
        # La textura de SDL se bloquea ANTES de entrar en GL: bloquearla no
        # toca OpenGL, pero podria vaciar la cola de dibujo de SDL, y eso
        # tiene que pasar con el contexto de SDL activo. Asi el fotograma se
        # lee de la GPU directamente sobre los pixeles de la textura, sin
        # pasar por una copia intermedia.
        destino = self._bloquear_textura()
        t1 = time.perf_counter()
        with self._gl() as ctx:
            fbo = self.fbo_ms or self.fbo
            fbo.use()
            ctx.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
            bruma_d = float(getattr(cfg, "GFX_FOG_DIST", 0.0))
            bruma_col = 0.5 * (np.asarray(pal["sky_bottom"], float)
                               + np.asarray(pal["haze"], float)) / 255.0
            # cielo, suelo, sol y montes: sin profundidad, debajo de todo
            ctx.disable(moderngl.DEPTH_TEST)
            pc = self.prog_cielo
            pc["u_tam"].value = (float(W), float(H))
            pc["u_f"].value = float(cam.f)
            pc["u_pitch"].value = float(pitch_ndc)
            pc["u_roll"].value = float(bank_cam)
            pc["u_rumbo"].value = float(rumbo)
            pc["u_alt_cam"].value = float(max(0.3, cam.extra_y))
            pc["u_cielo_alto"].value = tuple(np.asarray(pal["sky_top"], float) / 255.0)
            pc["u_cielo_bajo"].value = tuple(np.asarray(pal["sky_bottom"], float) / 255.0)
            pc["u_calima"].value = tuple(np.asarray(pal["haze"], float) / 255.0)
            pc["u_hierba"].value = tuple(np.asarray(pal["grass"][0], float) / 255.0)
            pc["u_monte"].value = tuple(np.asarray(pal["mountain"], float) / 255.0)
            pc["u_bruma_col"].value = tuple(bruma_col)
            pc["u_bruma_d"].value = bruma_d
            pc["u_sol"].value = 1.0 if (pal["sun"] and sol_px) else 0.0
            pc["u_sol_px"].value = sol_px or (-1e4, -1e4)
            self.vao_cielo.render(moderngl.TRIANGLES, vertices=3)
            # carretera
            ctx.enable(moderngl.DEPTH_TEST)
            self.prog["u_proj"].write(proy.T.astype("f4").tobytes())
            self.prog["u_view"].write(vista.T.astype("f4").tobytes())
            self.prog["u_bruma_col"].value = tuple(bruma_col)
            self.prog["u_bruma_d"].value = bruma_d
            datos = vertices.reshape(-1).tobytes()
            if len(datos) > self.vbo.size:
                self.vbo.orphan(len(datos) * 2)
            if idx.nbytes > self.ibo.size:
                self.ibo.orphan(idx.nbytes * 2)
            self.vbo.write(datos)
            self.ibo.write(idx.tobytes())
            self.vao.render(moderngl.TRIANGLES, vertices=len(idx))
            # balizas: ya en espacio de cámara -> vista identidad
            if bill is not None:
                vb, ib = bill
                self.prog["u_view"].write(np.eye(4, dtype="f4").tobytes())
                db = vb.reshape(-1).tobytes()
                if len(db) > self.vbo.size:
                    self.vbo.orphan(len(db) * 2)
                if ib.nbytes > self.ibo.size:
                    self.ibo.orphan(ib.nbytes * 2)
                self.vbo.write(db)
                self.ibo.write(ib.tobytes())
                self.vao.render(moderngl.TRIANGLES, vertices=len(ib))
            if self.fbo_ms is not None:
                ctx.copy_framebuffer(self.fbo, self.fbo_ms)
            self.ms_gl = (time.perf_counter() - t1) * 1000.0

            # --- leer el fotograma ------------------------------------------
            # Leer el framebuffer es SINCRONO: la CPU se queda esperando a
            # que la GPU termine de pintar y luego copia 8 MB (a 1080p). Con
            # la lectura asincrona se ENCARGA la lectura de este fotograma a
            # un PBO y se RECOGE la del anterior, que la GPU acabo mientras la
            # CPU hacia la fisica y el HUD: la espera desaparece a cambio de
            # mostrar la carretera con un fotograma de retraso (16-25 ms).
            # El primer fotograma (o tras cambiar de circuito) se lee al
            # momento para no ensenar nada viejo.
            t2 = time.perf_counter()
            asinc = (self.pbo is not None
                     and bool(getattr(cfg, "GFX_GPU_ASYNC", True)))
            self.asincrono = asinc
            if asinc:
                self.fbo.read_into(self.pbo[self._pbo_i], components=4,
                                   alignment=1)
                if self._pendiente is None:
                    listo, frame_mostrado = self._pbo_i, frame_actual
                else:
                    listo, frame_mostrado = self._pendiente
                self._pendiente = (self._pbo_i, frame_actual)
                self._pbo_i ^= 1
                origen = self.pbo[listo]
            else:
                self._pendiente = None
                origen = self.fbo
                frame_mostrado = frame_actual
            if destino is not None:
                if isinstance(origen, moderngl.Framebuffer):
                    origen.read_into(destino[0], components=4, alignment=1)
                else:
                    origen.read_into(destino[0])
            else:
                if isinstance(origen, moderngl.Framebuffer):
                    pixeles = origen.read(components=4, alignment=1)
                else:
                    pixeles = origen.read()
            self.ms_lectura = (time.perf_counter() - t2) * 1000.0
        # world_to_screen (fantasma, particulas) tiene que proyectar con la
        # camara del fotograma QUE SE VE, no con la del que se acaba de pedir
        self._frame = frame_mostrado

        # --- entregar a SDL ----------------------------------------------
        t3 = time.perf_counter()
        if destino is not None:
            sdl2.SDL_UnlockTexture(self.tex)
        else:
            sdl2.SDL_UpdateTexture(self.tex, None, pixeles, W * 4)
        sdl2.SDL_RenderCopy(self.r, self.tex, None, None)
        self.ms_subida = (time.perf_counter() - t3) * 1000.0

    def _bloquear_textura(self):
        """Bloquea la textura de la escena y devuelve (bufer ctypes sobre sus
        pixeles, paso) o None si no se puede (o el paso no es W*4: entonces
        se sube con SDL_UpdateTexture desde una copia)."""
        pix = ctypes.c_void_p()
        paso = ctypes.c_int()
        if sdl2.SDL_LockTexture(self.tex, None, ctypes.byref(pix),
                                ctypes.byref(paso)) != 0 or not pix.value:
            return None
        if paso.value != self.W * 4:
            sdl2.SDL_UnlockTexture(self.tex)
            return None
        buf = (ctypes.c_ubyte * (self.W * self.H * 4)).from_address(pix.value)
        return (buf, paso.value)

    def _sol_en_pantalla(self, rumbo, bank_cam, f, pitch_px):
        """Centro del sol en píxeles del framebuffer (origen abajo a la
        izquierda, como gl_FragCoord), o None si queda a la espalda."""
        a = SOL_AZIMUT - rumbo
        ce = math.cos(SOL_ELEVACION)
        px, py, pz = math.sin(a) * ce, math.sin(SOL_ELEVACION), math.cos(a) * ce
        cb, sb = math.cos(bank_cam), math.sin(bank_cam)
        vx, vy = px * cb - py * sb, px * sb + py * cb
        if pz < 0.05:
            return None
        W, H = self.W, self.H
        sx = W / 2 + f * vx / pz * (W / 2)
        sy = H / 2 - f * vy / pz * (H / 2) + pitch_px
        # la proyeccion va volteada en y para que la lectura salga con la
        # primera fila arriba, asi que la fila de la imagen ES la coordenada
        # y de gl_FragCoord: no hay que restarla de H
        return (float(sx), float(sy))

    def _balizas(self, vista, x, z, hx, hz, elev, cb, sb, hw, rels, seg_idx,
                 sm, kw):
        """Balizas de borde y paneles direccionales como cuadriláteros de
        frente a la cámara, en espacio de cámara. Devuelve (vértices,
        índices) o None."""
        quads = []       # (n,4,3) posiciones + (n,3) colores

        def a_vista(o, mask):
            px = x[mask] + hx[mask] * o * cb[mask]
            py = elev[mask] - o * sb[mask]
            pz = z[mask] + hz[mask] * o * cb[mask]
            p = np.stack([px, py, pz, np.ones_like(px)], axis=1)
            return p @ vista[:3].T                     # (n,3) en cámara

        def anade(v, col):
            """v: (n,4,3) en cámara; col: (3,) o (n,3)."""
            if len(v) == 0:
                return
            c = np.broadcast_to(np.asarray(col, float), (len(v), 3))
            quads.append((v, c))

        def cajas(pv, w, h, col, dz=0.0):
            """Rectángulos verticales de frente, de ancho w y alto h, con la
            base en cada punto pv (n,3)."""
            n = len(pv)
            v = np.empty((n, 4, 3))
            v[:, 0] = pv + (-w / 2, 0.0, dz)
            v[:, 1] = pv + (w / 2, 0.0, dz)
            v[:, 2] = pv + (-w / 2, h, dz)
            v[:, 3] = pv + (w / 2, h, dz)
            anade(v, col)

        # --- balizas (amarilla izquierda, azul derecha) cada 6 segmentos ----
        if cfg.TRACK_POLES:
            mask = (seg_idx % 6 == 0) & (rels >= 0.0) & (rels <= 700.0)
            alto = float(getattr(cfg, "TRACK_POLE_HEIGHT", 2.2))
            for lado, col in ((-1.0, (255, 215, 30)), (1.0, (60, 145, 255))):
                pv = a_vista(lado * (hw[mask] + kw + 0.5), mask)
                pv = pv[pv[:, 2] > 0.3]
                cajas(pv, 0.22, alto, col)
                cima = pv.copy()
                cima[:, 1] += alto * 0.75
                cajas(cima, 0.22, alto * 0.25, (245, 245, 245), dz=-0.01)

        # --- paneles direccionales en el exterior de las curvas cerradas ----
        r_chev = float(getattr(cfg, "CHEVRON_MAX_RADIUS", 0.0))
        if r_chev > 0.0:
            k = self.kap[sm]
            mask = ((seg_idx % 3 == 0) & (rels >= 0.0) & (rels <= 320.0)
                    & (np.abs(k) >= 1.0 / r_chev))
            if mask.any():
                lado = np.where(k[mask] > 0, -1.0, 1.0)      # exterior
                o = lado * (hw[mask] + kw + 1.1)
                pv = a_vista(o, mask)
                vis = pv[:, 2] > 0.3
                pv, lado = pv[vis], lado[vis]
                if len(pv):
                    ancho, alto = 0.95, 1.35
                    cajas(pv, ancho, alto, (245, 245, 245))
                    franja = pv.copy()
                    franja[:, 1] += alto * 0.91
                    cajas(franja, ancho, alto * 0.09, (60, 60, 60), dz=-0.01)
                    # galón rojo apuntando hacia la curva: dos trazos gruesos
                    g = -lado
                    gx = pv[:, 0] + ancho * 0.22 * g
                    ax_, ay_ = gx - ancho * 0.26 * g, pv[:, 1] + alto * 0.82
                    bx_, by_ = gx + ancho * 0.20 * g, pv[:, 1] + alto * 0.50
                    cx_, cy_ = gx - ancho * 0.26 * g, pv[:, 1] + alto * 0.18
                    grosor = ancho * 0.22
                    for (x0, y0, x1, y1) in ((ax_, ay_, bx_, by_),
                                             (bx_, by_, cx_, cy_)):
                        ux, uy = x1 - x0, y1 - y0
                        ln = np.hypot(ux, uy) + 1e-9
                        nx, ny = -uy / ln * grosor / 2, ux / ln * grosor / 2
                        v = np.empty((len(pv), 4, 3))
                        v[:, :, 2] = (pv[:, 2] - 0.02)[:, None]
                        v[:, 0, 0], v[:, 0, 1] = x0 - nx, y0 - ny
                        v[:, 1, 0], v[:, 1, 1] = x0 + nx, y0 + ny
                        v[:, 2, 0], v[:, 2, 1] = x1 - nx, y1 - ny
                        v[:, 3, 0], v[:, 3, 1] = x1 + nx, y1 + ny
                        anade(v, (205, 35, 35))
        if not quads:
            return None
        n_tot = sum(len(v) for v, _ in quads)
        vb = np.empty((n_tot, 4), dtype=_VERTICE)
        k0 = 0
        for v, c in quads:
            n = len(v)
            vb["pos"][k0:k0 + n] = v
            vb["col"][k0:k0 + n, :, :3] = c[:, None, :].astype(np.uint8)
            vb["col"][k0:k0 + n, :, 3] = 255
            k0 += n
        base = np.arange(n_tot, dtype=np.int32) * 4
        ib = np.stack([base, base + 1, base + 2, base + 1, base + 3, base + 2],
                      axis=1).reshape(-1)
        return vb, ib

    # -- proyección de puntos del mundo (fantasma, partículas) ---------------
    def world_to_screen(self, track, s_world, n, z_up):
        """Igual que ``Renderer.world_to_screen`` pero con la cámara de
        este fotograma. Devuelve (sx, sy, px_por_m) o None."""
        c = self._frame
        if c is None:
            return None
        s0, rels, x, z, hx, hz, elev, cb, sb, vista, f, pitch_px, L = c
        ds = (s_world - s0 + L / 2.0) % L - L / 2.0
        if ds <= rels[0] or ds >= rels[-1]:
            return None
        j = int(np.searchsorted(rels, ds, side="right")) - 1
        j = min(max(j, 0), len(rels) - 2)
        t = (ds - rels[j]) / (rels[j + 1] - rels[j])

        def lerp(a):
            return a[j] + (a[j + 1] - a[j]) * t
        px = lerp(x) + lerp(hx) * n * lerp(cb)
        py = lerp(elev) - n * lerp(sb) + z_up
        pz = lerp(z) + lerp(hz) * n * lerp(cb)
        v = vista @ np.array([px, py, pz, 1.0])
        if v[2] < 0.45:
            return None
        W, H = self.W, self.H
        sx = W / 2 + f * v[0] / v[2] * (W / 2)
        sy = H / 2 - f * v[1] / v[2] * (H / 2) + pitch_px
        return sx, sy, f / v[2] * (W / 2)

    def close(self):
        if self.tex:
            sdl2.SDL_DestroyTexture(self.tex)
            self.tex = None
        if self.ctx is not None:
            try:
                self.ctx.release()
            except Exception:                        # noqa: BLE001
                pass
            self.ctx = None
        self.ok = False


# --------------------------------------------------------------------------
_escena = None


def estado():
    """Texto corto para el panel F1: por que no hay escena en la GPU."""
    if not getattr(cfg, "GFX_GPU", False):
        return "GFX_GPU APAGADO EN AJUSTES"
    if moderngl is None:
        return "FALTA MODERNGL (PIP INSTALL MODERNGL)"
    if _escena is None:
        return "SIN INICIAR"
    return "ACTIVA" if _escena.ok else _escena.motivo.upper()


def obtener(sdl_renderer):
    """La escena de GPU de la ventana actual, o None si no se puede.

    Se crea una vez por proceso (el contexto y el framebuffer son caros) y
    se rehace si cambia el tamaño de la ventana. Devuelve None si
    ``GFX_GPU`` está apagado o la GPU no está disponible; entonces el juego
    usa el renderizador de SDL."""
    global _escena
    if not getattr(cfg, "GFX_GPU", False):
        return None
    W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
    if _escena is not None and (_escena.W, _escena.H) != (W, H):
        _escena.close()
        _escena = None
    if _escena is None:
        _escena = GpuScene(sdl_renderer, W, H, getattr(cfg, "GFX_MSAA", 4))
        if _escena.ok:
            print(f"Render GPU: {_escena.info.get('GL_RENDERER', '?')} "
                  f"(OpenGL {_escena.info.get('GL_VERSION', '?')}, "
                  f"MSAA x{_escena.msaa})")
        else:
            print(f"Render GPU no disponible ({_escena.motivo}): "
                  "se usa el renderizador de SDL")
    return _escena if _escena.ok else None
