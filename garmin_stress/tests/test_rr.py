"""Limpieza de artefactos."""

from pipeline import rr


def test_serie_limpia_pasa_entera():
    serie = [900, 905, 898, 902, 899]
    c = rr.clean(serie)
    assert c.n_valid == 5
    assert len(c.diffs) == 4
    assert c.artifact_fraction == 0.0


def test_descarta_fuera_de_rango():
    c = rr.clean([900, 120, 900, 5000, 900])
    assert c.n_valid == 3
    assert c.artifact_fraction == 0.4


def test_malik_descarta_el_salto():
    # 900 -> 1200 es un salto del 33 %, por encima del 20 % permitido.
    c = rr.clean([900, 900, 1200, 900, 900])
    assert 1200 not in c.nn
    assert c.n_valid == 4


def test_el_latido_perdido_no_genera_diferencia_falsa():
    """El punto clave de todo el módulo.

    Si se descarta un latido, la diferencia entre el anterior y el
    siguiente NO es una diferencia entre latidos consecutivos y no debe
    entrar en el RMSSD.
    """
    c = rr.clean([800, 800, 1600, 800, 800])   # el 1600 es un latido perdido
    assert 1600 not in c.nn
    assert c.n_valid == 4
    # Diferencias válidas: solo (800,800) al principio y (800,800) al
    # final. La que cruza el hueco no cuenta.
    assert len(c.diffs) == 2
    assert all(d == 0 for d in c.diffs)


def test_la_comparacion_es_contra_el_ultimo_valido():
    # Tras descartar el 1400, el 860 se compara con 900, no con 1400.
    c = rr.clean([900, 1400, 860])
    assert c.nn == [900.0, 860.0]
    # 900 y 860 no son adyacentes: entre medias había un latido malo.
    assert c.diffs == []


def test_serie_vacia():
    c = rr.clean([])
    assert c.n_valid == 0
    assert c.artifact_fraction == 1.0


def test_ignora_none():
    c = rr.clean([900, None, 900])
    assert c.n_valid == 2
    assert c.n_total == 2
