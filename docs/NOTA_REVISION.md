# Nota para revisión del proyecto

Este documento orienta a cualquier revisor (humano o IA) que llegue al
repositorio para auditar el código y proponer mejoras. Resume qué es el
proyecto, cómo está diseñado, qué decisiones se tomaron y dónde el feedback
aporta más valor. La física está descrita en detalle, ecuación a ecuación,
en `docs/FISICA.md` — este documento es el mapa; aquél, el territorio.

## Qué es

Simulador de conducción para Windows en **Python + PySDL2** (SDL2 usa
DirectInput en Windows), pensado para un volante **Thrustmaster** con
pedales. El objetivo principal son **las sensaciones físicas en el
volante**: todo el force feedback se calcula desde el modelo dinámico en
tiempo real, no hay efectos enlatados. El apartado gráfico es un
**renderizador 3D real** (proyección en perspectiva de la malla de la
carretera por triángulos, `SDL_RenderGeometryRaw` + numpy) de estética
deliberadamente retro.

## Arquitectura

```
simulator/main.py     bucle: menú → eventos → física (480 Hz, sub-pasos) → FFB → render
simulator/config.py   configuración base documentada parámetro a parámetro
simulator/garage.py   coches .car (lista blanca), condiciones de asfalto, récords
simulator/menu.py     menú de arranque: coche + circuito + estado del asfalto
simulator/wheel.py    entrada del volante + efectos hápticos SDL/DirectInput
simulator/physics.py  modelo del vehículo (núcleo del proyecto; ver docs/FISICA.md)
simulator/track.py    circuito: curvatura, rasante, peralte, superficies, baches,
                      trazada ideal con envolvente de frenada
simulator/render.py   renderizador 3D (malla adaptativa, peralte, recorte del
                      plano cercano longitudinal Y lateral), coche, HUD, telemetría
simulator/audio.py    sonido de motor + chirrido sintetizados (numpy)
simulator/font.py     fuente bitmap 5x7 (sin dependencias)
simulator/cars/*.car  8 vehículos (parámetros comentados uno a uno)
simulator/tracks/     circuitos: silverstone, spa (TUM + relieve/peralte
                      sintéticos), óvalo peraltado de diseño
tools/import_track.py importador TUM → formato interno (+ modo --enriquecer)
tools/make_oval.py    generador del óvalo peraltado
tests/test_physics.py 45 pruebas de comportamiento físico, sin SDL ni volante
```

## Modelo físico (resumen; detalle en docs/FISICA.md)

Convenios: x adelante, **y a la derecha**, guiñada positiva = giro a la
derecha; ruedas `0=del.izda, 1=del.dcha, 2=tras.izda, 3=tras.dcha`; el coche
vive en coordenadas locales de la carretera (s, n, psi).

- **Chasis**: 3 GDL planos + 3 verticales (heave/pitch/roll) con
  muelle/amortiguador por esquina y estabilizadoras por eje, más 4 GDL de
  **masa no suspendida** (el neumático es un muelle rígido contra el
  asfalto: la rueda "vuela" sobre los pianos y la carga de Pacejka sale de
  la compresión de la goma). Momentos de cabeceo/balanceo desde las
  fuerzas de neumático **a nivel del suelo** (funciona parado en pendiente
  y tumba el coche hacia el lado bajo de un peralte). Geometría
  **anti-dive/anti-squat** con reinyección de la carga desviada (la
  transferencia total se conserva).
- **Neumático**: curva combinada tipo Pacejka `μFz·sin(C·atan(B·ρ))` sobre
  el deslizamiento combinado normalizado, elipse de fricción, sensibilidad
  a la carga, **camber thrust** por balanceo con **camber gain**
  geométrico por compresión, **temperatura** por rueda (fricción calienta,
  el aire enfría, parábola de rendimiento) y *relaxation length* lateral.
- **Ruedas**: velocidad angular propia; integrador **híbrido** (rodadura:
  relajación exponencial exacta al equilibrio, incondicionalmente estable;
  deslizamiento profundo: explícito con captura y bloqueo). **Inercia
  efectiva** con el motor reflejado por el cuadrado de la desmultiplicación
  cuando el embrague está acoplado.
- **Transmisión**: RWD/FWD/AWD, diferencial viscoso por eje con tope
  (abierto/LSD/bloqueado), freno motor, limitador con histéresis, inercia
  de régimen, cambio automático conmutable con umbrales relativos al corte.
- **Frenos**: reparto configurable, par que supera el agarre a propósito
  (sin ABS bloquea), ABS por rueda opcional.
- **Carretera**: pendiente y curvatura vertical (gravedad, descarga en
  crestas), **peralte** con sus tres efectos (gravedad lateral, sobrecarga
  contra el asfalto, balanceo), superficie y microrrelieve **bajo cada
  rueda**, condiciones de asfalto multiplicativas.
- **FFB**: autoalineado con avance neumático decreciente + residual
  mecánico, scrub radius, sacudida de baches paso-alto, amortiguación de
  columna escalada con la velocidad, suavizado final. Signo DirectInput
  invertido (verificado en hardware T300RS), `FFB_INVERT` como conmutador.

## Decisiones y compromisos conocidos

- Python puro + SDL: portabilidad y sencillez frente a rendimiento. El
  render 3D vectorizado con numpy cuesta ~8 ms/frame a 1280×720; la física,
  ~50 µs/paso a 480 Hz.
- La estética del render es retro a propósito; la geometría no (proyección
  en perspectiva real, malla adaptativa 1/2/4 m, peralte inclinando cada
  sección, cámara solidaria al plano local del asfalto y al chasis —
  heave/pitch en las vistas interiores).
- El relieve y peralte de Silverstone/Spa son **sintéticos** (la base TUM
  solo trae la planta): plausibles y deterministas, no topografía real.
- Simplificaciones asumidas (candidatas a futuro, por orden de valor):
  temperatura/desgaste/presión de neumáticos, geometría de dirección
  completa (caster/convergencia), presión de neumáticos, embrague con
  pedal y calado real, colisiones, rivales con IA.
- El diferencial es viscoso con tope, no un Salisbury con precarga/rampas.
- A <1 m/s la guiñada pasa a un modelo cinemático amortiguado (evitar la
  singularidad de los deslizamientos).

## Cómo verificar sin volante ni Windows

```
pip install -r requirements.txt
python tests/test_physics.py                    # 45 pruebas de comportamiento
SDL_VIDEODRIVER=dummy python -m simulator.main --frames 300   # humo headless
```

Las pruebas cubren: 0–100 y frenadas realistas, bloqueo sin ABS (frena peor
y no dirige), cargas por rueda en curva/frenada/cresta/pendiente, apoyo
aerodinámico, freno motor, subviraje estable, RWD/FWD/AWD y diferenciales,
tirón al pisar hierba con un lado, **peralte** (deriva hacia el lado bajo,
sobrecarga y alivio del neumático en curva peraltada), **camber thrust**,
par de FFB coherente, 60 s de conducción autónoma y una pasada de
aceleración+frenada con los 8 coches del garaje.

## Dónde aporta más una revisión

1. **Realismo del FFB**: fidelidad y tuning del par de autoalineado,
   efectos que falten o sobren, rangos de `FFB_*`.
2. **Modelo de neumático**: la curva combinada, la sensibilidad a la carga
   y el camber thrust son simplificados; ¿errores conceptuales o mejoras de
   bajo coste?
3. **Estabilidad numérica**: casos límite del integrador híbrido de rueda,
   marcha atrás, velocidad casi nula, transiciones de superficie.
4. **Los coches del garaje**: ¿los 8 se sienten distintos por las razones
   físicas correctas? ¿Parámetros poco creíbles en algún `.car`?
5. **Ideas de contenido**: circuitos, telemetría exportable, rivales.

Se agradecen hallazgos concretos y accionables (con archivo/línea y
escenario de reproducción) más que valoraciones generales.
