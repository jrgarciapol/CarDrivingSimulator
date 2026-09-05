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
from . import modelo3d

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


class _CargadorSDL:
    """Cargador de funciones de OpenGL para moderngl a traves de SDL: asi
    moderngl se ENGANCHA al contexto que ya tiene el renderizador de SDL en
    vez de crear uno propio, en cualquier sistema (Windows, Linux, Deck)."""

    def load_opengl_function(self, name):
        return int(sdl2.SDL_GL_GetProcAddress(name.encode()) or 0)

    def __enter__(self):
        pass

    def __exit__(self, *args):
        pass

    def release(self):
        pass


# funciones crudas de GL que hacen falta para devolverle a SDL el estado
# que espera tras pintar con moderngl (nombre -> tipos de los argumentos)
_GL_CRUDAS = {
    "glGetIntegerv": (ctypes.c_uint, ctypes.POINTER(ctypes.c_int)),
    "glUseProgram": (ctypes.c_uint,),
    "glBindVertexArray": (ctypes.c_uint,),
    "glBindBuffer": (ctypes.c_uint, ctypes.c_uint),
    "glBindFramebuffer": (ctypes.c_uint, ctypes.c_uint),
    "glBindRenderbuffer": (ctypes.c_uint, ctypes.c_uint),
    "glPixelStorei": (ctypes.c_uint, ctypes.c_int),
}
_GL_UNPACK_ROW_LENGTH = 0x0CF2
_GL_UNPACK_SKIP_ROWS = 0x0CF3
_GL_UNPACK_SKIP_PIXELS = 0x0CF4
_GL_TEXTURE_BINDING_2D = 0x8069
_GL_ARRAY_BUFFER = 0x8892
_GL_ELEMENT_ARRAY_BUFFER = 0x8893
_GL_FRAMEBUFFER = 0x8D40
_GL_RENDERBUFFER = 0x8D41


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


def _mat_cabeceo(theta):
    """Giro sobre el eje x: +theta levanta el morro (+z sube hacia +y)."""
    c, s = math.cos(theta), math.sin(theta)
    m = np.eye(4)
    m[1, 1], m[1, 2] = c, s
    m[2, 1], m[2, 2] = -s, c
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


def _plantillas_arbol():
    """Dos arboles de formas sencillas, de altura 1 y con el pie en el
    origen, como listas de triangulos (T,3,3) con su color base (T,3) y su
    normal (T,3): 0 = frondoso (tronco + copa en bipiramide de 8 lados),
    1 = pino (tronco + dos conos de 6 lados). Se escalan por la altura."""
    out = []

    def cono(r, y0, y1, lados, col, tris, cols):
        a = np.linspace(0.0, 2 * math.pi, lados, endpoint=False)
        for k in range(lados):
            p0 = (r * math.cos(a[k]), y0, r * math.sin(a[k]))
            p1 = (r * math.cos(a[(k + 1) % lados]), y0, r * math.sin(a[(k + 1) % lados]))
            tris.append((p0, p1, (0.0, y1, 0.0)))
            cols.append(col)

    def tronco(w, h, col, tris, cols):
        c = [(-w, 0, -w), (w, 0, -w), (w, 0, w), (-w, 0, w)]
        for k in range(4):
            a, b = c[k], c[(k + 1) % 4]
            a2, b2 = (a[0], h, a[2]), (b[0], h, b[2])
            tris.append((a, b, b2))
            tris.append((a, b2, a2))
            cols += [col, col]

    for tipo in (0, 1):
        tris, cols = [], []
        if tipo == 0:
            tronco(0.035, 0.40, (95, 66, 38), tris, cols)
            cono(0.34, 0.62, 1.00, 8, (58, 122, 40), tris, cols)     # media copa alta
            cono(0.34, 0.62, 0.30, 8, (46, 98, 32), tris, cols)      # media copa baja
        else:
            tronco(0.03, 0.32, (90, 62, 36), tris, cols)
            cono(0.30, 0.30, 0.70, 6, (38, 92, 46), tris, cols)
            cono(0.22, 0.56, 1.00, 6, (44, 104, 52), tris, cols)
        t = np.array(tris, dtype=float)                       # (T,3,3)
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1), 1e-9)[:, None]
        # las caras deben mirar hacia fuera para el sombreado: se orientan
        # por el signo respecto al radio desde el eje del arbol
        centro = t.mean(axis=1)
        radial = centro.copy()
        radial[:, 1] = 0.0
        malas = (n * radial).sum(axis=1) < 0
        n[malas] *= -1
        out.append((t, np.array(cols, dtype=float), n))
    return out


_PLANTILLAS_ARBOL = None


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
        # modelo 3D del coche (modelo3d.ModeloGpu) y su sombra
        self._modelo_gpu = None
        self._vao_sombra = None
        self.coche_dibujado = False
        if sin_gl:
            # solo la geometria (pruebas): ni contexto ni textura
            self.motivo = "sin GL a proposito"
            return
        if moderngl is None:
            self.motivo = "falta moderngl (pip install moderngl)"
            return
        # 1) contexto COMPARTIDO con SDL: la GPU pinta directamente en la
        #    textura de fondo y no hay que leer el fotograma (ver
        #    _montar_compartido). Necesita que el renderizador de SDL sea
        #    el de OpenGL (main.py lo pide con SDL_HINT_RENDER_DRIVER).
        self.compartido = False
        self.motivo_compartido = ""
        self._gl_fn = {}
        if getattr(cfg, "GFX_GPU_COMPARTIDO", True):
            try:
                self._montar_compartido(msaa)
                self.ok = True
                self.compartido = True
            except Exception as e:                   # noqa: BLE001
                self.motivo_compartido = f"{type(e).__name__}: {str(e)[:120]}"
                if self.tex:
                    sdl2.SDL_DestroyTexture(self.tex)
                    self.tex = None
                self.ctx = None
        # 2) contexto PROPIO + lectura del fotograma (Direct3D en Windows,
        #    pruebas sin ventana, o si lo anterior no ha podido)
        if not self.ok:
            prev = self._contexto_sdl()
            try:
                self.ctx = self._crear_contexto()
                self._montar(msaa)
                self.ok = True
            except Exception as e:                   # noqa: BLE001
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
                    sdl2.SDL_SetTextureBlendMode(self.tex,
                                                 sdl2.SDL_BLENDMODE_NONE)

    # -- contexto compartido con SDL -----------------------------------------
    def _montar_compartido(self, msaa):
        """moderngl dentro del contexto OpenGL del renderizador de SDL.

        La textura de fondo la crea SDL; se averigua su identificador de GL
        (SDL la enlaza con SDL_GL_BindTexture y se pregunta a GL cual es la
        enlazada) y moderngl la usa como destino de un framebuffer. Cada
        fotograma: se vacia la cola de SDL (SDL_RenderFlush), se pinta la
        escena con moderngl, se devuelve el estado que SDL da por sentado
        (programa 0, sin VAO ni buferes, framebuffer 0, sin test de
        profundidad) y SDL copia la textura como siempre. Lo que se ahorra
        es leer 8 MB de la GPU cada fotograma: 15 ms en un Intel Arc."""
        info = sdl2.SDL_RendererInfo()
        if sdl2.SDL_GetRendererInfo(self.r, ctypes.byref(info)) != 0:
            raise RuntimeError("SDL no describe su renderizador")
        nombre = info.name.decode(errors="replace") if info.name else "?"
        if nombre != "opengl":
            raise RuntimeError(f"el renderizador de SDL es '{nombre}', no opengl")
        if not sdl2.SDL_GL_GetCurrentContext():
            raise RuntimeError("SDL no tiene un contexto OpenGL activo")
        for fn, tipos in _GL_CRUDAS.items():
            addr = sdl2.SDL_GL_GetProcAddress(fn.encode())
            if not addr:
                raise RuntimeError(f"sin {fn} en el contexto de SDL")
            self._gl_fn[fn] = ctypes.CFUNCTYPE(None, *tipos)(addr)
        moderngl.init_context(_CargadorSDL())
        ctx = moderngl.get_context()
        if ctx.version_code < 330:
            raise RuntimeError(f"OpenGL {ctx.version_code / 100:.1f} en el "
                               "contexto de SDL; hace falta 3.3")
        self.ctx = ctx
        self.tex = sdl2.SDL_CreateTexture(
            self.r, sdl2.SDL_PIXELFORMAT_ABGR8888,
            sdl2.SDL_TEXTUREACCESS_STATIC, self.W, self.H)
        if not self.tex:
            raise RuntimeError("SDL no pudo crear la textura de la escena")
        sdl2.SDL_SetTextureBlendMode(self.tex, sdl2.SDL_BLENDMODE_NONE)
        tw, th = ctypes.c_float(), ctypes.c_float()
        if sdl2.SDL_GL_BindTexture(self.tex, ctypes.byref(tw),
                                   ctypes.byref(th)) != 0:
            raise RuntimeError("SDL_GL_BindTexture no funciona con este "
                               "renderizador")
        glo = ctypes.c_int(0)
        self._gl_fn["glGetIntegerv"](_GL_TEXTURE_BINDING_2D, ctypes.byref(glo))
        sdl2.SDL_GL_UnbindTexture(self.tex)
        if glo.value <= 0 or abs(tw.value - 1.0) > 1e-6:
            raise RuntimeError("la textura de SDL no es una GL_TEXTURE_2D "
                               f"(id {glo.value}, escala {tw.value:.3f})")
        self._montar(msaa, externa=glo.value)
        self._restaurar_estado_sdl()

    def _restaurar_estado_sdl(self):
        """Deja GL como SDL lo espera tras pintar con moderngl. SDL guarda en
        cache que programa, mezcla y textura tiene puestos y solo los cambia
        cuando difieren de lo que quiere: si moderngl los ha tocado por su
        cuenta, SDL pintaria el HUD con nuestro sombreador o dentro de
        nuestro framebuffer."""
        ctx = self.ctx
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.screen.use()                     # framebuffer 0 y su viewport
        fn = self._gl_fn
        fn["glUseProgram"](0)
        fn["glBindVertexArray"](0)
        fn["glBindBuffer"](_GL_ARRAY_BUFFER, 0)
        fn["glBindBuffer"](_GL_ELEMENT_ARRAY_BUFFER, 0)
        fn["glBindRenderbuffer"](_GL_RENDERBUFFER, 0)
        fn["glBindFramebuffer"](_GL_FRAMEBUFFER, 0)
        # TEXTURAS: SDL recuerda cual dejo enlazada y no la vuelve a enlazar
        # si cree que sigue puesta. Tras pintar el modelo del coche (con sus
        # texturas) SDL copiaba el fondo con la textura de la RUEDA a pantalla
        # completa. SDL_GL_BindTexture/UnbindTexture le hacen olvidar lo que
        # tenia ("we trash this state"), asi que en el siguiente dibujo
        # enlaza la suya de nuevo.
        if self.tex:
            sdl2.SDL_GL_BindTexture(self.tex, None, None)
            sdl2.SDL_GL_UnbindTexture(self.tex)

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
        if self.compartido:
            # mismo contexto que SDL: vaciar su cola antes de pintar y
            # devolverle su estado al acabar. SDL deja puesto el paso de
            # fila (GL_UNPACK_ROW_LENGTH) de la ultima textura que subio
            # (el atlas de la fuente): con el, nuestras texturas mas
            # estrechas se cargarian con las filas descolocadas
            sdl2.SDL_RenderFlush(self.r)
            fn = self._gl_fn
            fn["glPixelStorei"](_GL_UNPACK_ROW_LENGTH, 0)
            fn["glPixelStorei"](_GL_UNPACK_SKIP_ROWS, 0)
            fn["glPixelStorei"](_GL_UNPACK_SKIP_PIXELS, 0)
            try:
                yield self.ctx
            finally:
                self._restaurar_estado_sdl()
            return
        prev = self._contexto_sdl()
        self.ctx.__enter__()
        try:
            yield self.ctx
        finally:
            self.ctx.__exit__(None, None, None)
            self._devolver_contexto_sdl(prev)

    def _montar(self, msaa, externa=None):
        """Programas, buferes y framebuffers. ``externa`` es el id de GL de
        la textura de SDL en el modo compartido: el framebuffer final pinta
        sobre ella; si no, sobre un renderbuffer que luego se lee."""
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
        if externa is not None:
            # la textura de SDL como destino: la GPU deja ahi la escena
            self.tex_externa = ctx.external_texture(int(externa), tam, 4, 0,
                                                    "f1")
            self.fbo = ctx.framebuffer([self.tex_externa],
                                       ctx.depth_renderbuffer(tam))
            self.pbo = None
        else:
            self.fbo = ctx.framebuffer([ctx.renderbuffer(tam, 4)],
                                       ctx.depth_renderbuffer(tam))
            # dos PBO (pixel buffer objects) para leer el fotograma sin
            # esperar a la GPU (GFX_GPU_ASYNC): se pide la lectura de este
            # fotograma y se recoge el del anterior, que ya esta listo
            try:
                self.pbo = [ctx.buffer(reserve=self.W * self.H * 4)
                            for _ in range(2)]
            except Exception:                        # noqa: BLE001
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
        self._arboles_track = self._plantar(track)

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

    def dibujar(self, track, car_state, cam, show_line, pal, coche=None):
        """Construye la malla del fotograma, la pinta y la copia al fondo del
        renderizador de SDL. ``cam`` es el estado de cámara que calcula
        ``Renderer._camara``; ``pal`` la paleta (ver ``render.paleta``).
        ``coche``: dict(datos=modelo cargado, steering, dt) para pintar el
        modelo 3D del coche dentro de la escena (vista de coche completo);
        ``coche_dibujado`` dice si se ha hecho."""
        t0 = time.perf_counter()
        self.coche_dibujado = False
        self._frame_s0 = float(car_state.s)      # (balizas a estaciones fijas)
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
        cam_x = -cam.mesh_dx
        # La calzada se construye con el peralte ABSOLUTO: a una distancia
        # lateral o del eje esta a elev - o*sin(peralte) (mas abajo por el
        # lado bajo). La camara va a cam_x del eje, asi que su suelo esta
        # en elev_cam - cam_x*tan(peralte): sin descontarlo, en el ovalo el
        # coche iba a la cota del eje y la pista se quedaba por encima (o
        # por debajo) de el segun el lado en que rodase.
        cam_y = elev_cam - cam_x * math.tan(bank_cam) + cam.extra_y
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

        # --- arboles en la hierba: geometria en el espacio de la escena -----
        arb = self._arboles(track, s0, rels, x, z, hx, hz, elev, cb, sb, hw,
                            kw, float(self.rumbo[int(s0 / L) % N]))

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
        destino = None if self.compartido else self._bloquear_textura()
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
            # arboles: misma vista que la carretera, con profundidad
            if arb is not None:
                va, ia = arb
                da = va.tobytes()
                if len(da) > self.vbo.size:
                    self.vbo.orphan(len(da) * 2)
                if ia.nbytes > self.ibo.size:
                    self.ibo.orphan(ia.nbytes * 2)
                self.vbo.write(da)
                self.ibo.write(ia.tobytes())
                self.vao.render(moderngl.TRIANGLES, vertices=len(ia))
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
            # el coche (vista de coche completo): modelo 3D con su sombra,
            # con profundidad, dentro de la misma escena
            if coche is not None and coche.get("datos") is not None:
                try:
                    self._dibujar_coche(ctx, coche, car_state, vista, proy,
                                        rels, elev, elev_cam, bank_cam,
                                        float(self.rumbo[int(s0 / L) % N]),
                                        pal, track)
                    self.coche_dibujado = True
                except Exception as e:               # noqa: BLE001
                    if not getattr(self, "_aviso_coche", False):
                        print(f"Modelo 3D del coche: no se pudo pintar "
                              f"({type(e).__name__}: {str(e)[:80]}); se usa "
                              "el coche de cajas")
                        self._aviso_coche = True
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
            asinc = (not self.compartido and self.pbo is not None
                     and bool(getattr(cfg, "GFX_GPU_ASYNC", False)))
            self.asincrono = asinc
            if self.compartido:
                # la escena ya esta en la textura de SDL: nada que leer
                self._pendiente = None
                frame_mostrado = frame_actual
            elif asinc:
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
            if self.compartido:
                pass
            elif destino is not None:
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
        if self.compartido:
            pass                    # la textura ya tiene la escena
        elif destino is not None:
            sdl2.SDL_UnlockTexture(self.tex)
        else:
            sdl2.SDL_UpdateTexture(self.tex, None, pixeles, W * 4)
        sdl2.SDL_RenderCopy(self.r, self.tex, None, None)
        self.ms_subida = (time.perf_counter() - t3) * 1000.0

    def _dibujar_coche(self, ctx, coche, st, vista, proy, rels, elev,
                       elev_cam, bank_cam, rumbo_seg, pal, track=None):
        """Modelo 3D del coche en la escena: posicion (n del eje, cota del
        asfalto bajo el), rumbo psi, peralte y pendiente del tramo mas el
        cabeceo, balanceo y bote de la suspension (exagerados como en el
        coche de cajas); ruedas delanteras giradas con la direccion y las
        cuatro rodando; sombra oscura en el suelo; luz del sol."""
        datos = coche["datos"]
        if self._modelo_gpu is None or self._modelo_gpu.datos is not datos:
            if self._modelo_gpu is not None:
                self._modelo_gpu.release()
            self._modelo_gpu = modelo3d.ModeloGpu(ctx, datos)
        m = self._modelo_gpu
        # Movimiento de la carroceria sobre las ruedas. Menos exagerado que
        # en el coche de cajas: con las ruedas fijas al suelo, un balanceo
        # de 7 grados hacia que pareciesen las ruedas las que se tumbaban
        ex = float(getattr(cfg, "CAR_BODY_MOTION_EXAG", 1.0)) * 0.35
        heave = max(-0.07, min(0.07, float(getattr(st, "heave", 0.0)) * ex))
        pitch = max(-0.05, min(0.05, float(getattr(st, "pitch", 0.0)) * ex))
        roll = max(-0.05, min(0.05, float(getattr(st, "roll", 0.0)) * ex))
        # pendiente del tramo bajo el coche (la malla lleva la cota real)
        j0 = int(np.searchsorted(rels, 0.0))
        j0 = min(max(j0, 1), len(rels) - 2)
        pendiente = math.atan2(elev[j0 + 1] - elev[j0 - 1],
                               rels[j0 + 1] - rels[j0 - 1])
        n = float(st.n)
        y_suelo = elev_cam - n * math.tan(bank_cam)
        # misma convencion que la camara: la vista gira el mundo con
        # _mat_guinada(psi) y _mat_balanceo(peralte), asi que el coche se
        # coloca con las inversas
        base = (_mat_traslacion(n, y_suelo, 0.0)
                @ _mat_balanceo(-bank_cam + roll)
                @ _mat_cabeceo(pendiente + pitch)
                @ _mat_guinada(-float(st.psi)))
        cuerpo = base @ _mat_traslacion(0.0, heave, 0.0)
        delta = (float(coche.get("steering", 0.0))
                 * math.radians(cfg.WHEEL_ROTATION_DEG / 2.0) / cfg.STEER_RATIO)
        delta = max(-0.6, min(0.6, delta))
        m.rodar(getattr(st, "omega", (0.0, 0.0, 0.0, 0.0)),
                float(coche.get("dt", 0.0)))
        # Las ruedas van con ``base``, NO con ``cuerpo``: el bote, cabeceo y
        # balanceo de la suspension mueven la carroceria sobre ellas, que se
        # quedan asentadas en el asfalto. Colgadas del cuerpo, al frenar o
        # en curva se levantaban del suelo o se hundian en el.
        # Cada rueda sigue ademas los BACHES del firme bajo ella (la misma
        # rugosidad que siente la fisica), que la malla de la carretera no
        # dibuja: sube y baja sola respecto a la carroceria, que la
        # suspension amortigua.
        mats = [cuerpo]
        superficies = getattr(st, "wheel_surface", ("road",) * 4)
        bump_fn = getattr(track, "bump_at", None) if track is not None else None
        for k in range(1, 5):
            c = m.centros[k]
            giro = _mat_guinada(-delta) if k <= 2 else np.eye(4)
            dy = 0.0
            if bump_fn is not None:
                try:
                    dy = float(bump_fn(st.s + c[2], st.n + c[0],
                                       superficies[k - 1]))
                except Exception:                        # noqa: BLE001
                    dy = 0.0
                dy = max(-0.06, min(0.06, dy))
            mats.append(base @ _mat_traslacion(c[0], c[1] + dy, c[2]) @ giro
                        @ _mat_cabeceo(-m.ang[k - 1]) @ _mat_traslacion(*(-c)))
        self._mats_coche = mats            # (pruebas)
        self._base_coche = base
        # sol: mismo azimut absoluto que el disco del cielo, pasado al
        # espacio de la escena (rumbo del tramo)
        az = SOL_AZIMUT - rumbo_seg
        ce = math.cos(SOL_ELEVACION)
        luz = (math.sin(az) * ce, math.sin(SOL_ELEVACION), math.cos(az) * ce)
        # sombra de contacto (oscura bajo los neumaticos y el centro del
        # bajo, difuminada hacia fuera), con el chasis en el suelo
        m.dibujar_sombra(ctx, vista, proy, base)
        # posicion de la camara en el espacio de la escena (para el brillo
        # especular y el Fresnel) y colores del cielo y el suelo para la
        # luz ambiente hemisferica
        cam_pos = np.linalg.inv(vista)[:3, 3]
        cielo = np.asarray(pal["sky_top"], float) / 255.0
        suelo = np.asarray(pal["grass"][0], float) / 255.0
        m.dibujar(vista, proy, mats, luz, cam_pos, cielo, suelo)

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

    # -- arboles ------------------------------------------------------------
    def _plantar(self, track):
        """Arboles FIJOS de un circuito: estacion, lado, distancia al borde
        de la calzada, altura, tipo y tono, repartidos al azar (con semilla
        fija: siempre los mismos) cada TREE_SPACING_M metros."""
        paso = float(getattr(cfg, "TREE_SPACING_M", 40.0))
        L = float(track.length)
        n = int(L / max(paso, 5.0))
        if n <= 0:
            return None
        rng = np.random.default_rng(int(L * 7.0) + self.N)
        s = (np.arange(n) * paso + rng.uniform(-0.4, 0.4, n) * paso) % L
        return dict(s=s,
                    lado=np.where(rng.random(n) < 0.5, -1.0, 1.0),
                    dist=rng.uniform(4.0, 24.0, n),
                    alto=rng.uniform(5.0, 11.0, n),
                    tipo=(rng.random(n) < 0.45).astype(int),
                    tono=rng.uniform(0.80, 1.15, n))

    def _arboles(self, track, s0, rels, x, z, hx, hz, elev, cb, sb, hw, kw,
                 rumbo_seg):
        """Los arboles a la vista este fotograma como triangulos en el
        espacio de la escena (misma vista que la carretera), con el
        sombreado del sol horneado en el color. (vertices, indices) o None."""
        global _PLANTILLAS_ARBOL
        arb = getattr(self, "_arboles_track", None)
        if arb is None or not getattr(cfg, "TRACK_TREES", True):
            return None
        L = float(track.length)
        ds = (arb["s"] - s0 + L / 2.0) % L - L / 2.0
        vis = (ds > max(rels[0], -30.0)) & (ds < min(rels[-1], 650.0))
        if not vis.any():
            return None
        if _PLANTILLAS_ARBOL is None:
            _PLANTILLAS_ARBOL = _plantillas_arbol()
        d = ds[vis]
        xi, zi = np.interp(d, rels, x), np.interp(d, rels, z)
        hxi, hzi = np.interp(d, rels, hx), np.interp(d, rels, hz)
        ei = np.interp(d, rels, elev)
        cbi, sbi = np.interp(d, rels, cb), np.interp(d, rels, sb)
        hwi = np.interp(d, rels, hw)
        dist = np.minimum(arb["dist"][vis], ANCHO_HIERBA - hwi - kw - 3.0)
        o = arb["lado"][vis] * (hwi + kw + dist)
        base = np.stack([xi + hxi * o * cbi, ei - o * sbi, zi + hzi * o * cbi],
                        axis=1)
        alto, tipo, tono = arb["alto"][vis], arb["tipo"][vis], arb["tono"][vis]
        az = SOL_AZIMUT - rumbo_seg
        ce = math.cos(SOL_ELEVACION)
        luz = np.array([math.sin(az) * ce, math.sin(SOL_ELEVACION),
                        math.cos(az) * ce])
        bloques = []
        for t in (0, 1):
            sel = tipo == t
            if not sel.any():
                continue
            tri, col, nrm = _PLANTILLAS_ARBOL[t]
            sombra = 0.55 + 0.45 * np.clip(nrm @ luz, 0.0, 1.0)       # (T,)
            pos = (tri[None, :, :, :] * alto[sel][:, None, None, None]
                   + base[sel][:, None, None, :])                    # (n,T,3,3)
            c = (col[None, :, :] * sombra[None, :, None]
                 * tono[sel][:, None, None])                        # (n,T,3)
            c = np.repeat(c[:, :, None, :], 3, axis=2)               # (n,T,3,3)
            bloques.append((pos.reshape(-1, 3), c.reshape(-1, 3)))
        pos = np.concatenate([p for p, _ in bloques])
        col = np.concatenate([c for _, c in bloques])
        vb = np.empty(len(pos), dtype=_VERTICE)
        vb["pos"] = pos
        vb["col"][:, :3] = np.clip(col, 0, 255).astype(np.uint8)
        vb["col"][:, 3] = 255
        return vb, np.arange(len(pos), dtype=np.int32)

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

        # --- balizas (amarilla izquierda, azul derecha) cada 6 m ------------
        # A ESTACIONES FIJAS, interpolando entre secciones: la malla es
        # adaptativa (secciones cada 1, 2 o 4 m) y colocarlas "cada 6
        # secciones" las agrupaba de distinta forma en cada tramo.
        if cfg.TRACK_POLES:
            paso_b = 6.0
            s0 = float(self._frame_s0) if getattr(self, "_frame_s0", None) is not None else 0.0
            ini = math.ceil((s0 + max(rels[0], 0.0)) / paso_b) * paso_b - s0
            est = np.arange(ini, min(rels[-1], 700.0), paso_b)
            est = est[est >= 0.0]
            alto = float(getattr(cfg, "TRACK_POLE_HEIGHT", 2.2))
            if len(est):
                xi, zi = np.interp(est, rels, x), np.interp(est, rels, z)
                hxi, hzi = np.interp(est, rels, hx), np.interp(est, rels, hz)
                ei = np.interp(est, rels, elev)
                cbi, sbi = np.interp(est, rels, cb), np.interp(est, rels, sb)
                hwi = np.interp(est, rels, hw)
                for lado, col in ((-1.0, (255, 215, 30)), (1.0, (60, 145, 255))):
                    o = lado * (hwi + kw + 0.5)
                    p = np.stack([xi + hxi * o * cbi, ei - o * sbi,
                                  zi + hzi * o * cbi, np.ones_like(xi)], axis=1)
                    pv = p @ vista[:3].T
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
            modo = ("contexto compartido con SDL, sin lectura"
                    if _escena.compartido else
                    "contexto propio + lectura del fotograma")
            print(f"Render GPU: {_escena.info.get('GL_RENDERER', '?')} "
                  f"(OpenGL {_escena.info.get('GL_VERSION', '?')}, "
                  f"MSAA x{_escena.msaa}; {modo})")
            if not _escena.compartido and _escena.motivo_compartido:
                print(f"  (sin contexto compartido: "
                      f"{_escena.motivo_compartido})")
        else:
            print(f"Render GPU no disponible ({_escena.motivo}): "
                  "se usa el renderizador de SDL")
    return _escena if _escena.ok else None
