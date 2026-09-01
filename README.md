# CarDrivingSimulator

Simulador de conducción con soporte de **volante Thrustmaster** (T300,
T150, TMX, T248, TX…) y sus pedales, con **force feedback realista**
calculado a partir de la física del vehículo.

Funciona en **Windows y en Linux** (incluida la **Steam Deck**): todo pasa
por SDL2, sin una sola dependencia específica de Windows. También se puede
jugar con **mando** (Steam Deck, XBox, PlayStation) o con teclado.

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
  length*). El modelo del neumático es **seleccionable** (`TIRE_MODEL`):
  `legacy` (una curva compartida) o `brush` (curvas longitudinal y lateral
  separadas, con mezcla direccional).
- **Suspensión completa**: altura, cabeceo y balanceo con muelle y
  amortiguador por rueda y barras estabilizadoras por eje. La transferencia
  de carga (frenar carga el morro, la curva carga las ruedas exteriores)
  emerge de la suspensión; apurando, la rueda interior puede llegar a
  levantarse.
- **Tracción configurable**: propulsión (RWD), delantera (FWD) o total (AWD),
  con **diferencial** abierto, autoblocante (con tope de capacidad
  `DIFF_MAX_LOCK`), bloqueado o viscoso por eje.
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
  siente la retención del volante motor). El motor es **seleccionable**
  (`ENGINE_MODEL`): `legacy` (régimen filtrado) o `inertia` (el cigüeñal como
  grado de libertad propio: acelerón libre en punto muerto y patinaje del
  embrague en la arrancada). El cambio da un **tirón de corte de par** real
  (`SHIFT_CUT_TIME`).
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
- **Firme con rugosidad**: zonas de asfalto dañado (deterministas por
  posición, escalables con `ROAD_ROUGHNESS`) con baches grandes que hacen
  fluctuar la carga vertical y el agarre — se ven en el asfalto, se sienten
  en el temblor de cámara y en la textura del volante.
- Relación de dirección real (900° de volante ≈ ±37° en las ruedas).
- Verificado con una batería de **215 pruebas** (`python tests/`): 120 de
  comportamiento (0-100 en ~7 s, frenada 100-0 en ~39 m con ABS, subviraje
  estable en el límite, AWD saliendo más rápido que RWD, deriva por
  peralte…), más pruebas de **magnitudes contra primeros principios**
  (transferencias de carga), de **convergencia y energía del integrador**, de
  los modelos de neumático y motor, de la transmisión y de los reglajes. El
  modelo está explicado ecuación a ecuación en
  [`docs/FISICA.md`](docs/FISICA.md); la última tanda de mejoras, en
  [`docs/EVOLUCION_v3.3.md`](docs/EVOLUCION_v3.3.md).

**Entorno:** renderizador **3D real** (proyección en perspectiva de la malla
de la carretera por triángulos, con malla adaptativa, peralte inclinando la
calzada y cámara solidaria al chasis: cabecea al frenar y sube y baja con la
suspensión), cronómetro de vueltas y sonido de motor y chirrido de
neumáticos sintetizados. Cuatro circuitos, elegibles en el menú de arranque:

- **Spa-Francorchamps** (7,0 km) con **geometría y rasante REALES**: el eje
  se trazó en Google Earth y la altura de cada punto se consultó en un
  modelo digital de elevación (EU-DEM 25 m), dando el desnivel real de
  **103 m** (Eau Rouge/Raidillon incluidos). Además, el trazado se
  **idealiza a alineaciones de diseño de carreteras** (rectas, círculos y
  clotoides en planta; rasantes y acuerdos parabólicos en alzado),
  eliminando el temblor de trazar a mano — la curvatura queda 29× más lisa.
  Todo regenerable con `tools/import_kml.py --idealizar`.
- **Silverstone** (5,9 km) importado del eje central escaneado del
  [racetrack-database de la TU München](https://github.com/TUMFTM/racetrack-database);
  como esa base solo trae la planta, su relieve (82 m) es sintético. El
  peralte (hasta 6°) es sintético en ambos.
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
| `M` | Mostrar/ocultar el plano del circuito **completo** (visión de conjunto) |
| `N` | Mostrar/ocultar la **planta del tramo que viene** (1 km, con los radios) |
| `ESC` | Salir |

| Mando (Steam Deck, XBox, PlayStation) | Acción |
| --- | --- |
| Stick izquierdo | Dirección |
| Gatillo derecho (R2/RT) | Acelerador (**analógico**) |
| Gatillo izquierdo (L2/LT) | Freno (**analógico**) |
| R1 / L1 | Subir / bajar marcha |
| A | Arrancar / parar el motor |
| B | Recolocar el coche |
| X | Cambiar vista |
| Y | Alternar cambio automático / manual |
| Select / View | Cámara lenta |

El mando se detecta solo. Un volante reconocido siempre tiene prioridad.

## Ayudas en pantalla

- **Plano del circuito completo** (tecla `M`, arriba a la izquierda): dónde
  estás dentro de la vuelta. Da la **visión de conjunto**.
- **Planta del tramo que viene** (tecla `N`, abajo a la derecha): el
  kilómetro siguiente en planta, con el coche abajo y el trazado
  desenrollándose por delante, como las notas de un copiloto. Tres capas
  de lectura:
  - **la forma**, para anticipar si una curva encadena con otra o da a una
    recta;
  - **el color** de cada punto según su radio (rojo < 80 m, ámbar < 200 m,
    verde por encima), así que la severidad se lee sin mirar números;
  - **el radio en metros** de las curvas más cerradas, que es el dato duro
    para **comparar circuitos** entre sí.

  El panel es semitransparente para no tapar la carretera, y la escala se
  ajusta en saltos discretos (nunca de forma continua, que haría el dibujo
  ilegible) con una regla de referencia abajo.

## Jugar en Steam Deck

El simulador corre **nativo** en SteamOS, sin Proton: es Python + SDL2 y el
force feedback usa `SDL_Haptic`, que en Linux se apoya en la interfaz de
force feedback de evdev. Si SDL no encuentra el háptico del volante —pasa en
la Deck con el T300RS— el juego habla **directamente con evdev**
(`simulator/ffb_evdev.py`), que es la misma vía por la que los juegos de
Steam sí mueven el volante. Se ve cuál de las dos está en uso con
`.venv/bin/python -m simulator.main --ffb`, o —sin necesidad del entorno
virtual, solo con el Python del sistema— con `python3 tools/ffb_info.py`.

### Instalación

En modo Escritorio, abre una consola en la carpeta del proyecto y ejecuta:

```bash
bash tools/instalar_steamdeck.sh
./jugar.sh
```

> **`pip: command not found`** o **`error: externally-managed-environment`.**
> Son lo normal en una Steam Deck y no falla nada del juego: **SteamOS trae
> Python 3 pero su imagen viene sin pip**, con el sistema de archivos raíz
> de solo lectura y el Python del sistema marcado como *externally-managed*
> (PEP 668), que rechaza instalar nada en él. El script de arriba lo evita:
> **no toca el Python del sistema**, crea un entorno virtual en `.venv`
> dentro del proyecto (que sí admite instalar paquetes) y, si ese entorno
> no trae pip, se lo inyecta con el `get-pip.py` oficial. Es lo más limpio
> en un sistema inmutable: no ensucia el sistema y se deshace con
> `rm -rf .venv`.
>
> Si prefieres hacerlo a mano, es exactamente esto:
> ```bash
> python3 -m venv --without-pip .venv
> curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
> .venv/bin/python /tmp/get-pip.py
> .venv/bin/python -m pip install pysdl2 pysdl2-dll numpy
> .venv/bin/python -m simulator.main --rendimiento
> ```

Instala **solo lo que el juego necesita** (`pysdl2`, `pysdl2-dll`,
`numpy`). El `matplotlib` de `requirements.txt` es únicamente para los
editores de trazado de `tools/`, que no se manejan con un mando: son unos
70 MB que en la Deck no pintan nada.

**Lo que NO conviene hacer** es `sudo steamos-readonly disable` y tirar de
`pacman`. Funciona, pero cada actualización de SteamOS reemplaza la
partición del sistema y se pierde, además de dejar el equipo en un estado
que Valve no da por soportado.

Si prefieres aislarlo del todo, **distrobox** viene de serie en SteamOS y
es la opción más robusta ante actualizaciones:

```bash
distrobox create --name sim --image archlinux:latest
distrobox enter sim
sudo pacman -S --needed python python-pip sdl2
pip install pysdl2 numpy && python -m simulator.main --rendimiento
```

### Añadirlo a Steam — IMPRESCINDIBLE para que el mando funcione

Fuera de Steam, la Deck **no anuncia su mando como un gamepad**: el juego lo
confundiría con un volante (el stick haría de dirección y los gatillos no
responderían). Quien lo convierte en un mando de Xbox de verdad es **Steam
Input**, y solo actúa si el juego se lanza desde Steam.

1. En modo Escritorio: **Steam → Añadir un juego → Añadir un juego que no
   sea de Steam → EXAMINAR** y elige `jugar.sh` (si no ves los `.sh`, pon el
   filtro en *Todos los archivos*).
2. Es una aplicación **nativa** de Linux: **no** fuerces ninguna herramienta
   de compatibilidad (Proton).
3. Lánzalo **desde Steam** (Modo Juego o Escritorio). Ahora los gatillos
   (R2 gas, L2 freno), el stick y los botones funcionan.

Si necesitas jugar sin Steam, puedes **forzar** el modo de entrada con
`--mando`, `--volante` o `--teclado` (o `INPUT_MODE` en `config.py`). Ojo:
`--mando` solo funciona si SDL reconoce el gamepad; en una Deck fuera de
Steam no lo reconoce, así que la vía buena sigue siendo lanzarlo desde Steam.

**Mando completo (la cruceta suple a las teclas F1/F2, que la Deck no
tiene):** stick izquierdo dirección · R2/L2 gas y freno · R1/L1 marchas ·
A motor · B recolocar · X vista · Y automático · cruceta ↑ telemetría,
← plano, → planta, ↓ trazada · START volver al menú.

### Ajustes pensados para la Deck

- **Resolución automática** (`WINDOW_AUTO`): la ventana se encaja en la
  pantalla manteniendo la proporción. En una Deck, 1920×1080 pasa a
  1280×720 en vez de salirse por los bordes. Se puede forzar con
  `--ventana 1280x800` o pedir pantalla completa con `--completa`.
- **`--rendimiento`**: apaga la bruma atmosférica y el sombreado solar y
  recorta el alcance de dibujado a 140 segmentos. Elegido midiendo: la
  bruma sola cuesta el 22 % del fotograma. **La física no se toca** —
  cuesta un 8 % y bajarla degradaría el force feedback.
- **Dirección adaptada al stick**: zona muerta reescalada, curva
  progresiva, velocidad de giro limitada y **tope que se cierra con la
  velocidad** (a 170 km/h queda el 30 % del recorrido). Sin esto un stick
  es incontrolable, porque recorre todo su rango en dos centímetros.
- **Vibración** en vez de par: el motor bajo avisa del eje que pierde
  agarre (el equivalente al aligeramiento del volante) y el alto da los
  pianos, la hierba y el golpe del cambio.

### Volante en la Steam Deck — OJO con Steam Input

Con el **volante T300 conectado a la Deck** el juego lo prefiere
automáticamente. Ten en cuenta que necesita alimentación propia y un hub
USB-C.

Sobre el **force feedback**: en la Deck, `SDL_JoystickIsHaptic` dice que no
para el T300RS aunque el volante sí tenga fuerza en los juegos de Steam. Como
esos juegos van por Proton, y el force feedback de Wine se implementa sobre
evdev, el núcleo está publicando la capacidad y el que no la encuentra es
SDL. Por eso el juego tiene una **segunda vía**: manda los efectos él mismo
con `ioctl(EVIOCSFF)` sobre `/dev/input/eventN`.

Para comprobarlo hay dos herramientas:

```bash
python3 tools/ffb_info.py            # qué publica el núcleo y con qué permisos
python3 tools/ffb_info.py --probar   # EMPUJA el volante: la prueba definitiva
.venv/bin/python -m simulator.main --ffb   # lo mismo, más lo que ve SDL
```

`tools/ffb_info.py` usa **solo la biblioteca estándar**: funciona con el
`python3` del sistema, sin `.venv`, sin pip y sin instalar nada. En una Deck
recién arrancada es lo primero que conviene ejecutar.

**El fallo más habitual**: lanzar desde Steam es lo que hace falta para que
funcione *el mando* de la Deck… pero es justo lo que **rompe el volante**.
Steam Input se apodera del volante y lo vuelve a presentar como un mando
virtual de Xbox, así que el juego ya no ve un Thrustmaster: ve un gamepad, y
la dirección y los pedales dejan de tener sentido. El volante hace su giro de
calibración y enciende el LED verde (eso es el driver, no el juego), pero
dentro no responde.

Para jugar **con volante** en la Deck:

1. En Steam, propiedades del juego → **Mando** → **Desactivar Steam Input**.
2. Lánzalo y comprueba qué ve el juego:
   ```bash
   ./jugar.sh --dispositivos
   ```
   Y para ver el **mapeo real de los ejes** (que en Linux NO coincide con el
   de Windows), un monitor en vivo que se para solo a los 60 s y guarda el
   informe en `diagnostico_ejes.txt`:
   ```bash
   ./jugar.sh --ejes            # o --ejes --segundos 90
   ```
   > **Sin Ctrl+C en la Deck**: el teclado virtual de Steam (**STEAM + X**)
   > sirve para escribir, pero **no tiene tecla `Ctrl`**, así que no se puede
   > cortar un programa con Ctrl+C. Por eso `--ejes` se **para solo** pasado
   > el tiempo (60 s por defecto) y guarda el informe: no hace falta ninguna
   > combinación de teclas.
   >
   > Si alguna vez necesitas parar algo a mano, abre otra pestaña en Konsole
   > (*New Tab*) y ejecuta `pkill -f simulator.main`. La otra vía es conectar
   > un teclado USB o Bluetooth al hub.
   Debe aparecer el Thrustmaster **por su nombre**, con
   `gamepad_para_SDL=no` y `force_feedback=si`. Si en su lugar sale un mando
   virtual, Steam Input sigue activo.
3. Si aun así no lo coge, fuérzalo con `./jugar.sh --volante`.

Resumen: **mando de la Deck → lanzar desde Steam con Steam Input activo;
volante → Steam Input desactivado** (o lanzarlo fuera de Steam con
`--volante`).

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
| `DIFF_TYPE` | Diferencial: `"open"`, `"lsd"`, `"locked"` o `"viscous"` |
| `TIRE_MODEL` | Neumático: `"legacy"` (curva compartida) o `"brush"` (long/lat separadas) |
| `ENGINE_MODEL` | Motor: `"legacy"` (régimen filtrado) o `"inertia"` (cigüeñal con inercia) |
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
  ffb_evdev.py force feedback hablando directamente con evdev (Linux/Steam Deck)
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
  import_kml.py    importa desde KML/KMZ de Google Earth (+ elevación real)
  alignment_editor.py  editor gráfico de alineaciones en planta (rectas,
                   círculos y clotoides) que ajusta el trazado a mano y
                   exporta al formato del simulador (requiere matplotlib)
  alignment_geom.py    geometría del editor (ajustes y ensamblado, testeable)
  make_oval.py     genera el óvalo peraltado
  ffb_info.py      diagnostico del force feedback sin SDL (solo stdlib)
docs/
  FISICA.md        el modelo físico explicado para un ingeniero
  NOTA_REVISION.md orientación para revisores del código
tests/
  test_physics.py           120 pruebas de comportamiento del modelo fisico
  test_referencia_fisica.py magnitudes contra primeros principios (transferencias)
  test_integrador.py        convergencia temporal y energia del integrador
  test_neumatico_brush.py   curvas long/lat separadas (TIRE_MODEL brush)
  test_motor_inercia.py     cigueñal con inercia + embrague (ENGINE_MODEL)
  test_transmision.py       corte de par al cambiar + diferenciales
  test_settings.py          persistencia de reglajes y guardado de coches
  test_ffb_evdev.py         ioctl y estructuras del force feedback de Linux
```

Los modelos seleccionables (`TIRE_MODEL`, `ENGINE_MODEL`, `DRIVE_TYPE`,
`DIFF_TYPE`) y el resto de reglajes se pueden cambiar desde el menú de
**AJUSTES** del juego, sin editar `config.py`.

## Solución de problemas

- **"SIN FFB" en pantalla**: cierra el Panel de control de Thrustmaster y
  cualquier otro juego (DirectInput solo permite un dueño del force feedback),
  y arranca con el volante ya conectado.
- **La fuerza va al revés** (el volante se va hacia fuera de la curva):
  pon `FFB_INVERT = True` en `config.py`.
- **No detecta el volante**: prueba otro puerto USB y comprueba que aparece en
  *Dispositivos e impresoras* → *Configuración del dispositivo de juego*.
- **Va lento**: reduce `WINDOW_WIDTH/HEIGHT` o `DRAW_DISTANCE` en `config.py`.

## Licencia

Copyright (C) 2026 Jesús Rafael García Pol

Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo
los términos de la **Licencia Pública General de GNU (GNU GPL) versión 3**,
publicada por la Free Software Foundation. Se distribuye con la esperanza de
que sea útil, pero **SIN NINGUNA GARANTÍA**. El texto completo está en el
archivo [`LICENSE`](LICENSE) y en <https://www.gnu.org/licenses/>.

En la práctica esto significa que cualquiera puede usar, estudiar y mejorar
este simulador, pero **si lo distribuye o publica una versión modificada
debe mantener esta misma licencia, conservar la autoría y publicar también
su código fuente**: no se puede convertir en un producto cerrado.
