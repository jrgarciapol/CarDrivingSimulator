"""Etiquetado: la corrección de latencia es lo que se comprueba aquí."""

from pipeline import labels
from pipeline.session import Sample, Session


def _sesion_con_marca(marca_en_s, code=2, onset=1, total=1800, t0=1000.0):
    s = Session(samples=[
        Sample(t=t0 + i, rr=[900], act=5, ax=0, ay=980, az=0)
        for i in range(total)
    ])
    for i in range(marca_en_s, marca_en_s + 3):
        s.samples[i].mark, s.samples[i].mark_seq, s.samples[i].onset = code, 1, onset
    for i in range(marca_en_s + 3, total):
        s.samples[i].mark_seq = 1
    return s


def _etiqueta_en(etiquetadas, t0_relativo, base=1000.0):
    for e in etiquetadas:
        if abs(e.window.t0 - (base + t0_relativo)) < 1e-6:
            return e
    raise AssertionError(f"no hay ventana que empiece en +{t0_relativo}")


def test_la_ventana_del_boton_no_se_etiqueta_como_estres():
    """Los segundos justo anteriores a la pulsación quedan fuera.

    Ahí está el gesto de levantar el brazo, y si entrase el modelo
    acabaría aprendiendo a detectar pulsaciones de botón.
    """
    s = _sesion_con_marca(900, onset=0)     # marca en +900, "justo ahora"
    ventanas = list(s.windows(60.0, 15.0))
    etiquetadas = labels.label_windows(s, ventanas)

    # Ventana [+855, +915]: contiene la pulsación (+900). Con onset=0 el
    # intervalo positivo es [+840, +885], que solapa 30 s de 60: menos
    # del mínimo, así que no es positiva.
    e = _etiqueta_en(etiquetadas, 855)
    assert e.label != 1


def test_se_etiqueta_hacia_atras_desde_el_inicio_declarado():
    # Marca en +900 diciendo "empezó hace ~3 min" (onset=2 -> 180 s).
    # Intervalo positivo: [900-180-60, 900-15] = [+660, +885].
    s = _sesion_con_marca(900, onset=2)
    etiquetadas = labels.label_windows(s, list(s.windows(60.0, 15.0)))

    assert _etiqueta_en(etiquetadas, 720).label == 1     # dentro
    assert _etiqueta_en(etiquetadas, 810).label == 1     # dentro
    assert _etiqueta_en(etiquetadas, 300).label != 1     # muy anterior


def test_zona_gris_no_es_negativa():
    s = _sesion_con_marca(900, onset=0)
    etiquetadas = labels.label_windows(s, list(s.windows(60.0, 15.0)))
    # A dos minutos de la marca: ni positivo ni negativo.
    e = _etiqueta_en(etiquetadas, 1020)
    assert e.label is None
    assert e.reason in ("zona gris", "solape parcial")


def test_lejos_de_toda_marca_es_negativo_debil():
    s = _sesion_con_marca(900, onset=0)
    etiquetadas = labels.label_windows(s, list(s.windows(60.0, 15.0)))
    e = _etiqueta_en(etiquetadas, 60)      # a 14 min de la marca
    assert e.label == 0
    assert e.weight < 1.0
    assert e.reason == "sin marca"


def test_calma_declarada_pesa_mas_que_el_silencio():
    s = _sesion_con_marca(900, code=4, onset=0)   # MARK_CALM
    etiquetadas = labels.label_windows(s, list(s.windows(60.0, 15.0)))
    e = _etiqueta_en(etiquetadas, 855)
    assert e.label == 0
    assert e.weight == 1.0
    assert e.reason == "calma declarada"


def test_pregunta_sin_respuesta_solo_crea_zona_gris():
    s = _sesion_con_marca(900, code=19, onset=0)  # MARK_PROMPT_SKIP
    etiquetadas = labels.label_windows(s, list(s.windows(60.0, 15.0)))
    assert _etiqueta_en(etiquetadas, 870).label is None
    assert not any(e.label == 1 for e in etiquetadas)


def test_resumen_cuadra():
    s = _sesion_con_marca(900, onset=2)
    etiquetadas = labels.label_windows(s, list(s.windows(60.0, 15.0)))
    r = labels.summary(etiquetadas)
    assert r["total"] == len(etiquetadas)
    assert r["pos"] + r["neg"] + r["excluidas"] == r["total"]
    assert r["pos"] > 0
