# Revisión crítica de la arquitectura

Respuesta a "¿ves algún cuello de botella en el guardado de datos
personalizados en ficheros `.fit` mediante el SDK Connect IQ?".

Sí, hay uno serio y varios menores. El serio tiene solución y está
implementada; los menores condicionan decisiones de diseño que conviene
tomar antes de escribir código, no después.

---

## 1. El cuello de botella de verdad: los registros van a 1 Hz

Los mensajes `record` de un fichero FIT se escriben **como máximo una vez
por segundo**. Un campo personalizado escalar (`FitContributor` con
`MESG_TYPE_RECORD`) guarda **un valor por registro**. O sea: un valor por
segundo.

Los intervalos R-R no llegan a un ritmo fijo — llegan uno por latido. A
60 ppm es un latido por segundo justo; a 75 ppm son 1,25; a 100 ppm son
1,67. **Por encima de 60 pulsaciones por minuto, un campo escalar pierde
latidos.**

Y perder latidos aquí no es perder precisión, es corromper el dato. El
RMSSD se calcula sobre diferencias entre latidos *consecutivos*. Si se
pierde el latido del medio, dos intervalos de 900 ms se convierten en uno
de 1800 ms y aparece una diferencia de 900 ms donde no había ninguna. Un
solo latido perdido por minuto puede duplicar el RMSSD de la ventana. El
modelo lo leería como "muy relajado" justo cuando probablemente pasaba lo
contrario.

**Solución implementada.** Un campo de tipo array:

```monkeyc
mFldRr = session.createField("rr", 0, FitContributor.DATA_TYPE_UINT16,
    { :mesgType => FitContributor.MESG_TYPE_RECORD,
      :units => "ms", :count => 4 });
```

Cuatro huecos por segundo dan capacidad hasta 240 ppm. Los intervalos van
a una cola FIFO en el callback del sensor y se vacían cuatro por segundo
en el tick de 1 Hz, así que ni se pierde nada ni importa que lleguen a
ráfagas. Un campo `rr_n` acompaña cada registro diciendo cuántos huecos
son válidos, y `rr_lost` cuenta lo que no cupo (tiene que ser 0 siempre;
si no lo es, hay que enterarse).

**Plan B.** Si tu versión del SDK no acepta `:count`, pon
`Config.RR_ARRAY_FIELD = false` y la app crea cuatro campos escalares
`rr0..rr3`. Ocupa más en el fichero y es más feo, pero funciona igual. El
pipeline de Python lee los dos formatos sin que haya que decirle nada.

**Esto es lo primero que hay que verificar en el reloj**, antes de
recoger un solo día de datos útiles. Es la única pieza de todo el diseño
que no he podido comprobar sin el hardware delante.

**Red de seguridad.** Muchos Garmin escriben por su cuenta mensajes `hrv`
nativos con los intervalos R-R cuando hay una banda conectada. El lector
de Python los aprovecha automáticamente si el campo de la app viene
vacío. No dependas de ello — es comportamiento no documentado y varía con
el firmware — pero puede salvarte una sesión.

---

## 2. Tiene que ser una watch-app, no un data field

Un *data field* es lo natural para grabar durante una actividad, y aquí
no sirve:

- **No puede capturar los botones.** Los usa la actividad nativa
  (start/stop/lap). Sin botones no hay marcado manual, y el marcado
  manual es la mitad del proyecto.
- **Memoria mucho menor.** Un data field simple tiene un presupuesto muy
  ajustado; una watch-app en un Epix Pro tiene margen de sobra para el
  buffer circular de latidos y el detector.

El precio es que la app tiene que estar en primer plano, o sea, más gasto
de batería que un data field dentro de una actividad nativa. Con el
Epix Pro y sin GPS, una jornada de trabajo entera es perfectamente
asumible.

---

## 3. El problema científico más gordo: la marca llega tarde

Este no es un problema del SDK, es del método, y es el que más
probabilidades tiene de arruinar el resultado sin que te des cuenta.

Cuando marcas un episodio de estrés no lo marcas cuando empieza. Lo
marcas cuando te das cuenta, decides marcarlo, levantas la muñeca y
pulsas. Entre el pico fisiológico y el botón pueden pasar de diez
segundos a varios minutos.

Si etiquetas "la ventana que contiene la pulsación", pasan dos cosas:

1. Etiquetas como estrés el gesto de levantar el brazo y pulsar. Con
   suficientes ejemplos, el modelo aprende a detectar **pulsaciones de
   botón**. Y funcionará espléndidamente en validación, porque las
   pulsaciones de botón están perfectamente correlacionadas con las
   etiquetas.
2. Te pierdes el comienzo del episodio, que es donde está la firma más
   limpia: la descarga simpática inicial.

**Lo que hace este diseño:**

- Tras elegir el nivel, la app pregunta **"¿desde cuándo?"** (ahora / ~1
  min / ~3 min / 10 min o más). Es un toque más, y es el dato que permite
  colocar la ventana de etiquetado en el sitio correcto.
- El etiquetado descarta los **últimos 15 segundos** antes de la
  pulsación: ahí está el gesto.
- Además exige que la ventana positiva **termine** antes de ese corte, no
  solo que solape con el episodio. Sin esa segunda condición, una ventana
  con 50 % de solape podía contener la pulsación igualmente.
- Las ventanas cercanas a una marca pero fuera del episodio quedan en
  **zona gris**: ni positivas ni negativas. No sabemos qué había ahí.

La pulsación múltiple (1/2/3 toques en el botón de abajo) sigue
disponible para marcar sin mirar el reloj, en mitad de una reunión. Asume
"hace ~1 min" por defecto, que es lo más probable.

---

## 4. El confusor que hay que batir: el movimiento

Subir tres tramos de escaleras hunde la HRV exactamente igual que una
discusión. Sin acelerómetro, el modelo no puede distinguirlos y aprenderá
a detectar actividad física.

La app muestrea el acelerómetro a 25 Hz y **reduce a bordo**: no cabe (ni
hace falta) meter 75 valores por segundo en el FIT. Por cada segundo se
guardan cuatro números:

- `act` — desviación típica del módulo de la aceleración. Inmune a la
  orientación del reloj, que es lo que la hace buen índice de movimiento.
- `ax`, `ay`, `az` — media de cada eje, o sea la dirección de la
  gravedad, o sea **la postura**.

Lo segundo importa más de lo que parece. **Ponerse de pie hunde el RMSSD
tanto como un disgusto serio**, y no es emoción: es el reflejo
barorreceptor compensando la caída de presión. Sin esta señal, el modelo
aprendería que levantarse de la silla es estrés. Con ella, el pipeline
calcula `posture_change` (ángulo entre la gravedad al principio y al
final de la ventana) y puede descartar o penalizar esas ventanas.

En los datos sintéticos, `act` acaba siendo la feature con más peso del
modelo, con signo negativo. Es correcto y es lo que se buscaba: el modelo
aprende que estrés agudo es *variabilidad baja **estando quieto***.

---

## 5. Cuidado con lo que le haces a Garmin Connect

Grabar una "actividad" de ocho horas todos los días le destroza a Garmin
Connect el estado de entrenamiento, la carga aguda y el Body Battery. Es
un efecto secundario real y molesto que no suele mencionarse.

La app crea la sesión con `Activity.SPORT_GENERIC` a propósito: el
deporte genérico no computa como entrenamiento. Aun así, si vas a hacer
esto meses, plantéate descargar los `.fit` por USB y borrar la actividad
de Connect, o directamente no sincronizar.

---

## 6. Batería, comodidad y el límite real

- **Batería.** Watch-app en primer plano, sin GPS, con ANT+ y pantalla
  casi siempre apagada: una jornada laboral entra sin apuros en un
  Epix Pro.
- **Tamaño del fichero.** 1 Hz × 8 h = 28 800 registros con una docena de
  campos: unos pocos MB. Irrelevante.
- **La banda de pecho.** Aquí está el límite real, y no es técnico. Ocho
  horas seguidas con una banda es incómodo, irrita la piel y los
  electrodos se secan. Lo realista son **bloques de 3 a 6 horas**
  cubriendo la franja donde de verdad te pasan cosas. Es mejor tener
  cuatro horas de señal limpia que ocho de las cuales tres son artefactos
  por electrodo seco.

Humedece los electrodos antes de ponerte la banda. En serio: la mayoría
de los datos malos de HRV vienen de ahí, no del algoritmo.

---

## 7. Extracción de los ficheros

Se guardan en `/GARMIN/ACTIVITY/` de la memoria del reloj. Se conecta por
USB (el Epix Pro monta como dispositivo MTP) y se copian. Mejor eso que
exportar desde Garmin Connect: el fichero original va sin procesar.

---

## 8. Sobre tu pregunta: ¿es real el dato de estrés intenso?

Sí, con matices que conviene tener claros desde el principio.

**Lo que se mide no son emociones.** Es la respuesta del sistema nervioso
autónomo. Ante estrés agudo se activa el simpático, se suprime el tono
vagal, el corazón se vuelve metronómico y la variabilidad se desploma.
Esa firma es inconfundible en los datos crudos. Lo que no se puede saber
por la HRV es *por qué*: la firma de una discusión, de un susto y de un
café doble se parecen mucho.

**Ventanas.** El RMSSD sobre 60 s sigue estando bien correlacionado con
el de 5 minutos, que es el estándar; por debajo de ~30 s deja de
estarlo. Por eso la ventana en vivo es de 60 s. Las métricas
frecuenciales necesitan al menos 2 minutos para que la banda LF tenga
dos ciclos completos, y por eso no están en el modelo del reloj.

**Sobre LF/HF**, ya que aparecía en el planteamiento inicial: no mide
"balance simpático-vagal". Esa interpretación lleva desacreditada años —
la LF depende sobre todo de la respiración y del reflejo barorreceptor,
no es un marcador limpio de actividad simpática. El pipeline la calcula
para explorar, pero si acaba pesando mucho en un modelo, sospecha de la
respiración antes que del sistema nervioso.

**Confusores que hay que respetar**, por orden de lo que van a molestar:

| Confusor | Efecto | Cómo se maneja aquí |
|---|---|---|
| Actividad física | Hunde la HRV igual que el estrés | Acelerómetro, feature `act` |
| Cambio de postura | Levantarse tira el RMSSD como un disgusto | `ax/ay/az`, `posture_change` |
| **Hablar** | Cambia la respiración y con ella toda la HRV | Sin resolver — ver abajo |
| Cafeína, comidas | Suben la frecuencia durante horas | La línea base móvil los absorbe |
| Ritmo circadiano | La HRV varía sistemáticamente durante el día | Línea base móvil (τ = 30 min) |
| Alcohol la noche antes | Baja la HRV todo el día siguiente | Base de ese día, no de ayer |

Lo de **hablar** merece atención porque no está resuelto y te va a
afectar: los momentos de estrés agudo de un ingeniero suelen ser
conversaciones tensas, y hablar por sí solo altera la respiración lo
bastante como para mover la HRV. Con estos sensores no se puede separar
del todo. Si al mirar los datos ves que el modelo dispara en reuniones
tranquilas, es probablemente esto.

**La normalización personal no es opcional.** Un umbral absoluto de
RMSSD no sirve: el de una persona sana puede ser 20 ms y el de otra
90 ms. Lo que significa algo es "tu RMSSD ha caído dos desviaciones
respecto a cómo estabas hace veinte minutos, y no te has movido". Todo el
modelo está construido sobre eso.

**Modera las expectativas con la intensidad.** Detectar
estrés / no-estrés es un problema tratable; distinguir nivel 1 de nivel 2
es bastante más difícil, porque la etiqueta subjetiva es ruidosa (lo que
hoy llamas nivel 2 mañana lo llamas nivel 3). Recoge los tres niveles
desde el principio — no cuesta nada y no se pueden inventar después — pero
entrena primero el modelo binario y no toques la intensidad hasta que el
binario funcione.

---

## 9. ¿Esto o el estrés que ya calcula Garmin?

Miden cosas distintas y se complementan.

El de Garmin (Firstbeat) es un modelo generalista entrenado con millones
de usuarios y está pensado para **carga alostática**: fatiga acumulada,
mala noche, digestión pesada. Es bueno en eso.

Este busca **picos agudos** de minutos. Garmin suele perdérselos: si te
mueves algo descarta la lectura, y su puntuación de 1 a 100 está
suavizada para no dar saltos. Un modelo entrenado solo con tu fisiología
y tus etiquetas puede ser bastante mejor **para tu contexto** — que es
también su limitación: no servirá para nadie más, y no debería.

---

## 10. Lo que hay que verificar el primer día

Antes de dar por buena una sola sesión larga:

1. **El campo array funciona.** Graba 10 minutos, descarga el `.fit`,
   pasa `python -m pipeline inspect`. El número de latidos tiene que
   cuadrar con `duración × frecuencia media / 60`. Si sale la mitad, el
   campo array no está guardando y toca el plan B.
2. **`rr_lost` es cero.** Si no, la cola se está llenando.
3. **Las marcas sobreviven.** Marca cinco veces con niveles distintos y
   comprueba que salen las cinco, con su nivel y su código de inicio.
4. **La banda no se despega.** Mira la fracción de artefactos que reporta
   `inspect`. Por encima del 5 % sostenido, revisa el ajuste y humedece
   los electrodos.
5. **La sesión se guarda al salir.** Cierra la app y comprueba que el
   `.fit` está en `/GARMIN/ACTIVITY/`.

Los puntos 1 y 2 son los que pueden invalidar días enteros de trabajo si
se descubren tarde.
