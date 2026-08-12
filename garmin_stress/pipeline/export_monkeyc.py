"""Genera watch/source/ModelParams.mc a partir del modelo entrenado.

Este es el puente de vuelta al reloj y el punto donde es más fácil
meter la pata sin enterarse: si el orden de los pesos no coincide con el
orden de `module Features` en Monkey C, el modelo seguirá compilando,
seguirá dando probabilidades de aspecto razonable y estará
multiplicando el peso del RMSSD por la frecuencia cardíaca. Por eso se
comprueba el orden antes de escribir nada.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import features as feat
from .train import Model

HEADER = """//! GENERADO por pipeline/export_monkeyc.py — no editar a mano.
//!
//! Modelo v{version}
//! Entrenado con {n} ventanas ({pos} positivas) de {dias} día(s).
//! PR-AUC (un día fuera): {pr_auc}   ·   azar: {base}
//! Umbral: {umbral} -> {avisos}/día, {falsas} falsas/día, recall {recall}

using Toybox.Lang;

module ModelParams {{
"""


def _fmt_floats(values) -> str:
    return ", ".join(f"{v:.6f}" for v in values)


def _fmt_bools(values) -> str:
    return ", ".join("true" if v else "false" for v in values)


def _num(m, key, fmt="{:.3f}"):
    v = m.get(key)
    if v is None:
        return "n/d"
    try:
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return str(v)


def render(model: Model) -> str:
    """Devuelve el contenido del fichero .mc."""
    expected = feat.LIVE_FEATURES
    got = [n[2:] if n.startswith("z_") else n for n in model.feature_names]
    if got != expected:
        raise ValueError(
            "El orden de las features del modelo no coincide con el de "
            f"module Features en Monkey C.\n  esperado: {expected}\n  "
            f"recibido: {got}"
        )
    if not (len(model.w) == len(model.use_z) == len(model.mu0)
            == len(model.sd0) == len(expected)):
        raise ValueError("Longitudes inconsistentes en el modelo.")

    m = model.metrics
    out = [HEADER.format(
        version=model.version,
        n=m.get("n", "?"), pos=m.get("positivos", "?"), dias=m.get("dias", "?"),
        pr_auc=_num(m, "pr_auc"), base=_num(m, "pr_auc_base"),
        umbral=_num(m, "umbral", "{:.2f}"),
        avisos=_num(m, "avisos_dia", "{:.1f}"),
        falsas=_num(m, "falsas_alarmas_dia", "{:.1f}"),
        recall=_num(m, "recall", "{:.2f}"),
    )]

    out.append(f"    const MODEL_VERSION = {model.version};\n")
    out.append("    const TRAINED = true;\n\n")

    out.append("    //! Orden: " + ", ".join(expected) + "\n")
    out.append(f"    const W = [{_fmt_floats(model.w)}];\n")
    out.append(f"    const B0 = {model.b0:.6f};\n\n")

    out.append(f"    const USE_Z = [{_fmt_bools(model.use_z)}];\n")
    out.append(f"    const MU0 = [{_fmt_floats(model.mu0)}];\n")
    out.append(f"    const SD0 = [{_fmt_floats(model.sd0)}];\n\n")

    out.append(f"    const P_ALERT = {model.p_alert:.4f};\n")
    out.append(f"    const P_UNC_LO = {model.p_unc_lo:.4f};\n")
    out.append(f"    const P_UNC_HI = {model.p_unc_hi:.4f};\n")
    out.append("}\n")
    return "".join(out)


def export(model: Model, path) -> Path:
    path = Path(path)
    path.write_text(render(model), encoding="utf-8")
    return path


def read_feature_order(path) -> list[str]:
    """Lee el orden de `module Features` de un fichero Monkey C.

    Devuelve los nombres en minúsculas y en el orden de sus índices, para
    poder compararlo con features.LIVE_FEATURES.
    """
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(r"module\s+Features\s*\{(.*?)\}", text, re.S)
    if not m:
        raise ValueError(f"No hay `module Features` en {path}")

    pairs = []
    for name, idx in re.findall(r"const\s+(\w+)\s*=\s*(\d+)\s*;", m.group(1)):
        if name == "COUNT":
            continue
        pairs.append((int(idx), name.lower()))
    return [name for _idx, name in sorted(pairs)]


def read_constants(path) -> dict:
    """Lee las constantes escalares de un .mc de Monkey C.

    Sirve para los tests de paridad: comprobar que watch/source/Config.mc
    y las constantes de Python siguen diciendo lo mismo.
    """
    text = Path(path).read_text(encoding="utf-8")
    out: dict[str, float | bool] = {}
    for name, value in re.findall(
            r"const\s+(\w+)\s*=\s*([-\w.]+)\s*;", text):
        if value in ("true", "false"):
            out[name] = (value == "true")
            continue
        try:
            out[name] = float(value)
        except ValueError:
            continue
    return out
