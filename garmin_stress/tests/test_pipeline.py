"""Ciclo completo sobre datos sintéticos: sintetizar, etiquetar, entrenar,
exportar y volver a leer.

Aquí no se comprueba que el modelo sea bueno — eso solo lo dirán tus
datos reales — sino que la cadena no pierde ni tuerce nada por el
camino.
"""

import re

import pytest

from pipeline import dataset as ds_mod
from pipeline import export_monkeyc, fitio, synth
from pipeline import train as train_mod


@pytest.fixture(scope="module")
def sesiones():
    return synth.make_days(n_days=4, seed=7, hours=3.0)


@pytest.fixture(scope="module")
def datos(sesiones):
    return ds_mod.build(sesiones)


def test_el_sintetico_tiene_marcas_y_latidos(sesiones):
    for s in sesiones:
        assert s.n_beats > 3000               # ~3 h a ~60 ppm
        marcas = s.markers()
        assert len(marcas) >= 3
        assert any(m.is_stress for m in marcas)
        assert any(m.is_negative for m in marcas)


def test_no_se_pierden_marcas_al_deduplicar(sesiones):
    """Con 6 episodios y un 80 % de probabilidad de marcar, salen ~5.

    Este test existe porque llegaron a salir cero: las marcas se sellaban
    en el orden en que se generaban, no en orden cronológico, y el
    relleno del número de secuencia borraba las posteriores.
    """
    for s in sesiones:
        marcadas = sum(1 for m in s.markers() if m.is_stress)
        assert marcadas >= 3, f"solo {marcadas} marcas de estrés en {s.source}"


def test_el_conjunto_tiene_las_dos_clases(datos):
    c = datos.counts()
    assert c["pos"] > 20
    assert c["neg"] > 100
    assert c["dias"] == 4
    assert len(datos.feature_names) == 5


def test_ida_y_vuelta_por_csv(sesiones, tmp_path):
    origen = sesiones[0]
    ruta = tmp_path / "s.csv"
    fitio.write_csv(origen, ruta)
    vuelta = fitio.load(ruta)

    assert len(vuelta.samples) == len(origen.samples)
    assert vuelta.n_beats == origen.n_beats
    assert len(vuelta.markers()) == len(origen.markers())
    for a, b in zip(origen.markers(), vuelta.markers()):
        assert (a.code, a.onset_s) == (b.code, b.onset_s)


def test_entrena_y_supera_al_azar(datos):
    modelo = train_mod.train(datos, verbose=False)
    m = modelo.metrics
    # El listón: mejor que la proporción de positivos, que es lo que
    # sacaría un clasificador que responde al azar.
    assert m["pr_auc"] > m["pr_auc_base"] * 1.5
    assert m["roc_auc"] > 0.6
    assert len(modelo.w) == 5
    assert 0.0 < modelo.p_alert < 1.0


def test_la_fisiologia_va_en_la_direccion_correcta(datos):
    """Cada feature POR SEPARADO tiene que comportarse como la teoría dice.

    Con estrés bajan la variabilidad (log_rmssd, pnn50) y sube la
    frecuencia. Los coeficientes multivariantes pueden salir con otro
    signo por acoplamiento entre features, pero esto no.
    """
    modelo = train_mod.train(datos, verbose=False)
    uni = modelo.metrics["univariante"]
    assert uni["z_log_rmssd"] < 0.45, "el estrés debería bajar el RMSSD"
    assert uni["z_pnn50"] < 0.45, "el estrés debería bajar el pNN50"
    assert uni["z_mean_hr"] > 0.55, "el estrés debería subir la frecuencia"
    assert uni["act"] < 0.45, "los positivos son en reposo, no moviéndose"


def test_el_presupuesto_de_falsas_alarmas_se_respeta(datos):
    modelo = train_mod.train(datos, max_false_alarms=2.0, verbose=False)
    assert modelo.metrics["falsas_alarmas_dia"] <= 2.0


def test_exporta_monkeyc_valido(datos, tmp_path):
    modelo = train_mod.train(datos, verbose=False)
    texto = export_monkeyc.render(modelo)

    assert "module ModelParams {" in texto
    assert "const TRAINED = true;" in texto
    assert texto.count("const ") >= 8
    assert texto.rstrip().endswith("}")

    # Los arrays tienen que tener exactamente cinco elementos.
    for nombre in ("W", "USE_Z", "MU0", "SD0"):
        m = re.search(rf"const {nombre} = \[(.*?)\];", texto)
        assert m, f"falta el array {nombre}"
        assert len(m.group(1).split(",")) == 5

    ruta = tmp_path / "ModelParams.mc"
    export_monkeyc.export(modelo, ruta)
    leidas = export_monkeyc.read_constants(ruta)
    assert leidas["TRAINED"] is True
    assert abs(leidas["P_ALERT"] - modelo.p_alert) < 1e-4


def test_el_exportador_rechaza_un_orden_equivocado(datos):
    modelo = train_mod.train(datos, verbose=False)
    modelo.feature_names = list(reversed(modelo.feature_names))
    with pytest.raises(ValueError, match="orden"):
        export_monkeyc.render(modelo)


def test_guardar_y_cargar_el_modelo(datos, tmp_path):
    modelo = train_mod.train(datos, verbose=False)
    ruta = tmp_path / "model.json"
    modelo.save(ruta)
    vuelta = train_mod.Model.load(ruta)

    assert vuelta.w == modelo.w
    assert vuelta.b0 == modelo.b0
    fila = [0.5, -0.5, -1.0, -1.0, -0.5]
    assert abs(vuelta.predict_proba(fila) - modelo.predict_proba(fila)) < 1e-12


def test_la_probabilidad_replica_a_sklearn(datos):
    """El cálculo que hará el reloj tiene que dar lo mismo que sklearn.

    Model.predict_proba es la misma aritmética que Detector.mc, escrita
    a mano. Si se desviara de sklearn, el reloj estaría ejecutando un
    modelo distinto del que se validó.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    X = np.asarray(datos.X)
    y = np.asarray(datos.y)
    clf = LogisticRegression(max_iter=2000, class_weight="balanced")
    clf.fit(X, y, sample_weight=np.asarray(datos.weights))

    modelo = train_mod.Model(
        feature_names=list(datos.feature_names),
        w=[float(v) for v in clf.coef_[0]],
        b0=float(clf.intercept_[0]),
    )
    esperado = clf.predict_proba(X[:200])[:, 1]
    for fila, p in zip(X[:200], esperado):
        assert abs(modelo.predict_proba(list(fila)) - p) < 1e-9
