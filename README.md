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
  y las crestas descargan el coche (se siente en el volante).
- Superficie por rueda: con dos ruedas en la hierba el coche tira hacia ese
  lado, como en la realidad.
- Relación de dirección real (900° de volante ≈ ±37° en las ruedas).
- Verificado con una batería de 23 pruebas físicas (`python tests/test_physics.py`):
  0-100 en ~7 s, frenada 100-0 en ~39 m con ABS (y peor sin él), subviraje
  estable en el límite, AWD saliendo más rápido que RWD, etc.

**Entorno:** circuito de 2,8 km con curvas rápidas, chicane, horquilla y
cambios de rasante, gráficos pseudo-3D, cronómetro de vueltas y sonido de
motor sintetizado que sigue a las RPM.

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

| Teclado | Acción |
| --- | --- |
| Flechas | Conducir (si no hay volante) |
| `A` / `Z` | Subir / bajar marcha |
| `R` | Recolocar el coche |
| `F1` | Diagnóstico de ejes y botones |
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
  main.py     bucle principal (eventos, física a 240 Hz, render, FFB)
  config.py   toda la configuración: mapeo, FFB, física, circuito
  wheel.py    entrada DirectInput del volante y efectos de force feedback
  physics.py  modelo del vehículo de 4 ruedas (neumáticos, suspensión,
              transmisión, diferenciales, ABS, motor)
  track.py    circuito: curvas, pendientes, superficies y baches
  render.py   carretera pseudo-3D, coche y HUD
  audio.py    sonido de motor sintetizado
  font.py     fuente bitmap del HUD
tests/
  test_physics.py  bateria de 23 pruebas del modelo fisico (sin volante)
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
