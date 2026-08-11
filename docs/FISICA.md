# El modelo físico, explicado para un ingeniero

Este documento describe con detalle el modelo dinámico de `simulator/physics.py`
(y sus entradas desde `track.py`): estados, convenios, ecuaciones, método de
integración y las decisiones de diseño detrás de cada aproximación. Los
parámetros citados (`CAR_MASS`, `TIRE_MU`…) están documentados uno a uno en
`simulator/config.py`, y cada coche del garaje los redefine en su
`simulator/cars/*.car`.

> **¿Buscas el porqué en vez del cómo?** [`NEUMATICO.md`](NEUMATICO.md)
> explica desde cero la física del contacto neumático-asfalto —deriva, modelo
> de cepillo, curva de Pacejka, par autoalineante, elipse de fricción y
> transferencia de carga—, con figuras y con el mapa de qué está modelizado y
> dónde. Este documento describe el modelo; aquél, los fundamentos.

Contenido:

1. [Convenios y variables de estado](#1-convenios-y-variables-de-estado)
2. [Bucle de integración](#2-bucle-de-integración)
3. [Suspensión y dinámica vertical del chasis](#3-suspensión-y-dinámica-vertical-del-chasis)
4. [El neumático](#4-el-neumático)
5. [Dinámica de cada rueda (integrador híbrido)](#5-dinámica-de-cada-rueda-integrador-híbrido)
6. [Dinámica plana del chasis](#6-dinámica-plana-del-chasis)
7. [La carretera: pendientes, peralte y superficies](#7-la-carretera-pendientes-peralte-y-superficies)
8. [Motor y transmisión](#8-motor-y-transmisión)
9. [Frenos y ABS](#9-frenos-y-abs)
10. [Force feedback](#10-force-feedback)
11. [Validación](#11-validación)

---

## 1. Convenios y variables de estado

**Ejes del cuerpo**: `x` hacia delante, `y` hacia la **derecha**, guiñada
positiva = giro a la derecha (sistema levógiro visto desde arriba, elegido
para que "positivo = derecha" en todo el código). Ruedas numeradas
`0=delantera izquierda, 1=delantera derecha, 2=trasera izquierda,
3=trasera derecha`; posiciones respecto al centro de masas
`X_POS = [+a, +a, −b, −b]`, `Y_POS = [−t/2, +t/2, −t/2, +t/2]`, con
`a = CG→eje delantero`, `b = CG→eje trasero` (derivadas de `WHEELBASE` y
`WEIGHT_DIST_FRONT`) y `t = CAR_TRACK_WIDTH`.

**Coordenadas de carretera** (curvilíneas, tipo Frenet): el coche no vive en
un plano XY global sino pegado al circuito:

- `s` — abscisa curvilínea a lo largo del eje del circuito (m);
- `n` — desplazamiento lateral respecto al eje (m, positivo a la derecha);
- `psi` — rumbo relativo a la tangente local de la carretera (rad).

La geometría del circuito se define por segmento de 4 m: curvatura `κ(s)`
(positiva = curva a derechas), cota `y(s)`, peralte `β(s)` (positivo = borde
izquierdo elevado, el peralte correcto de una curva a derechas) y si hay
piano. Ventaja del sistema curvilíneo: la "salida de pista", la superficie
bajo cada rueda y la trazada ideal son triviales de evaluar, y no hay
acumulación de error de posición global.

**Estado dinámico** (`CarState`): `vx, vy, yaw_rate` (dinámica plana);
`heave, pitch, roll` y sus velocidades (dinámica vertical del chasis,
relativas al plano local de la vía); `omega[4]` (velocidad angular de cada
rueda); `rpm`, `gear`; y magnitudes derivadas expuestas para HUD/FFB
(`fz[4]`, `slip_ratio[4]`, `slip_angle[4]`, `steer_column_torque`…).

**Grados de libertad**: 3 planos + 3 verticales del chasis + 4 verticales
de masa no suspendida (`zu`, §3) + 4 de giro de rueda + 1 de régimen de
motor = 15 GDL dinámicos, más 4 estados térmicos (temperatura de cada
goma, §4).

## 2. Bucle de integración

La física corre a **480 Hz** (`PHYSICS_HZ`), desacoplada del render mediante
un acumulador de tiempo con sub-pasos (patrón *fixed timestep*): el bucle de
`main.py` ejecuta tantos pasos de `Car.step(dt=1/480)` como tiempo real haya
transcurrido (con la escala de cámara lenta aplicada). Todos los
integradores son de primer orden (Euler semi-implícito: primero velocidad,
luego posición) **salvo** la rotación de la rueda en régimen de rodadura,
que usa una solución exponencial exacta (§5) porque es el único subsistema
rígido del modelo.

Orden de un paso (elegido para que cada bloque use el estado más fresco
posible sin resolver sistemas acoplados):

1. peralte y superficie/baches bajo cada rueda;
2. suspensión → cargas verticales `Fz` por rueda;
3. dinámica vertical del chasis (heave/pitch/roll);
4. motor, transmisión y reparto de par por rueda;
5. par de freno por rueda (con ABS);
6. fuerzas de neumático por rueda (con las `ω` del paso anterior);
7. dinámica plana del chasis y cinemática s/n/psi;
8. rotación de cada rueda con el par y las fuerzas ya calculados;
9. par de columna de dirección para el FFB.

Los acoplamientos diferidos un paso (p. ej. el momento de cabeceo usa las
fuerzas de neumático del paso anterior) introducen un retardo de ~2 ms,
despreciable frente a las constantes de tiempo del vehículo (>100 ms).

## 3. Suspensión y dinámica vertical del chasis

Cada esquina es un sistema de **dos masas**: el chasis (masa suspendida) y
la mangueta+rueda (masa no suspendida `m_u = UNSPRUNG_MASS`, con posición
vertical propia `zu_i`). El muelle y el amortiguador de suspensión trabajan
entre chasis y mangueta; el neumático es otro muelle mucho más rígido
(`TIRE_VERT_STIFF`, con su amortiguación interna `TIRE_VERT_DAMP`) entre la
mangueta y el asfalto:

```
d_i = zu_i − (h + θ·X_i + φ·Y_i)               (+ = muelle comprimido)
c_i = COMPRESION si ḋ_i > 0, si no EXTENSION   (por eje y por sentido)
F_susp,i = k_i·d_i + c_i·ḋ_i + F_tope,i         (± estabilizadoras)
F_tope,i = SUSP_BUMP_STIFF·(d_i − hueco_i)²     si d_i > hueco_i, si no 0
q_i = z_bache,i − zu_i                          (compresión de la goma)
F_neum,i = K_t·q_i + C_t·q̇_i
m_u·z̈u_i = F_neum,i − F_susp,i − a_rasante
```

donde `z_bache,i` es el microrrelieve determinista muestreado bajo esa rueda
(pianos corrugados de 40 cm, ondulación de la hierba, rugosidad leve del
asfalto — `track.bump_at`). La frecuencia propia de la masa no suspendida
(*wheel hop*) queda en ~14 Hz con los valores por defecto: sobre un piano
agresivo a velocidad (excitación de 40–60 Hz) la rueda **no puede seguir
los dientes y vuela** — la carga de contacto oscila hasta anularse aunque
el chasis apenas se mueva (verificado en la batería: Fz mínima 0 N sobre el
piano con el chasis moviéndose ~11 mm). El chasis (`h`, `θ`, `φ`) siente
solo `F_susp`, filtrada por la suspensión, como en un coche real. A 480 Hz
el modo de wheel hop está sobradamente resuelto (ω·dt ≈ 0.2) y el
amortiguamiento conjunto lo deja en ζ ≈ 0.6–0.7.

La **amortiguación va separada por eje y por sentido**: un amortiguador
real no opone lo mismo comprimiéndose que extendiéndose, y la extensión
suele ser 2-3 veces más dura. La razón es que en compresión pelea contra
el muelle (que ya sostiene el coche) mientras que en extensión controla la
energía que el muelle devuelve, que es lo que hace **rebotar**. Es el
reglaje que gobierna el comportamiento **transitorio** —cómo entra el
coche en curva y cómo se asienta al salir— frente a muelles y barras, que
mandan en el estacionario.

Los **topes de recorrido** impiden que la suspensión se comprima sin fin.
Son **cuadráticos**, como un tope de poliuretano: los primeros milímetros
apenas se notan y luego se dispara. Sin ellos, una hondonada fuerte
comprimía la suspensión **317 mm**, más recorrido del que tiene un coche
entero; con topes se queda en 109 mm. Aparte de proteger, son un
**reglaje**: un coche con mucha carga aerodinámica se sienta en los topes
en recta rápida, manteniendo la altura constante —que es lo que la aero
necesita— sin muelles durísimos que arruinarían la curva lenta.

Las **barras estabilizadoras** añaden un término proporcional a la
diferencia de deflexión izquierda–derecha de cada eje:
`±ARB·(d_izda − d_dcha)/2`.

Ecuaciones del chasis (m = `CAR_MASS`, momentos de inercia de `config`):

```
ḧ = ΣF_susp/m − κ_v·vx²  − press/m
θ̈ = ( Σ F_susp,i·X_i + Fx_neum·h_cg·(1 − anti) ) / I_pitch
φ̈ = ( Σ F_susp,i·Y_i + Fy_neum·h_cg           ) / I_roll
```

- `κ_v·vx²` es la aceleración vertical impuesta por la **curvatura vertical**
  de la rasante (cresta: κ_v<0 ⇒ el suelo "cae" y el coche se descarga;
  badén al revés). Así el aligeramiento en las crestas es emergente.
- `Fx_neum, Fy_neum` son las sumas de fuerzas de neumático en ejes cuerpo
  **aplicadas a nivel del suelo**, a `h_cg = CAR_CG_HEIGHT` por debajo del
  CG. Usar las fuerzas de contacto (y no `m·ax`) tiene una consecuencia
  física importante: aparcado en pendiente con freno, los neumáticos
  sostienen el coche y el morro se hunde aunque `ax = 0`; y en un peralte,
  yendo recto, la carrocería se tumba hacia el lado bajo.
- `anti = SUSP_ANTI_PITCH` es la **geometría anti-hundimiento**: los brazos
  de suspensión desvían una fracción del momento de cabeceo directamente al
  chasis sin pasar por los muelles. Esa fracción **no desaparece**: se
  reinyecta como transferencia de carga instantánea entre ejes
  (`±anti·Fx_neum·h_cg/(2·batalla)` en las `Fz`), de modo que la
  transferencia longitudinal total se conserva exactamente y solo cambia el
  reparto entre el camino elástico (muelles, con retardo) y el geométrico
  (instantáneo).
- `press` es el término de **peralte** (§7).

La carga vertical de cada rueda sale del **muelle del neumático** (no del
de suspensión): si la goma se despega del asfalto la carga es cero aunque
el muelle de suspensión siga empujando la mangueta:

```
Fz_i = max(0, Fz_estática,i + F_neum,i + aero_i ± anti_fz)
```

con la carga estática derivada del reparto de pesos, y la **carga
aerodinámica** `aero = AERO_DOWNFORCE·vx²` repartida entre ejes por
`AERO_DF_FRONT_SHARE`. El `max(0,·)` permite que una rueda se levante del
suelo (interior en el apoyo fuerte, crestas): con `Fz=0` no genera fuerza.

Nótese que **todas las transferencias de carga son emergentes** de esta
dinámica (frenar carga el morro porque las fuerzas de frenada crean momento
de cabeceo que comprime los muelles delanteros), no fórmulas cuasi-estáticas
`ΔFz = m·a·h/L` — por eso tienen su transitorio y su rebote naturales.

### Rigidez torsional del chasis

El bastidor no es infinitamente rígido: el tren delantero y el trasero
balancean ángulos distintos, acoplados por el muelle de torsión del chasis
`K_c` (`CHASSIS_TORSION_STIFF`, N·m/° por coche: monocasco de fórmula 60k,
GT ~35k, turismo 10-25k, chasis de largueros ~7k). Se resuelve el equilibrio
cuasi-estático (los modos de torsión reales, 20-40 Hz, quedan muy por encima
de la dinámica de conducción):

```
K_f·φ_f + K_c·(φ_f − φ_r) = M_f          M_i = Fy_eje,i · h_cg
K_r·φ_r + K_c·(φ_r − φ_f) = M_r          K_i = (k_muelle,i + k_barra,i)·B²/2
Δφ = (M_f·K_r − M_r·K_f) / (K_f·K_r + K_c·(K_f + K_r))
```

La torsión `Δφ` (filtrada a ~50 ms) se superpone al balanceo rígido:
cada eje usa `φ ± Δφ/2` al evaluar sus muelles y barras. Con `K_c → ∞`
(o 0 = desactivado) se recupera el chasis rígido exacto. El efecto físico
es el conocido de pista: un chasis blando **desacopla los ejes** — el
reparto de transferencia de carga se acerca al de los momentos generados
y las barras estabilizadoras **pierden autoridad**, así que el balance
sub/sobrevirador responde menos al reglaje. No cambia la rapidez de
respuesta de la dirección (eso es la longitud de relajación del neumático
y la inercia de guiñada); cambia el *balance*.

## 4. El neumático

### Deslizamientos

Para cada rueda se calcula la velocidad del punto de contacto en el plano
(incluyendo el término de guiñada) y, en las delanteras, se proyecta al eje
de la rueda girada el ángulo de dirección `δ`:

```
v_along = componente de la velocidad según el plano de la rueda
v_side  = componente perpendicular
s = (ω·R − v_along) / max(|v_along|, 1.5)      deslizamiento longitudinal
α = atan2(v_side, max(|v_along|, 1.5))          ángulo de deriva
```

El suelo `1.5 m/s` en el denominador regulariza la singularidad a velocidad
nula (un clásico de los modelos de slip: sin él, s→∞ al parar).

### Curva combinada (Pacejka simplificada)

Los dos deslizamientos se normalizan por sus picos y se combinan en un único
deslizamiento adimensional (elipse de fricción continua):

```
s_n = s/s_pico          (TIRE_PEAK_SLIP_RATIO)
a_n = α/α_pico          (TIRE_PEAK_SLIP_ANGLE_DEG)
ρ  = √( (s_n/λ)² + a_n² )          λ = TIRE_LONG_GRIP_RATIO = 1.10
F  = μ_ef·Fz·sin( C·atan(B·ρ) )    B = 2.07, C = 1.4
fx = F·(s_n/λ)/ρ·λ ;   fy = −F·a_n/ρ
```

La *fórmula mágica* `sin(C·atan(B·ρ))` con estos B y C alcanza el máximo
exactamente en `ρ = 1` y decae hacia ~80 % en deslizamiento profundo: una
rueda bloqueada o patinando agarra menos que una en el pico, y el coche
cruzado frena peor — el comportamiento que castiga pasarse del límite. El
factor `λ` da al neumático un 10 % más de capacidad longitudinal que
lateral (elipse en vez de círculo).

### Sensibilidad a la carga

```
μ_ef = μ_base · clamp( 1 − k_load·(Fz − Fz₀)/Fz₀ , 0.6, 1.3 )
```

con `Fz₀` la carga estática **de esa rueda** y `k_load = TIRE_LOAD_SENS`.
Es la no-linealidad esencial del comportamiento de un coche: transferir
carga *reduce* el agarre total de un eje (lo que gana la rueda cargada no
compensa lo que pierde la descargada). De aquí emergen el subviraje al
frenar en curva, el efecto de las estabilizadoras sobre el equilibrio
(más barra delante ⇒ más transferencia delante ⇒ subvirador) y la
sensibilidad al reparto de frenada.

### Caída (camber): ángulo, empuje y huella

Lo único que le importa al neumático es su ángulo **contra el asfalto**, que
suma cuatro aportaciones (detalle completo en [`NEUMATICO.md`](NEUMATICO.md)
§6):

```
γ_i = lado_i · γ_est − φ − lado_i · SUSP_CAMBER_GAIN · d_i  [+ caster, eje directriz]
                                                   lado_i = signo(Y_i)
```

- **γ_est**: CAIDA ESTATICA de reglaje (`STATIC_CAMBER_FRONT_DEG` /
  `_REAR_DEG`, por coche). Negativa = la rueda abraza el coche por arriba.
  Se pone para que la rueda EXTERIOR quede plana cuando la carrocería se
  tumbe: en el DEPORTIVO, −2° llevan la exterior de 1,93° a 0,04° en curva.
- **−φ**: el balanceo la tumba hacia **fuera**, deshaciendo la estática.
- **camber gain**: al comprimirse, la geometría recupera caída negativa. El
  autobús (eje rígido, 0) lo sufre entero; un paralelogramo la recupera.
- **caster**: solo el eje directriz, la ganada al girar.

El signo por lado importa: la misma compresión tumba la rueda izquierda
hacia la derecha y la derecha hacia la izquierda (en un apoyo simétrico por
aero los dos empujes se cancelan exactamente).

Ese ángulo produce **dos efectos que compiten**, y de su contraste sale el
óptimo de reglaje:

```
fy   ← fy + TIRE_CAMBER_THRUST · γ_i · Fz_i        (LINEAL: empuje)
mu_i ← mu_i · (1 − TIRE_CAMBER_PATCH · γ_i²)       (CUADRATICO: huella)
```

- **Empuje por caída** (*camber thrust*): una rueda inclinada genera fuerza
  lateral hacia el lado al que se tumba, como una motocicleta. Crece
  **linealmente**.
- **Pérdida de huella**: inclinada no apoya plana, la carga se concentra en
  un hombro y el agarre disponible baja. Crece **cuadráticamente** (1° →
  0,5 %; 3° → 4,9 %; 5° → 13,7 %).

Para inclinaciones pequeñas gana el empuje; pasado ~1° manda la huella. Si
la pérdida fuese lineal, el neumático siempre querría apoyar plano y no
existiría óptimo alguno. De aquí sale el compromiso real: **−4° de caída
estática alargan la frenada 100-0 de 35,1 a 41,3 m**, a cambio de agarre en
curva. La caída además **calienta más** la goma (`TIRE_CAMBER_HEAT`): es el
desgaste asimétrico del hombro interior.

### Temperatura

Cada goma integra un estado térmico de primer orden: la potencia de
fricción calienta (con la tasa limitada por la masa térmica de la goma) y
el aire refrigera con la velocidad:

```
Ṫ = min(6 C/s, H·|F_neum|·|v_deslizamiento|) − C·(2 + |vx|)·(T − T_amb)
μ ← μ · max(0.72, 1 − TIRE_TEMP_SENS·(T − T_opt)²)
```

La parábola invertida centrada en `TIRE_TEMP_OPT` penaliza la goma fría
(a 25 °C rinde ~77 %: hay que ponerla en temperatura) y la recalentada por
abusar del derrape. Las gomas de competición (`.car` de la fórmula y el
GT) tienen el óptimo más alto: más margen caliente, peor en frío.

### Retardo de respuesta lateral (relaxation length)

La carcasa no genera su fuerza lateral instantáneamente: necesita rodar una
distancia `L_r = TIRE_RELAX_LENGTH` para deformarse. Se modela como filtro
de primer orden **en distancia recorrida**, no en tiempo:

```
fy_estado += (fy_estacionaria − fy_estado) · min(1, v·dt/L_r)
```

A alta velocidad el retardo es corto; casi parado, largo — lo que además
estabiliza el modelo a baja velocidad.

## 5. Dinámica de cada rueda (integrador híbrido)

Cada rueda integra su velocidad angular con la EDO:

```
I_ef·ω̇ = T_aplicado − fx·R          T_aplicado = T_tracción + T_freno
```

### Tamaño de rueda: el catálogo (`WHEEL_SPEC`)

El radio `R`, la inercia `I` y la masa de la rueda deben ser COHERENTES
entre sí (una rueda mayor pesa y "vuela" más). En vez de tres números
sueltos, cada coche declara su neumático con la designación real
`ANCHO/PERFIL R LLANTA` (p.ej. `245/35R18`) y el garaje deriva:

```
R = llanta/2 + ancho·perfil                       (exacto, por definición)
m_cubierta ≈ 9.5·(ancho/205)·(R/0.316)²           (empírica)
m_llanta   ≈ 8.0·(llanta/16)²                     (aleación)
I ≈ 0.92·m_cub·(0.94·R)² + 0.55·m_lla·r_lla²      (anillo + disco)
UNSPRUNG_MASS = UNSPRUNG_HUB_MASS + rueda completa
```

Un valor explícito en el `.car` gana al derivado (llanta de magnesio del
fórmula, gemelas del autobús). Efectos emergentes de montar rueda mayor:
desarrollo más largo (menos empuje, `F = T/R`), arranque y frenada más
perezosos (más `I`, también reflejada del motor), y peor contacto sobre
bache (más masa no suspendida). Medido con el deportivo: 0–100 en 6.78 s
con 205/50R15 frente a 7.40 s con 285/30R21.

El **ancho** además compra agarre — no por el Coulomb de escuela (área
irrelevante) sino por la **sensibilidad a la carga**: más huella = menos
presión de contacto = el μ cae menos al sobrecargar. Con el ancho `w` del
`WHEEL_SPEC` (referencia 205 mm):

```
μ_ef        = μ · (w/205)^0.10          (huella: algo más de agarre)
sens_carga  = LS · (205/w)^0.6          (ancho: menos caída al cargar)
calentamiento ∝ (205/w)^0.5             (más goma que calentar)
```

Por eso el eje motriz de un RWD potente monta goma ancha: la transferencia
al acelerar castiga menos a un neumático ancho. Medido: en apoyo saturado,
8.15 m/s² con 155 mm frente a 8.79 m/s² con 305 mm.

### Montaje escalonado (por eje) y transmisión

Cada eje lleva su montura (`WHEEL_SPEC_FRONT` / `WHEEL_SPEC_REAR`) y la
física trabaja con **radio, inercia y ancho por rueda** (`R_w`, `I_w`). El
fórmula reproduce el neumático real de F1: **305 delante y 405 detrás con
el mismo diámetro** (670 mm). Medido al límite, la deriva del eje trasero
baja monótonamente al ensanchar la goma trasera: 3.5° (205) → 3.2° (225) →
3.0° (275/305).

Al recalzar, el **desarrollo** cambia (`F = T/R`), así que `apply_wheel`
reescala `FINAL_DRIVE` en proporción al radio del eje motriz —lo que haría
un ingeniero al montar otra rueda— salvo que se desactive
`GEARING_KEEP_ON_WHEEL_CHANGE`. Sin recalzar, el efecto es grande: 16.3 m
en 3 s recalzado frente a 13.8 m sin recalzar con la misma rueda.

En el menú, las filas **RUEDAS DELANTE / DETRÁS** eligen del catálogo
(`WHEEL_CATALOG`, con el uso habitual de cada medida: utilitario, GT3,
fórmula, todoterreno, autobús…) sin editar archivos.

## 5b. Precesión giroscópica de las ruedas

Cada rueda es un giróscopo: su momento angular de giro `L = I·ω` apunta
según el eje transversal. Cuando ese eje gira —guiñada del coche, y en las
delanteras también el propio volante— aparece un par de precesión
perpendicular a ambos, que resulta ser un **momento de balanceo**:

```
M_balanceo = GYRO_GAIN · [ (Ω_guiñada + δ̇/STEER_RATIO)·L_del + Ω_guiñada·L_tras ]
M_volante  = GYRO_FFB_GAIN · Ω_balanceo · L_del / STEER_RATIO
```

Con el convenio de aquí sale positivo en curva a derechas: la precesión
**suma** al balanceo de la curva. Medido con el deportivo a 160 km/h: 147
N·m de par giroscópico, que añade 0.06° a los 3.0° de balanceo — real pero
sutil, como corresponde a un coche (en una moto sería dominante). Con
rueda mayor crece: 277 N·m con 325/30R21. También llega al volante como el
"peso vivo" al cambiar de apoyo rápido.

### Inercia efectiva (acoplamiento con el motor)

Con el embrague acoplado, la rueda motriz arrastra la inercia rotacional
del motor reflejada por el cuadrado de la desmultiplicación total
(resultado estándar de inercia reflejada):

```
I_ef = CAR_WHEEL_INERTIA + ENGINE_INERTIA · (ratio_marcha·grupo)² / N_motrices
```

En 1ª el término del motor domina (es mucho más difícil hacer patinar la
rueda de golpe) y al reducir se siente la retención del volante motor. Con
embrague abierto, punto muerto o motor parado, `I_ef` es solo la de la rueda.

### El problema de rigidez y la solución híbrida

Cerca de la rodadura libre, `fx ≈ k_v·(ωR − v_along)` con una rigidez

```
k_v = ∂F/∂v_slip = μ_ef·Fz·C·B / (s_pico·max(|v_along|,1.5))
```

que a baja velocidad y plena carga da constantes de tiempo
`τ = I_ef/(k_v·R²)` de **décimas de milisegundo**: integrar esto
explícitamente exigiría >5 kHz. En vez de eso, mientras la rueda está en
régimen de rodadura (fricción estática, `|s| < 0.9·s_pico` y par aplicado
por debajo del límite de agarre), la EDO linealizada se resuelve
**exactamente**:

```
ω_eq = ( v_along + (T_aplicado/R)/k_v ) / R      (deslizamiento de equilibrio)
ω ← ω_eq + (ω − ω_eq)·e^(−dt/τ)
```

Es incondicionalmente estable para cualquier `dt` y, crucialmente,
**transmite el par aplicado al suelo** (el equilibrio no es `ω = v/R` sino
el pequeño deslizamiento que genera exactamente la fuerza `T/R` — así el
freno motor y la tracción suave funcionan sin patinar).

En **deslizamiento profundo** (bloqueo, derrape de tracción) la fuerza ya
no es lineal en el deslizamiento y se integra explícitamente con la fuerza
de la curva del neumático, con dos salvaguardas: si la rueda cruza la
rodadura libre sin par suficiente para seguir deslizando, se captura al
régimen de rodadura; y una rueda frenada no invierte su sentido de giro
(para eso está la parada rígida: coche casi detenido con freno dominante ⇒
`ω = 0`).

## 6. Dinámica plana del chasis

Las fuerzas de las cuatro ruedas (las delanteras rotadas `δ`) se ensamblan:

```
ΣFx, ΣFy,  M_z = Σ ( X_i·fy_i − Y_i·fx_i )
ax = ( ΣFx − drag − f_rodadura + g_x ) / m       drag = AERO_DRAG·vx·|vx|
ay = ( ΣFy + m·g·sin β ) / m                      (β = peralte, §7)
v̇y = ay − vx·r ;   ṙ = M_z / I_z
```

con `g_x = −m·g·pendiente` (la gravedad frena en subida) y la resistencia a
la rodadura aumentada en las ruedas que pisan hierba (se "hunden"). Los
términos `vy` y `r` llevan un amortiguamiento numérico muy ligero (3 %/s y
1.5 %/s) que no altera el comportamiento pero corta derivas numéricas de
larga duración.

**Baja velocidad**: por debajo de ~1 m/s el modelo de deslizamientos pierde
sentido físico (y condicionamiento), así que la guiñada pasa a un modelo
cinemático de Ackermann amortiguado: `r = vx·tan(δ)/batalla`, `vy → 0`.
La transición es la fuente clásica de artefactos en simuladores; el suelo
de 1.5 m/s en los denominadores de slip (§4) + este cambio de modelo la
resuelven de forma robusta.

**Cinemática sobre la carretera** (acoplamiento curvilíneo):

```
ψ̇ = r − κ(s)·vx        (la curvatura de la carretera "consume" guiñada)
ṅ = vx·sin ψ + vy·cos ψ
ṡ = vx·cos ψ − vy·sin ψ
```

## 7. La carretera: pendientes, peralte y superficies

Por segmento de 4 m el circuito define `κ`, cota, piano y peralte `β`. De la
cota se precalculan la **pendiente** (`grade = dy/ds`) y la **curvatura
vertical** (`κ_v = d²y/ds²`), ambas suavizadas ±3 segmentos.

**Peralte** — tres efectos físicos, todos con la misma β:

1. *Gravedad lateral*: `+m·g·sin β` en la ecuación de `ay` — empuja hacia el
   lado bajo; en un peralte bien construido, hacia el vértice: aporta parte
   de la aceleración centrípeta y permite curvar más rápido con el mismo
   neumático.
2. *Sobrecarga*: la componente de la aceleración lateral perpendicular al
   plano inclinado aprieta el coche contra el asfalto:
   `press = m·( ay·sin β + g·(cos β − 1) )`, aplicado como fuerza externa en
   la ecuación de heave — los muelles se comprimen, las `Fz` suben con su
   dinámica natural y el agarre (y el peso del volante, vía FFB) crecen.
   En llano, `press = 0` exactamente.
3. *Balanceo*: como el momento de balanceo sale de las fuerzas de contacto a
   nivel del suelo (§3), en peralte la carrocería se tumba hacia el lado
   bajo aunque el coche vaya recto.

**Superficies**: se muestrean **bajo cada rueda** (asfalto / piano / hierba
según `n` y `s` de esa rueda): frenar con dos ruedas en la hierba genera la
guiñada asimétrica real, y el piano corrugado excita la suspensión de un
solo lado. Las condiciones del menú (hormigón/arena/lluvia) multiplican los
μ antes de arrancar.

Los circuitos importados de la base TUM (solo planta) reciben peralte y
rasante **sintéticos** deterministas (`tools/import_track.py`): peralte
hacia el interior proporcional a la curvatura suavizada (tope 6°) y rasante
como suma de ondas senoidales cerradas sobre la vuelta (pendiente máxima
combinada ~9 %). El óvalo (`tools/make_oval.py`) tiene peralte de diseño de
hasta 18°.

## 8. Motor y transmisión

**Curva de par** paramétrica (`engine_torque`): sube del 47 % del par
máximo a 1000 rpm hasta el 100 % en `ENGINE_TORQUE_PEAK_RPM`, cae al 75 %
hacia la zona roja. Todo el motor se define con 6 números en el `.car`
(par máximo, rpm de par, ralentí, zona roja, corte, freno motor) — la
potencia resultante se muestra al arrancar.

**Freno motor**: `−ENGINE_BRAKE_COEFF·(rpm/corte)·(1 − gas)`. Con el motor
apagado y engranado, arrastra además un par de compresión constante.

**Régimen**: la aguja no sigue instantáneamente a las ruedas; filtro de
primer orden con τ = 0.12 s hacia `rpm_ruedas` (o hacia el ralentí si es
mayor). **Limitador** con histéresis de 300 rpm (corta la inyección, no
"clava" la aguja). **Embrague** automático simplificado: por debajo del
régimen de ralentí equivalente patina (75 % del par, sin freno motor).

**Transmisión**: `T_rueda = T_motor·ratio·grupo·η`, repartido entre ejes
según `DRIVE_TYPE` (`AWD_FRONT_SPLIT` configurable) y dentro de cada eje por
el **diferencial**, con cuatro tipos:

```
"lsd"      T_bloqueo = ½·( PRECARGA + rampa·|T_eje| )        <- SENSIBLE AL PAR
"viscous"  T_transfer = clamp( k·(ω_izda − ω_dcha), ±250 )   <- a la VELOCIDAD
"open"     50/50
"locked"   T_bloqueo enorme
T_transfer = T_bloqueo · tanh( (ω_izda − ω_dcha) / banda )
```

El **autoblocante de discos** (`"lsd"`) es el de los deportivos y los
coches de competición, y es **sensible al par**: bloquea en cuanto pasa
par, sin esperar a que la rueda patine. Su capacidad tiene dos orígenes,
que son dos reglajes distintos:

- **`DIFF_PRELOAD`**: unos muelles Belleville aprietan los discos
  **siempre**, aun sin par. Manda con el coche soltado, en el punto de
  inflexión de la curva.
- **Rampas**, con **ángulos distintos** para cada sentido:
  `DIFF_RAMP_POWER` acelerando (tracción a la salida, a costa de subvirar
  al abrir gas) y `DIFF_RAMP_COAST` reteniendo (bloquear de más deja el
  coche perezoso al entrar). Se dan en **porcentaje de bloqueo**, como en
  la realidad: `(T_alta − T_baja) / T_total`.

El `tanh` reproduce el rozamiento **seco** de los discos (satura, no crece
sin fin) sin el corte en seco que haría oscilar la integración. Su
**banda** se ensancha con el par de bloqueo: si un solo paso pudiera
cambiar la diferencia de giro más de lo que mide la banda, el bloqueo
oscilaría de un extremo a otro y las ruedas nunca se estabilizarían.

El acoplamiento **viscoso** (`"viscous"`) es el modelo anterior y se
conserva porque es lo que monta un turismo de tracción total permanente:
reacciona a la diferencia de velocidad, es decir **después** de que la
rueda ya esté patinando. La diferencia medida es enorme: en una salida a
fondo en 2.ª, el viscoso deja que la rueda interior se dispare a 59 rad/s
de diferencia mientras el de discos la mantiene en 0,4.

**Cambio automático** (conmutable en carrera): sube cerca del corte si no
hay patinaje, baja a bajas vueltas o por kick-down (nunca a 1ª), con tiempo
de permanencia de 1.2 s y protección de sobrerégimen al reducir. Umbrales
relativos al corte de cada motor (funciona igual para el autobús a 2500 rpm
que para la fórmula a 15000).

## 9. Frenos y ABS

Par de freno por rueda con reparto `BRAKE_BIAS_FRONT`; el par máximo total
(`BRAKE_FORCE_MAX`) supera deliberadamente el agarre disponible: sin ABS,
pisar a fondo **bloquea**. El ABS (opcional por coche) es un regulador de
deslizamiento por rueda: si `s < −ABS_SLIP_TARGET` a más de 2 m/s, reduce
la presión de esa rueda (hasta el 25 %) a 8 unidades/s y la recupera a 4 —
la pulsación resultante se siente en el volante vía la textura del FFB y el
término de scrub radius.

Nota sobre la fórmula: sus frenos están dimensionados para el agarre CON
apoyo aerodinámico a alta velocidad; a baja velocidad, sin apoyo y sin ABS,
la misma presión bloquea con facilidad — como en la realidad.

## 10. Force feedback

El par que se envía al volante se construye enteramente desde la física:

```
M_z = Σ_delanteras [ −fy_i · (t_neum(α_i) + t_mec(R_i)) ]
      + (fx_FL − fx_FR)·scrub_radius

t_neum(α) = max( −f_neg·TIRE_TRAIL,  TIRE_TRAIL·(1 − |α|/α_sat) )
t_mec(R)  = R·tan(CASTER_ANGLE_DEG) + STEER_TRAIL_OFFSET
```

- El **par de autoalineado** suma **dos avances independientes**, cada uno
  con su propia física (detalle completo en [`NEUMATICO.md`](NEUMATICO.md)):
  - **Avance neumático** `t_neum`: nace de la **deformación** de la huella
    (la resultante de la fuerza lateral queda retrasada). **Se derrumba con
    la deriva** y pasado el pico llega a hacerse ligeramente **negativo**.
  - **Avance mecánico** `t_mec`: **geometría pura** del ángulo de avance
    (*caster*), el efecto «carrito de la compra». **Constante** con la
    deriva, y existiría aunque la rueda fuese rígida. Depende del **radio**,
    así que montar rueda mayor endurece el volante.
- Que uno caiga y el otro no es lo que hace que **M_z alcance su máximo
  ANTES que la fuerza lateral**: con el reglaje de serie, el par pica a ~3,9°
  de deriva cuando el agarre pica a 7°, y cae un **35 %** hasta la saturación.
  El volante se aligera como **aviso anticipado de subviraje**, pero nunca
  queda muerto porque el avance mecánico permanece.
- El **caster** además genera **caída al girar** (*caster camber gain*): la
  rueda exterior se tumba hacia dentro de la curva y empuja a favor. Es la
  razón de que los coches de competición monten mucho avance.
- El término de **scrub radius** transmite la diferencia de fuerzas
  longitudinales entre las dos ruedas delanteras: torque-steer en FWD,
  tirón al frenar con medio coche en la hierba, pulsación del ABS.
- **Sacudida por baches**: la diferencia de fuerzas de suspensión
  izquierda–derecha del eje delantero, **filtrada paso-alto** — los
  transitorios (pianos, baches) pasan; la transferencia estacionaria de las
  curvas no (sin el filtro, cancelaba el autoalineado en apoyo).
- **Amortiguación de columna** proporcional a la velocidad de giro del
  volante y creciente con la velocidad del coche (el lazo
  volante→física→FFB→mano se desestabiliza en recta rápida), más un
  suavizado paso-bajo final (`FFB_SMOOTHING_S`).
- El par de columna resultante (`M_z/STEER_RATIO·2`) se normaliza por
  `FFB_MAX_TORQUE_NM` y se envía como fuerza constante DirectInput. El
  **signo se invierte** en `wheel.py`: probado en el T300RS, un nivel
  positivo empuja en el sentido que ayuda a girar, y el autoalineado debe
  resistirse (`FFB_INVERT` lo deshace para hardware que venga al revés).
  Sobre esto se superponen los efectos de condición (muelle de
  aparcamiento, amortiguador a baja velocidad) y las texturas senoidales
  (asfalto/piano/hierba/ralentí/ABS).

## 11. Validación

`python tests/test_physics.py` — **45 pruebas** sin SDL ni volante, en
cinco bloques:

- **Aceleración y frenada**: 0–100 en rango realista, distancia de frenada
  con ABS (33–60 m desde 100), sin ABS bloquea y frena más largo, con las
  delanteras bloqueadas el coche no dirige.
- **Suspensión y transferencias**: las cargas estáticas suman el peso, la
  curva carga las ruedas exteriores, la frenada el eje delantero, la cresta
  descarga, cuesta abajo carga el morro (parado, con freno), el apoyo
  aerodinámico crece con v², el freno motor decelera.
- **Equilibrio y transmisiones**: subviraje estable en el límite, RWD/FWD
  patinan el eje correcto, AWD sale de parado al menos tan rápido como RWD,
  bloqueado tracciona más que abierto en curva, hierba a un lado desvía al
  frenar.
- **Peralte y caída**: el peralte empuja hacia el lado bajo, la curva
  peraltada carga más el coche y alivia el trabajo del neumático, el camber
  thrust resta guiñada en apoyo.
- **Masas no suspendidas y temperatura**: la rueda vuela sobre el piano
  corrugado (Fz llega a 0) mientras el chasis lo filtra, derrapar calienta
  la goma y el aire la enfría, la goma fría agarra menos, el camber gain
  recupera agarre en el apoyo.

Más el par de FFB en rango, 60 s de conducción autónoma sin divergencias y
una pasada de aceleración+frenada con los **8 coches** del garaje
(umbrales por coche: la fórmula supera 190 km/h donde el autobús pasa de
40). Como prueba de humo del juego completo:
`SDL_VIDEODRIVER=dummy python -m simulator.main --frames 300`.
