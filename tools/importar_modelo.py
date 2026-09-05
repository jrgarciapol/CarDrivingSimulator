"""Convierte un modelo 3D de coche en glTF binario (.glb, el formato de
Sketchfab y de Blender) al formato propio del juego (.npz de numpy).

    python tools/importar_modelo.py simulator/models/coche.glb f1 [--frente=-z]

Deja simulator/models/f1.npz con:

  - la geometria triangulada en metros (posiciones, normales, coordenadas
    de textura, color de material) con el origen en el centro del coche
    y el suelo en y = 0, el morro hacia +z y la derecha hacia +x,
  - las texturas DECODIFICADAS (a lo sumo 1024 px) para que el juego no
    necesite Pillow ni nada mas que numpy,
  - las PIEZAS: 0 carroceria, 1 rueda delantera izquierda, 2 delantera
    derecha, 3 trasera izquierda, 4 trasera derecha, con su centro y su
    radio, para girar las delanteras con la direccion y hacerlas rodar.

Las ruedas se reconocen por su forma: piezas casi tan anchas como el coche
(los dos lados de un eje juntos), redondas vistas de lado (alto = fondo) y
lejos del centro. Cada eje se parte en dos ruedas por el signo de x. Si el
modelo tiene el morro hacia -z, --frente=-z le da la vuelta.

Solo hace falta ejecutarlo una vez por modelo; el .npz se versiona.
"""

import io
import json
import os
import struct
import sys

import numpy as np

TAM_TEXTURA_MAX = 1024
_TIPOS = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4",
          5126: "f4"}
_N = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def leer_glb(ruta):
    """(json, bytes del bufer binario)."""
    with open(ruta, "rb") as f:
        magic, version, _ = struct.unpack("<4sII", f.read(12))
        if magic != b"glTF":
            raise ValueError("no es un archivo glTF binario (.glb)")
        clen, ctype = struct.unpack("<II", f.read(8))
        js = json.loads(f.read(clen))
        binario = b""
        while True:
            cab = f.read(8)
            if len(cab) < 8:
                break
            blen, btype = struct.unpack("<II", cab)
            datos = f.read(blen)
            if btype == 0x004E4942:          # "BIN"
                binario = datos
    return js, binario


def accesor(js, binario, i):
    a = js["accessors"][i]
    bv = js["bufferViews"][a["bufferView"]]
    dt = np.dtype(_TIPOS[a["componentType"]])
    n = _N[a["type"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    paso = bv.get("byteStride", 0)
    if paso and paso != n * dt.itemsize:
        crudo = np.frombuffer(binario, dtype=np.uint8, count=paso * a["count"],
                              offset=off)
        v = np.lib.stride_tricks.as_strided(
            crudo.view(dt), shape=(a["count"], n), strides=(paso, dt.itemsize))
        return np.array(v)
    return np.frombuffer(binario, dtype=dt, count=a["count"] * n,
                         offset=off).reshape(a["count"], n).copy()


def _matriz_nodo(n):
    if "matrix" in n:
        return np.array(n["matrix"], dtype=float).reshape(4, 4).T
    m = np.eye(4)
    if "scale" in n:
        m = m @ np.diag(list(n["scale"]) + [1.0])
    if "rotation" in n:
        x, y, z, w = n["rotation"]
        r = np.eye(4)
        r[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        m = r @ m
    if "translation" in n:
        t = np.eye(4)
        t[:3, 3] = n["translation"]
        m = t @ m
    return m


def _texturas(js, binario):
    """Decodifica las imagenes con Pillow; devuelve lista de arrays (h,w,3)
    uint8 con la fila 0 ABAJO (convencion de OpenGL) o None si falla."""
    try:
        from PIL import Image
    except ImportError:
        print("AVISO: sin Pillow no se pueden decodificar las texturas; "
              "el modelo saldra con colores planos (pip install pillow)")
        return [None] * len(js.get("images", []))
    out = []
    for im in js.get("images", []):
        bv = js["bufferViews"][im["bufferView"]]
        off = bv.get("byteOffset", 0)
        img = Image.open(io.BytesIO(binario[off:off + bv["byteLength"]]))
        img = img.convert("RGB")
        w, h = img.size
        k = max(w, h) / TAM_TEXTURA_MAX
        if k > 1.0:
            img = img.resize((max(1, int(w / k)), max(1, int(h / k))),
                             Image.LANCZOS)
        out.append(np.asarray(img, dtype=np.uint8)[::-1].copy())
    return out


def _piezas(js, binario):
    """Recorre la escena y devuelve una lista de mallas ya en coordenadas
    del mundo: dict(pos, nrm, uv, idx, color, tex, nombre)."""
    piezas = []

    def visita(i, M):
        n = js["nodes"][i]
        M = M @ _matriz_nodo(n)
        if "mesh" in n:
            for p in js["meshes"][n["mesh"]]["primitives"]:
                if p.get("mode", 4) != 4:
                    continue                    # solo triangulos
                at = p["attributes"]
                pos = accesor(js, binario, at["POSITION"]).astype(float)
                pos = (np.c_[pos, np.ones(len(pos))] @ M.T)[:, :3]
                if "NORMAL" in at:
                    nrm = accesor(js, binario, at["NORMAL"]).astype(float)
                    R = M[:3, :3]
                    nrm = nrm @ np.linalg.inv(R).T
                    nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-9)[:, None]
                else:
                    nrm = None
                uv = (accesor(js, binario, at["TEXCOORD_0"]).astype(float)
                      if "TEXCOORD_0" in at else np.zeros((len(pos), 2)))
                idx = (accesor(js, binario, p["indices"]).ravel().astype(np.uint32)
                       if "indices" in p else np.arange(len(pos), dtype=np.uint32))
                color, tex = (1.0, 1.0, 1.0, 1.0), -1
                if "material" in p:
                    mt = js["materials"][p["material"]]
                    pbr = mt.get("pbrMetallicRoughness", {})
                    color = tuple(pbr.get("baseColorFactor", (1.0, 1.0, 1.0, 1.0)))
                    if "baseColorTexture" in pbr:
                        tex = js["textures"][pbr["baseColorTexture"]["index"]]["source"]
                if nrm is None:
                    nrm = _normales(pos, idx)
                piezas.append(dict(pos=pos, nrm=nrm, uv=uv, idx=idx,
                                   color=color, tex=tex, nombre=n.get("name", "")))
        for c in n.get("children", []):
            visita(c, M)

    escena = js["scenes"][js.get("scene", 0)]
    for r in escena["nodes"]:
        visita(r, np.eye(4))
    return piezas


def _normales(pos, idx):
    tri = idx.reshape(-1, 3)
    n = np.cross(pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]])
    out = np.zeros_like(pos)
    for k in range(3):
        np.add.at(out, tri[:, k], n)
    return out / np.maximum(np.linalg.norm(out, axis=1), 1e-9)[:, None]


def clasificar(piezas):
    """Asigna a cada pieza su parte: 0 carroceria, 1..4 ruedas (ver arriba).
    Las ruedas van agrupadas por EJE en el modelo; aqui se parten en
    izquierda/derecha por el signo de x."""
    todo = np.concatenate([p["pos"] for p in piezas])
    lo, hi = todo.min(0), todo.max(0)
    ancho, largo = hi[0] - lo[0], hi[2] - lo[2]
    ejes = []
    for p in piezas:
        a, b = p["pos"].min(0), p["pos"].max(0)
        tam = b - a
        c = (a + b) / 2
        redonda = abs(tam[1] - tam[2]) < 0.25 * max(tam[1], tam[2])
        if (tam[0] > 0.7 * ancho and redonda and tam[2] < 0.35 * largo
                and abs(c[2]) > 0.15 * largo):
            ejes.append((c[2], p))
    delante = max((z for z, _ in ejes), default=None)
    detras = min((z for z, _ in ejes), default=None)
    salida = []
    for p in piezas:
        es_eje = next((z for z, q in ejes if q is p), None)
        if es_eje is None:
            salida.append((0, p))
            continue
        frontal = abs(es_eje - delante) < abs(es_eje - detras)
        for lado, mask in (("izq", p["pos"][:, 0] < 0), ("der", p["pos"][:, 0] >= 0)):
            parte = (1 if frontal else 3) + (0 if lado == "izq" else 1)
            salida.append((parte, _recortar(p, mask)))
    return salida, (ancho, largo)


def _recortar(p, mask):
    """Subconjunto de una malla: los triangulos cuyos vertices estan todos
    en mask, reindexados."""
    tri = p["idx"].reshape(-1, 3)
    keep = mask[tri].all(axis=1)
    tri = tri[keep]
    usados = np.unique(tri)
    remap = np.full(len(p["pos"]), -1, dtype=np.int64)
    remap[usados] = np.arange(len(usados))
    q = dict(p)
    q["pos"], q["nrm"], q["uv"] = p["pos"][usados], p["nrm"][usados], p["uv"][usados]
    q["idx"] = remap[tri].ravel().astype(np.uint32)
    return q


def convertir(ruta_glb, nombre, frente="+z", carpeta=None):
    js, binario = leer_glb(ruta_glb)
    piezas = _piezas(js, binario)
    if not piezas:
        raise ValueError("el modelo no tiene mallas de triangulos")
    if frente == "-z":                  # girar 180 grados sobre y
        for p in piezas:
            p["pos"][:, 0] *= -1
            p["pos"][:, 2] *= -1
            p["nrm"][:, 0] *= -1
            p["nrm"][:, 2] *= -1
    partes, (ancho, largo) = clasificar(piezas)
    # centrar en x/z y apoyar en el suelo
    todo = np.concatenate([p["pos"] for _, p in partes])
    lo, hi = todo.min(0), todo.max(0)
    desplazar = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    pos, nrm, uv, col, tex, parte, idx = [], [], [], [], [], [], []
    centros = np.zeros((5, 3))
    radios = np.zeros(5)
    base = 0
    for k, p in partes:
        q = p["pos"] - desplazar
        pos.append(q)
        nrm.append(p["nrm"])
        uv.append(p["uv"])
        c = np.array(p["color"][:4]) if len(p["color"]) >= 4 else np.r_[p["color"], 1.0]
        col.append(np.tile((np.clip(c, 0, 1) * 255).astype(np.uint8), (len(q), 1)))
        tex.append(np.full(len(q), p["tex"], dtype=np.int8))
        parte.append(np.full(len(q), k, dtype=np.int8))
        idx.append(p["idx"] + base)
        base += len(q)
    pos = np.concatenate(pos).astype(np.float32)
    parte_v = np.concatenate(parte)
    for k in range(1, 5):
        m = parte_v == k
        if m.any():
            a, b = pos[m].min(0), pos[m].max(0)
            centros[k] = (a + b) / 2
            radios[k] = (b[1] - a[1]) / 2
    if (parte_v == 0).any():
        a, b = pos[parte_v == 0].min(0), pos[parte_v == 0].max(0)
        centros[0] = (a + b) / 2
    texs = _texturas(js, binario)
    datos = dict(pos=pos, nrm=np.concatenate(nrm).astype(np.float32),
                 uv=np.concatenate(uv).astype(np.float32),
                 col=np.concatenate(col), tex=np.concatenate(tex),
                 parte=parte_v, idx=np.concatenate(idx).astype(np.uint32),
                 centros=centros.astype(np.float32),
                 radios=radios.astype(np.float32),
                 medidas=np.array([hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]],
                                  dtype=np.float32),
                 n_texturas=np.int32(len(texs)))
    for i, t in enumerate(texs):
        if t is not None:
            datos[f"tex{i}"] = t
    carpeta = carpeta or os.path.join(os.path.dirname(__file__), "..",
                                      "simulator", "models")
    ruta = os.path.join(carpeta, f"{nombre}.npz")
    np.savez_compressed(ruta, **datos)
    return ruta, datos


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    ops = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    if len(args) < 2:
        print(__doc__)
        return 1
    ruta, datos = convertir(args[0], args[1], ops.get("frente", "+z"))
    m = datos["medidas"]
    print(f"Guardado {ruta}: {len(datos['idx']) // 3} triangulos, "
          f"{len(datos['pos'])} vertices, {int(datos['n_texturas'])} texturas; "
          f"{m[0]:.2f} x {m[1]:.2f} x {m[2]:.2f} m (ancho x alto x largo)")
    nombres = ("carroceria", "rueda del. izq.", "rueda del. der.",
               "rueda tras. izq.", "rueda tras. der.")
    for k in range(5):
        n = int((datos["parte"] == k).sum())
        c = datos["centros"][k]
        print(f"  {nombres[k]:18s} {n:6d} vertices  centro "
              f"({c[0]:+.2f}, {c[1]:.2f}, {c[2]:+.2f})"
              + (f"  radio {datos['radios'][k]:.2f} m" if k else ""))
    print(f"  tamano del archivo: {os.path.getsize(ruta) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
