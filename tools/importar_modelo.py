"""Convierte un modelo 3D de coche en glTF binario (.glb, el formato de
Sketchfab y de Blender) al formato propio del juego (.npz de numpy).

    python tools/importar_modelo.py simulator/models/coche.glb nombre [opciones]

Deja simulator/models/nombre.npz con:

  - la geometria triangulada en metros (posiciones, normales, coordenadas
    de textura, color de material) con el origen en el centro del coche
    y el suelo en y = 0, el morro hacia +z y la derecha hacia +x,
  - las texturas DECODIFICADAS (1024 px como mucho, menos si hay muchas)
    para que el juego no necesite Pillow ni nada mas que numpy,
  - las PIEZAS: 0 carroceria, 1 rueda delantera izquierda, 2 delantera
    derecha, 3 trasera izquierda, 4 trasera derecha, con su centro y su
    radio, para girar las delanteras con la direccion y hacerlas rodar.

Los modelos de Sketchfab vienen de cualquier manera (en centimetros, con
el morro hacia -x, con 800.000 triangulos, con un plano de suelo...), de
ahi las opciones:

  --frente=+z|-z|+x|-x   hacia donde mira el morro en el archivo (+z)
  --arriba=y|z           eje vertical del archivo (y)
  --escala=0.01          factor a metros; o bien
  --largo=4.2            largo real del coche en m (escala a partir del bbox)
  --quitar=regex         mallas que sobran (planos de suelo, entorno...)
  --ruedas=regex         mallas que son ruedas, si no se reconocen solas
  --max_tri=150000       simplificar (agrupando vertices) hasta ese numero
  --textura_max=1024     lado maximo de las texturas

Las ruedas se reconocen solas de tres formas, por este orden: mallas
INDIVIDUALES con forma de rueda (dos medidas iguales, la tercera menor, a
la altura de su radio, lejos del eje); una malla con las CUATRO ruedas
(se parte en cuatro por x y por z); o EJES (las dos ruedas de un eje en
una malla, se parte por x). Si no hay forma, el coche va entero y las
ruedas no giran.

Solo hace falta ejecutarlo una vez por modelo; el .npz se versiona.
"""

import io
import json
import math
import os
import re
import struct
import sys

import numpy as np

TAM_TEXTURA_MAX = 1024
PIXELES_TEXTURA_MAX = 20e6      # presupuesto total de texturas por modelo
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


def _texturas(js, binario, usadas, tam_max):
    """Decodifica las imagenes con Pillow; devuelve lista de arrays (h,w,3)
    uint8 con la fila 0 ABAJO (convencion de OpenGL) o None. Solo las
    texturas ``usadas``; el resto van a None. Si hay muchas, se reduce el
    lado hasta que quepan en el presupuesto de pixeles."""
    n_img = len(js.get("images", []))
    try:
        from PIL import Image
    except ImportError:
        print("AVISO: sin Pillow no se pueden decodificar las texturas; "
              "el modelo saldra con colores planos (pip install pillow)")
        return [None] * n_img
    lado = tam_max
    while lado > 128 and len(usadas) * lado * lado > PIXELES_TEXTURA_MAX:
        lado //= 2
    out = []
    for i, im in enumerate(js.get("images", [])):
        if i not in usadas:
            out.append(None)
            continue
        bv = js["bufferViews"][im["bufferView"]]
        off = bv.get("byteOffset", 0)
        img = Image.open(io.BytesIO(binario[off:off + bv["byteLength"]]))
        img = img.convert("RGB")
        w, h = img.size
        k = max(w, h) / lado
        if k > 1.0:
            img = img.resize((max(1, int(w / k)), max(1, int(h / k))),
                             Image.LANCZOS)
        out.append(np.asarray(img, dtype=np.uint8)[::-1].copy())
    return out


def _alfa_texturas(js, binario, indices):
    """Alfa medio (0..1) del canal alfa de cada imagen de ``indices`` (1.0 si
    no tiene o no hay Pillow): los cristales de los modelos de Sketchfab
    llevan la transparencia en la textura, no en el factor del material."""
    out = {}
    try:
        from PIL import Image
    except ImportError:
        return {i: 1.0 for i in indices}
    for i in indices:
        im = js["images"][i]
        bv = js["bufferViews"][im["bufferView"]]
        off = bv.get("byteOffset", 0)
        img = Image.open(io.BytesIO(binario[off:off + bv["byteLength"]]))
        a = 1.0
        if "A" in img.getbands() or img.mode == "P":
            a = float(np.asarray(img.convert("RGBA"))[:, :, 3].mean()) / 255.0
        out[i] = a
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
                color, tex, modo = (1.0, 1.0, 1.0, 1.0), -1, "OPAQUE"
                if "material" in p:
                    mt = js["materials"][p["material"]]
                    pbr = mt.get("pbrMetallicRoughness", {})
                    color = tuple(pbr.get("baseColorFactor", (1.0, 1.0, 1.0, 1.0)))
                    modo = mt.get("alphaMode", "OPAQUE")
                    if "baseColorTexture" in pbr:
                        tex = js["textures"][pbr["baseColorTexture"]["index"]]["source"]
                if nrm is None:
                    nrm = _normales(pos, idx)
                piezas.append(dict(pos=pos, nrm=nrm, uv=uv, idx=idx,
                                   color=color, tex=tex, modo=modo,
                                   nombre=n.get("name", "")))
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


# ---------------------------------------------------------------- orientar
def _orientar(piezas, frente, arriba):
    """Deja el eje vertical en +y y el morro en +z."""
    def aplicar(R):
        for p in piezas:
            p["pos"] = p["pos"] @ R.T
            p["nrm"] = p["nrm"] @ R.T
    if arriba == "z":                       # z arriba -> y arriba (gira -90 en x)
        aplicar(np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=float))
        # con z arriba, el frente suele darse como +y/-y: ahora es +z/-z
        frente = {"+y": "+z", "-y": "-z"}.get(frente, frente)
    giros = {"+z": None,
             "-z": np.array([[-1, 0, 0], [0, 1, 0], [0, 0, -1]], dtype=float),
             "+x": np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]], dtype=float),
             "-x": np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=float)}
    if frente not in giros:
        raise ValueError(f"--frente={frente}: usar +z, -z, +x o -x")
    if giros[frente] is not None:
        aplicar(giros[frente])


# ------------------------------------------------------------------ ruedas
def _bbox(p):
    a, b = p["pos"].min(0), p["pos"].max(0)
    return a, b, (a + b) / 2, b - a


def _es_rueda_suelta(p, ancho, largo, y_suelo):
    """Malla individual con forma de rueda: dos medidas parecidas (el
    diametro), la tercera menor (la banda), a la altura de su radio sobre
    el suelo, y apartada del eje longitudinal."""
    a, b, c, tam = _bbox(p)
    d = sorted(tam)
    diam, banda = d[2], d[0]
    if not (0.35 <= diam <= 1.3 and banda < 0.6 * diam
            and abs(d[1] - diam) < 0.2 * diam):     # redonda de verdad
        return False
    if abs(tam[0] - diam) < 0.3 * diam and abs(tam[1] - diam) < 0.3 * diam:
        return False                    # redonda vista de frente: no es rueda
    if abs((c[1] - y_suelo) - diam / 2) > 0.35 * diam:
        return False
    return abs(c[0]) > 0.2 * ancho and tam[0] < 0.5 * ancho


def _espejo(p):
    """La misma pieza reflejada en x (izquierda <-> derecha), con el
    sentido de los triangulos invertido para que sigan mirando hacia
    fuera."""
    q = dict(p)
    q["pos"] = p["pos"] * np.array([-1.0, 1.0, 1.0])
    q["nrm"] = p["nrm"] * np.array([-1.0, 1.0, 1.0])
    tri = p["idx"].reshape(-1, 3)[:, ::-1]
    q["idx"] = tri.ravel().astype(np.uint32)
    q["nombre"] = (p.get("nombre") or "") + "_espejo"
    return q


def _recortar(p, mask):
    """Subconjunto de una malla: los triangulos cuyos vertices estan todos
    en mask, reindexados. None si no queda nada."""
    tri = p["idx"].reshape(-1, 3)
    keep = mask[tri].all(axis=1)
    tri = tri[keep]
    if len(tri) == 0:
        return None
    usados = np.unique(tri)
    remap = np.full(len(p["pos"]), -1, dtype=np.int64)
    remap[usados] = np.arange(len(usados))
    q = dict(p)
    q["pos"], q["nrm"], q["uv"] = p["pos"][usados], p["nrm"][usados], p["uv"][usados]
    q["idx"] = remap[tri].ravel().astype(np.uint32)
    return q


def clasificar(piezas, patron_ruedas=None):
    """Lista de (parte, pieza): 0 carroceria, 1..4 ruedas (DI, DD, TI, TD).
    Devuelve tambien el metodo usado."""
    todo = np.concatenate([p["pos"] for p in piezas])
    lo, hi = todo.min(0), todo.max(0)
    ancho, largo, y_suelo = hi[0] - lo[0], hi[2] - lo[2], lo[1]
    zc = (lo[2] + hi[2]) / 2

    def parte_de(c, z_ref):
        frontal = c[2] > z_ref
        return (1 if frontal else 3) + (0 if c[0] < 0 else 1)

    # 1) por nombre (--ruedas) o por forma: ruedas sueltas
    if patron_ruedas:
        rx = re.compile(patron_ruedas, re.I)
        sueltas = [p for p in piezas if rx.search(p["nombre"] or "")]
    else:
        sueltas = [p for p in piezas if _es_rueda_suelta(p, ancho, largo, y_suelo)]
    if len(sueltas) >= 4:
        # una por cuadrante. Las candidatas se agrupan por diametro y se
        # toma el grupo de diametro MAYOR que cubra los cuatro cuadrantes:
        # los tapacubos, tambores de freno y llantas interiores tambien
        # tienen forma de rueda, pero son mas pequenos que el neumatico
        # Se prueba cada grupo de diametro y se elige el que cubre los
        # cuatro cuadrantes con la BATALLA mas larga: las ruedas de verdad
        # estan en los extremos del coche; los pasos de rueda, tapacubos y
        # tambores tambien parecen ruedas pero quedan hacia el centro o son
        # mas pequenos.
        diam = np.array([sorted(_bbox(p)[3])[2] for p in sueltas])
        zs = [_bbox(p)[2][2] for p in sueltas]
        z_ref = (max(zs) + min(zs)) / 2
        mejor, mejor_puntos = {}, -1.0
        for d in sorted(set(np.round(diam, 2)), reverse=True):
            grupo = [i for i in range(len(sueltas)) if abs(diam[i] - d) < 0.15 * d]
            grupo.sort(key=lambda i: -len(sueltas[i]["idx"]))
            prueba = {}
            for i in grupo:
                k = parte_de(_bbox(sueltas[i])[2], z_ref)
                if k not in prueba:
                    prueba[k] = sueltas[i]
            if len(prueba) == 3:
                # falta una (el Bugatti trae tres ruedas sueltas y la cuarta
                # fundida con la aleta): se fabrica en espejo de la del
                # otro lado del mismo eje
                falta = ({1, 2, 3, 4} - set(prueba)).pop()
                gemela = prueba.get(falta + 1 if falta in (1, 3) else falta - 1)
                if gemela is not None:
                    prueba[falta] = _espejo(gemela)
            if len(prueba) == 4:
                z_del = np.mean([_bbox(prueba[k])[2][2] for k in (1, 2)])
                z_tra = np.mean([_bbox(prueba[k])[2][2] for k in (3, 4)])
                puntos = (z_del - z_tra) + 0.1 * d
                if puntos > mejor_puntos:
                    mejor, mejor_puntos = prueba, puntos
        elegidas = mejor
        if len(elegidas) == 4:
            salida = [(0, p) for p in piezas if not any(p is q for q in elegidas.values())]
            salida += [(k, elegidas[k]) for k in sorted(elegidas)]
            return salida, "ruedas sueltas"
    # 2) EJES: las dos ruedas de un eje en una malla (el F1 y el Lamborghini
    #    del mismo autor vienen asi)
    salida = _por_ejes(piezas, ancho, largo, y_suelo, zc)
    if salida is not None:
        return salida, "ejes partidos en izquierda/derecha"
    # 3) una malla con las CUATRO ruedas: casi tan ancha como el coche,
    #    casi tan larga como la batalla, baja, NO la pieza principal (un
    #    autobus de una sola malla cumplia lo demas y salia troceado) y con
    #    los vertices en las cuatro ESQUINAS, no repartidos (un fondo plano
    #    del Lamborghini cumplia las medidas y salia partido en cuartos)
    mayor = max(len(p["idx"]) for p in piezas)
    for p in piezas:
        a, b, c, tam = _bbox(p)
        if (tam[0] > 0.7 * ancho and tam[2] > 0.5 * largo and tam[1] < 0.45 * largo
                and abs((c[1] - y_suelo) - tam[1] / 2) < 0.3 * tam[1]
                and 100 < len(p["idx"]) < mayor):
            m = p["pos"]
            centro_x = np.abs(m[:, 0] - c[0]) < 0.25 * tam[0]
            centro_z = np.abs(m[:, 2] - c[2]) < 0.2 * tam[2]
            if (centro_x | centro_z).mean() > 0.12:
                continue                 # hay vertices en medio: no son ruedas
            cuartos = {}
            for k, mask in ((1, (m[:, 0] < c[0]) & (m[:, 2] >= c[2])),
                            (2, (m[:, 0] >= c[0]) & (m[:, 2] >= c[2])),
                            (3, (m[:, 0] < c[0]) & (m[:, 2] < c[2])),
                            (4, (m[:, 0] >= c[0]) & (m[:, 2] < c[2]))):
                q = _recortar(p, mask)
                if q is not None:
                    cuartos[k] = q
            if len(cuartos) == 4:
                salida = [(0, q) for q in piezas if q is not p]
                salida += [(k, cuartos[k]) for k in sorted(cuartos)]
                return salida, "malla de cuatro ruedas partida en cuartos"
    return [(0, p) for p in piezas], "sin ruedas reconocidas (coche entero)"


def _por_ejes(piezas, ancho, largo, y_suelo, zc):
    """Ejes: mallas casi tan anchas como el coche, redondas vistas de lado,
    cortas, apartadas del centro y a la altura de su radio. Hace falta un
    eje delante y otro detras; cada uno se parte por x. None si no hay."""
    ejes = []
    for p in piezas:
        a, b, c, tam = _bbox(p)
        redonda = abs(tam[1] - tam[2]) < 0.25 * max(tam[1], tam[2])
        if (tam[0] > 0.7 * ancho and redonda and tam[2] < 0.35 * largo
                and abs(c[2] - zc) > 0.15 * largo
                and abs((c[1] - y_suelo) - tam[1] / 2) < 0.3 * tam[1]):
            ejes.append((c[2], p))
    if len(ejes) < 2:
        return None
    delante = max(z for z, _ in ejes)
    detras = min(z for z, _ in ejes)
    if delante - detras < 0.3 * largo:
        return None                      # los dos en el mismo sitio
    salida = []
    for p in piezas:
        z_eje = next((z for z, q in ejes if q is p), None)
        if z_eje is None:
            salida.append((0, p))
            continue
        frontal = abs(z_eje - delante) < abs(z_eje - detras)
        for k, mask in (((1 if frontal else 3), p["pos"][:, 0] < 0),
                        ((2 if frontal else 4), p["pos"][:, 0] >= 0)):
            q = _recortar(p, mask)
            if q is not None:
                salida.append((k, q))
    return salida


def _eje_rueda(pos):
    """Direccion del eje de una rueda: la de MENOR varianza de la banda
    exterior del neumatico (los 10 cm mas alejados del centro del coche),
    que es un disco. Con toda la pieza fallaria: los tirantes y palieres
    que llegan hasta el centro estiran la nube a lo largo del eje."""
    ax = np.abs(pos[:, 0])
    banda = pos[ax >= ax.max() - 0.10]
    if len(banda) < 30:
        banda = pos
    q = banda - banda.mean(0)
    w, v = np.linalg.eigh(np.cov(q.T))
    eje = v[:, 0]
    return eje if eje[0] >= 0 else -eje


def _enderezar_ruedas(partes):
    """Los modelos de exposicion traen a veces las ruedas delanteras GIRADAS
    (el Lamborghini 10 grados, el 2CV 22): al hacerlas rodar sobre el eje x
    del coche se bamboleaban como una rueda doblada, y la direccion del
    juego se sumaba al giro de fabrica. Se gira cada rueda sobre su
    vertical hasta que su eje queda paralelo a x. Devuelve los grados
    corregidos por rueda."""
    giros = {}
    for k in range(1, 5):
        piezas_k = [p for kk, p in partes if kk == k]
        if not piezas_k:
            continue
        # el eje se mide sobre la rueda ENTERA (neumatico, llanta, disco,
        # pinza juntos) y el mismo giro se aplica a todas sus piezas: pieza
        # a pieza, una pinza de freno o un buje sin forma de disco daban
        # angulos absurdos y la rueda salia hecha pedazos
        # el eje se mide en la pieza principal (el neumatico, la que mas
        # triangulos tiene) y se itera: la banda exterior cambia al girar
        # y con una sola pasada quedaban 5-8 grados
        ref = max(piezas_k, key=lambda p: len(p["idx"]))
        if len(ref["pos"]) < 30:
            continue
        todo = np.concatenate([p["pos"] for p in piezas_k])
        c = (todo.min(0) + todo.max(0)) / 2
        total = 0.0
        for _ in range(6):
            eje = _eje_rueda(ref["pos"])
            theta = math.atan2(eje[2], eje[0])
            if abs(theta) < math.radians(0.5) or abs(theta) > math.radians(45.0):
                break
            if total == 0.0 and abs(theta) < math.radians(2.0):
                break                    # recta de fabrica: no tocar
            cs, sn = math.cos(theta), math.sin(theta)
            R = np.array([[cs, 0.0, sn], [0.0, 1.0, 0.0], [-sn, 0.0, cs]])
            for p in piezas_k:
                p["pos"] = (p["pos"] - c) @ R.T + c
                p["nrm"] = p["nrm"] @ R.T
            total += math.degrees(theta)
        if total:
            giros[k] = total
    return giros


# ------------------------------------------------------------- simplificar
def simplificar(p, celda):
    """Agrupa los vertices por celdas de ``celda`` metros (vertex clustering):
    cada celda pasa a ser un vertice (media de posicion y normal, primera
    uv) y se tiran los triangulos degenerados y repetidos."""
    pos = p["pos"]
    clave = np.floor(pos / celda).astype(np.int64)
    _, inv, cnt = np.unique(clave, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    n = len(cnt)
    npos = np.zeros((n, 3))
    np.add.at(npos, inv, pos)
    npos /= cnt[:, None]
    nnrm = np.zeros((n, 3))
    np.add.at(nnrm, inv, p["nrm"])
    nnrm /= np.maximum(np.linalg.norm(nnrm, axis=1), 1e-9)[:, None]
    nuv = np.zeros((n, 2))
    primero = np.full(n, -1)
    orden = np.arange(len(pos))[::-1]
    primero[inv[orden]] = orden           # el primer vertice de cada celda
    nuv[:] = p["uv"][primero]
    tri = inv[p["idx"].reshape(-1, 3)]
    ok = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
    tri = tri[ok]
    if len(tri):
        tri = np.unique(tri, axis=0)          # triangulos repetidos
    q = dict(p)
    q["pos"], q["nrm"], q["uv"] = npos, nnrm, nuv
    q["idx"] = tri.ravel().astype(np.uint32)
    return q


def simplificar_hasta(partes, max_tri, largo):
    total = sum(len(p["idx"]) // 3 for _, p in partes)
    if total <= max_tri:
        return partes, total, 0.0
    celda = largo / 400.0
    while True:
        nuevas = [(k, simplificar(p, celda)) for k, p in partes]
        total = sum(len(p["idx"]) // 3 for _, p in nuevas)
        if total <= max_tri or celda > largo / 20.0:
            return nuevas, total, celda
        celda *= 1.25


# --------------------------------------------------------------- convertir
def convertir(ruta_glb, nombre, frente="+z", arriba="y", escala=None,
              largo=None, quitar=None, ruedas=None, max_tri=150000,
              textura_max=TAM_TEXTURA_MAX, carpeta=None, verbose=False):
    js, binario = leer_glb(ruta_glb)
    piezas = _piezas(js, binario)
    if quitar:
        rx = re.compile(quitar, re.I)
        piezas = [p for p in piezas if not rx.search(p["nombre"] or "")]
    if not piezas:
        raise ValueError("el modelo no tiene mallas de triangulos")
    # CRISTALES: alfa efectivo = factor del material x alfa medio de su
    # textura (en los modelos de Sketchfab la transparencia suele ir en la
    # textura). Se guarda en el color del vertice y el juego pinta esas
    # piezas translucidas al final, con mezcla. Antes se tiraban las de
    # factor < 0,3 (faltaban los pilotos) y el resto salian opacas (los
    # faros, chapas blancas). Solo se descarta lo practicamente invisible.
    blend = {p["tex"] for p in piezas if p.get("modo") == "BLEND" and p["tex"] >= 0}
    alfa_tex = _alfa_texturas(js, binario, sorted(blend)) if blend else {}
    for p in piezas:
        c = list(p["color"][:4]) if len(p["color"]) >= 4 else list(p["color"][:3]) + [1.0]
        if p.get("modo") == "BLEND":
            c[3] *= alfa_tex.get(p["tex"], 1.0)
        else:
            c[3] = 1.0
        p["color"] = tuple(c)
    visibles = [p for p in piezas if p["color"][3] >= 0.05]
    if visibles:
        piezas = visibles
    _orientar(piezas, frente, arriba)
    # escala a metros
    todo = np.concatenate([p["pos"] for p in piezas])
    lo, hi = todo.min(0), todo.max(0)
    if largo:
        escala = float(largo) / float(hi[2] - lo[2])
    if escala and escala != 1.0:
        for p in piezas:
            p["pos"] = p["pos"] * float(escala)
    partes, metodo = clasificar(piezas, ruedas)
    giros = _enderezar_ruedas(partes)
    # centrar en x/z y apoyar en el suelo (con las ruedas, que son lo que
    # toca el asfalto, si se han reconocido)
    todo = np.concatenate([p["pos"] for _, p in partes])
    lo, hi = todo.min(0), todo.max(0)
    con_ruedas = [p for k, p in partes if k > 0]
    y_suelo = (min(p["pos"][:, 1].min() for p in con_ruedas)
               if con_ruedas else lo[1])
    desplazar = np.array([(lo[0] + hi[0]) / 2, y_suelo, (lo[2] + hi[2]) / 2])
    for _, p in partes:
        p["pos"] = p["pos"] - desplazar
    # cada rueda apoya en el suelo POR SU CUENTA: en el Lamborghini las
    # delanteras (mas pequenas) quedaban 2 cm en el aire porque el suelo lo
    # marcaban las traseras
    for k in range(1, 5):
        piezas_k = [p for kk, p in partes if kk == k]
        if piezas_k:
            fondo = min(p["pos"][:, 1].min() for p in piezas_k)
            for p in piezas_k:
                p["pos"] = p["pos"] - np.array([0.0, fondo, 0.0])
    largo_m = float(hi[2] - lo[2])
    partes, n_tri, celda = simplificar_hasta(partes, int(max_tri), largo_m)
    pos, nrm, uv, col, tex, parte, idx = [], [], [], [], [], [], []
    base = 0
    for k, p in partes:
        q = p["pos"]
        if len(q) == 0 or len(p["idx"]) == 0:
            continue
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
    tex_v = np.concatenate(tex)
    centros = np.zeros((5, 3))
    radios = np.zeros(5)
    for k in range(1, 5):
        m = parte_v == k
        if m.any():
            a, b = pos[m].min(0), pos[m].max(0)
            centros[k] = (a + b) / 2
            radios[k] = (b[1] - a[1]) / 2
    if (parte_v == 0).any():
        a, b = pos[parte_v == 0].min(0), pos[parte_v == 0].max(0)
        centros[0] = (a + b) / 2
    usadas = {int(t) for t in np.unique(tex_v) if t >= 0}
    texs = _texturas(js, binario, usadas, int(textura_max))
    datos = dict(pos=pos, nrm=np.concatenate(nrm).astype(np.float32),
                 uv=np.concatenate(uv).astype(np.float32),
                 col=np.concatenate(col), tex=tex_v,
                 parte=parte_v, idx=np.concatenate(idx).astype(np.uint32),
                 centros=centros.astype(np.float32),
                 radios=radios.astype(np.float32),
                 medidas=np.array([hi[0] - lo[0], hi[1] - y_suelo, hi[2] - lo[2]],
                                  dtype=np.float32),
                 n_texturas=np.int32(len(texs)))
    for i, t in enumerate(texs):
        if t is not None:
            datos[f"tex{i}"] = t
    carpeta = carpeta or os.path.join(os.path.dirname(__file__), "..",
                                      "simulator", "models")
    ruta = os.path.join(carpeta, f"{nombre}.npz")
    np.savez_compressed(ruta, **datos)
    datos["metodo_ruedas"] = metodo
    datos["celda"] = celda
    datos["giros_ruedas"] = giros
    return ruta, datos


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    ops = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    if len(args) < 2:
        print(__doc__)
        return 1
    ruta, datos = convertir(
        args[0], args[1], frente=ops.get("frente", "+z"),
        arriba=ops.get("arriba", "y"),
        escala=float(ops["escala"]) if "escala" in ops else None,
        largo=float(ops["largo"]) if "largo" in ops else None,
        quitar=ops.get("quitar"), ruedas=ops.get("ruedas"),
        max_tri=int(ops.get("max_tri", 150000)),
        textura_max=int(ops.get("textura_max", TAM_TEXTURA_MAX)))
    m = datos["medidas"]
    print(f"Guardado {ruta}: {len(datos['idx']) // 3} triangulos, "
          f"{len(datos['pos'])} vertices, {int(datos['n_texturas'])} texturas; "
          f"{m[0]:.2f} x {m[1]:.2f} x {m[2]:.2f} m (ancho x alto x largo)")
    if datos["celda"]:
        print(f"  simplificado con celdas de {datos['celda'] * 100:.1f} cm")
    print(f"  ruedas: {datos['metodo_ruedas']}")
    for k, g in sorted(datos["giros_ruedas"].items()):
        print(f"  rueda {k} venia girada {g:+.1f} grados: enderezada")
    nombres = ("carroceria", "rueda del. izq.", "rueda del. der.",
               "rueda tras. izq.", "rueda tras. der.")
    for k in range(5):
        n = int((datos["parte"] == k).sum())
        if n == 0:
            continue
        c = datos["centros"][k]
        print(f"  {nombres[k]:18s} {n:6d} vertices  centro "
              f"({c[0]:+.2f}, {c[1]:.2f}, {c[2]:+.2f})"
              + (f"  radio {datos['radios'][k]:.2f} m" if k else ""))
    print(f"  tamano del archivo: {os.path.getsize(ruta) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
