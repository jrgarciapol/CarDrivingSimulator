# Consulta: force feedback del Thrustmaster T300RS en Steam Deck

Documento para pedir una segunda opinión (Gemini, ChatGPT u otro). Contiene
**todas las pruebas ya hechas**, para no repetir trabajo ni recibir consejos
genéricos. Copia y pega el documento entero.

---

## El problema

Un simulador de conducción propio (Python + PySDL2, usa el subsistema
**háptico de SDL2**) corre bien en una Steam Deck con un volante Thrustmaster
T300RS: la dirección, los tres pedales y los botones responden
perfectamente. **Lo único que no hay es force feedback**: el volante no hace
fuerza ni vibra.

## Entorno

| | |
|---|---|
| Equipo | Steam Deck, modo Escritorio |
| Sistema | SteamOS, kernel `6.16.12-valve24.5-1-neptune-616-gb2f7cfe85e45` |
| Python | 3.13.5, PySDL2 con binarios de `pysdl2-dll` 2.32.10 |
| Volante | Thrustmaster T300RS, **conmutador en modo PC** (no PlayStation) |
| Lanzamiento | Desde la terminal (Konsole), no desde Steam |

## Lo que ya está comprobado (con datos)

### La entrada funciona: el problema es SOLO el force feedback

```
DISPOSITIVOS DE ENTRADA QUE VE SDL: 1
  [0] Thrustmaster T300RS Racing wheel
      ejes=4  botones=13  gamepad_para_SDL=no  force_feedback=no
```

Calibración medida mando a mando (reposo, volante, acelerador, freno):

```
reposo por eje: [22, 32767, 32767, 32767]
VOLANTE     -> eje 0   (recorre los dos lados)
ACELERADOR  -> eje 2   (recorrido completo)
FRENO       -> eje 1   (recorrido completo)
PEDALS_INVERTED = True (los pedales reposan en +32767)
```

O sea: el volante está en el modo correcto, SDL lo reconoce por su nombre y
**no** lo confunde con un gamepad, y los cuatro ejes se leen bien.

### El force feedback no existe para el volante

```
hapticos que ve SDL: 1
dispositivo: Thrustmaster T300RS Racing wheel
SDL_JoystickIsHaptic: NO
  haptico [0]: Microsoft X-Box 360 pad 0      <-- NO es el volante
    no  fuerza constante
    no  senoidal
    no  muelle
    no  amortiguador
```

El **único** háptico del sistema es el mando interno de la Deck (Steam lo
presenta como un pad de Xbox 360), y encima no soporta ningún efecto útil:
solo vibra. `SDL_JoystickIsHaptic` sobre el volante devuelve **NO**.

### Estado de los módulos y de los permisos

```
modulo hid_tmff2:        no cargado
modulo hid_thrustmaster: CARGADO
modulo ff_memless:       CARGADO
/dev/input/event*: 19 dispositivos, 8 con permiso de lectura+escritura
```

## Diagnóstico de partida (a validar o rebatir)

El T300RS **no expone la capacidad de force feedback a evdev** porque falta
el módulo fuera de árbol [`hid-tmff2`](https://github.com/Kimplul/hid-tmff2).
El `hid_thrustmaster` de la rama principal solo hace el cambio de modo
inicial del volante; no implementa FF para este modelo.

## Preguntas concretas

1. ¿Es correcto el diagnóstico, o hay alguna otra causa compatible con estos
   datos? En particular: ¿puede `hid_thrustmaster` estar **impidiendo** que
   `hid-tmff2` tome el dispositivo? ¿Conviene ponerlo en la lista negra?
2. **Instalación en SteamOS**, que tiene el sistema de archivos inmutable:
   ¿cuál es el procedimiento que de verdad funciona hoy, y **sobrevive a las
   actualizaciones de SteamOS**? ¿DKMS basta, o hay que rehacerlo tras cada
   actualización? ¿Qué paquete de cabeceras corresponde al kernel
   `6.16.12-valve24.5-1-neptune-616` (¿`linux-neptune-616-headers`?).
3. ¿Hace falta `sudo steamos-readonly disable`? Si es así, ¿qué se rompe al
   actualizar y cómo se recupera?
4. El README de hid-tmff2 exige **firmware 31 o superior** en el volante.
   ¿Cómo se comprueba y se actualiza el firmware **desde Linux**, sin un PC
   con Windows?
5. ¿Existe alguna alternativa **sin tocar el kernel**? Por ejemplo, escribir
   los efectos de FF directamente sobre `/dev/input/eventX` con `ioctl`
   (`EVIOCSFF`) desde Python, o alguna biblioteca en espacio de usuario.
   ¿Serviría de algo si el driver no anuncia la capacidad `FF_CONSTANT`?
6. ¿Hay incompatibilidad conocida entre **Steam Input** y el FFB del volante
   en la Deck, y afecta si el juego se lanza **fuera** de Steam?

## Qué NO hace falta que respondan

- Cómo mapear ejes o botones: ya está resuelto y medido.
- "Comprueba que el volante esté conectado / en modo PC": ya está.
- Consejos genéricos de Windows: el problema es específico de Linux/SteamOS.
