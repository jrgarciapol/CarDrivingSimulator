# Protocolo de recogida de datos

El código es la parte fácil. Lo que decide si esto funciona es la
disciplina de estos días.

---

## Antes de nada: el día 0

Sesión corta, de 10 a 15 minutos, sentado, para verificar la cadena
entera. Marca tres o cuatro veces con niveles distintos aunque no
sientas nada — lo que se comprueba es la tubería, no la fisiología.

Descarga el `.fit` y pasa:

```
python -m pipeline inspect data/raw/<fichero>.fit
```

Cinco cosas tienen que cuadrar:

1. **Latidos ≈ duración × frecuencia media / 60.** Si sale la mitad, el
   campo array no está guardando: pon `Config.RR_ARRAY_FIELD = false` y
   recompila.
2. **Las marcas salen todas**, con su nivel y su código de inicio.
3. **La fracción de artefactos es baja.** Por debajo del 5 %.
4. **El fichero está en `/GARMIN/ACTIVITY/`** después de cerrar la app.
5. **La app aguanta 15 minutos** sin quedarse sin memoria.

No sigas hasta que los cinco estén en verde. Un fallo aquí invalida días
enteros más adelante.

---

## Fase 1 — Solo recoger (días 1 a 5)

El reloj **no infiere nada** todavía (`ModelParams.TRAINED = false`). No
vibra, no pregunta. Solo graba y espera tus marcas.

### Rutina diaria

- **Ponte la banda con los electrodos húmedos.** De verdad. La mayoría de
  los datos malos de HRV vienen de un electrodo seco, no del algoritmo.
- **Arranca la app al empezar la jornada** y déjala. Bloques de 3 a 6
  horas que cubran la franja donde te pasan cosas. Ocho horas seguidas
  con banda es incómodo y acabas quitándotela: es mejor tener cuatro
  horas limpias que ocho con tres de artefactos.
- **Marca en cuanto te des cuenta.** No esperes a que el episodio acabe.
  Cuanto antes marques, menos tienes que estimar el inicio.
- **Marca la calma 3-5 veces al día**, repartidas y en momentos de verdad
  tranquilos. Cuesta dos toques y vale mucho: sin negativos declarados,
  la clase negativa es "todo lo que no marqué", que incluye los episodios
  que se te pasaron.
- **Cierra la app al terminar** y confirma que guarda.

### Cómo marcar

| Vía | Cuándo |
|---|---|
| **START** → nivel → ¿desde cuándo? | Lo normal. Dos toques y el dato del inicio, que es el que coloca bien la etiqueta. |
| **ABAJO** ×1, ×2, ×3 | Discreto, sin mirar el reloj, en mitad de una reunión. Asume "hace ~1 min". |

El reloj vibra tantas veces como el nivel que ha entendido. Si vibra dos
veces y querías tres, has registrado un 2 — no pasa nada, pero por eso
existe el menú.

### Qué no hacer

- **No marques a posteriori.** "Esta mañana estuve fatal" no sirve: no
  sabemos qué ventana etiquetar.
- **No marques el estrés físico.** Correr no es esto. Si estás
  entrenando, cierra la app.
- **No cambies de banda a mitad del estudio.** Cada sensor tiene su
  ruido; el modelo se entrena con el tuyo.
- **No revises los datos cada noche buscando el resultado.** Con tres
  días no hay nada que ver, y mirar demasiado pronto lleva a tocar cosas
  que no se deben tocar.

### Al final de la fase

```
python -m pipeline inspect data/raw
python -m pipeline train --data data/raw --model data/model.json
```

Mira **la columna de AUC univariante** antes que ninguna otra cosa: con
estrés tiene que subir la frecuencia y bajar `log_rmssd` y `pnn50`. Si
eso no se cumple, el problema está en el etiquetado y no en el modelo.

---

## Fase 2 — Desplegar el modelo (día 6)

```
python -m pipeline export --model data/model.json
```

Reescribe `watch/source/ModelParams.mc`. Recompila e instala.

Ahora el reloj infiere en tiempo real y puede preguntar. Sube
`MODEL_VERSION` en cada iteración: queda grabado en el resumen de cada
sesión, así que después se puede saber qué modelo generó qué avisos.

---

## Fase 3 — Aprendizaje activo (días 6 en adelante)

Ahora conviven las dos vías, y las dos hacen falta:

- **El reloj pregunta** cuando cree que hay algo (alerta) o cuando duda
  (aprendizaje). Máximo 8 veces por sesión, con 10 minutos entre
  preguntas.
- **Tú sigues marcando** cuando quieras, haya preguntado o no.

Lo segundo no es opcional. Sin ello no puedes capturar los **falsos
negativos** — los episodios que el reloj no vio y por tanto no preguntó —
y son el error que más importa y el único que no se puede recuperar de
otra forma. Un modelo que solo aprende de momentos que él mismo eligió se
reafirma en lo que ya cree.

**Contesta siempre**, aunque sea que no. Un "no" en un momento que el
modelo consideraba dudoso es de los datos más valiosos que vas a dar. Si
te ves ignorando preguntas de forma sistemática, baja
`PROMPT_MAX_PER_SESSION` en vez de acostumbrarte a ignorarlas.

---

## Fase 4 — Reentrenar (cada 3-5 días)

Descarga, reentrena con **todos** los días acumulados, exporta,
recompila.

Qué mirar en cada iteración:

- **PR-AUC frente al azar.** El número solo no dice nada.
- **Falsas alarmas al día.** Si te molesta, baja `--max-false-alarms`.
- **Recall de episodios.** Cuántos de los que marcaste habría cogido.
- **Si los coeficientes bailan mucho** entre reentrenamientos, aún no hay
  datos suficientes. Sigue recogiendo.

Cuando el modelo lleve dos o tres reentrenamientos estable, se puede
empezar a mirar la intensidad (nivel 1/2/3) como problema aparte.

---

## Registro de sesiones

Merece la pena llevar una nota por día — fuera del reloj — con lo que el
sensor no puede saber:

```
2026-08-12  09:15-13:40  banda ok
  10:50  nivel 3  incidencia en obra, llamada tensa ~15 min
  12:10  nivel 1  reunión larga, más aburrimiento que otra cosa
  café a las 9:30 y a las 11:45
  dormí mal (5 h)
```

Cuando dentro de tres semanas el modelo haga algo raro un martes, esta
libreta es lo que te va a decir por qué. Las horas de café y de comida
explican más falsos positivos de los que parece.
