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

**Física del vehículo:**
- Modelo de bicicleta con deriva de neumáticos (curva tipo Pacejka con
  saturación): subviraje estable en el límite y sobreviraje de potencia si
  pisas a fondo en curva (tracción trasera con círculo de fricción).
- Transferencia de carga al frenar/acelerar.
- Motor con curva de par, limitador, y caja de 6 marchas + marcha atrás con
  levas.
- Relación de dirección real (900° de volante ≈ ±37° en las ruedas).

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
| `TIRE_MU` | Agarre del asfalto (baja a ~0.7 para "lluvia") |
| `TIRE_REAR_GRIP_FACTOR` | <1.0 hace el coche sobrevirador (drift) |

## Consejos de conducción

- El volante comunica: cuando en plena curva **se aligera de golpe**, el tren
  delantero está saturado — abre un poco la dirección o levanta gas.
- Frena en recta: al frenar el peso pasa al eje delantero y el trasero pierde
  agarre.
- En 2ª/3ª a fondo el trasero puede patinar (aviso `TRACCION` en pantalla).
- Los pianos vibran con frecuencia proporcional a la velocidad; la hierba
  resta mucho agarre.

## Estructura del código

```
simulator/
  main.py     bucle principal (eventos, física a 120 Hz, render, FFB)
  config.py   toda la configuración: mapeo, FFB, física, circuito
  wheel.py    entrada DirectInput del volante y efectos de force feedback
  physics.py  modelo del vehículo (neumáticos, motor, transmisión)
  track.py    definición del circuito y superficies
  render.py   carretera pseudo-3D, coche y HUD
  audio.py    sonido de motor sintetizado
  font.py     fuente bitmap del HUD
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
