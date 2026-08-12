"""Métricas HRV."""

import math

from pipeline import features


def _serie(n=60, base=900.0, alterna=0.0):
    """Serie de n latidos alternando +/- `alterna` ms alrededor de `base`."""
    return [base + (alterna if i % 2 else -alterna) for i in range(n)]


def test_serie_constante_no_tiene_variabilidad():
    f = features.time_domain([900.0] * 60)
    assert f is not None
    assert f["mean_nn"] == 900.0
    assert f["mean_hr"] == 60000.0 / 900.0
    assert f["sdnn"] == 0.0
    assert f["rmssd"] == 0.0
    assert f["pnn50"] == 0.0


def test_rmssd_de_una_alternancia_conocida():
    # Alternando +/-10 ms, cada diferencia consecutiva vale 20 ms, así
    # que el RMSSD tiene que ser exactamente 20.
    f = features.time_domain(_serie(60, 900.0, 10.0))
    assert f is not None
    assert abs(f["rmssd"] - 20.0) < 1e-9
    assert abs(f["sdnn"] - 10.0) < 1e-9
    assert f["pnn50"] == 0.0          # 20 ms no supera el umbral de 50


def test_pnn50_cuenta_las_diferencias_grandes():
    # Alternando +/-30 ms: cada diferencia vale 60 ms, todas > 50.
    f = features.time_domain(_serie(60, 900.0, 30.0))
    assert f is not None
    assert f["pnn50"] == 1.0


def test_log_rmssd_es_coherente():
    f = features.time_domain(_serie(60, 900.0, 10.0))
    assert abs(f["log_rmssd"] - math.log(20.0)) < 1e-9


def test_pocos_latidos_devuelve_none():
    assert features.time_domain([900.0] * 5) is None


def test_demasiados_artefactos_devuelve_none():
    # Una de cada tres muestras es basura: por encima del 15 % tolerado.
    serie = []
    for i in range(90):
        serie.append(50.0 if i % 3 == 0 else 900.0)
    assert features.time_domain(serie) is None


def test_poincare_sd1_equivale_a_rmssd():
    # SD1 = SDSD / raíz de 2, y SDSD coincide con el RMSSD solo si la
    # media de las diferencias es cero. Con un número impar de
    # diferencias no lo es exactamente, de ahí la tolerancia relativa.
    serie = _serie(80, 900.0, 12.0)
    f = features.time_domain(serie)
    p = features.poincare(serie)
    esperado = f["rmssd"] / math.sqrt(2.0)
    assert abs(p["sd1"] - esperado) / esperado < 1e-3


def test_angulo_entre_vectores():
    assert abs(features._angle_between((0, 1000, 0), (0, 1000, 0))) < 1e-6
    assert abs(features._angle_between((1000, 0, 0), (0, 1000, 0)) - 90.0) < 1e-6


def test_movimiento_detecta_cambio_de_postura():
    from pipeline.session import Sample

    # Primero tumbado (gravedad en y), luego de pie (gravedad en z).
    tumbado = [Sample(t=i, act=5, ax=0, ay=1000, az=0) for i in range(30)]
    de_pie = [Sample(t=30 + i, act=5, ax=0, ay=0, az=1000) for i in range(30)]
    m = features.movement(tumbado + de_pie)
    assert m["posture_change"] > 80.0

    quieto = features.movement(tumbado)
    assert quieto["posture_change"] < 5.0
