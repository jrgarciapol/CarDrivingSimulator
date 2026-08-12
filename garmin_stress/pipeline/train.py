"""Entrenamiento y evaluación honesta del modelo.

Tres decisiones que condicionan todo lo demás:

1. NADA de train_test_split aleatorio. Las ventanas se solapan y van
   seguidas en el tiempo: la ventana de las 10:00:15 y la de las
   10:00:30 comparten 45 de sus 60 segundos. Repartirlas al azar mete
   casi la misma ventana a los dos lados y da un AUC de 0,97 que no
   significa absolutamente nada. Se valida DEJANDO UN DÍA FUERA
   (LeaveOneGroupOut por día), que además es la pregunta que de verdad
   nos interesa: ¿funcionará mañana?

2. La métrica es PR-AUC, no accuracy ni ROC-AUC. Los episodios de
   estrés agudo son el 2-5 % del día. Un modelo que diga siempre "no hay
   estrés" acierta el 96 % de las veces; la accuracy es inútil aquí, y
   el ROC-AUC es demasiado optimista con clases tan desbalanceadas.

3. El umbral no se elige en 0,5. Se elige por PRESUPUESTO DE FALSAS
   ALARMAS: cuántas interrupciones al día estás dispuesto a aguantar.
   Un modelo que te pregunta veinte veces al día es un modelo que vas a
   desinstalar el jueves, por bueno que sea su AUC.

Modelo por defecto: regresión logística regularizada. No es por
conservadurismo:
  - con 100-300 ejemplos positivos, cualquier cosa con más capacidad
    memoriza;
  - da probabilidades calibradas, que es lo que hace falta para elegir
    umbral por presupuesto de alarmas;
  - se exporta al reloj como siete multiplicaciones y una suma;
  - los coeficientes se leen: si sale que el estrés correlaciona con
    RMSSD ALTO, hay un error en los datos y lo vas a ver.

Se entrena también un gradient boosting como techo de referencia. Si le
saca mucha ventaja a la logística, la respuesta correcta no es desplegar
el boosting: es mirar qué está capturando y añadir esa feature.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import dataset as ds_mod
from . import features as feat

# Presupuesto por defecto de falsas alarmas al día.
MAX_FALSE_ALARMS_PER_DAY = 4.0

# Dos avisos separados por menos de esto son el mismo aviso.
ALARM_REFRACTORY_S = 600.0


@dataclass
class Model:
    version: int = 1
    feature_names: list[str] = field(default_factory=list)
    w: list[float] = field(default_factory=list)
    b0: float = 0.0
    use_z: list[bool] = field(default_factory=list)
    mu0: list[float] = field(default_factory=list)
    sd0: list[float] = field(default_factory=list)
    p_alert: float = 0.8
    p_unc_lo: float = 0.35
    p_unc_hi: float = 0.65
    metrics: dict = field(default_factory=dict)

    def predict_proba(self, row: list[float]) -> float:
        z = self.b0 + sum(wi * xi for wi, xi in zip(self.w, row))
        if z > 30:
            return 1.0
        if z < -30:
            return 0.0
        return 1.0 / (1.0 + math.exp(-z))

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @staticmethod
    def load(path) -> "Model":
        return Model(**json.loads(Path(path).read_text(encoding="utf-8")))


def train(data: ds_mod.Dataset, max_false_alarms: float = MAX_FALSE_ALARMS_PER_DAY,
          verbose: bool = True) -> Model:
    """Entrena, valida dejando un día fuera y elige el umbral."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score, roc_auc_score

    X = np.asarray(data.X, dtype=float)
    y = np.asarray(data.y, dtype=int)
    sw = np.asarray(data.weights, dtype=float)
    groups = np.asarray(data.groups)

    if len(set(y.tolist())) < 2:
        raise ValueError(
            "El conjunto solo tiene una clase. Faltan marcas de estrés "
            "o faltan negativos: revisa pipeline.labels.summary()."
        )

    oof = _cross_val_proba(X, y, sw, groups, verbose=verbose)

    metrics = {
        "n": int(len(y)),
        "positivos": int(y.sum()),
        "dias": int(len(set(groups.tolist()))),
        "pr_auc": float(average_precision_score(y, oof)),
        "roc_auc": float(roc_auc_score(y, oof)),
        "pr_auc_base": float(y.mean()),   # lo que sacaría el azar
    }
    metrics["boosting_pr_auc"] = _reference_boosting(X, y, groups)
    metrics["univariante"] = {
        name: float(roc_auc_score(y, X[:, i]))
        for i, name in enumerate(data.feature_names)
    }

    thr = choose_threshold(y, oof, np.asarray(data.times, dtype=float), groups,
                           max_false_alarms=max_false_alarms)
    metrics.update(thr)

    # Modelo final: reentrenado con todos los días.
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
    clf.fit(X, y, sample_weight=sw)

    model = Model(
        feature_names=list(data.feature_names),
        w=[float(v) for v in clf.coef_[0]],
        b0=float(clf.intercept_[0]),
        use_z=[ds_mod.USE_Z[n] for n in feat.LIVE_FEATURES],
        mu0=[ds_mod.BASELINE_MU0[n] for n in feat.LIVE_FEATURES],
        sd0=[ds_mod.BASELINE_SD0[n] for n in feat.LIVE_FEATURES],
        p_alert=float(thr["umbral"]),
        metrics=metrics,
    )

    if verbose:
        report(model)
    return model


def _cross_val_proba(X, y, sw, groups, verbose=True):
    """Probabilidades fuera de muestra, un día fuera cada vez."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import LeaveOneGroupOut

    oof = np.zeros(len(y), dtype=float)
    uniq = sorted(set(groups.tolist()))

    if len(uniq) < 2:
        # Con un solo día no se puede validar entre días. Partimos por la
        # mitad temporal, que al menos no mezcla ventanas solapadas.
        if verbose:
            print("AVISO: un solo día de datos. La validación parte el día "
                  "por la mitad; el número resultante es optimista.")
        mid = len(y) // 2
        for tr, te in ((slice(0, mid), slice(mid, None)),
                       (slice(mid, None), slice(0, mid))):
            if len(set(y[tr].tolist())) < 2:
                continue
            clf = LogisticRegression(max_iter=2000, class_weight="balanced")
            clf.fit(X[tr], y[tr], sample_weight=sw[tr])
            oof[te] = clf.predict_proba(X[te])[:, 1]
        return oof

    for tr, te in LeaveOneGroupOut().split(X, y, groups):
        if len(set(y[tr].tolist())) < 2:
            oof[te] = y[tr].mean() if len(tr) else 0.0
            continue
        clf = LogisticRegression(max_iter=2000, class_weight="balanced")
        clf.fit(X[tr], y[tr], sample_weight=sw[tr])
        oof[te] = clf.predict_proba(X[te])[:, 1]
    return oof


def _reference_boosting(X, y, groups) -> float:
    """Techo de referencia. Si gana por mucho, faltan features."""
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import average_precision_score
    from sklearn.model_selection import LeaveOneGroupOut

    uniq = sorted(set(groups.tolist()))
    if len(uniq) < 2:
        return float("nan")

    oof = np.zeros(len(y), dtype=float)
    for tr, te in LeaveOneGroupOut().split(X, y, groups):
        if len(set(y[tr].tolist())) < 2:
            continue
        clf = HistGradientBoostingClassifier(max_depth=3, max_iter=120,
                                             learning_rate=0.1)
        clf.fit(X[tr], y[tr])
        oof[te] = clf.predict_proba(X[te])[:, 1]
    return float(average_precision_score(y, oof))


def choose_threshold(y, proba, times, groups,
                     max_false_alarms: float = MAX_FALSE_ALARMS_PER_DAY,
                     refractory_s: float = ALARM_REFRACTORY_S) -> dict:
    """Umbral más sensible que respeta el presupuesto de falsas alarmas.

    Un "aviso" no es una ventana por encima del umbral: son todas las
    ventanas seguidas por encima del umbral, colapsadas, más un periodo
    refractario. Contar ventanas en vez de avisos multiplicaría por
    cuatro las alarmas aparentes sin que el reloj vibrara ni una vez de
    más.
    """
    import numpy as np

    y = np.asarray(y)
    proba = np.asarray(proba)
    times = np.asarray(times)
    n_days = max(1, len(set(np.asarray(groups).tolist())))

    order = np.argsort(times)
    best = {"umbral": 0.9, "falsas_alarmas_dia": 0.0,
            "avisos_dia": 0.0, "recall": 0.0, "precision": 0.0}

    for thr in np.arange(0.95, 0.04, -0.01):
        alarms = 0
        false_alarms = 0
        caught = set()
        last_t = -1e18
        for i in order:
            if proba[i] < thr:
                continue
            if times[i] - last_t < refractory_s:
                # Mismo aviso: no vibra otra vez, pero sí puede "pillar"
                # un positivo que empezó después.
                if y[i] == 1:
                    caught.add(int(times[i] // refractory_s))
                continue
            last_t = times[i]
            alarms += 1
            if y[i] == 1:
                caught.add(int(times[i] // refractory_s))
            else:
                false_alarms += 1

        fa_day = false_alarms / n_days
        if fa_day > max_false_alarms:
            continue

        pos_events = len(set(int(t // refractory_s)
                             for t, yy in zip(times, y) if yy == 1))
        recall = len(caught) / pos_events if pos_events else 0.0
        if recall >= best["recall"]:
            best = {
                "umbral": float(thr),
                "falsas_alarmas_dia": float(fa_day),
                "avisos_dia": float(alarms / n_days),
                "recall": float(recall),
                "precision": float((alarms - false_alarms) / alarms) if alarms else 0.0,
            }

    return best


def report(model: Model) -> None:
    m = model.metrics
    print()
    print("=" * 62)
    print("  RESULTADO DEL ENTRENAMIENTO")
    print("=" * 62)
    print(f"  ventanas          {m.get('n')}  ({m.get('positivos')} positivas)")
    print(f"  días              {m.get('dias')}")
    print()
    print(f"  PR-AUC            {m.get('pr_auc', float('nan')):.3f}"
          f"   (azar: {m.get('pr_auc_base', float('nan')):.3f})")
    print(f"  ROC-AUC           {m.get('roc_auc', float('nan')):.3f}")
    ref = m.get("boosting_pr_auc", float("nan"))
    print(f"  PR-AUC boosting   {ref:.3f}   (techo de referencia)")
    print()
    print(f"  umbral elegido    {m.get('umbral', float('nan')):.2f}")
    print(f"  avisos/día        {m.get('avisos_dia', float('nan')):.1f}")
    print(f"  falsas alarmas    {m.get('falsas_alarmas_dia', float('nan')):.1f}/día")
    print(f"  recall episodios  {m.get('recall', float('nan')):.2f}")
    print()
    # Dos columnas, y conviene mirar las dos.
    #
    # El AUC de cada feature POR SEPARADO dice si la fisiología va en la
    # dirección esperada: el estrés debe bajar log_rmssd y pnn50 y subir
    # la frecuencia. Si eso no se cumple, hay un problema en los datos o
    # en el etiquetado y no merece la pena seguir.
    #
    # El coeficiente del modelo NO es eso. Es el efecto de cada feature
    # con las demás ya tenidas en cuenta, y con features fisiológicamente
    # acopladas (la frecuencia y la HRV lo están, y mucho) puede salir
    # con el signo contrario sin que nada esté mal. No lo interpretes
    # como "el estrés baja el pulso".
    uni = m.get("univariante", {})
    print("  Feature          AUC solo   coef. modelo")
    for name, wi in zip(model.feature_names, model.w):
        auc = uni.get(name)
        # Un AUC de 0,3 separa igual de bien que uno de 0,7: la flecha
        # dice hacia dónde.
        if auc is None:
            col = "   n/d  "
        else:
            arrow = "sube" if auc > 0.5 else "baja"
            col = f"  {auc:.3f} {arrow}"
        bar = "#" * min(24, int(abs(wi) * 8))
        print(f"    {name:<14} {col}   {wi:+7.3f}  {bar}")
    print("=" * 62)

    if m.get("pr_auc", 0) < m.get("pr_auc_base", 0) * 2:
        print("  ATENCIÓN: el modelo apenas mejora al azar. Con pocos días")
        print("  esto es normal; sigue recogiendo datos antes de sacar")
        print("  conclusiones.")
        print("=" * 62)
