"""Pruebas del REGISTRO DE RENDIMIENTO (simulator/perf_log.py, tecla F3).

Con un reloj simulado se comprueba que:

  - inactivo no escribe nada ni cuesta nada,
  - cada segundo sale una fila del CSV con las fases y la configuracion,
  - un cambio de configuracion (activar la telemetria) abre un bloque nuevo
    y cierra la fila en curso, sin mezclar las dos situaciones,
  - el resumen dice que cambio ("TELEMETRIA F2 SI") y cuanto costo,
  - el 'trabajo' descuenta la espera de presentar (vsync),
  - los percentiles se calculan bien sin numpy.

    python tests/test_registro.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import perf_log                    # noqa: E402


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return bool(cond)


class Reloj:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class GpuFalsa:
    ms_malla, ms_gl, ms_lectura, ms_subida = 1.0, 2.0, 0.7, 0.5
    info = {"GL_RENDERER": "Tarjeta de prueba", "GL_VERSION": "4.5"}


def ctx(**cambios):
    base = perf_log.contexto(GpuFalsa(), 0, False, False, True, True, True,
                             1.0, "DEPORTIVO", "SPA", "SECO")
    base.update(cambios)
    return base


def fotograma(reg, reloj, ctx_, fases, gpu=None, v=50.0):
    """Simula un fotograma con las duraciones (ms) dadas por fase."""
    reg.inicio()
    for fase, ms in fases.items():
        reloj.t += ms / 1000.0
        reg.marca(fase)
    reg.fotograma(ctx_, gpu, v)


def main():
    r = []
    carpeta = tempfile.mkdtemp(prefix="registro_")
    try:
        reloj = Reloj()
        reg = perf_log.RegistroRendimiento(carpeta, reloj)
        reg.describir_equipo("opengl", GpuFalsa())

        # --- inactivo: nada ------------------------------------------------
        fotograma(reg, reloj, ctx(), {"escena": 5.0, "presentar": 10.0})
        r.append(check("inactivo no escribe archivos",
                       not os.listdir(carpeta)))
        r.append(check("inactivo no acumula nada", reg._bloques == []))

        # --- grabando: bloque 1, fotogramas de 4 ms de trabajo + 12 de espera
        reg.arrancar()
        r.append(check("al arrancar crea el CSV",
                       os.path.exists(reg.ruta_csv)))
        for _ in range(150):                     # 150 x 16 ms = 2,4 s
            fotograma(reg, reloj, ctx(),
                      {"entrada": 0.1, "fisica": 0.9, "sonido": 0.3,
                       "escena": 2.0, "coche": 0.2, "hud": 0.5,
                       "presentar": 12.0}, GpuFalsa())
        with open(reg.ruta_csv, encoding="utf-8") as f:
            filas = [x.strip().split(";") for x in f if x.strip()]
        cab, datos = filas[0], filas[1:]
        r.append(check("una fila por segundo (2,4 s -> 2 filas)",
                       len(datos) == 2, f"{len(datos)} filas"))
        col = {k: i for i, k in enumerate(cab)}
        f0 = datos[0]
        r.append(check("la fila lleva la media del fotograma (16 ms)",
                       abs(float(f0[col["ms_media"]]) - 16.0) < 0.05,
                       f0[col["ms_media"]]))
        r.append(check("...y el TRABAJO descuenta la espera de presentar (4 ms)",
                       abs(float(f0[col["ms_trabajo"]]) - 4.0) < 0.05,
                       f0[col["ms_trabajo"]]))
        r.append(check("...y los fps que salen de esa media (62,5)",
                       abs(float(f0[col["fps"]]) - 62.5) < 0.2,
                       f0[col["fps"]]))
        r.append(check("...y los tiempos de la GPU",
                       f0[col["ms_gpu_gl"]] == "2.00", f0[col["ms_gpu_gl"]]))
        r.append(check("...y la configuracion de pantalla",
                       f0[col["telemetria"]] == "NO"
                       and f0[col["vista"]] == "INTERIOR"
                       and f0[col["coche"]] == "DEPORTIVO"
                       and f0[col["aguja"]] in ("SI", "NO")))
        r.append(check("...y la velocidad media",
                       f0[col["velocidad_kmh"]] == "50"))

        # --- cambio de configuracion: telemetria, mas cara ------------------
        n_antes = len(datos)
        for _ in range(100):
            fotograma(reg, reloj, ctx(telemetria="SI"),
                      {"entrada": 0.1, "fisica": 0.9, "sonido": 0.3,
                       "escena": 2.0, "coche": 0.2, "hud": 3.5,
                       "presentar": 9.0}, GpuFalsa())
        r.append(check("el cambio de configuracion abre un bloque nuevo",
                       len(reg._bloques) == 2))
        with open(reg.ruta_csv, encoding="utf-8") as f:
            filas = [x.strip().split(";") for x in f if x.strip()][1:]
        # la fila en curso del bloque 1 se cerro al cambiar: ninguna fila
        # mezcla telemetria SI y NO
        mezcla = False
        for fila in filas:
            trabajo = float(fila[col["ms_trabajo"]])
            if fila[col["telemetria"]] == "NO" and trabajo > 4.1:
                mezcla = True
            if fila[col["telemetria"]] == "SI" and trabajo < 6.9:
                mezcla = True
        r.append(check("ninguna fila mezcla las dos configuraciones",
                       not mezcla and len(filas) > n_antes,
                       f"{len(filas)} filas"))

        # --- resumen ---------------------------------------------------------
        reg.parar()
        r.append(check("al parar escribe el resumen",
                       os.path.exists(reg.ruta_txt)))
        with open(reg.ruta_txt, encoding="utf-8") as f:
            txt = f.read()
        r.append(check("el resumen describe el equipo",
                       "Tarjeta de prueba" in txt and "opengl" in txt))
        r.append(check("...lista la configuracion de partida",
                       "CONFIGURACION DE PARTIDA" in txt
                       and "CIRCUITO           SPA" in txt))
        lineas = [x for x in txt.splitlines() if x.strip().startswith(("1 ", "2 "))]
        r.append(check("...tiene una linea por bloque", len(lineas) == 2))
        r.append(check("...y dice que cambio en el bloque 2",
                       "TELEMETRIA F2 SI" in lineas[1]
                       and "(igual que el bloque 1)" in lineas[0]))
        # el trabajo del bloque 2 es 7 ms frente a 4: se lee en la tabla
        campos1 = lineas[0].split("|")[0].split()
        campos2 = lineas[1].split("|")[0].split()
        r.append(check("...con el coste de cada uno (trabajo 4 -> 7 ms)",
                       abs(float(campos1[6]) - 4.0) < 0.05
                       and abs(float(campos2[6]) - 7.0) < 0.05,
                       f"{campos1[6]} -> {campos2[6]}"))
        r.append(check("tras parar, las llamadas no hacen nada",
                       reg.alternar() is True and reg.activo))
        reg.parar()
        r.append(check("alternar arranca un registro NUEVO (otro archivo)",
                       len([x for x in os.listdir(carpeta)
                            if x.endswith(".csv")]) == 2))

        # --- F3 a mitad de fotograma: la primera fase no cuenta el pasado ---
        # (en el primer registro real salio un fotograma de 794 segundos)
        reg3 = perf_log.RegistroRendimiento(carpeta, reloj)
        reloj.t += 3600.0                        # una hora sin grabar
        reg3.arrancar()                          # pulsado en la fase de entrada
        reloj.t += 0.005
        reg3.marca("entrada")
        reloj.t += 0.010
        reg3.marca("presentar")
        reg3.fotograma(ctx(), GpuFalsa())
        b = reg3._bloques[0]
        r.append(check("al arrancar a mitad de fotograma la 'entrada' mide "
                       "solo desde F3 (5 ms, no 3600 s)",
                       abs(b.fases["entrada"] - 5.0) < 0.01
                       and abs(b.total[0] - 15.0) < 0.01,
                       f"entrada={b.fases['entrada']:.2f} ms"))
        r.append(check("la lectura de la GPU tiene su columna",
                       b.gpu["lectura"] == 0.7))
        reg3.parar()

        # --- percentiles sin numpy ------------------------------------------
        r.append(check("percentil 50 de 1..10 = 5,5",
                       abs(perf_log._p(list(range(1, 11)), 50) - 5.5) < 1e-9))
        r.append(check("percentil 95 de 1..100 = 95,05",
                       abs(perf_log._p(list(range(1, 101)), 95) - 95.05) < 1e-9))
        r.append(check("percentil de lista vacia = 0", perf_log._p([], 95) == 0.0))
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
