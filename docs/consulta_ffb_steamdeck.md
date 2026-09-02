# Encargo: force feedback del Thrustmaster T300RS en Steam Deck

Documento para encargar una búsqueda técnica. Contiene **todo lo que ya está
medido y descartado**, para que no se gaste esfuerzo en repetirlo, y termina
con **las preguntas concretas** que quedan abiertas.

Se puede copiar y pegar entero.

**Aviso a quien responda**: el apartado *"Una premisa que se dio por buena y
era falsa"*, al final, descarta la pista más tentadora. Conviene leerlo antes
de empezar.

---

## Resumen en una frase

Un simulador de conducción propio (Python + PySDL2) corre en una Steam Deck
con un Thrustmaster T300RS: dirección, tres pedales y botones funcionan
perfectamente, **pero no hay force feedback**, porque el núcleo toma el
volante con `hid-generic`, que no lo implementa. Se intentó mandar la fuerza
desde espacio de usuario escribiendo informes HID en `/dev/hidraw`, copiando
el protocolo del driver `hid-tmff2`, y **el volante quedó en modo bootloader
y hubo que reinstalarle el firmware**.

---

## Entorno, medido

| | |
|---|---|
| Equipo | Steam Deck, modo Escritorio (Konsole) |
| Sistema | SteamOS, kernel `6.16.12-valve24.5-1-neptune-616-gb2f7cfe85e45` |
| Python | 3.13.5, PySDL2 con binarios de `pysdl2-dll` 2.32.10 |
| Volante | Thrustmaster T300RS, **conmutador en PC/PS3** |
| Firmware del volante | **34.00** (por encima del 31 que exige `hid-tmff2`) |
| Corona montada | "PS Wheel" (el panel de Thrustmaster la reconoce) |
| Driver de Windows | 2.11.57.0, paquete `1.TTRS.2026` |

## Lo que YA está comprobado

### La entrada funciona; falta solo la fuerza

```
[0] Thrustmaster T300RS Racing wheel
    ejes=4  botones=13  gamepad_para_SDL=no  force_feedback=no

VOLANTE     -> eje 0    ACELERADOR -> eje 2    FRENO -> eje 1
reposo por eje: [22, 32767, 32767, 32767]   (pedales invertidos)
```

### El núcleo NO publica force feedback para el volante

Inventario completo de `/dev/input/event*` (19 aparatos). El **único** con
capacidad de fuerza es el mando interno de la propia Deck, y solo vibración:

```
/dev/input/event10  rw  -          -             Microsoft X-Box 360 pad 0
      FF: vibracion
/dev/input/event11  rw  044f:b66e  hid-generic   Thrustmaster T300RS Racing wheel
      (sin FF)
/dev/hidraw4        rw  044f:b66e  hid-generic   Thrustmaster T300RS Racing wheel
```

Leído de `/sys/class/input/eventN/device/capabilities/ff`, que refleja lo que
el driver declara. `SDL_JoystickIsHaptic` sobre el volante devuelve **NO**.

### Módulos

```
hid_tmff2:        no cargado
hid_thrustmaster: CARGADO
ff_memless:       CARGADO
usbhid:           no cargado (integrado en el núcleo)
hid_generic:      no cargado (integrado en el núcleo)
```

### El nodo de hidraw del volante SÍ tiene permiso de escritura

`/dev/hidraw4`, lectura y escritura, sin necesidad de root ni de tocar udev.

## Lo que se intentó, y cómo salió mal

Razonamiento: `hid-tmff2` no hace nada que exija estar en el núcleo — manda
**informes HID de salida**. Y un informe HID de salida se puede escribir desde
espacio de usuario en `/dev/hidraw`. Así que se copió el protocolo de
`src/tmt300rs/hid-tmt300rs.c` (GPL-2.0-or-later) y se mandó desde Python.

Los paquetes enviados, en orden, cada uno rellenado con ceros hasta la
longitud del informe y precedido del identificador de informe:

```
apertura           01 05
subir constante    00 01 6a  <nivel:s16le>  <envolvente:8 ceros>  00
                   4f <duracion:u16le> 00 00 <retardo:u16le> 00 ff ff
reproducir         00 01 89 41 <veces:u16le>
actualizar const.  00 01 6a  <nivel:s16le>  <envolvente:8 ceros>  00 45
                   <duracion:u16le> <retardo:u16le>
```

El **identificador de informe y la longitud de carga** se leyeron del
descriptor HID del propio aparato
(`/sys/class/hidraw/hidraw4/device/report_descriptor`), buscando el informe de
SALIDA declarado.

**Resultado**: el volante no se movió, se le apagó el LED, y a partir de ahí
enumeró como `044f:b66c` — **modo bootloader** — sin ejes, sin botones y sin
que lo reconociera ninguna aplicación. Se recuperó con el procedimiento de
despertado de Thrustmaster (L3+R3 al conectar el USB) y reinstalando el
firmware. El volante está bien.

## La duda concreta que lo explica

En `hid-tmff2`, el driver **reescribe el descriptor de informes** del volante.
En el descriptor corregido, el informe de salida es:

```c
0x85, 0x60,        /* Report ID (96), prev 10 */
0x06, 0x00, 0xff,  /* Usage page (Vendor 1) */
0x09, 0x60,        /* Usage (96), prev 10 */
0x75, 0x08,        /* Report size (8) */
0x95, 0x3f,        /* Report count (63) */
0x91, 0x02,        /* Output (Variable, Absolute) */
```

El comentario `prev 10` dice que el volante declaraba **otro** identificador
y el driver lo cambia a `0x60`. De ahí **no se puede deducir** si:

- **(a)** el volante espera de verdad el `0x60` en el cable, y el descriptor
  de fábrica está mal — en cuyo caso leer el de fábrica, como hicimos, manda
  el identificador equivocado; o
- **(b)** el renumerado es solo para evitar un choque interno en el núcleo, y
  en el cable viaja el original.

Es un dato que no aparece en ninguna documentación pública: el protocolo del
T300RS no lo publica Thrustmaster, y `hid-tmff2` es ingeniería inversa.

---

## PREGUNTAS

Ordenadas por lo que más resolvería.

1. **El identificador del informe de salida.** ¿Cuál es el que acepta un
   T300RS en modo PC (`044f:b66e`) cuando se le escribe un informe de salida
   por `/dev/hidraw`? ¿Es el `0x60` que fuerza `hid-tmff2`, o el que declara
   el descriptor de fábrica? Lo ideal sería el **volcado del descriptor de
   informes de fábrica** de un T300RS `b66e` (`xxd
   /sys/class/hidraw/hidrawN/device/report_descriptor`), que zanjaría la
   pregunta sin conjeturas.

2. **¿Es viable la vía de espacio de usuario?** ¿Alguien ha conseguido force
   feedback en un T300RS escribiendo en `/dev/hidraw` (o con `hidapi` /
   `libusb`), sin módulo de kernel? ¿Existe algún proyecto que lo haga, para
   cualquier volante Thrustmaster? Si es imposible por diseño —por ejemplo
   porque el volante solo acepta la fuerza por el endpoint de interrupción y
   `hidraw` no llega ahí, o porque `hid-generic` interfiere—, **saberlo
   también es una respuesta útil** y cierra la línea.

3. **¿Qué deja a un T300RS en modo bootloader (`044f:b66c`)?** ¿Es una
   respuesta conocida a un informe malformado, o hay una secuencia concreta
   que lo provoca? Interesa para saber qué NO volver a mandar.

4. **`hid-tmff2` en SteamOS.** ¿Compila y funciona con el kernel
   `6.16.12-valve24.5-1-neptune-616`? ¿Qué paquete de cabeceras le
   corresponde (`pacman -Ss linux-neptune`)? ¿Hace falta poner
   `hid_thrustmaster` en la lista negra —el README del proyecto lo
   recomienda— y hay que rehacer la instalación tras cada actualización de
   SteamOS, que reemplaza la partición del sistema?

5. **Alternativas.** ¿Hay alguna otra forma de obtener el par en Linux con
   este volante: un módulo distinto, un parche ya integrado en algún kernel
   reciente, o un demonio en espacio de usuario?

## Una premisa que se dio por buena y era FALSA

Durante un tiempo se trabajó suponiendo que los juegos de Steam **sí** movían
el volante con fuerza en esta misma Deck, y de ahí se dedujo que el núcleo
tenía que estar publicando la capacidad por algún camino. **No era cierto.**

Lo que se estaba notando era el **par de autocentrado del propio volante**,
que aparece en cuanto se inicializa y es cosa del firmware, no de ningún
juego. Un T300RS parado ofrece bastante resistencia al girarlo a mano —
tanta que se agradecen las dos manos—, y es fácil confundirlo con force
feedback si nunca se ha girado el volante fuera de un juego.

**Comprobado después con BeamNG.drive**, que tiene de los mejores force
feedback disponibles en Linux: en esta Deck **tampoco da fuerza**. Solo se
nota el autocentrado, igual que fuera del juego. Es la prueba definitiva de
que no es cosa de nuestro programa ni del camino de SDL: **ningún** juego
obtiene par en esta máquina, porque el núcleo no publica la capacidad.

Se deja escrito porque quien responda no debe buscar por ahí: **no hay
ninguna evidencia de que el force feedback funcione en esta Deck, por ningún
camino**, y la vía de Steam/Proton está descartada por medición directa.

## Qué NO hace falta responder

- Cómo mapear ejes, pedales o botones: medido y funcionando.
- "Comprueba que el volante esté en modo PC / encendido / con corriente": sí.
- El firmware: es el 34.00, actualizado, y el volante funciona.
- Consejos genéricos de Windows: en Windows el force feedback **ya funciona**
  por DirectInput. El problema es exclusivamente Linux/SteamOS.
- Instrucciones generales de `SDL_Haptic`: SDL no ve el volante como háptico
  porque el núcleo no publica la capacidad, no por un fallo de SDL.

## Qué sería una buena respuesta

Confirmado que **ningún** juego obtiene fuerza en esta máquina (probado con
BeamNG.drive), la única vía que queda es instalar el driver que falta.

> **Este encargo ya está respondido.** Ver el apartado final,
> *"Respuestas recibidas: qué se ha verificado"*.
Cualquiera de estas tres cierra el asunto:

- un procedimiento de instalación de `hid-tmff2` verificado en SteamOS con
  kernel 6.16-neptune, indicando si sobrevive a las actualizaciones — es la
  vía **oficial** del proyecto y la única con sentido ahora;
- el volcado del descriptor de informes de fábrica de un T300RS `b66e`,
  con el identificador del informe de salida señalado, por si alguna vez se
  retoma la vía de espacio de usuario;
- una confirmación fundamentada de que esa vía de espacio de usuario no
  puede funcionar, y por qué.

---

# Respuestas recibidas: qué se ha verificado

Se consultaron cuatro fuentes. Coinciden en casi todo, pero **coinciden
también en un error**, y seguir su consejo repetiría exactamente el fallo que
dejó el volante en modo bootloader. Aquí se separa lo comprobado contra las
fuentes primarias (el código de `hid-tmff2` y el subsistema HID de Linux) de
lo que es opinión.

## Lo que queda CONFIRMADO

- **No hay alternativa a `hid-tmff2`.** Ni otro módulo en el núcleo oficial,
  ni un demonio en espacio de usuario mantenido. Las cuatro coinciden.
- **La vía de espacio de usuario no merece la pena.** Comprobado en el código
  del driver: la inicialización del T300RS incluye dos **transferencias de
  control USB** (`bRequestType 0xc1, bRequest 86` para la versión de firmware,
  y otra para el tipo de corona) que **`/dev/hidraw` no puede enviar**. Harían
  falta `libusb` o `usbfs`, y una captura del tráfico real para acertar la
  secuencia.
- **El modo bootloader es una autoprotección del firmware** ante un informe
  malformado, no un daño. Se recupera con L3+R3 y reinstalación de firmware.
- **Hay que poner `hid_thrustmaster` en la lista negra.** Lo dice el propio
  README del proyecto, literalmente.

## El error compartido: el identificador del informe

Las cuatro respuestas concluyen que **el volante espera `0x0A` en el cable** y
que el `0x60` es "una ficción interna del núcleo" que nunca sale al USB. Tres
de ellas explican así nuestro fallo: *"mandaste `0x60` o `0x00`"*.

**Las dos afirmaciones son falsas.**

1. **Nuestro código NO mandó `0x60`.** Lee el descriptor del propio aparato y
   usa el identificador del informe de salida que este declara
   (`simulator/ffb_t300rs.py`, funciones `informes_salida` y `buscar`). O sea:
   mandamos exactamente el de fábrica, que según ellos es el correcto. Su
   explicación no describe lo que pasó.

2. **El `0x60` SÍ sale al cable.** En Linux, `hid_hw_request(...,
   HID_REQ_SET_REPORT)` acaba en `hid_output_report()`, que escribe
   `report->id` como **primer byte del paquete** cuando el informe está
   numerado:

   ```c
   void hid_output_report(struct hid_report *report, __u8 *data)
   {
           if (report->id > 0)
                   *data++ = report->id;
           ...
   ```

   Y `report->id` vale `0x60`, porque `hid-tmff2` ha reescrito el descriptor
   antes. Es decir: el driver que funciona **manda `0x60` por el USB**.

**Conclusión invertida**: si `hid-tmff2` funciona mandando `0x60`, entonces el
descriptor de fábrica está equivocado y el volante quiere el `0x60`. Nosotros
mandamos el de fábrica, y de ahí el paquete malformado. La respuesta a la
pregunta (a) vs (b) del encargo es **(a)**, no (b).

**Ojo, esto no es una invitación a reintentarlo con `0x60`.** Queda sin
resolver si el volante lee ese primer byte o lo ignora, y sigue faltando la
inicialización por transferencias de control. Solo una captura USB del driver
funcionando lo zanjaría. Hasta entonces, **no se escribe nada en
`/dev/hidraw`**.

## Lo que se contradice entre ellas

**¿Sobrevive DKMS a las actualizaciones de SteamOS?** Una dice que sí ("no
toca `/usr/src` ni `/var/lib/dkms`"); tres dicen que no, porque SteamOS usa
particiones A/B que se reemplazan enteras. El README del proyecto **no dice
nada** al respecto. Lo prudente es asumir que **no sobrevive** y dejar
preparado un script para rehacerlo.

**El paquete de cabeceras.** Se proponen `linux-neptune-6.16-headers`,
`linux-neptune-616-headers` y "prueba 61/65/68". El README solo lista
`linux-neptune-61/65/68-headers`. **No hay que adivinarlo**:

```bash
uname -r
pacman -Ss linux-neptune | grep headers
```

## Errores de detalle, comprobados contra el repositorio

- El proyecto es **`Kimplul/hid-tmff2`**. Una respuesta manda a un fork de
  `gotzl` y menciona a "kmicki"; no es la fuente oficial.
- **No existe un objetivo `make dkms-install`.** Los objetivos reales del
  `Makefile` son `all`, `install`, `steamdeck-rules` y `clean`. La
  instalación por DKMS se hace con `sudo ./dkms/dkms-install.sh`.
- El módulo se llama por dentro **`hid-tmff-new`** (más `hid-tminit-new` y
  `usb-tminit-new`), no `tmff2`. Importa para comprobarlo con `lsmod`.
- `make steamdeck-rules` **sí existe** e instala
  `udev/71-thrustmaster-steamdeck.rules`, que da `uaccess` sobre el `hidraw`
  del volante. En nuestra Deck ese permiso ya lo teníamos, así que esa regla
  no es la que falta.

## Procedimiento, tomado del repositorio

```bash
uname -r
pacman -Ss linux-neptune | grep headers        # elegir el que coincida

sudo steamos-readonly disable
sudo pacman-key --init && sudo pacman-key --populate archlinux
sudo pacman -S base-devel dkms git <paquete-de-cabeceras>

echo 'blacklist hid_thrustmaster' | sudo tee /etc/modprobe.d/hid_thrustmaster.conf

git clone --recurse-submodules https://github.com/Kimplul/hid-tmff2.git
cd hid-tmff2
sudo ./dkms/dkms-install.sh
sudo make steamdeck-rules

sudo udevadm control --reload-rules && sudo udevadm trigger
sudo steamos-readonly enable
```

Reconectar el volante y comprobar:

```bash
lsmod | grep tmff                    # debe aparecer hid_tmff_new
dmesg | grep -i 'tmff\|t300'         # "force feedback for T300RS"
python3 tools/ffb_info.py            # ya debe declarar fuerza constante
```

Si el juego no coge la fuerza, `tools/ffb_info.py --probar` la prueba por
evdev, que es la vía que expone el módulo. Esa sí es segura: son llamadas
`ioctl` estándar del núcleo, no informes en bruto.
