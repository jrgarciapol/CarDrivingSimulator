# Detector personal de estrés agudo — Garmin Epix Pro + HRM Dual

Sistema de **evaluación ecológica momentánea** (EMA) con aprendizaje
activo: el reloj registra los intervalos entre latidos y el movimiento,
tú marcas los momentos de estrés, y un modelo entrenado con **tus** datos
aprende a reconocer tu firma fisiológica.

El reloj hace de registrador y de interfaz. El entrenamiento se hace en
el ordenador. Del modelo entrenado solo vuelven al reloj cinco pesos y un
umbral, que es todo lo que necesita para inferir en tiempo real.

```
   ┌──────────────────────┐         ┌──────────────────────────┐
   │  Epix Pro + HRM Dual │  .fit   │   Pipeline de Python     │
   │  ──────────────────  │ ──USB─▶ │   ────────────────────   │
   │  · R-R sin perder    │         │  · limpieza artefactos   │
   │    latidos           │         │  · features HRV          │
   │  · acelerómetro      │         │  · etiquetado corregido  │
   │  · marcas manuales   │         │  · validación por días   │
   │  · inferencia local  │ ◀────── │  · ModelParams.mc        │
   └──────────────────────┘  pesos  └──────────────────────────┘
```

## Documentación

| Documento | Contenido |
|---|---|
| [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) | Revisión crítica: cuellos de botella del FIT, confusores fisiológicos, qué verificar el primer día |
| [`docs/MODELO.md`](docs/MODELO.md) | Qué modelo y por qué, validación, política de preguntas |
| [`docs/PROTOCOLO.md`](docs/PROTOCOLO.md) | Cómo recoger los datos día a día |

## Prueba rápida, sin reloj

Todo el pipeline funciona sobre datos sintéticos, así que se puede
verificar la instalación antes de tener nada grabado:

```bash
pip install -r requirements.txt
python -m pipeline demo
```

Genera cinco días sintéticos con episodios de estrés, ratos de
movimiento, artefactos y latencia realista de marcado; entrena, valida
dejando un día fuera y enseña el `ModelParams.mc` que se generaría.

```
  ventanas          2281  (231 positivas)
  días              5

  PR-AUC            0.379   (azar: 0.101)
  ROC-AUC           0.789
  PR-AUC boosting   0.255   (techo de referencia)

  umbral elegido    0.54
  avisos/día        9.4
  falsas alarmas    4.0/día
  recall episodios  0.85

  Feature          AUC solo   coef. modelo
    z_mean_hr        0.641 sube    +0.997
    z_sdnn           0.521 sube    +0.920
    z_log_rmssd      0.328 baja    -0.456
    z_pnn50          0.345 baja    +0.192
    act              0.365 baja    -4.828
```

Estos números son de datos inventados y no predicen nada sobre los tuyos.
Sirven para comprobar que la cadena está entera.

## Ciclo real

```bash
# 1. Copiar los .fit desde /GARMIN/ACTIVITY/ del reloj
cp /media/garmin/GARMIN/ACTIVITY/*.fit data/raw/

# 2. Ver qué hay: duración, latidos, marcas, artefactos
python -m pipeline inspect data/raw

# 3. Entrenar y validar dejando un día fuera
python -m pipeline train --data data/raw --model data/model.json

# 4. Llevar el modelo al reloj y recompilar la app
python -m pipeline export --model data/model.json
```

## La app del reloj

Aplicación Connect IQ (`watch/`), no campo de datos: un data field no
puede capturar los botones y tiene mucha menos memoria.

**Marcar estrés**

| | |
|---|---|
| **START** | menú: nivel 1/2/3 o "estoy tranquilo", y después **¿desde cuándo?** |
| **ABAJO** ×1/×2/×3 | marca discreta del nivel, sin mirar el reloj |
| **ATRÁS** | guardar y salir (con confirmación) |

Lo de "¿desde cuándo?" parece un detalle y es lo más importante de la
interfaz. Una marca no ocurre cuando ocurre el episodio: ocurre cuando te
das cuenta, que puede ser tres minutos después. Sin ese dato, el
etiquetado se desplaza y el modelo acaba aprendiendo a detectar el gesto
de pulsar un botón.

**Compilar**

```bash
cd watch
monkeyc -f monkey.jungle -o estres.prg -y <tu-clave>.der -d epix2pro47mm
```

Devices: `epix2pro42mm`, `epix2pro47mm`, `epix2pro51mm`. Para instalar,
copia el `.prg` a `/GARMIN/APPS/` del reloj.

## Estructura

```
watch/                  App Connect IQ (Monkey C)
  source/
    Config.mc           Constantes compartidas con Python
    Recorder.mc         Sesión FIT, campos, sensores
    Hrv.mc              Ventana R-R, RMSSD, línea base personal
    Detector.mc         Inferencia y política de preguntas
    ModelParams.mc      GENERADO por el pipeline
    MainView.mc / MainDelegate.mc / MarkerMenu.mc / PromptMenu.mc

pipeline/               Procesamiento y entrenamiento (Python)
  rr.py                 Limpieza de artefactos
  features.py           Métricas HRV
  session.py            Muestras, marcas, ventanas
  fitio.py              Lectura de .fit y .csv
  labels.py             Marcas -> etiquetas (corrección de latencia)
  dataset.py            Normalización contra línea base personal
  train.py              Entrenamiento y validación
  export_monkeyc.py     Modelo -> ModelParams.mc
  synth.py              Generador de datos sintéticos

tests/                  58 tests, ninguno necesita el reloj
```

## Paridad reloj ↔ pipeline

El fallo más caro de un sistema así, y el más difícil de diagnosticar, es
que el reloj calcule las features de una manera y el entrenamiento de
otra. No explota nada: la app compila, el modelo da probabilidades
razonables y las predicciones son basura, sin ningún síntoma que apunte a
la causa.

`tests/test_parity.py` lee `watch/source/Config.mc` y `Hrv.mc` y
comprueba contra el código Python que las constantes valen lo mismo y que
el orden del vector de features coincide. Si tocas un umbral en un lado y
no en el otro, el test falla.

```bash
pytest tests -q
```

## Estado

- **Listo:** registro completo, marcado por las dos vías, pipeline
  entero, entrenamiento, validación, exportación y tests.
- **Pendiente de hardware:** confirmar que los campos FIT de tipo array
  (`:count`) guardan bien en el Epix Pro. Es lo único que no se puede
  verificar sin el reloj. Si fallan, `Config.RR_ARRAY_FIELD = false`
  activa el plan B (cuatro campos escalares) y el pipeline lo lee igual.
  Ver el día 0 en [`docs/PROTOCOLO.md`](docs/PROTOCOLO.md).
