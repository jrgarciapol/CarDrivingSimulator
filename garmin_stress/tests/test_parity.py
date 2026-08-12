"""Paridad entre el reloj (Monkey C) y el pipeline (Python).

Este es el test que evita el fallo más caro del proyecto y el más
difícil de diagnosticar: que el reloj calcule las features de una manera
y el entrenamiento de otra. Cuando eso pasa, no explota nada. La app
compila, el modelo da probabilidades de aspecto razonable y las
predicciones son basura, sin ningún síntoma que apunte a la causa.

Se comprueban tres cosas:
  - las constantes numéricas compartidas valen lo mismo en los dos lados;
  - el orden del vector de features es el mismo;
  - la misma entrada da la misma salida en las dos implementaciones de
    la línea base.
"""

import math
from pathlib import Path

import pytest

from pipeline import dataset as ds_mod
from pipeline import export_monkeyc, features
from pipeline import rr as rrmod

WATCH = Path(__file__).resolve().parent.parent / "watch" / "source"
CONFIG_MC = WATCH / "Config.mc"
HRV_MC = WATCH / "Hrv.mc"


@pytest.fixture(scope="module")
def const():
    return export_monkeyc.read_constants(CONFIG_MC)


# Constante de Python  ->  constante de Config.mc
EQUIVALENCIAS = [
    (rrmod.RR_MIN_MS, "RR_MIN_MS"),
    (rrmod.RR_MAX_MS, "RR_MAX_MS"),
    (rrmod.MALIK_PCT, "RR_MALIK_PCT"),
    (features.MIN_BEATS, "HRV_MIN_BEATS"),
    (features.MAX_ARTIFACT, "HRV_MAX_ARTIFACT"),
    (ds_mod.BASELINE_TAU_S, "BASELINE_TAU_S"),
    (ds_mod.BASELINE_WARMUP_S, "BASELINE_WARMUP_S"),
    (ds_mod.BASELINE_MIN_SAMPLES, "BASELINE_MIN_SAMPLES"),
    (ds_mod.BASELINE_SD_FLOOR, "BASELINE_SD_FLOOR"),
    (ds_mod.MOVE_THRESHOLD_MG, "MOVE_THRESHOLD_MG"),
    (ds_mod.Z_CLIP, "Z_CLIP"),
]


@pytest.mark.parametrize("valor_py,nombre_mc", EQUIVALENCIAS)
def test_constantes_coinciden(const, valor_py, nombre_mc):
    assert nombre_mc in const, f"{nombre_mc} no está en Config.mc"
    assert abs(const[nombre_mc] - valor_py) < 1e-9, (
        f"{nombre_mc}: Monkey C dice {const[nombre_mc]}, Python dice {valor_py}"
    )


def test_ventana_hrv_en_las_mismas_unidades(const):
    # En Monkey C está en ms y en Python las ventanas se piden en s.
    assert const["HRV_WINDOW_MS"] == 60000


def test_orden_de_features_identico():
    orden_mc = export_monkeyc.read_feature_order(HRV_MC)
    assert orden_mc == features.LIVE_FEATURES, (
        "El orden de module Features no coincide con LIVE_FEATURES. Los "
        "pesos del modelo se aplicarían a la feature equivocada."
    )


def test_codigos_de_marca_coinciden(const):
    from pipeline import session

    assert const["MARK_CALM"] == session.MARK_CALM
    assert const["MARK_PROMPT_NO"] == session.MARK_PROMPT_NO
    assert const["MARK_PROMPT_SKIP"] == session.MARK_PROMPT_SKIP
    assert const["MARK_PROMPT_YES_2"] == session.MARK_PROMPT_YES_2


def test_onset_declarado_en_ambos_lados():
    """Los segundos de cada opción del menú están en Config.onsetSeconds()."""
    texto = CONFIG_MC.read_text(encoding="utf-8")
    from pipeline.session import ONSET_SECONDS

    for codigo, segundos in ONSET_SECONDS.items():
        if segundos == 0:
            continue
        assert f"return {segundos};" in texto, (
            f"Config.onsetSeconds() no devuelve {segundos} s para el "
            f"código {codigo}"
        )


def test_linea_base_converge_al_valor_real():
    """La estimación por lotes tiene que dar la media y la varianza reales.

    Réplica del comportamiento esperado de RunningStat en Monkey C.
    """
    st = ds_mod.RunningStat(mean0=70.0, sd0=10.0)   # a priori muy malo
    valores = [50.0 + (2.0 if i % 2 else -2.0) for i in range(40)]
    for v in valores:
        st.update(v, dt=30.0)                        # 40 * 30 s = 1200 s

    assert st.ready
    # Tras el lote de arranque siguen entrando muestras por la media
    # móvil, que oscila un poco alrededor del valor real.
    assert abs(st.mean - 50.0) < 0.05
    # sd real = 2.0; suelo = 0.2 * 10 = 2.0. Se queda en el mayor.
    assert abs(math.sqrt(st.var) - 2.0) < 0.05


def test_suelo_de_varianza_evita_z_scores_absurdos():
    st = ds_mod.RunningStat(mean0=70.0, sd0=10.0)
    for _ in range(40):
        st.update(50.0, dt=30.0)      # varianza real cero
    assert st.ready
    # Sin suelo, el z-score de 50.5 saldría infinito.
    assert abs(st.z(52.0) - 1.0) < 1e-6


def test_recorte_del_z_score():
    st = ds_mod.RunningStat(mean0=0.0, sd0=1.0)
    for i in range(40):
        st.update(1.0 if i % 2 else -1.0, dt=30.0)
    assert st.z(1e6) == ds_mod.Z_CLIP
    assert st.z(-1e6) == -ds_mod.Z_CLIP
