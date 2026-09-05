"""Modelo 3D del coche para la vista de coche completo, pintado en la GPU.

Los modelos viven en simulator/models/NOMBRE.npz, que produce
tools/importar_modelo.py a partir de un .glb (Sketchfab, Blender). Llevan
la geometria en metros con el suelo en y = 0 y el morro hacia +z, las
texturas ya decodificadas y las cinco PIEZAS (carroceria y cuatro ruedas)
con su centro, de modo que las delanteras giran con la direccion y todas
ruedan con la velocidad de cada rueda que calcula la fisica.

Que modelo se usa lo dice CAR_MODEL_3D (en config.py o en el archivo .car
de cada coche); vacio = el coche de cajas de siempre. Si el archivo no
existe, tambien.

La iluminacion es la del sol de la escena (misma direccion que el disco
del cielo): color del material o de la textura por un termino ambiente y
otro difuso; y una sombra oscura bajo el coche, que es lo que mas lo
"pega" al suelo.

La sombra tiene dos partes sobre el mismo rectangulo a ras de suelo: la de
CONTACTO (oscura bajo los neumaticos y el bajo, un mapa fijo por modelo) y
la PROYECTADA por el sol: cada fotograma se aplasta el modelo sobre el
suelo a lo largo del rayo de sol y se pinta su silueta en una textura
pequena (proyeccion planar, sin doble oscurecimiento porque la silueta se
pinta primero en la textura y luego se mezcla una sola vez con el suelo).
Con el sol tapado (lluvia, niebla) solo queda la de contacto.
"""

import os

import numpy as np

try:
    import moderngl
except ImportError:                                  # pragma: no cover
    moderngl = None

#: carpeta de los modelos y cache de los ya leidos (nombre -> dict o None)
CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
_CACHE = {}

PARTES = ("carroceria", "rueda_di", "rueda_dd", "rueda_ti", "rueda_td")

_VS_MODELO = """#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat4 u_model;
in vec3 in_pos;
in vec3 in_nrm;
in vec2 in_uv;
in vec4 in_col;
out vec3 v_pos;
out vec3 v_nrm;
out vec2 v_uv;
out vec4 v_col;
void main() {
    vec4 p = u_model * vec4(in_pos, 1.0);
    v_pos = p.xyz;
    v_nrm = mat3(u_model) * in_nrm;      // sin escala: la rotacion basta
    v_uv = in_uv;
    v_col = in_col;
    gl_Position = u_proj * u_view * p;
}
"""

# Iluminacion pensada para que un coche de Sketchfab se parezca a como se
# ve alli: se trabaja en espacio LINEAL (las texturas y los colores vienen
# en sRGB; iluminar sin convertirlos apaga los medios tonos), con luz
# ambiente HEMISFERICA (cielo por arriba, suelo por abajo), difusa del sol,
# brillo especular (la chapa refleja el sol) y un termino de Fresnel que
# tine con el cielo las superficies vistas de refilon, como hace la
# pintura de un coche.
_FS_MODELO = """#version 330
uniform sampler2D u_tex;
uniform float u_tex_on;              // 1 = pieza con textura
uniform vec3 u_luz;                  // hacia el sol, en el espacio de la escena
uniform vec3 u_cam;                  // posicion de la camara, idem
uniform vec3 u_cielo;                // color del cielo (ambiente por arriba)
uniform vec3 u_suelo;                // color del suelo (ambiente por abajo)
in vec3 v_pos;
in vec3 v_nrm;
in vec2 v_uv;
in vec4 v_col;
out vec4 f_col;
vec3 lineal(vec3 c) { return pow(c, vec3(2.2)); }
void main() {
    // glTF: color base = factor del material x textura
    vec3 base = lineal(v_col.rgb) * mix(vec3(1.0), lineal(texture(u_tex, v_uv).rgb), u_tex_on);
    vec3 n = normalize(v_nrm);
    vec3 v = normalize(u_cam - v_pos);
    if (dot(n, v) < 0.0) n = -n;         // caras de dos lados
    // el cielo y el suelo, DESATURADOS: la luz ambiente real es mucho mas
    // neutra que el azul del cenit (tal cual, un coche blanco salia celeste)
    vec3 cielo = lineal(u_cielo);
    vec3 suelo = lineal(u_suelo);
    cielo = mix(cielo, vec3(dot(cielo, vec3(0.3, 0.59, 0.11))), 0.7);
    suelo = mix(suelo, vec3(dot(suelo, vec3(0.3, 0.59, 0.11))), 0.7);
    // ambiente hemisferica: cuanto mira hacia arriba, cielo; hacia abajo, suelo
    float arriba = 0.5 + 0.5 * n.y;
    vec3 ambiente = mix(suelo * 0.45, cielo * 0.75, arriba);
    float difusa = max(dot(n, u_luz), 0.0);
    vec3 sol = vec3(1.0, 0.97, 0.90);
    vec3 col = base * (ambiente + sol * 1.05 * difusa);
    // brillo del sol sobre la chapa (Blinn-Phong) y REFLEJO DEL ENTORNO:
    // un mapa de entorno procedural (cielo arriba, calima en el horizonte,
    // suelo abajo) muestreado con el vector reflejado y pesado por Fresnel,
    // que es lo que da a la pintura su aspecto de espejo curvo
    vec3 h = normalize(u_luz + v);
    float espec = pow(max(dot(n, h), 0.0), 48.0) * 0.6 * step(0.001, difusa);
    vec3 r = reflect(-v, n);
    vec3 calima = lineal(mix(u_cielo, vec3(0.93, 0.95, 0.98), 0.55));
    vec3 entorno = (r.y >= 0.0)
        ? mix(calima, lineal(u_cielo), smoothstep(0.0, 0.45, r.y))
        : mix(calima, lineal(u_suelo) * 0.8, smoothstep(0.0, 0.25, -r.y));
    float fres = 0.04 + 0.96 * pow(1.0 - max(dot(n, v), 0.0), 5.0);
    col = mix(col, entorno, fres * 0.55) + sol * espec;
    f_col = vec4(pow(col, vec3(1.0 / 2.2)), v_col.a);
}
"""


# La sombra: un rectangulo a ras de suelo en el sistema del chasis (x, z en
# metros) que lleva dos texturas, la de contacto (rectangulo fijo de
# mapa_sombra) y la silueta proyectada (rectangulo que cambia con el sol)
_VS_SOMBRA = """#version 330
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat4 u_model;
in vec3 in_pos;
out vec2 v_xz;
void main() {
    v_xz = in_pos.xz;
    gl_Position = u_proj * u_view * u_model * vec4(in_pos, 1.0);
}
"""

_FS_SOMBRA = """#version 330
uniform sampler2D u_tex;         // sombra de contacto (alfa)
uniform sampler2D u_tex_proy;    // silueta proyectada por el sol (alfa)
uniform vec2 u_semi;             // semiancho, semilargo del mapa de contacto
uniform vec4 u_rect;             // xmin, zmin, xmax, zmax de la silueta
uniform float u_proy;            // opacidad de la sombra del sol (0 = sin sol)
in vec2 v_xz;
out vec4 f_col;
void main() {
    vec2 uvc = (v_xz + u_semi) / (2.0 * u_semi);
    float c = texture(u_tex, uvc).a;
    // borde suave: 5 muestras de la silueta (penumbra de unos centimetros)
    vec2 uvp = (v_xz - u_rect.xy) / (u_rect.zw - u_rect.xy);
    vec2 d = 0.8 / vec2(textureSize(u_tex_proy, 0));
    float p = texture(u_tex_proy, uvp).a * 0.36
            + texture(u_tex_proy, uvp + vec2(d.x, 0.0)).a * 0.16
            + texture(u_tex_proy, uvp - vec2(d.x, 0.0)).a * 0.16
            + texture(u_tex_proy, uvp + vec2(0.0, d.y)).a * 0.16
            + texture(u_tex_proy, uvp - vec2(0.0, d.y)).a * 0.16;
    float a = 1.0 - (1.0 - c) * (1.0 - p * u_proy);
    f_col = vec4(0.0, 0.0, 0.0, a);
}
"""

# la silueta: el modelo aplastado sobre el suelo, visto desde arriba
_VS_SILUETA = """#version 330
uniform mat4 u_mvp;
in vec3 in_pos;
void main() { gl_Position = u_mvp * vec4(in_pos, 1.0); }
"""

_FS_SILUETA = """#version 330
out vec4 f_col;
void main() { f_col = vec4(1.0); }
"""

#: lado (pixeles) de la textura de la silueta proyectada
SILUETA_PX = 160
#: tope de texturas por modelo (para la clave de agrupacion pieza/textura)
_MAX_TEXTURAS = 4096
#: opacidad de la sombra del sol sobre el asfalto (la de contacto llega a 0,92)
SOMBRA_SOL = 0.5
#: tangente maxima del rayo de sol respecto a la vertical (sol muy bajo:
#: la sombra se alargaria sin fin)
_TAN_MAX = 3.0


def mapa_sombra(medidas, centros, radios, n=96):
    """Sombra de contacto del coche vista desde arriba, como mapa de
    opacidad (n x n, 0..1) sobre un rectangulo algo mayor que el coche:
    oscura bajo la carroceria (y mas en el centro), muy oscura justo bajo
    cada neumatico, y difuminada hacia fuera. Un rectangulo uniforme, que
    era lo que habia, hacia que el coche pareciera levitar sobre una
    losa; lo que "pega" un coche al suelo es la oscuridad bajo las ruedas.
    Devuelve (mapa, semiancho, semilargo) del rectangulo en metros."""
    an, _, la = [float(v) for v in medidas]
    sx, sz = an * 0.5 + 0.45, la * 0.5 + 0.45
    xs = np.linspace(-sx, sx, n)
    zs = np.linspace(-sz, sz, n)
    X, Z = np.meshgrid(xs, zs, indexing="xy")          # filas = z
    # carroceria: 1 dentro (menos un margen), cae en 0,45 m fuera
    dx = np.maximum(0.0, np.abs(X) - (an * 0.5 - 0.10))
    dz = np.maximum(0.0, np.abs(Z) - (la * 0.5 - 0.15))
    d = np.hypot(dx, dz)
    cuerpo = 0.50 * np.clip(1.0 - d / 0.45, 0.0, 1.0) ** 1.6
    # mas oscuro hacia el centro del bajo (menos luz llega)
    centro = np.clip(1.0 - np.hypot(X / max(an * 0.5, 0.1),
                                    Z / max(la * 0.5, 0.1)), 0.0, 1.0)
    cuerpo += 0.18 * centro
    mapa = cuerpo
    for k in range(1, 5):
        if radios[k] <= 0.0:
            continue
        cx, cz, r = float(centros[k][0]), float(centros[k][2]), float(radios[k])
        dr = np.hypot((X - cx) / (r * 0.75), (Z - cz) / (r * 1.05))
        rueda = 0.85 * np.clip(1.0 - dr, 0.0, 1.0) ** 0.6
        mapa = 1.0 - (1.0 - mapa) * (1.0 - rueda)
    return np.clip(mapa, 0.0, 0.92).astype(np.float32), sx, sz


def ruta(nombre):
    return os.path.join(CARPETA, f"{nombre}.npz")


def cargar(nombre):
    """Datos del modelo (dict de arrays) o None si no hay nombre o no existe
    el archivo. Se lee una sola vez por proceso."""
    if not nombre:
        return None
    if nombre in _CACHE:
        return _CACHE[nombre]
    datos = None
    r = ruta(nombre)
    if os.path.exists(r):
        with np.load(r) as z:
            datos = {k: z[k] for k in z.files}
        datos["nombre"] = nombre
    _CACHE[nombre] = datos
    return datos


class ModeloGpu:
    """El modelo subido a la GPU: un VBO entrelazado, los indices ordenados
    por (pieza, textura) para pintar cada grupo con su matriz y su textura,
    y las texturas con mipmaps."""

    def __init__(self, ctx, datos):
        self.datos = datos
        self.ctx = ctx
        self.prog = ctx.program(vertex_shader=_VS_MODELO,
                                fragment_shader=_FS_MODELO)
        n = len(datos["pos"])
        vert = np.empty(n, dtype=[("pos", "f4", 3), ("nrm", "f4", 3),
                                  ("uv", "f4", 2), ("col", "u1", 4)])
        vert["pos"], vert["nrm"] = datos["pos"], datos["nrm"]
        vert["uv"], vert["col"] = datos["uv"], datos["col"]
        self.vbo = ctx.buffer(vert.tobytes())
        tri = datos["idx"].reshape(-1, 3)
        parte = datos["parte"][tri[:, 0]].astype(int)
        tex = datos["tex"][tri[:, 0]].astype(int)
        # clave (pieza, textura) con sitio para cualquier numero de
        # texturas: con un multiplicador de 16, el Rolls (67 texturas)
        # pintaba dos tercios de la carroceria con la matriz de una rueda,
        # y las puertas y el capo giraban con la direccion
        M = _MAX_TEXTURAS
        clave = parte * M + (tex + 1)
        orden = np.argsort(clave, kind="stable")
        tri, clave = tri[orden], clave[orden]
        alfa = datos["col"][tri[:, 0], 3].astype(float) / 255.0
        self.grupos = []       # (pieza, textura, primer indice, n, alfa)
        for c in np.unique(clave):
            sel = np.nonzero(clave == c)[0]
            self.grupos.append((int(c // M), int(c % M) - 1,
                                int(sel[0]) * 3, len(sel) * 3,
                                float(alfa[sel].mean())))
        self.ibo = ctx.buffer(tri.astype("u4").tobytes())
        self.vao = ctx.vertex_array(
            self.prog, [(self.vbo, "3f 3f 2f 4f1", "in_pos", "in_nrm",
                         "in_uv", "in_col")],
            index_buffer=self.ibo, index_element_size=4)
        self.texturas = {}
        for i in range(int(datos.get("n_texturas", 0))):
            t = datos.get(f"tex{i}")
            if t is None:
                continue
            h, w = t.shape[:2]
            tx = ctx.texture((w, h), 3, np.ascontiguousarray(t).tobytes())
            tx.build_mipmaps()
            tx.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            tx.repeat_x = tx.repeat_y = True
            self.texturas[i] = tx
        self.centros = np.asarray(datos["centros"], dtype=float)
        self.radios = np.asarray(datos["radios"], dtype=float)
        self.medidas = np.asarray(datos["medidas"], dtype=float)
        self.ang = np.zeros(4)           # angulo de rodadura de cada rueda
        self.n_triangulos = len(tri)
        # sombra de contacto: un rectangulo a ras de suelo con el mapa de
        # opacidad de mapa_sombra como textura de un canal
        mapa, sx, sz = mapa_sombra(self.medidas, self.centros, self.radios)
        # RGBA (negro con el mapa en el alfa): una textura de un solo canal
        # salia como una manta opaca en un Intel bajo Windows
        rgba = np.zeros(mapa.shape + (4,), dtype=np.uint8)
        rgba[:, :, 3] = (mapa * 255).astype(np.uint8)
        self.tex_sombra = ctx.texture(mapa.shape[::-1], 4, rgba.tobytes())
        self.tex_sombra.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.tex_sombra.repeat_x = self.tex_sombra.repeat_y = False
        self.prog_sombra = ctx.program(vertex_shader=_VS_SOMBRA,
                                       fragment_shader=_FS_SOMBRA)
        self.semi_sombra = (sx, sz)
        # el rectangulo cambia cada fotograma con la sombra del sol
        self.vbo_sombra = ctx.buffer(reserve=4 * 3 * 4, dynamic=True)
        self.ibo_sombra = ctx.buffer(np.array([0, 1, 2, 0, 2, 3],
                                              dtype=np.uint32).tobytes())
        self.vao_sombra = ctx.vertex_array(
            self.prog_sombra, [(self.vbo_sombra, "3f", "in_pos")],
            index_buffer=self.ibo_sombra, index_element_size=4)
        self.rect_sombra = (-sx, -sz, sx, sz)
        # silueta proyectada: el modelo aplastado sobre el suelo, pintado
        # desde arriba en una textura pequena de su propio framebuffer
        self.prog_silueta = ctx.program(vertex_shader=_VS_SILUETA,
                                        fragment_shader=_FS_SILUETA)
        self.vao_silueta = ctx.vertex_array(
            self.prog_silueta, [(self.vbo, "3f 24x", "in_pos")],
            index_buffer=self.ibo, index_element_size=4)
        self.tex_proy = ctx.texture((SILUETA_PX, SILUETA_PX), 4)
        self.tex_proy.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.tex_proy.repeat_x = self.tex_proy.repeat_y = False
        self.fbo_proy = ctx.framebuffer([self.tex_proy])
        # caja del modelo (esquinas), para saber hasta donde llega la sombra
        lo, hi = datos["pos"].min(0), datos["pos"].max(0)
        self.esquinas = np.array([[x, y, z] for x in (lo[0], hi[0])
                                  for y in (lo[1], hi[1])
                                  for z in (lo[2], hi[2])], dtype=float)

    def _silueta(self, ctx, base, matrices, luz):
        """Pinta en tex_proy la silueta del modelo aplastado sobre el suelo
        del chasis a lo largo del rayo de sol y devuelve el rectangulo
        (xmin, zmin, xmax, zmax) que cubre, en el sistema del chasis; None
        si el sol esta demasiado bajo."""
        # el sol en el sistema del chasis (la rotacion de base es ortonormal)
        lb = base[:3, :3].T @ np.asarray(luz, dtype=float)
        if lb[1] < 0.2:
            return None
        tx = max(-_TAN_MAX, min(_TAN_MAX, lb[0] / lb[1]))
        tz = max(-_TAN_MAX, min(_TAN_MAX, lb[2] / lb[1]))
        # aplastar: (x, y, z) -> (x - tx*y, 0, z - tz*y)
        apl = np.eye(4)
        apl[0, 1], apl[2, 1], apl[1, 1] = -tx, -tz, 0.0
        inv_base = np.linalg.inv(base)
        # rectangulo: la caja de la carroceria aplastada mas el mapa de contacto
        c = self.esquinas @ apl[:3, :3].T
        sx, sz = self.semi_sombra
        margen = 0.35
        xmin, xmax = min(c[:, 0].min(), -sx) - margen, max(c[:, 0].max(), sx) + margen
        zmin, zmax = min(c[:, 2].min(), -sz) - margen, max(c[:, 2].max(), sz) + margen
        # vista cenital ortografica sobre ese rectangulo
        orto = np.eye(4)
        orto[0, 0], orto[0, 3] = 2.0 / (xmax - xmin), -(xmax + xmin) / (xmax - xmin)
        orto[1, 2], orto[1, 3] = 2.0 / (zmax - zmin), -(zmax + zmin) / (zmax - zmin)
        orto[2, 2] = 0.0
        previo = ctx.fbo
        self.fbo_proy.use()
        self.fbo_proy.clear(0.0, 0.0, 0.0, 0.0)
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND)
        p = self.prog_silueta
        ultima = None
        for pieza, _tex, primero, n, _alfa in self.grupos:
            if pieza != ultima:
                mvp = orto @ apl @ inv_base @ matrices[pieza]
                p["u_mvp"].write(mvp.T.astype("f4").tobytes())
                ultima = pieza
            self.vao_silueta.render(moderngl.TRIANGLES, vertices=n, first=primero)
        previo.use()
        return (float(xmin), float(zmin), float(xmax), float(zmax))

    def dibujar_sombra(self, ctx, vista, proy, base, matrices=None, luz=None,
                       sol=True):
        """La sombra, con la matriz del chasis en el suelo (sin bote ni
        cabeceo: la sombra no se levanta con la carroceria): la de contacto
        siempre y, con ``matrices`` (las cinco piezas), ``luz`` y ``sol``,
        la silueta proyectada por el sol encima."""
        sx, sz = self.semi_sombra
        rect = None
        if sol and matrices is not None and luz is not None:
            rect = self._silueta(ctx, base, matrices, luz)
        p = self.prog_sombra
        if rect is None:
            rect = (-sx, -sz, sx, sz)
            p["u_proy"].value = 0.0
        else:
            p["u_proy"].value = SOMBRA_SOL
        self.rect_sombra = rect                      # (pruebas)
        xmin, zmin, xmax, zmax = rect
        y = 0.012
        quad = np.array([[xmin, y, zmin], [xmax, y, zmin],
                         [xmax, y, zmax], [xmin, y, zmax]], dtype="f4")
        self.vbo_sombra.write(quad.tobytes())
        p["u_view"].write(vista.T.astype("f4").tobytes())
        p["u_proj"].write(proy.T.astype("f4").tobytes())
        p["u_model"].write(base.T.astype("f4").tobytes())
        self.tex_sombra.use(location=0)
        self.tex_proy.use(location=1)
        p["u_tex"].value = 0
        p["u_tex_proy"].value = 1
        p["u_semi"].value = (float(sx), float(sz))
        p["u_rect"].value = tuple(float(v) for v in rect)
        # SIN test de profundidad: el cuadrado es plano y la calzada bajo el
        # coche no lo es (rasantes, peralte que cambia, la trazada
        # levantada): con el test, al girar el coche un trozo de la sombra
        # quedaba bajo el asfalto y desaparecia. Va justo despues de la
        # carretera y antes del coche, asi que encima solo esta el coche.
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.vao_sombra.render(moderngl.TRIANGLES, vertices=6)
        ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.DEPTH_TEST)

    #: rad/s por encima de los cuales la rueda deja de girar en pantalla.
    #: Se probo congelarla a partir de 14 rad/s para evitar el efecto
    #: estroboscopico (a 120 fps una rueda a 80 rad/s avanza 0,7 rad por
    #: fotograma), pero el resultado era peor: "las ruedas no rotan". Sin
    #: tope: a veces pareceran girar hacia atras, como en el cine.
    OMEGA_VISIBLE = 1e9

    def rodar(self, omegas, dt):
        """Acumula el giro de cada rueda (rad/s de la fisica, orden DI DD
        TI TD, el mismo que las piezas 1..4)."""
        for i in range(4):
            w = float(omegas[i])
            if abs(w) < self.OMEGA_VISIBLE:
                self.ang[i] = (self.ang[i] + w * dt) % (2.0 * np.pi)

    def dibujar(self, vista, proy, matrices, luz, cam=(0.0, 1.0, -6.0),
                cielo=(0.45, 0.65, 0.95), suelo=(0.25, 0.45, 0.2)):
        """Pinta todas las piezas. ``matrices``: lista de 5 matrices 4x4
        (carroceria, DI, DD, TI, TD) modelo -> escena. ``luz``: vector
        unitario hacia el sol en el espacio de la escena; ``cam`` la
        posicion de la camara; ``cielo`` y ``suelo`` los colores (0..1)
        de la luz ambiente por arriba y por abajo."""
        p = self.prog
        p["u_view"].write(vista.T.astype("f4").tobytes())
        p["u_proj"].write(proy.T.astype("f4").tobytes())
        p["u_luz"].value = tuple(float(v) for v in luz)
        p["u_cam"].value = tuple(float(v) for v in cam)
        p["u_cielo"].value = tuple(float(v) for v in cielo)
        p["u_suelo"].value = tuple(float(v) for v in suelo)
        # dos pasadas: lo opaco con escritura de profundidad y despues los
        # CRISTALES (alfa < 0,95) con mezcla y sin escribir profundidad,
        # para que se vea lo que hay detras (faros, pilotos, interior)
        ctx = self.ctx
        for translucido in (False, True):
            if translucido:
                ctx.enable(moderngl.BLEND)
                ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
                ctx.depth_mask = False
            ultima = None
            for pieza, tex, primero, n, alfa in self.grupos:
                if (alfa < 0.95) != translucido:
                    continue
                if pieza != ultima:
                    p["u_model"].write(matrices[pieza].T.astype("f4").tobytes())
                    ultima = pieza
                tx = self.texturas.get(tex) if tex >= 0 else None
                if tx is not None:
                    tx.use(location=0)
                    p["u_tex"].value = 0
                    p["u_tex_on"].value = 1.0
                else:
                    p["u_tex_on"].value = 0.0
                self.vao.render(moderngl.TRIANGLES, vertices=n, first=primero)
            if translucido:
                ctx.depth_mask = True
                ctx.disable(moderngl.BLEND)

    def release(self):
        for tx in self.texturas.values():
            tx.release()
        for obj in (self.vao_sombra, self.vbo_sombra, self.ibo_sombra,
                    self.tex_sombra, self.prog_sombra, self.vao_silueta,
                    self.prog_silueta, self.fbo_proy, self.tex_proy):
            obj.release()
        self.vao.release()
        self.vbo.release()
        self.ibo.release()
        self.prog.release()
