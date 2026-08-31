# Evolución de la física y la jugabilidad (v3.3)

Este documento recoge las mejoras incorporadas en la última tanda de trabajo,
por qué se hicieron y **cómo se han validado**. La filosofía ha sido la misma
en todo: modelos **seleccionables** (el anterior se conserva como `legacy` de
referencia/regresión), y ningún cambio se da por bueno "porque se siente
mejor" — cada uno se contrasta con pruebas.

---

## 1. Neumático: curvas longitudinal y lateral separadas

**Qué había:** una única curva combinada (misma forma `B`, `C`) para
longitudinal y lateral; solo cambiaba la escala de la elipse.

**Qué hay ahora:** `TIRE_MODEL = "legacy" | "brush"` (editable en AJUSTES).
En `brush`, cada eje tiene su propia forma de curva (`B_LONG/C_LONG`,
`B_LAT/C_LAT`) y la mezcla se interpola según la dirección del deslizamiento,
manteniendo la elipse de combinación.

- La **longitudinal** queda más rígida y con pico más marcado (límite de
  tracción/frenada más nítido).
- La **lateral** es más progresiva y cae menos tras el pico (entrada avisada,
  derrapes más controlables).

> Nota de terminología: en rigor es un **modelo híbrido de deslizamiento
> independiente** (curvas separadas + mezcla direccional + elipse), no un
> "brush model" que reparta la tensión cortante en la huella.

**Validación:** `tests/test_neumatico_brush.py` (curvas realmente distintas,
0-100 razonable, ~0,92 g lateral, estable, cadena de cargas intacta) y la
figura de calibración `docs/img/curvas_neumatico.png`, que confirma que los
**picos coinciden con μ·Fz** (lateral) y μ·Fz·ratio (longitudinal), en
deslizamientos realistas (long ~10-13 %, lateral 7-8,5°).

---

## 2. Motor: cigüeñal con inercia + embrague

**Qué había:** el régimen seguía a las ruedas con un filtro de 0,12 s (no era
un sistema dinámico).

**Qué hay ahora:** `ENGINE_MODEL = "legacy" | "inertia"`. En `inertia` el
cigüeñal es un grado de libertad propio:

```
I_e · dω/dt = combustión − freno motor − embrague
```

En marcha va rígido con las ruedas (como legacy, que ya maneja el wheelspin);
el cigüeñal independiente y el embrague que patina actúan solo en **punto
muerto** (acelerón libre) y en la **salida** desde parado (flare del embrague).

**Emergen** el acelerón en punto muerto, el patinaje del embrague en la
arrancada y un régimen que ya no va pegado a las ruedas.

**Validación:** `tests/test_motor_inercia.py` (5/5).

---

## 3. Transmisión y diferencial

- **Corte de par en el cambio** (`SHIFT_CUT_TIME`): al engranar, el par a las
  ruedas cae casi a cero ~0,1 s y se recupera progresivamente → el tirón real
  del cambio.
- **Tope de capacidad del LSD** (`DIFF_MAX_LOCK`): el autoblocante de discos
  no bloquea sin fin; satura en su capacidad. Completa un diferencial que ya
  tenía precarga y rampas de aceleración/retención separadas.

**Validación:** `tests/test_transmision.py` (5/5): el corte baja la
aceleración tras el cambio; el diferencial abierto reparte 50/50, el LSD
transfiere a la rueda que agarra, bloquea más acelerando que reteniendo, y el
tope satura.

---

## 4. Firme: rugosidad y zonas dañadas

- **Zonas dañadas** deterministas por tramos (`damage_at`): el firme está sano
  la mayor parte del tiempo (~11 % dañado) y de vez en cuando hay parches rotos
  con baches grandes (hasta ~5 cm, más que un piano). Escalado por
  `ROAD_ROUGHNESS`.
- Es **física real**, no cosmética: en un parche roto la carga vertical de una
  rueda oscila el doble (±3700 N vs ±1867 N) y la suspensión se mueve casi el
  triple (13 mm vs 4,6 mm); como la Fz fluctúa, **el agarre también**.
- Se **ve** (el asfalto dañado se pinta más oscuro y moteado) y se **siente**
  en el temblor de cámara y en el volante (el FFB de textura se multiplica en
  las zonas malas), con el mismo criterio que la física.

---

## 5. Cámara (efectos visuales, no tocan la física)

Cuatro efectos en las vistas a bordo, ajustables en AJUSTES:

- **Mirar a la curva** (`CAMERA_LOOK_GAIN`): la cámara gira hacia donde gira el
  coche, anticipando el vértice.
- **FOV con la velocidad** (`CAMERA_FOV_SPEED`): el campo se abre al acelerar.
- **Balanceo de cabeza** (`CAMERA_GLEAN`): la cabeza cae hacia fuera con la g
  lateral.
- **Temblor** (`CAMERA_SHAKE`): por fuerza g (frenada/curva), baches/pianos y
  patinaje.

---

## 6. Ajustes y menú

- El editor de AJUSTES admite **parámetros de opciones** (enum): así
  `ENGINE_MODEL`, `TIRE_MODEL`, **`DRIVE_TYPE` (RWD/FWD/AWD)** y **`DIFF_TYPE`**
  se cambian desde el menú.
- Los reglajes se organizan por **categorías** (coche / pantalla / mandos…),
  se persisten y se pueden **guardar como coche nuevo**.

---

## 7. Validación de primeros principios (lo más importante)

Además de los tests de comportamiento, ahora se contrastan las **magnitudes**
del modelo contra la teoría clásica de dinámica vehicular:

`tests/test_referencia_fisica.py` (9/9):

- carga estática por rueda = reparto de peso (exacto);
- transferencia longitudinal `ΔFz = m·a·h/L` (dentro del 1 %);
- transferencia lateral `ΔFz = m·a·h/vía` (dentro del 3 %);
- conservación `ΣFz = m·g + downforce` (al newton).

`tests/test_integrador.py` (6/6):

- **Convergencia temporal** (480/960/1920 Hz): el error se reduce a la mitad
  al doblar la frecuencia (480→1920 = 21 mm de posición tras una maniobra
  dura; las fuerzas convergen a 5 N). **480 Hz está convergido.**
- **Energía**: el integrador no crea energía artificial (en coasting la
  velocidad solo baja; una suspensión perturbada amortigua; un corrugado
  mantiene la masa no suspendida acotada).

**Decisión con datos:** NO se implementa un integrador predictor-corrector.
Con 480 Hz ya convergido y sin energía artificial, su coste/beneficio es malo
(diferencias de milímetros que el jugador no percibiría).

---

## Inventario de pruebas

| Archivo | Qué valida | Nº |
|---|---|---|
| `test_physics.py` | comportamientos (0-100, frenada, subviraje, vueltas…) | 120 |
| `test_referencia_fisica.py` | magnitudes contra primeros principios | 9 |
| `test_integrador.py` | convergencia temporal + energía | 6 |
| `test_neumatico_brush.py` | curvas separadas long/lat | 6 |
| `test_motor_inercia.py` | cigüeñal + embrague | 5 |
| `test_transmision.py` | corte de cambio + diferencial | 5 |
| `test_settings.py` | persistencia y reglajes | 11 |
| **Total** | | **162** |

Más las suites de herramientas de trazado (`test_clothoid`, `test_georef`,
`test_alignment`, `test_profile`, `test_solver`).

---

## Estado

El modelo físico está en un punto **sólido y validado**: neumático con curvas
separadas y magnitudes reales, motor con inercia, transmisión con corte de
par, diferencial completo, firme con rugosidad física, y una batería que
comprueba tanto el comportamiento como las magnitudes y la calidad de la
integración. El siguiente trabajo no es más física, sino **dar carácter a cada
coche** con todos estos sistemas.
