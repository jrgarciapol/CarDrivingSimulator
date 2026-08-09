# Epix Digital — Esfera de reloj para Garmin Epix Pro 51 mm (Gen 2)

Esfera **digital moderna y minimalista** para el **Garmin Epix Pro 51 mm (Gen 2)**
(pantalla AMOLED redonda de 454 × 454 px, ID de dispositivo `epix2pro51mm`).

## Diseño

- **Fondo oscuro** (negro) — ideal para AMOLED y batería.
- **Hora grande** `HH:MM` en blanco, en el centro.
- **Día de la semana + fecha** arriba (`LUN 09 AGO`), en gris discreto.
- **Segundos** en color de **acento azul** debajo de la hora (se ocultan
  automáticamente en reposo para cuidar el AMOLED).
- Fina **línea de acento** bajo la hora.

### Personalizable desde Garmin Connect

- **Formato 24 horas** (activado por defecto).
- **Color de acento**: Azul (por defecto), Rojo, Verde, Naranja o Blanco.

## Estructura del proyecto

```
garmin-watchface/
├── manifest.xml                     # Dispositivo objetivo y metadatos
├── monkey.jungle                    # Configuración de build
├── source/
│   ├── EpixWatchFaceApp.mc          # Clase de la aplicación
│   └── EpixWatchFaceView.mc         # Dibujado de la esfera
├── resources/
│   ├── drawables/                   # Icono de lanzador
│   ├── strings/                     # Textos (inglés + fallback)
│   └── settings/                    # Ajustes del usuario
└── resources-spa/
    └── strings/                     # Textos en español (días/meses)
```

## Cómo compilarla y cargarla en tu reloj

Para generar el archivo instalable necesitas el **Connect IQ SDK** de Garmin
(gratuito). Yo he dejado todo el código listo; estos son los pasos en tu PC:

### 1. Instala las herramientas

1. Descarga el **Connect IQ SDK Manager**:
   https://developer.garmin.com/connect-iq/sdk/
2. Con el SDK Manager, instala el **SDK más reciente** y el **device Epix Pro
   51 mm (Gen 2)**.
3. Instala **Visual Studio Code** y la extensión oficial **Monkey C**
   (Garmin) — es lo más cómodo.

### 2. Genera tu clave de desarrollador (solo la primera vez)

Necesaria para firmar la app. En una terminal:

```bash
openssl genrsa -out developer_key.pem 4096
openssl pkcs8 -topk8 -inform PEM -outform DER -in developer_key.pem \
    -out developer_key.der -nocrypt
```

Guarda `developer_key.der` en un lugar seguro (está en `.gitignore` para no
subirla nunca al repositorio).

### 3. Compila (genera el `.prg`)

Desde la carpeta `garmin-watchface/`:

```bash
monkeyc \
  -o bin/EpixDigital.prg \
  -f monkey.jungle \
  -y /ruta/a/developer_key.der \
  -d epix2pro51mm
```

> En VS Code: pulsa **F5** (con el device Epix Pro 51 mm seleccionado) para
> compilarla y abrirla directamente en el **simulador**.

### 4. Cárgala en el reloj

**Opción A — Sideload por USB (rápido para probar):**

1. Conecta el Epix Pro al PC por USB.
2. Copia `bin/EpixDigital.prg` a la carpeta `GARMIN/APPS/` del reloj.
3. Desconecta. La esfera aparecerá en la lista de esferas del reloj.

**Opción B — Vía Connect IQ Store (para tenerla “oficial”):**

1. Crea un `.iq` con `monkeyc` (o **Build → Export Wizard** en VS Code).
2. Súbela a tu cuenta de desarrollador en https://apps.garmin.com/ y luego
   instálala desde la app **Connect IQ** en el móvil.

### 5. Actívala

En el reloj: mantén pulsado el botón central → **Esfera del reloj** (Watch
Face) → elige **Epix Digital**. Los ajustes (24 h / color) se cambian desde
**Garmin Connect → tu reloj → Connect IQ → Epix Digital → Configuración**.

## Notas técnicas

- `onPartialUpdate` refresca los segundos una vez por segundo solo con la
  pantalla activa; en reposo se hace un único refresco por minuto y se ocultan
  los segundos (menos píxeles encendidos = menos consumo y menos riesgo de
  *burn-in* en AMOLED).
- No requiere permisos: solo usa hora, fecha del sistema.
- `minApiLevel` 3.3.0 para asegurar compatibilidad con el Epix Pro Gen 2.
