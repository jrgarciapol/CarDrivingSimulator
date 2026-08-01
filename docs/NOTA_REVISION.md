# Nota para revisión del proyecto

Este documento orienta a cualquier revisor (humano o IA) que llegue al
repositorio para auditar el código y proponer mejoras. Resume qué es el
proyecto, cómo está diseñado, qué decisiones se tomaron y dónde el feedback
aporta más valor.

## Qué es

Simulador de conducción para Windows en **Python + PySDL2** (SDL2 usa
DirectInput en Windows), pensado para un volante **Thrustmaster** con
pedales. El objetivo no es el apartado gráfico (pseudo-3D arcade deliberado)
sino **las sensaciones físicas en el volante**: todo el force feedback se
calcula desde el modelo dinámico en tiempo real, no hay efectos enlatados.

## Arquitectura

```
simulator/main.py     bucle: eventos → física (240 Hz, sub-pasos) → FFB → render
simulator/config.py   única fuente de configuración (mapeo, FFB, física, coche)
simulator/wheel.py    entrada del volante + efectos hápticos SDL/DirectInput
simulator/physics.py  modelo del vehículo (núcleo del proyecto)
simulator/track.py    circuito: curvatura, pendiente, superficies, baches
simulator/render.py   carretera pseudo-3D por franjas + HUD
simulator/audio.py    sonido de motor sintetizado (numpy, opcional)
simulator/font.py     fuente bitmap 5x7 (sin dependencias)
tests/test_physics.py 23 pruebas de comportamiento físico, sin SDL ni volante
```

## Modelo físico (physics.py)

Convenios: x adelante, **y a la derecha**, guiñada positiva = giro a la
derecha; ruedas `0=del.izda, 1=del.dcha, 2=tras.izda, 3=tras.dcha`; el coche
vive en coordenadas locales de la carretera (s = distancia, n = offset
lateral, psi = rumbo relativo).

- **Chasis**: 3 GDL planos (vx, vy, yaw) + 3 GDL verticales (altura, cabeceo,
  balanceo) con muelle/amortiguador por esquina y estabilizadoras por eje.
  Las cargas por rueda salen de la deflexión de suspensión; las
  transferencias de carga son emergentes, no fórmulas cuasi-estáticas.
- **Neumático**: curva combinada tipo Pacejka simplificada
  `F = mu·Fz·sin(C·atan(B·rho))` sobre el deslizamiento combinado
  normalizado `rho = |(s/s_pico, alfa/alfa_pico)|`, con sensibilidad a la
  carga (mu cae al cargar) y *relaxation length* lateral.
- **Ruedas**: velocidad angular propia. Integrador **híbrido**: en rodadura,
  relajación exponencial exacta al deslizamiento de equilibrio
  (incondicionalmente estable, transmite el par aplicado); en deslizamiento
  profundo (bloqueo/patinaje), integración explícita. Motivo: la EDO de la
  rueda es rígida a baja velocidad y la integración explícita pura exigiría
  >1 kHz.
- **Transmisión**: RWD/FWD/AWD configurable, diferencial viscoso por eje
  (abierto/LSD/bloqueado, con tope de par de acoplamiento), freno motor,
  limitador con histéresis e inercia de régimen, embrague automático
  simplificado.
- **Frenos**: par por rueda con reparto delantero configurable; el par máximo
  supera el agarre a propósito (sin ABS se bloquea). ABS por rueda opcional.
- **Carretera**: pendiente y curvatura vertical suavizadas por segmento
  (gravedad en cuesta, descarga en crestas); superficie y microrrelieve
  muestreados **bajo cada rueda**.
- **FFB**: par de autoalineado por rueda delantera con avance neumático
  decreciente + avance mecánico residual; sacudida por diferencia de fuerzas
  de suspensión izquierda-derecha **filtrada paso-alto** (los transitorios
  pasan, la transferencia estacionaria de las curvas no).

## Decisiones y compromisos conocidos

- Python puro + SDL: portabilidad y sencillez frente a rendimiento; la física
  cuesta ~50 µs/paso (~1 % de CPU a 240 Hz). El render por franjas es el
  coste dominante; en Windows va con renderer acelerado.
- El render es deliberadamente arcade; la física no.
- Simplificaciones asumidas (candidatas a futuro, por orden de valor):
  temperatura/desgaste/presión de neumáticos, carga aerodinámica, peralte,
  geometría de dirección completa (caída/caster/convergencia), masas no
  suspendidas, embrague/calado real con pedal, colisiones.
- El "coche" es un turismo deportivo genérico definido enteramente en
  `config.py`; no hay sistema de varios coches.
- El bloqueo de diferencial es viscoso con tope, no un modelo de Salisbury.
- La marcha atrás y el comportamiento a <1 m/s usan un modelo cinemático
  amortiguado (evitar singularidades de deslizamiento).

## Cómo verificar sin volante ni Windows

```
pip install -r requirements.txt
python tests/test_physics.py                    # 23 pruebas de comportamiento
SDL_VIDEODRIVER=dummy python -m simulator.main --frames 300   # humo headless
```

Las pruebas cubren: 0-100 y frenada realistas, bloqueo sin ABS (frena peor y
no dirige), cargas por rueda en curva/frenada/cresta, freno motor, subviraje
estable, diferencias RWD/FWD/AWD y entre diferenciales, tirón al pisar hierba
con un lado, par de FFB coherente y 60 s de conducción autónoma sin
divergencias numéricas.

## Dónde aporta más una revisión

1. **Realismo del FFB**: fidelidad y tuning del par de autoalineado, efectos
   que falten o sobren, rangos de `FFB_*` en config.
2. **Modelo de neumático**: la curva combinada y la sensibilidad a la carga
   son simplificadas; ¿errores conceptuales o mejoras de bajo coste?
3. **Estabilidad numérica**: casos límite del integrador híbrido de rueda,
   marcha atrás, velocidad casi nula, dt variable.
4. **Estructura del código**: acoplamientos, nombres, testabilidad.
5. **Ideas de contenido**: circuitos, coches presets, HUD, telemetría.

Se agradecen hallazgos concretos y accionables (con archivo/línea y
escenario de reproducción) más que valoraciones generales.
