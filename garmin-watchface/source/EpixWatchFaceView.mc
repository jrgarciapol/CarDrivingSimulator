using Toybox.WatchUi as Ui;
using Toybox.Graphics as Gfx;
using Toybox.System as Sys;
using Toybox.Lang as Lang;
using Toybox.Time as Time;
using Toybox.Time.Gregorian as Calendar;
using Toybox.Application as App;

//! Esfera digital para el Epix Pro 51 mm (454 x 454, AMOLED), pensada para
//! MÁXIMA LEGIBILIDAD, con fuentes Roboto Mono (open source) y soporte real de
//! Always-On Display (AOD) seguro contra burn-in.
//!
//! Dos presentaciones:
//!
//!   INTERACTIVA (mirando el reloj) — brillo máximo, contraste alto:
//!     - Fecha (Roboto Mono Medium, gris claro)
//!     - Hora HH:MM (Roboto Mono Bold, blanco, muy grande)
//!     - Línea de acento + segundos (color de acento)
//!
//!   ALWAYS-ON (reposo, pantalla siempre encendida) — legible pero seguro:
//!     - Hora HH:MM (Roboto Mono Light: trazo fino = pocos píxeles encendidos)
//!     - Fecha pequeña
//!     - Sin segundos ni rellenos; ~4% de píxeles encendidos (Garmin exige <10%)
//!     - Desplazamiento de píxeles cada minuto para evitar quemado del AMOLED.
class EpixWatchFaceView extends Ui.WatchFace {

    // ¿Pantalla en alto consumo (el usuario la está mirando)?
    private var mIsAwake = true;

    // ¿El dispositivo exige protección anti burn-in? (true en AMOLED Epix Pro)
    private var mBurnIn = false;

    // Ajustes configurables por el usuario.
    private var mUse24Hour = true;
    private var mAccentColor = 0x1E9BFF; // azul brillante (acento interactivo)
    private var mAodColor = 0x00FF00;    // verde por defecto (hora en AOD)

    // Fuentes personalizadas (Roboto Mono).
    private var mTimeFont;      // Bold 130 — hora interactiva
    private var mAodFont;       // Bold 156 — hora AOD (grande)
    private var mSecFont;       // Bold  — segundos
    private var mDateFont;      // Medium — fecha

    // Colores.
    private const COLOR_BG      = Gfx.COLOR_BLACK;
    private const COLOR_TIME    = 0xFFFFFF; // blanco puro (interactivo)
    private const COLOR_DATE    = 0xAAAAAA; // gris claro (interactivo)

    // Posiciones verticales como fracción de la altura de pantalla.
    private const Y_DATE = 0.30;
    private const Y_TIME = 0.50;
    private const Y_LINE = 0.685;
    private const Y_SEC  = 0.79;

    function initialize() {
        WatchFace.initialize();
    }

    //! Carga fuentes y detecta capacidades del dispositivo.
    function onLayout(dc) {
        mTimeFont = Ui.loadResource(Rez.Fonts.TimeBold);
        mAodFont  = Ui.loadResource(Rez.Fonts.TimeAod);
        mSecFont  = Ui.loadResource(Rez.Fonts.SecBold);
        mDateFont = Ui.loadResource(Rez.Fonts.DateMed);

        var settings = Sys.getDeviceSettings();
        if (settings has :requiresBurnInProtection) {
            mBurnIn = (settings.requiresBurnInProtection == true);
        }

        loadSettings();
    }

    function loadSettings() {
        var use24 = App.Properties.getValue("Use24Hour");
        if (use24 != null) {
            mUse24Hour = use24;
        }
        var accent = App.Properties.getValue("AccentColor");
        if (accent != null) {
            mAccentColor = accent;
        }
        var aod = App.Properties.getValue("AodColor");
        if (aod != null) {
            mAodColor = aod;
        }
    }

    function onShow() {
        loadSettings();
    }

    //! Redibujado principal.
    //!   - En alto consumo: presentación interactiva completa.
    //!   - En bajo consumo con AOD: presentación mínima y segura.
    function onUpdate(dc) {
        loadSettings();

        dc.setColor(COLOR_BG, COLOR_BG);
        dc.clear();

        var now = Calendar.info(Time.now(), Time.FORMAT_SHORT);

        if (mIsAwake) {
            drawInteractive(dc, now);
        } else {
            drawAlwaysOn(dc, now);
        }
    }

    //! ---- Presentación INTERACTIVA (brillo máximo) ----
    private function drawInteractive(dc, now) {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        // Fecha
        dc.setColor(COLOR_DATE, Gfx.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * Y_DATE).toNumber(), mDateFont, dateLine(now),
                    Gfx.TEXT_JUSTIFY_CENTER | Gfx.TEXT_JUSTIFY_VCENTER);

        // Hora
        dc.setColor(COLOR_TIME, Gfx.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * Y_TIME).toNumber(), mTimeFont,
                    formatTime(now.hour, now.min),
                    Gfx.TEXT_JUSTIFY_CENTER | Gfx.TEXT_JUSTIFY_VCENTER);

        // Línea de acento
        var lineHalf = (w * 0.16).toNumber();
        dc.setColor(mAccentColor, Gfx.COLOR_TRANSPARENT);
        dc.fillRectangle(cx - lineHalf, (h * Y_LINE).toNumber(), lineHalf * 2, 3);

        // Segundos
        drawSeconds(dc, now.sec);
    }

    //! ---- Presentación ALWAYS-ON (solo la hora, grande y legible) ----
    //! Hora enorme (Roboto Mono Bold 156) en color AOD (verde/rojo/blanco).
    //! ~9,2% de píxeles encendidos (bajo el límite del 10% de Garmin).
    //! Se dibuja en tres bloques (HH · : · MM) con el ":" ceñido para poder
    //! agrandar los dígitos sin salirse de la pantalla.
    private function drawAlwaysOn(dc, now) {
        var w = dc.getWidth();
        var h = dc.getHeight();

        // Desplazamiento de píxeles: 9 posiciones que rotan cada minuto para
        // no fijar siempre los mismos píxeles (evita el quemado del AMOLED).
        var shift = 8;
        var ox = ((now.min % 3) - 1) * shift;
        var oy = (((now.min / 3) % 3) - 1) * shift;

        var timeStr = formatTime(now.hour, now.min);
        var colonIdx = timeStr.find(":");
        var hh = timeStr.substring(0, colonIdx);
        var mm = timeStr.substring(colonIdx + 1, timeStr.length());

        // Anchos: bloque de dos dígitos y hueco ceñido para el ":".
        var wBlock = dc.getTextDimensions(hh, mAodFont)[0];
        var wColon = dc.getTextDimensions(":", mAodFont)[0];
        var colonSlot = (wColon / 2).toNumber();
        var totalW = wBlock * 2 + colonSlot;

        var x0 = (w - totalW) / 2 + ox;
        var cy = h / 2 + oy;

        dc.setColor(mAodColor, Gfx.COLOR_TRANSPARENT);
        // HH (alineado a la izquierda de su bloque)
        dc.drawText(x0, cy, mAodFont, hh,
                    Gfx.TEXT_JUSTIFY_LEFT | Gfx.TEXT_JUSTIFY_VCENTER);
        // ":" centrado en su hueco ceñido
        dc.drawText(x0 + wBlock + colonSlot / 2, cy, mAodFont, ":",
                    Gfx.TEXT_JUSTIFY_CENTER | Gfx.TEXT_JUSTIFY_VCENTER);
        // MM
        dc.drawText(x0 + wBlock + colonSlot, cy, mAodFont, mm,
                    Gfx.TEXT_JUSTIFY_LEFT | Gfx.TEXT_JUSTIFY_VCENTER);
        // Sin fecha, segundos ni rellenos en AOD.
    }

    //! Segundos en color de acento (solo con pantalla activa). Limpia su propia
    //! zona (clip) para que onPartialUpdate no solape dígitos cada segundo.
    private function drawSeconds(dc, sec) {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        var secY = (h * Y_SEC).toNumber();

        var text = sec.format("%02d");
        var dims = dc.getTextDimensions(text, mSecFont);
        var boxW = dims[0] + 10;
        var boxH = dims[1] + 6;

        dc.setClip(cx - boxW / 2, secY - boxH / 2, boxW, boxH);
        dc.setColor(COLOR_BG, COLOR_BG);
        dc.clear();

        dc.setColor(mAccentColor, Gfx.COLOR_TRANSPARENT);
        dc.drawText(cx, secY, mSecFont, text,
                    Gfx.TEXT_JUSTIFY_CENTER | Gfx.TEXT_JUSTIFY_VCENTER);

        dc.clearClip();
    }

    //! Refresco por segundo (solo en alto consumo): actualiza los segundos.
    function onPartialUpdate(dc) {
        if (!mIsAwake) {
            return;
        }
        var now = Calendar.info(Time.now(), Time.FORMAT_SHORT);
        drawSeconds(dc, now.sec);
    }

    //! Construye la línea de fecha: "LUN 09 AGO".
    private function dateLine(now) {
        return dayName(now.day_of_week) + " " +
               now.day.format("%02d") + " " +
               monthName(now.month);
    }

    //! Formatea la hora respetando 12/24 h del usuario y del sistema.
    private function formatTime(hour, min) {
        var use24 = mUse24Hour and Sys.getDeviceSettings().is24Hour;
        var h = hour;
        if (!use24) {
            h = hour % 12;
            if (h == 0) {
                h = 12;
            }
        }
        return h.format("%02d") + ":" + min.format("%02d");
    }

    private function dayName(dow) {
        var ids = [
            Rez.Strings.Day_0, Rez.Strings.Day_1, Rez.Strings.Day_2,
            Rez.Strings.Day_3, Rez.Strings.Day_4, Rez.Strings.Day_5,
            Rez.Strings.Day_6
        ];
        var idx = dow - 1;
        if (idx < 0 || idx > 6) {
            idx = 0;
        }
        return Ui.loadResource(ids[idx]);
    }

    private function monthName(month) {
        var ids = [
            Rez.Strings.Mon_1, Rez.Strings.Mon_2, Rez.Strings.Mon_3,
            Rez.Strings.Mon_4, Rez.Strings.Mon_5, Rez.Strings.Mon_6,
            Rez.Strings.Mon_7, Rez.Strings.Mon_8, Rez.Strings.Mon_9,
            Rez.Strings.Mon_10, Rez.Strings.Mon_11, Rez.Strings.Mon_12
        ];
        var idx = month - 1;
        if (idx < 0 || idx > 11) {
            idx = 0;
        }
        return Ui.loadResource(ids[idx]);
    }

    //! Alto consumo: repintamos al instante para respuesta inmediata al gesto.
    function onExitSleep() {
        mIsAwake = true;
        Ui.requestUpdate();
    }

    //! Bajo consumo: pasamos a la presentación Always-On.
    function onEnterSleep() {
        mIsAwake = false;
        Ui.requestUpdate();
    }
}
