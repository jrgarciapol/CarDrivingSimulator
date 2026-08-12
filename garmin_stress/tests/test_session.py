"""Modelo de sesión: deduplicación de marcas, tiempos de latido, ventanas."""

from pipeline.session import Sample, Session


def _sesion(n=600, rr_por_segundo=1, t0=1000.0):
    return Session(samples=[
        Sample(t=t0 + i, rr=[900] * rr_por_segundo, act=5, ax=0, ay=980, az=0)
        for i in range(n)
    ])


def test_marca_pegada_cuenta_como_un_solo_evento():
    """El reloj deja la marca puesta 3 segundos; son un evento, no tres."""
    s = _sesion(60)
    for i in (10, 11, 12):
        s.samples[i].mark = 2
        s.samples[i].mark_seq = 1
        s.samples[i].onset = 1
    for i in range(13, 60):
        s.samples[i].mark_seq = 1

    marcas = s.markers()
    assert len(marcas) == 1
    assert marcas[0].code == 2
    assert marcas[0].level == 2
    assert marcas[0].onset_s == 60
    assert marcas[0].t == s.samples[10].t


def test_dos_marcas_iguales_seguidas_se_distinguen_por_secuencia():
    s = _sesion(120)
    for i in (10, 11):
        s.samples[i].mark, s.samples[i].mark_seq = 2, 1
    for i in range(12, 40):
        s.samples[i].mark_seq = 1
    for i in (40, 41):
        s.samples[i].mark, s.samples[i].mark_seq = 2, 2
    for i in range(42, 120):
        s.samples[i].mark_seq = 2

    assert len(s.markers()) == 2


def test_codigos_de_respuesta_a_pregunta():
    s = _sesion(60)
    s.samples[10].mark, s.samples[10].mark_seq = 12, 1   # sí, nivel 2
    for i in range(11, 60):
        s.samples[i].mark_seq = 1
    m = s.markers()[0]
    assert m.is_prompt_reply
    assert m.level == 2
    assert m.is_stress

    s2 = _sesion(60)
    s2.samples[10].mark, s2.samples[10].mark_seq = 15, 1  # no
    for i in range(11, 60):
        s2.samples[i].mark_seq = 1
    m2 = s2.markers()[0]
    assert m2.is_prompt_reply
    assert m2.level == 0
    assert m2.is_negative


def test_tiempos_de_latido_van_hacia_atras_dentro_del_segundo():
    s = Session(samples=[Sample(t=1000.0, rr=[400, 400])])
    tiempos = s.beat_times()
    assert len(tiempos) == 2
    # El último termina en t; el anterior, 400 ms antes.
    assert tiempos[1][0] == 1000.0
    assert abs(tiempos[0][0] - 999.6) < 1e-9


def test_ventanas_cubren_la_sesion_con_el_salto_pedido():
    s = _sesion(300)
    ventanas = list(s.windows(win_s=60.0, hop_s=15.0))
    assert len(ventanas) >= 15
    assert ventanas[1].t0 - ventanas[0].t0 == 15.0
    assert all(w.t1 - w.t0 == 60.0 for w in ventanas)
    # Una ventana de 60 s a un latido por segundo lleva ~60 latidos.
    assert 55 <= len(ventanas[0].rr) <= 61


def test_dia_agrupa_por_fecha():
    a = _sesion(10, t0=1_760_000_000.0)
    b = _sesion(10, t0=1_760_000_000.0 + 86400)
    assert a.day() != b.day()
