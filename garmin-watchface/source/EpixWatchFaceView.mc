using Toybox.WatchUi as Ui;
using Toybox.Graphics as Gfx;
using Toybox.System as Sys;
using Toybox.Lang as Lang;
using Toybox.Time as Time;
using Toybox.Time.Gregorian as Calendar;
using Toybox.Application as App;

//! Esfera digital moderna para el Epix Pro 51 mm (454 x 454, AMOLED).
//!
//! Distribución:
//!   - Arriba:  DÍA  DD MES        (gris claro, discreto)
//!   - Centro:  HH:MM              (blanco, muy grande)
//!   - Abajo:   SS                 (color de acento; solo con pantalla activa)
//!
//! En modo de bajo consumo (muñeca abajo / reposo) se ocultan los segundos
//! para reducir píxeles encendidos y cuidar el AMOLED y la batería.
class EpixWatchFaceView extends Ui.WatchFace {

    // ¿Está la pantalla en alto consumo (mirándola)?
    private var mIsAwake = true;

    // Ajustes configurables por el usuario.
    private var mUse24Hour = true;
    private var mAccentColor = 0x1E9BFF; // azul brillante por defecto

    // Colores fijos del tema oscuro.
    private const COLOR_BG    = Gfx.COLOR_BLACK;
    private const COLOR_TIME  = 0xFFFFFF; // blanco puro
    private const COLOR_DATE  = 0xAAAAAA; // gris claro

    function initialize() {
        WatchFace.initialize();
    }

    //! Carga (o recarga) los ajustes del usuario.
    function onLayout(dc) {
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
    }

    //! Se llama cada vez que se muestra la esfera.
    function onShow() {
        loadSettings();
    }

    //! Redibujado completo. En alto consumo ocurre cada segundo (vía
    //! onPartialUpdate); en bajo consumo, una vez por minuto.
    function onUpdate(dc) {
        loadSettings();

        var width  = dc.getWidth();
        var height = dc.getHeight();
        var cx = width / 2;

        // Fondo.
        dc.setColor(COLOR_BG, COLOR_BG);
        dc.clear();

        var now = Calendar.info(Time.now(), Time.FORMAT_SHORT);

        // ---- Línea de fecha: "LUN 09 AGO" ----
        var dayStr   = dayName(now.day_of_week);
        var monStr   = monthName(now.month);
        var dateLine = dayStr + " " + now.day.format("%02d") + " " + monStr;

        var dateY = (height * 0.30).toNumber();
        dc.setColor(COLOR_DATE, Gfx.COLOR_TRANSPARENT);
        dc.drawText(cx, dateY, Gfx.FONT_MEDIUM, dateLine,
                    Gfx.TEXT_JUSTIFY_CENTER | Gfx.TEXT_JUSTIFY_VCENTER);

        // ---- Hora grande: "HH:MM" ----
        var timeStr = formatTime(now.hour, now.min);
        var timeY = (height * 0.50).toNumber();
        dc.setColor(COLOR_TIME, Gfx.COLOR_TRANSPARENT);
        dc.drawText(cx, timeY, Gfx.FONT_NUMBER_THAI_HOT, timeStr,
                    Gfx.TEXT_JUSTIFY_CENTER | Gfx.TEXT_JUSTIFY_VCENTER);

        // ---- Acento: pequeña línea horizontal bajo la hora ----
        var lineY = (height * 0.68).toNumber();
        var lineHalf = (width * 0.16).toNumber();
        dc.setColor(mAccentColor, Gfx.COLOR_TRANSPARENT);
        dc.fillRectangle(cx - lineHalf, lineY, lineHalf * 2, 3);

        // ---- Segundos (solo con pantalla activa) ----
        if (mIsAwake) {
            drawSeconds(dc, now.sec);
        }
    }

    //! Redibujado parcial (una vez por segundo en alto consumo).
    //! Solo actualiza los segundos para gastar poca batería.
    function onPartialUpdate(dc) {
        if (!mIsAwake) {
            return;
        }
        var now = Calendar.info(Time.now(), Time.FORMAT_SHORT);
        drawSeconds(dc, now.sec);
    }

    //! Dibuja los segundos en color de acento, centrados bajo la línea.
    //! Limpia primero solo su propia zona (una "clip region"), imprescindible
    //! para que en onPartialUpdate no se solapen los dígitos cada segundo.
    private function drawSeconds(dc, sec) {
        var width  = dc.getWidth();
        var height = dc.getHeight();
        var cx = width / 2;
        var secY = (height * 0.78).toNumber();

        var text = sec.format("%02d");
        var font = Gfx.FONT_NUMBER_MEDIUM;
        var dims = dc.getTextDimensions(text, font);
        var boxW = dims[0] + 8;
        var boxH = dims[1] + 4;

        dc.setClip(cx - boxW / 2, secY - boxH / 2, boxW, boxH);
        dc.setColor(COLOR_BG, COLOR_BG);
        dc.clear();

        dc.setColor(mAccentColor, Gfx.COLOR_TRANSPARENT);
        dc.drawText(cx, secY, font, text,
                    Gfx.TEXT_JUSTIFY_CENTER | Gfx.TEXT_JUSTIFY_VCENTER);

        dc.clearClip();
    }

    //! Formatea la hora respetando el ajuste de 12/24 h y el del sistema.
    private function formatTime(hour, min) {
        // Usamos 24 h solo si el usuario lo pide Y el sistema también lo tiene.
        // Si el sistema está en 12 h, mandamos a 12 h para no confundir.
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

    //! Nombre corto del día de la semana (1 = domingo en FORMAT_SHORT).
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

    //! Nombre corto del mes (1 = enero).
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

    //! La pantalla pasa a alto consumo (el usuario mira el reloj).
    function onExitSleep() {
        mIsAwake = true;
        Ui.requestUpdate();
    }

    //! La pantalla pasa a bajo consumo (reposo).
    function onEnterSleep() {
        mIsAwake = false;
        Ui.requestUpdate();
    }
}
