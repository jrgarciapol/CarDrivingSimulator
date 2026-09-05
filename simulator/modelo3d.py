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
out vec3 v_nrm;
out vec2 v_uv;
out vec4 v_col;
void main() {
    vec4 p = u_model * vec4(in_pos, 1.0);
    v_nrm = mat3(u_model) * in_nrm;      // sin escala: la rotacion basta
    v_uv = in_uv;
    v_col = in_col;
    gl_Position = u_proj * u_view * p;
}
"""

_FS_MODELO = """#version 330
uniform sampler2D u_tex;
uniform float u_tex_on;              // 1 = pieza con textura
uniform vec3 u_luz;                  // hacia el sol, en el espacio de la escena
in vec3 v_nrm;
in vec2 v_uv;
in vec4 v_col;
out vec4 f_col;
void main() {
    vec3 base = mix(v_col.rgb, texture(u_tex, v_uv).rgb, u_tex_on);
    vec3 n = normalize(v_nrm);
    float difusa = max(dot(n, u_luz), 0.0);
    // ambiente algo mas claro por arriba (cielo) que por abajo (suelo)
    float ambiente = 0.38 + 0.10 * (0.5 + 0.5 * n.y);
    f_col = vec4(base * (ambiente + 0.62 * difusa), 1.0);
}
"""


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
        clave = parte * 16 + (tex + 1)
        orden = np.argsort(clave, kind="stable")
        tri, clave = tri[orden], clave[orden]
        self.grupos = []                 # (pieza, textura, primer indice, n)
        for c in np.unique(clave):
            sel = np.nonzero(clave == c)[0]
            self.grupos.append((int(c // 16), int(c % 16) - 1,
                                int(sel[0]) * 3, len(sel) * 3))
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

    #: rad/s por encima de los cuales la rueda deja de girar en pantalla.
    #: A 60-120 fotogramas por segundo una rueda a 80 rad/s avanza 0,7-1,3
    #: radianes por fotograma: efecto estroboscopico, parece que patina o
    #: que gira hacia atras. En la realidad a esa velocidad la llanta se ve
    #: borrosa; congelarla es lo que menos llama la atencion.
    OMEGA_VISIBLE = 14.0

    def rodar(self, omegas, dt):
        """Acumula el giro de cada rueda (rad/s de la fisica, orden DI DD
        TI TD, el mismo que las piezas 1..4)."""
        for i in range(4):
            w = float(omegas[i])
            if abs(w) < self.OMEGA_VISIBLE:
                self.ang[i] = (self.ang[i] + w * dt) % (2.0 * np.pi)

    def dibujar(self, vista, proy, matrices, luz):
        """Pinta todas las piezas. ``matrices``: lista de 5 matrices 4x4
        (carroceria, DI, DD, TI, TD) modelo -> escena. ``luz``: vector
        unitario hacia el sol en el espacio de la escena."""
        p = self.prog
        p["u_view"].write(vista.T.astype("f4").tobytes())
        p["u_proj"].write(proy.T.astype("f4").tobytes())
        p["u_luz"].value = tuple(float(v) for v in luz)
        ultima = None
        for pieza, tex, primero, n in self.grupos:
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

    def release(self):
        for tx in self.texturas.values():
            tx.release()
        self.vao.release()
        self.vbo.release()
        self.ibo.release()
        self.prog.release()
