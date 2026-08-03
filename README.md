# CarDrivingSimulator

Simulador de conducción sencillo para Windows con soporte de **volante
Thrustmaster** (T300, T150, TMX, T248, TX…) y sus pedales, con **force
feedback realista** calculado a partir de la física del vehículo.

## Qué simula

**Force feedback (DirectInput):**
- **Par de autoalineado**: el volante se endurece con el apoyo en curva y se
  **aligera cuando el neumático delantero pierde agarre** (el aviso clásico de
  subviraje de un coche real).
- Volante pesado al aparcar (muelle + amortiguación a baja velocidad) que se
  libera en marcha.
- Vibración de **pianos**, **hierba**, textura del asfalto con la velocidad y
  ralentí del motor.
- Sacudida al cambiar de marcha.

**Física del vehículo (4 ruedas independientes):**
- Cada rueda tiene su velocidad de giro: **bloqueo de frenada real** (una
  rueda bloqueada agarra menos y no dirige), patinaje de tracción y **ABS**
  desconectable por configuración.
- Neumáticos con curva combinada tipo Pacejka (círculo de fricción continuo),
  **sensibilidad a la carga** y retardo de respuesta lateral (*relaxation
  length*).
- **Suspensión completa**: altura, cabeceo y balanceo con muelle y
  amortiguador por rueda y barras estabilizadoras por eje. La transferencia
  de carga (frenar carga el morro, la curva carga las ruedas exteriores)
  emerge de la suspensión; apurando, la rueda interior puede llegar a
  levantarse.
- **Tracción configurable**: propulsión (RWD), delantera (FWD) o total (AWD),
  con **diferencial** abierto, autoblocante o bloqueado por eje.
- Motor con curva de par, **freno motor**, limitador con histéresis y caja de
  6 marchas + marcha atrás con levas.
- **Pendientes y rasantes físicas**: las subidas frenan, las bajadas empujan
  y las crestas descargan el coche (se siente en el volante); aparcado en
  pendiente, el peso se desplaza al eje que corresponde.
- **Carga aerodinámica**: el apoyo crece con el cuadrado de la velocidad y
  pasa por la sensibilidad a la carga del neumático (más aplomo en curvas
  rápidas y más peso en el volante).
- **Geometría anti-dive/anti-squat** e **inercia del motor acoplada** a las
  ruedas motrices (en 1ª cuesta mucho más hacer patinar; al reducir se
  siente la retención del volante motor).
- **Camber thrust**: al tumbarse la carrocería en el apoyo las ruedas se
  inclinan y pierden agarre — los coches altos y blandos subviran más.
- **Peralte** con física completa: la gravedad empuja hacia el vértice, la
  fuerza centrípeta aprieta el coche contra el asfalto (más agarre y más
  peso en el volante) y la carrocería se tumba hacia el lado bajo.
- **Masas no suspendidas**: cada rueda tiene su grado de libertad vertical
  y el neumático es un muelle contra el asfalto — sobre un piano agresivo
  la rueda "vuela" y pierde la carga aunque el chasis lo filtre.
- **Temperatura del neumático**: derrapar y frenar fuerte calienta la
  goma, el aire la enfría; fría o recalentada agarra menos (temperaturas
  en vivo en la telemetría F2).
- **Camber gain**: la suspensión gana caída al comprimirse y endereza la
  rueda exterior en el apoyo (cada coche según su geometría).
- Superficie por rueda: con dos ruedas en la hierba el coche tira hacia ese
  lado, como en la realidad.
- Relación de dirección real (900° de volante ≈ ±37° en las ruedas).
- Verificado con una batería de **45 pruebas físicas** (`python tests/test_physics.py`):
  0-100 en ~7 s, frenada 100-0 en ~39 m con ABS (y peor sin él), subviraje
  estable en el límite, AWD saliendo más rápido que RWD, deriva por
  peralte, etc. El modelo está explicado ecuación a ecuación en
  [`docs/FISICA.md`](docs/FISICA.md).

**Entorno:** renderizador **3D real** (proyección en perspectiva de la malla
de la carretera por triángulos, con malla adaptativa, peralte inclinando la
calzada y cámara solidaria al chasis: cabecea al frenar y sube y baja con la
suspensión), cronómetro de vueltas y sonido de motor y chirrido de
neumáticos sintetizados. Cuatro circuitos, elegibles en el menú de arranque:

- **Silverstone** (5,9 km) y **Spa-Francorchamps** (7,0 km) reales,
  importados del eje central escaneado del
  [racetrack-database de la TU München](https://github.com/TUMFTM/racetrack-database).
  La base solo trae la planta, así que el relieve (82 y 105 m de desnivel) y
  el peralte (hasta 6°) son sintéticos: plausibles y deterministas.
- **Óvalo peraltado** (2,1 km): curvas de 180° con 18° de peralte — se toman
  a más de 170 km/h donde en llano el límite serían ~150.
- El circuito de pruebas integrado (2,8 km, con colinas y dos curvas
  peraltadas).
- Puedes importar más circuitos del mismo repositorio con
  `python tools/import_track.py <entrada.csv> simulator/tracks/<nombre>.csv`
  (genera también relieve y peralte; `--sin-peralte` / `--sin-rasante` los
  desactivan).

**Ayudas de pilotaje:**
- **Trazada ideal** sobre el asfalto (tecla `L`): verde = margen de sobra,
  ámbar = al límite, **rojo = ya no llegas a frenar para la siguiente curva**
  (calculado con la distancia de frenada real, como en los juegos
  comerciales).
- **Balizas de colores** en los bordes (amarillas a la izquierda, azules a
  la derecha) para leer el trazado de la siguiente curva desde lejos.
- **Carrocería viva**: el coche en pantalla cabecea al frenar/acelerar y se
  balancea en las curvas con los ángulos reales de la suspensión (algo
  exagerados, ajustable con `CAR_BODY_MOTION_EXAG`), para leer las
  transferencias de peso de un vistazo.
- **Cambio automático** conmutables con `G` o el botón 2 del volante
  (indicador `AUTO`/`MAN` junto al cuentavueltas); las levas siguen
  activas en modo manual.
- **Cuentavueltas grande** arriba centrado, con zonas verde/ámbar/roja,
  marca del corte y la marcha en grande — siempre a la vista.
- **Tres vistas** (tecla `C` o botón 3, en ciclo): **sin coche** (cámara
  interior, por defecto), trasera cercana con la carrocería viva, y **coche
  completo en 3D** con cámara de persecución: el coche gira visiblemente
  hacia donde se dirige, con las ruedas delanteras siguiendo la dirección.
  La inicial se elige con `VIEW_MODE`.
- **Plano del circuito** (tecla `M`): minimapa arriba a la izquierda con el
  trazado completo, los próximos 600 m resaltados en ámbar, la meta y el
  coche como punto rojo — para leer la siguiente curva con antelación.
- **Cámara lenta** (tecla `T` o botón 10): 1×/0,5×/0,25×/0,1× para estudiar
  el comportamiento del coche con calma.
- **Coche fantasma**: al completar una vuelta, tu mejor vuelta de la sesión
  se reproduce como un coche translúcido sobre la pista — la referencia
  perfecta para encontrar dónde pierdes tiempo (`GHOST_ENABLED`).
- **Humo, chispas y polvo**: partículas procedurales al pasarse del límite
  de agarre — humo blanco derrapando en asfalto, chispas naranjas sobre
  los pianos y polvo en la hierba (`PARTICLES_ENABLED`).
- **ADAS (avisos acústicos)**: un pitido avisa cuando te acercas y superas
  el límite de adherencia; su frecuencia de repetición sube con la
  severidad. Subviraje (tono grave) y sobreviraje (tono agudo y urgente)
  suenan distinto para diferenciarlos de oído (`ADAS_ENABLED`).
- **Temperatura de neumáticos en F2**: el aro de color de cada círculo de
  fricción indica la temperatura de esa goma (azul fría, verde en ventana
  óptima, roja recalentada), con el valor numérico al lado.
- **Chirrido de neumáticos**: cuando una rueda supera el pico de agarre
  (bloqueo de frenada o deriva al límite en curva) se oye chirriar, con
  volumen proporcional al deslizamiento. La hierba no chirría (`SCREECH_VOLUME`).
- **Arranque y parada del motor** (tecla `E` o botón 9), con aviso grande
  `MOTOR PARADO` en pantalla; con el motor parado el coche no empuja, y en
  marcha lo frena la compresión.

**Garaje, condiciones y récords:**
- **Menú de arranque**: elige coche, circuito y estado del asfalto con las
  flechas y ENTER.
- **8 coches** definidos en `simulator/cars/*.car` (un archivo editable por
  coche): utilitario, berlina de lujo, deportivo, GT italiano, fórmula
  (sin ABS), rally AWD, todoterreno y autobús de 12 toneladas. Puedes crear
  el tuyo copiando un archivo y cambiando los valores.
- **Estado del asfalto**: seco (aglomerado), hormigón, arena o lluvia — con
  su efecto en el agarre y en la paleta visual.
- **Récords**: la mejor vuelta se guarda en `records.json` por combinación
  de circuito + coche + asfalto; el HUD arranca mostrándola como referencia
  y al batirla aparece `NUEVO RECORD` y se guarda automáticamente.

## Instalación (Windows)

1. Instala los **drivers de Thrustmaster** ([soporte oficial](https://support.thrustmaster.com))
   y comprueba el volante en el *Panel de control de Thrustmaster*.
   - Configura el giro a **900°** (o cambia `WHEEL_ROTATION_DEG` en
     `simulator/config.py` para que coincida).
   - Deja el efecto de muelle/autocentrado en "por el juego" si existe la opción.
2. Instala **Python 3.10 o superior** desde [python.org](https://www.python.org/downloads/)
   (marca la casilla *Add Python to PATH*).
3. En una consola dentro de la carpeta del proyecto:
   ```bat
   pip install -r requirements.txt
   ```
4. Conecta el volante **antes** de arrancar y ejecuta:
   ```bat
   run.bat
   ```
   o bien `python -m simulator.main`.

Si no hay volante conectado, el simulador funciona con teclado (flechas).

## Controles

| Volante Thrustmaster | Acción |
| --- | --- |
| Volante | Dirección |
| Pedal derecho | Acelerador |
| Pedal central | Freno |
| Leva derecha / izquierda | Subir / bajar marcha |
| Botón 2 | Alternar cambio automático / manual |
| Botón 3 | Cambiar vista: interior / trasera / coche completo |
| Botón 8 | Recolocar el coche |
| Botón 9 | Arrancar / parar el motor |
| Botón 10 | Cámara lenta (1× / 0,5× / 0,25× / 0,1×) |

| Teclado | Acción |
| --- | --- |
| Flechas | Conducir (si no hay volante) |
| `A` / `Z` | Subir / bajar marcha |
| `R` | Recolocar el coche |
| `F1` | Diagnóstico de ejes y botones |
| `F2` | Telemetría: círculo de fricción por rueda y deriva del chasis |
| `L` | Mostrar/ocultar la trazada ideal |
| `G` | Alternar cambio automático / manual |
| `C` | Cambiar vista: interior / trasera / coche completo |
| `E` | Arrancar / parar el motor |
| `T` | Cámara lenta (1× / 0,5× / 0,25× / 0,1×) |
| `M` | Mostrar/ocultar el plano del circuito |
| `ESC` | Salir |

## Ajustar el mapeo del volante

Cada modelo de volante puede exponer los ejes en distinto orden. Si el
acelerador o el freno no responden:

1. Pulsa **F1** dentro del simulador: verás el valor en crudo de cada eje y el
   número de cada botón al pulsarlo.
2. Pisa cada pedal y anota qué eje se mueve; pulsa las levas y anota el botón.
3. Edita `simulator/config.py` (`AXIS_THROTTLE`, `AXIS_BRAKE`,
   `BUTTON_SHIFT_UP`, `BUTTON_SHIFT_DOWN`…).

Otros ajustes útiles en `config.py`:

| Parámetro | Efecto |
| --- | --- |
| `FFB_GAIN` | Intensidad global del force feedback (0..1) |
| `FFB_INVERT` | Ponlo a `True` si el volante empuja hacia fuera de la curva |
| `FFB_KERB_MAGNITUDE` | Fuerza de la vibración de los pianos |
| `WHEEL_ROTATION_DEG` | Grados configurados en el panel Thrustmaster |
| `WHEELBASE` / `WEIGHT_DIST_FRONT` | Batalla y reparto de pesos, como en la ficha técnica |
| `ENGINE_MAX_TORQUE_NM` | Par máximo del motor (~232 CV con los 320 Nm por defecto; la potencia resultante se muestra al arrancar) |
| `FFB_SMOOTHING_S` | Súbelo si el volante da bandazos en recta |
| `AERO_DOWNFORCE` | Carga aerodinámica (súbelo para sentir un GT/fórmula) |
| `DRIVE_TYPE` | `"RWD"` propulsión, `"FWD"` delantera, `"AWD"` total |
| `DIFF_TYPE` | Diferencial: `"open"`, `"lsd"` o `"locked"` |
| `ABS_ENABLED` | `False` para frenar sin ayudas (bloqueos reales) |
| `TIRE_MU` | Agarre del asfalto (baja a ~0.7 para "lluvia") |
| `TIRE_REAR_GRIP_FACTOR` | <1.0 hace el coche sobrevirador (drift) |
| `ARB_FRONT` / `ARB_REAR` | Estabilizadoras: su reparto ajusta el equilibrio |
| `SUSP_SPRING_*` / `SUSP_DAMPER` | Rigidez y amortiguación de la suspensión |

## Consejos de conducción

- El volante comunica: cuando en plena curva **se aligera de golpe**, el tren
  delantero está saturado — abre un poco la dirección o levanta gas.
- Frena en recta: al frenar el peso pasa al eje delantero y el trasero pierde
  agarre. Con `ABS_ENABLED = False`, pasarte de frenada **bloquea las
  ruedas**: el coche sigue recto aunque gires (aviso `BLOQUEO` en pantalla) y
  frena más largo.
- En 2ª/3ª a fondo el trasero puede patinar (aviso `TRACCION`); en las
  crestas el coche se aligera y pierde agarre.
- Los pianos vibran con frecuencia proporcional a la velocidad (solo en el
  lado que los pisa); la hierba resta mucho agarre y frena el coche.
- Prueba `DRIVE_TYPE = "FWD"` o `"AWD"` y los tres diferenciales: el
  comportamiento al acelerar en curva cambia por completo.

## Estructura del código

```
simulator/
  main.py     bucle principal (menú, eventos, física a 480 Hz, render, FFB)
  config.py   configuración base documentada parámetro a parámetro
  garage.py   coches .car, condiciones del asfalto y récords
  menu.py     menú de arranque (coche + circuito + asfalto)
  wheel.py    entrada DirectInput del volante y efectos de force feedback
  physics.py  modelo del vehículo de 4 ruedas (neumáticos, suspensión,
              transmisión, diferenciales, ABS, motor, peralte)
  track.py    circuito: curvas, rasantes, peralte, superficies, baches y
              trazada ideal con envolvente de frenada
  render.py   renderizador 3D de la carretera, coche, HUD y telemetría
  audio.py    sonido de motor y chirrido sintetizados
  font.py     fuente bitmap del HUD
  cars/       los 8 vehículos (.car, parámetros comentados)
  tracks/     circuitos (silverstone, spa, ovalo)
tools/
  import_track.py  importa circuitos reales (TUM) y sintetiza relieve/peralte
  make_oval.py     genera el óvalo peraltado
docs/
  FISICA.md        el modelo físico explicado para un ingeniero
  NOTA_REVISION.md orientación para revisores del código
tests/
  test_physics.py  bateria de 45 pruebas del modelo fisico (sin volante)
```

## Solución de problemas

- **"SIN FFB" en pantalla**: cierra el Panel de control de Thrustmaster y
  cualquier otro juego (DirectInput solo permite un dueño del force feedback),
  y arranca con el volante ya conectado.
- **La fuerza va al revés** (el volante se va hacia fuera de la curva):
  pon `FFB_INVERT = True` en `config.py`.
- **No detecta el volante**: prueba otro puerto USB y comprueba que aparece en
  *Dispositivos e impresoras* → *Configuración del dispositivo de juego*.
- **Va lento**: reduce `WINDOW_WIDTH/HEIGHT` o `DRAW_DISTANCE` en `config.py`.
