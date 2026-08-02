# El modelo físico, explicado para un ingeniero

Este documento describe con detalle el modelo dinámico de `simulator/physics.py`
(y sus entradas desde `track.py`): estados, convenios, ecuaciones, método de
integración y las decisiones de diseño detrás de cada aproximación. Los
parámetros citados (`CAR_MASS`, `TIRE_MU`…) están documentados uno a uno en
`simulator/config.py`, y cada coche del garaje los redefine en su
`simulator/cars/*.car`.

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

**Grados de libertad**: 3 planos + 3 verticales + 4 de rueda + 1 de régimen
de motor = 11 GDL dinámicos. Las masas no suspendidas no se modelan por
separado (la rueda no tiene GDL vertical propio: el microrrelieve entra
como excitación directa del muelle, §3).

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

El chasis tiene 3 GDL verticales relativos al plano local de la vía:
`h` (heave, + arriba), `θ` (pitch, + morro arriba), `φ` (roll, + lado
derecho elevado). Cada esquina `i` tiene una deflexión:

```
d_i = z_bache,i − (h + θ·X_i + φ·Y_i)          (+ = muelle comprimido)
F_susp,i = k_i·d_i + c·ḋ_i                      k_i = SUSP_SPRING_FRONT/REAR
```

donde `z_bache,i` es el microrrelieve determinista muestreado bajo esa rueda
(pianos corrugados de 40 cm, ondulación de la hierba, rugosidad leve del
asfalto — `track.bump_at`). Las **barras estabilizadoras** añaden un término
proporcional a la diferencia de deflexión izquierda–derecha de cada eje:
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

La carga vertical de cada rueda es entonces:

```
Fz_i = max(0, Fz_estática,i + F_susp,i + aero_i ± anti_fz)
```

con la carga estática derivada del reparto de pesos, y la **carga
aerodinámica** `aero = AERO_DOWNFORCE·vx²` repartida entre ejes por
`AERO_DF_FRONT_SHARE`. El `max(0,·)` permite que una rueda se levante del
suelo (interior en el apoyo fuerte, crestas): con `Fz=0` no genera fuerza.

Nótese que **todas las transferencias de carga son emergentes** de esta
dinámica (frenar carga el morro porque las fuerzas de frenada crean momento
de cabeceo que comprime los muelles delanteros), no fórmulas cuasi-estáticas
`ΔFz = m·a·h/L` — por eso tienen su transitorio y su rebote naturales.

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

### Empuje por caída (camber thrust)

Al balancear, la carrocería inclina las ruedas consigo (suspensión
independiente idealizada, sin recuperación de caída). Una rueda inclinada
genera empuje lateral hacia el lado al que se tumba (como una motocicleta):

```
fy ← fy − TIRE_CAMBER_THRUST · φ · Fz
```

En curva la carrocería se tumba hacia **fuera**, así que el término se
opone a la fuerza lateral del neumático: resta agarre. El efecto escala con
el balanceo real: castiga a los coches altos y blandos (autobús,
todoterreno) y apenas a los rígidos (fórmula).

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
el **diferencial**: abierto (50/50), autoblocante o bloqueado, modelados
como acoplamiento viscoso `T_transfer = clamp( k·(ω_izda − ω_dcha), ±tope )`
con `k` y tope según el tipo (250 N·m para LSD, 450 N·m bloqueado). No es
un Salisbury con precarga/rampas, pero reproduce lo esencial: el abierto
pierde tracción con cargas asimétricas y el bloqueado empuja recto.

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
M_z = Σ_delanteras [ −fy_i · t(α_i) ]  +  (fx_FL − fx_FR)·scrub_radius
t(α) = TIRE_TRAIL · (0.15 + 0.85·max(0, 1 − |α|/α_sat))
```

- El **par de autoalineado** usa un avance neumático que cae con la deriva
  (el volante se aligera al saturar el tren delantero — el aviso clásico de
  subviraje) más un 15 % de avance mecánico residual que nunca desaparece.
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

`python tests/test_physics.py` — **39 pruebas** sin SDL ni volante, en
cuatro bloques:

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

Más el par de FFB en rango, 60 s de conducción autónoma sin divergencias y
una pasada de aceleración+frenada con los **8 coches** del garaje
(umbrales por coche: la fórmula supera 190 km/h donde el autobús pasa de
40). Como prueba de humo del juego completo:
`SDL_VIDEODRIVER=dummy python -m simulator.main --frames 300`.
