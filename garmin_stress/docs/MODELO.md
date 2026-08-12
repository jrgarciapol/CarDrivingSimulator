# Qué modelo, y por qué

Respuesta a "¿qué modelo ligero de ML sería el más adecuado para empezar
con este dataset pequeño e iterativo?".

**Regresión logística regularizada.** Y no es conservadurismo.

---

## Por qué una regresión logística

**Por el tamaño del conjunto.** Después de una semana buena tendrás del
orden de 25-40 episodios marcados, que dan quizá 200-400 ventanas
positivas frente a varios miles de negativas. Con eso, cualquier modelo
con más capacidad memoriza. Un random forest encontrará estructura en el
ruido y te dará una validación preciosa que no se sostendrá el lunes
siguiente.

**Por las probabilidades calibradas.** Es lo que permite elegir el
umbral por presupuesto de falsas alarmas (más abajo). Un bosque da
"probabilidades" que son fracciones de votos y no están calibradas; con
ellas, "0,8" no significa 80 % de las veces.

**Porque cabe en el reloj.** Cinco multiplicaciones y una suma. La
alternativa — exportar cien árboles a Monkey C como condicionales
anidados — es posible pero es un generador de código que hay que
mantener, depurar y volver a verificar en cada reentrenamiento.

**Porque los coeficientes se leen.** Y eso es un test. Si sale que el
estrés correlaciona con RMSSD alto, hay un error en los datos o en el
etiquetado, y lo ves. Con un bosque no ves nada.

Un aviso sobre esa última ventaja, porque tiene letra pequeña: el
coeficiente de una regresión multivariante **no** es la correlación
marginal de esa feature. Con features fisiológicamente acopladas — y la
frecuencia cardíaca y la HRV lo están, y mucho — un coeficiente puede
salir con el signo "equivocado" sin que nada esté mal. Por eso el informe
de entrenamiento imprime **dos columnas**: el AUC de cada feature *por
separado*, que es donde se comprueba la fisiología, y el coeficiente del
modelo, que es otra cosa.

```
  Feature          AUC solo   coef. modelo
    z_mean_hr        0.641 sube    +0.997
    z_sdnn           0.521 sube    +0.920
    z_log_rmssd      0.328 baja    -0.456
    z_pnn50          0.345 baja    +0.192
    act              0.365 baja    -4.828
```

Lo que hay que mirar es la columna del medio: con estrés sube la
frecuencia y bajan `log_rmssd` y `pnn50`. Eso es fisiología correcta. Si
esa columna sale al revés, no sigas: revisa el etiquetado.

## Y el techo de referencia

En cada entrenamiento se entrena también un *gradient boosting* poco
profundo, solo para saber cuánto se está dejando sobre la mesa. Si le
saca mucha ventaja a la logística, la respuesta correcta **no** es
desplegar el boosting: es mirar qué está capturando y convertirlo en una
feature nueva (una interacción, un umbral, una ventana distinta). Así se
gana capacidad sin perder ni la calibración ni la portabilidad.

---

## Las tres decisiones de validación que más importan

### 1. Nada de particiones aleatorias

Las ventanas se solapan: la de las 10:00:15 y la de las 10:00:30
comparten 45 de sus 60 segundos. Repartirlas al azar entre entrenamiento
y prueba mete prácticamente la misma ventana a los dos lados y da un AUC
de 0,97 que no significa **nada**.

Se valida **dejando un día fuera** (`LeaveOneGroupOut` por día). Además
de ser lo correcto, es la pregunta que interesa: ¿funcionará mañana?

Con un solo día de datos el pipeline avisa y parte el día por la mitad,
pero ese número es optimista y está etiquetado como tal.

### 2. PR-AUC, no accuracy

Los episodios de estrés agudo son el 2-10 % del tiempo. Un modelo que
diga siempre "no hay estrés" acierta el 95 % de las veces. La accuracy
aquí no mide nada, y el ROC-AUC es demasiado indulgente con clases tan
desbalanceadas.

El informe imprime siempre el PR-AUC **junto a lo que sacaría el azar**
(la proporción de positivos), porque un PR-AUC de 0,38 es excelente si el
azar da 0,10 y malo si da 0,35.

### 3. El umbral se elige por presupuesto de interrupciones

No en 0,5, que no tiene ninguna propiedad especial. Se elige el umbral
**más sensible que respeta un máximo de falsas alarmas al día** (4 por
defecto, `--max-false-alarms`).

Un modelo que te pregunta veinte veces al día es un modelo que vas a
desinstalar el jueves, por bueno que sea su AUC.

Y un aviso no es "una ventana por encima del umbral": son todas las
ventanas seguidas por encima, colapsadas, más un periodo refractario de
10 minutos. Contar ventanas multiplicaría por cuatro las alarmas
aparentes sin que el reloj vibrase ni una vez de más.

---

## Aprendizaje activo: cuándo preguntar

Aquí hay una trampa que conviene ver antes de caer en ella.

El instinto es preguntar cuando el modelo está **muy seguro** de que hay
estrés. Para ti como usuario está bien. Para **aprender** es justo lo que
menos aporta: si el modelo ya está seguro, tu respuesta no le enseña casi
nada.

Los casos que más enseñan son los que caen **cerca de la frontera de
decisión**. Eso es muestreo por incertidumbre, y es de lo poco en
aprendizaje activo que funciona de forma consistente.

Así que el presupuesto de preguntas se reparte:

- `p >= P_ALERT` → **alerta**. Útil para ti, confirma verdaderos
  positivos.
- `P_UNC_LO <= p <= P_UNC_HI` → **duda**. Útil para el modelo.

Con dos límites duros: al menos 10 minutos entre preguntas y un máximo de
8 por sesión. Si preguntas más, dejas de contestar, y las respuestas
apresuradas estropean más datos de los que aportan.

## Y por qué el botón manual sigue haciendo falta en fase 4

Porque sin él solo puedes medir tres de las cuatro casillas de la matriz
de confusión. Lo que el botón captura y las preguntas no:

- **Falsos negativos.** Tuviste un pico y el reloj no lo vio, así que no
  preguntó. Sin el botón, ese caso **no existe en tus datos** y el modelo
  nunca aprenderá a cogerlo. Es el error que más importa y el único que
  no se puede recuperar de otra forma.
- **Sesgo de confirmación.** Si solo aprende de momentos que él mismo
  eligió, el modelo se reafirma en lo que ya cree y su cobertura se
  encoge con cada iteración.

Por eso las marcas espontáneas y las respuestas a preguntas se guardan
con **códigos distintos** (1-3 frente a 11-13): son estadísticamente
distintas — las espontáneas están sesgadas hacia lo memorable, las
preguntadas hacia donde el modelo ya miraba — y hay que poder separarlas
al analizar.

---

## El problema de los negativos, que es más grave de lo que parece

Tú marcas cuando hay estrés. No marcas cuando no lo hay. Así que el
etiquetado supone que **todo lo no marcado es calma**, y eso es falso:
los episodios que se te pasaron también están ahí dentro, etiquetados
como negativos. En la literatura esto es aprendizaje *positive-unlabeled*
y mete ruido justo en la clase mayoritaria.

Tres mitigaciones, y conviene usar las tres:

1. **El botón "estoy tranquilo".** No es relleno. Un negativo declarado
   vale mucho más que la ausencia de marca, y por eso pesa 1,0 frente al
   0,3 de los negativos por silencio.
2. **Las respuestas "no" a las preguntas del reloj.** Negativos
   declarados en momentos que el modelo consideraba dudosos: exactamente
   donde más falta hacen.
3. **La zona gris.** Las ventanas cercanas a una marca de estrés pero
   fuera del episodio no se etiquetan de ninguna forma. Meterlas como
   calma sería enseñar que el estado justo anterior a un episodio es
   tranquilidad.

Un objetivo razonable: **de 3 a 5 marcas de calma al día**, repartidas.
Cuestan dos toques y son de lo más valioso que vas a recoger.

---

## Cuántos días hacen falta

Muy a ojo, y dependerá de cuántos episodios tengas de verdad:

| Días | Qué esperar |
|---|---|
| 1 | Comprobar que la cadena funciona. Ningún número es creíble. |
| 3-5 | Primer modelo entrenable. Validación entre días ya significativa. Suficiente para desplegar en fase 4. |
| 10-15 | El modelo empieza a estabilizarse. Los coeficientes dejan de bailar entre reentrenamientos. |
| 20+ | Se puede intentar la intensidad (nivel 1/2/3) como problema ordinal. |

Con menos de 20 ventanas positivas el pipeline avisa explícitamente de
que lo que salga es una anécdota, no una medida.

---

## Si no funciona

En orden de probabilidad:

1. **Mira la columna de AUC univariante.** Si `log_rmssd` no baja con el
   estrés, el problema está en el etiquetado, no en el modelo.
2. **Mira la fracción de artefactos** (`inspect`). Por encima del 10 % la
   banda no está haciendo contacto y todo lo demás da igual.
3. **Mira si tus marcas llegan muy tarde.** Si casi todas dicen "hace 10
   min o más", la ventana de etiquetado está tapando episodio y no
   episodio a partes iguales. Marca antes, aunque sea con menos
   precisión en el nivel.
4. **Comprueba que hay negativos declarados.** Si son cero, la clase
   negativa es puro ruido.
5. **Sube la ventana a 120 s** (`--window 120`). Menos ventanas pero cada
   una con una estimación de HRV más estable. A veces compensa.
6. **Y considera que quizá tus episodios no sean fisiológicamente
   intensos.** El estrés cognitivo sostenido de "esto no me sale" tiene
   una firma mucho más tenue que un sobresalto. Es un resultado legítimo,
   y saberlo también vale.
