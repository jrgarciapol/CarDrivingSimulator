# CarDrivingSimulator v3.2 → v4.0
## Plan de evolución física basado en el código actual

Este proyecto YA tiene:

- modelo de 4 ruedas independientes;
- masas no suspendidas;
- suspensión por rueda;
- heave/pitch/roll;
- barras estabilizadoras;
- bump stops;
- anti-dive/anti-squat;
- camber estático y camber gain;
- caster;
- toe;
- neumático combinado;
- load sensitivity;
- relaxation length;
- temperatura;
- diferencial abierto/LSD/viscoso/bloqueado;
- motor;
- transmisión;
- ABS;
- aerodinámica;
- FFB;
- circuitos con curvatura, rasante y peralte;
- batería extensa de tests.

NO quiero rehacer estas partes desde cero.

Quiero evolucionar el modelo actual hacia una simulación físicamente más coherente.

---

## FASE 0 — CONGELAR LA REFERENCIA

Antes de cambiar nada:

1. Ejecutar todos los tests.
2. Guardar resultados.
3. Guardar los valores actuales de:
   - 0-100;
   - 100-0;
   - velocidad máxima;
   - cargas Fz;
   - slip;
   - yaw;
   - roll;
   - pitch;
   - RPM;
   - wheelspin;
   - FFB.
4. Crear una referencia reproducible.

No aceptar una mejora subjetiva que rompa una propiedad física existente.

---

# FASE 1 — AUDITORÍA CUANTITATIVA DEL MODELO ACTUAL

No modificar todavía.

Crear un pequeño sistema de telemetría/debug capaz de registrar:

Por rueda:

- Fz;
- Fx;
- Fy;
- slip ratio;
- slip angle;
- camber;
- omega;
- velocidad de contacto;
- temperatura;
- grip utilizado.

Por vehículo:

- ax;
- ay;
- yaw rate;
- roll;
- pitch;
- heave;
- engine RPM;
- engine torque;
- wheel torque;
- brake torque;
- steering torque.

Ejecutar escenarios:

1. parado;
2. 100 km/h recta;
3. aceleración;
4. frenada 1 g;
5. curva 1 g;
6. frenada + curva;
7. aceleración + curva;
8. wheelspin;
9. lift-off;
10. piano;
11. cresta.

Comparar las magnitudes con cálculos independientes.

---

# FASE 2 — NUEVA SUITE DE TESTS FÍSICOS

Añadir tests que no sean simplemente "el coche hace X".

## 2.1 Peso estático

Con:

M = 1250 kg
g = 9.81
front distribution = 0.546

esperar aproximadamente:

Fz_front_total = 6692 N
Fz_rear_total = 5568 N

y:

Fz_FL ≈ Fz_FR ≈ 3346 N
Fz_RL ≈ Fz_RR ≈ 2784 N

con pequeñas diferencias únicamente si la configuración lo justifica.

---

## 2.2 Transferencia longitudinal

Para una aceleración/frenada dada:

ΔFz = m·ax·h/L

Comparar el resultado teórico con la suma de Fz del modelo.

No sustituir el modelo dinámico por esta ecuación.

Usarla únicamente como referencia de validación.

---

## 2.3 Transferencia lateral

Para una aceleración lateral dada:

ΔFz_total ≈ m·ay·h/t

Comparar:

- transferencia total;
- distribución por eje;
- efecto de ARB;
- efecto de torsión de chasis.

---

## 2.4 Conservación de carga vertical

En contacto:

ΣFz ≈ mg + Fdownforce

teniendo en cuenta las componentes normales de la carretera/peralte cuando correspondan.

La transferencia entre ruedas no debe crear ni destruir carga vertical.

---

# FASE 3 — MEJORAR EL MODELO DE NEUMÁTICO

NO eliminar inmediatamente el modelo actual.

Crear una implementación alternativa seleccionable:

`TIRE_MODEL = "legacy"`
`TIRE_MODEL = "hybrid"`

El modelo híbrido debe tener:

### Longitudinal

Curva independiente:

Fx = f(slip_ratio, Fz, temperature, camber)

### Lateral

Curva independiente:

Fy = f(slip_angle, Fz, temperature, camber)

### Combinado

Combinar ambas mediante una formulación continua de saturación.

No utilizar simplemente una magnitud radial:

rho = sqrt(slip² + alpha²)

como única variable de forma.

La razón es que un neumático real tiene curvas longitudinales y laterales diferentes y su interacción no es perfectamente circular.

---

# FASE 4 — MEJORAR EL SLIP A BAJA VELOCIDAD

Actualmente se utiliza:

denom = max(abs(v_along), 1.5)

No eliminar esta protección de golpe.

Crear dos regímenes:

### Alta velocidad

Utilizar definición normal de slip.

### Baja velocidad

Utilizar velocidad relativa de contacto y fricción estática/dinámica.

La transición debe ser continua.

Objetivos:

- arrancada suave;
- aparcamiento;
- giro de volante a baja velocidad;
- marcha atrás;
- transición parada → rodadura.

Crear tests específicos.

---

# FASE 5 — RELAXATION LENGTH REAL

Mantener el parámetro actual:

TIRE_RELAX_LENGTH

pero comprobar que la fuerza lateral no se actualice simplemente con una aproximación algebraica.

Utilizar:

d(alpha_effective)/dt =
(Vx / L_relax) · (alpha - alpha_effective)

o equivalente.

La longitud de relajación debe depender de velocidad de forma que:

- a alta velocidad la respuesta sea rápida;
- a baja velocidad no aparezcan tiempos de respuesta absurdos.

---

# FASE 6 — CARGA Y TEMPERATURA

Mantener load sensitivity y temperatura actuales.

Pero desacoplar claramente:

μ(Fz)
μ(T)
μ(camber)

para evitar que un efecto se contabilice dos veces.

Validar con una matriz:

Fz × temperatura × camber.

La salida debe ser suave y monótona donde corresponda.

---

# FASE 7 — MOTOR DINÁMICO

Sustituir progresivamente el filtro artificial de RPM por una dinámica de motor.

Implementar:

I_engine * omega_dot =
T_combustion
- T_friction
- T_pumping
- T_driveline

El par de combustión debe depender de:

- RPM;
- throttle.

La curva actual puede seguir siendo la fuente de la curva base.

NO hace falta utilizar una tabla enorme todavía.

---

# FASE 8 — EMBRAGUE

Convertir el embrague simplificado en un acoplamiento dinámico.

Debe existir:

- clutch capacity;
- slip;
- transferencia de par;
- pedal position.

El sistema debe permitir que el motor y la transmisión tengan velocidades diferentes durante el cambio.

---

# FASE 9 — TRANSMISIÓN

Separar claramente:

engine omega
→ clutch
→ gearbox
→ final drive
→ differential
→ wheel omega

Validar conservación de potencia aproximadamente:

P_engine ≈ P_wheels / efficiency

salvo pérdidas y almacenamiento de energía rotacional.

---

# FASE 10 — DIFERENCIAL

Mantener las cuatro modalidades actuales.

Para LSD:

separar explícitamente:

- preload;
- power locking;
- coast locking;
- torque capacity;
- speed difference.

El comportamiento debe depender de la diferencia real de velocidad de las ruedas.

Crear tests de:

- aceleración en curva;
- levantamiento;
- una rueda descargada;
- cambio de sentido de par.

---

# FASE 11 — INTEGRACIÓN ACOPLADA

No subir simplemente PHYSICS_HZ.

Actualmente la simulación utiliza Euler semi-implícito y algunos acoplamientos usan fuerzas del paso anterior.

Crear un predictor/corrector opcional.

Prioridad:

1. neumático;
2. rueda;
3. chasis.

Comparar estabilidad y resultados con el integrador actual.

Mantener el integrador actual como referencia.

---

# FASE 12 — SUSPENSIÓN

NO cambiar la arquitectura de suspensión existente.

Auditar:

- spring;
- damper;
- ARB;
- bump stop;
- unsprung mass;
- tire spring.

Comprobar especialmente que:

ARB

redistribuye transferencia lateral

pero no cambia:

ΣFz.

Comprobar también que:

anti-dive / anti-squat

cambia el camino de transmisión de la fuerza y el pitch, pero no crea/destruye transferencia de carga.

---

# FASE 13 — CAMBER

Mantener:

- static camber;
- body roll;
- camber gain;
- caster camber.

Pero separar:

1. geometría;
2. orientación de la rueda;
3. efecto de camber sobre Fy;
4. efecto de camber sobre μ.

No introducir dos veces la misma penalización.

Validar el camber real de cada rueda en:

- parado;
- 0.5 g;
- 1 g;
- 1.5 g.

---

# FASE 14 — DIRECCIÓN Y FFB

El FFB debe proceder principalmente de:

- pneumatic trail;
- mechanical trail;
- caster;
- lateral force;
- scrub radius.

Mantener los efectos artificiales:

- kerb;
- grass;
- road texture;
- engine idle;

como canales separados.

Nunca mezclarlos con el torque físico de neumático.

Objetivo:

cuando el neumático delantero se aproxima a saturación:

→ pneumatic trail disminuye
→ aligning torque disminuye
→ volante se aligera.

---

# FASE 15 — AERODINÁMICA

Mantener:

Fdownforce ∝ v²

pero separar:

- downforce;
- drag;
- aero balance.

Comprobar que la downforce entre correctamente en Fz y por tanto en la capacidad de neumático.

Validar:

0
50
100
150
200
250 km/h.

---

# FASE 16 — SUPERFICIES

Mantener el sistema actual por rueda.

Mejorar gradualmente:

- μ;
- rolling resistance;
- temperatura;
- vibración;
- audio.

Especialmente importante:

transición asfalto → piano → hierba

sin saltos artificiales.

---

# FASE 17 — AUDIO

Sólo después de estabilizar la física.

Actualmente el audio es procedural.

Mantenerlo procedural inicialmente.

Pero sustituir el modelo actual:

RPM + throttle → sonido

por:

RPM
+
engine load
+
engine acceleration
+
gear
+
vehicle speed
+
wheel slip
+
surface
+
wind.

Separar:

ENGINE
INTAKE
EXHAUST
MECHANICAL
DRIVELINE
TIRES
WIND
SURFACE
SHIFT

Los neumáticos deben tener:

- lateral scrub;
- longitudinal wheelspin;
- braking scrub;

como componentes diferentes.

---

# FASE 18 — CÁMARA

Mantener el movimiento de carrocería actual.

Pero separar:

physical roll/pitch

de

visual exaggeration.

El parámetro `CAR_BODY_MOTION_EXAG` puede seguir existiendo.

La cámara no debe modificar la física.

---

# FASE 19 — VALIDACIÓN FINAL

Comparar versión actual y nueva en:

### Dinámica

- 0-100;
- 100-0;
- vmax;
- skidpad;
- frenada en curva;
- aceleración en curva.

### Neumáticos

- peak slip;
- force curve;
- combined slip;
- load sensitivity.

### Suspensión

- natural frequency;
- damping;
- wheel hop;
- load transfer.

### Dirección

- steering torque;
- aligning torque;
- saturation.

### Drivetrain

- RPM;
- wheel torque;
- wheelspin;
- engine braking.

---

# PRINCIPIO FUNDAMENTAL

No quiero más parámetros simplemente porque el simulador pueda tenerlos.

Quiero que cada parámetro corresponda a un fenómeno físico identificable.

No sustituir una aproximación funcional que ya funciona por un modelo más complejo si no mejora el comportamiento observable.

La prioridad es:

1. coherencia física;
2. estabilidad numérica;
3. respuesta al límite;
4. sensación de conducción;
5. audio;
6. complejidad.

Implementar cada fase separadamente y mantener todos los tests anteriores.