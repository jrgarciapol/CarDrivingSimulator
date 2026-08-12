//! Pantalla principal.
//!
//! Dibujada a mano en vez de con layouts XML porque tiene que quedar
//! bien en los tres tamaños del Epix Pro (42/47/51 mm) sin mantener tres
//! layouts. Todo va en fracciones de la altura de la pantalla.

using Toybox.WatchUi;
using Toybox.Graphics;
using Toybox.Activity;
using Toybox.Lang;

class MainView extends WatchUi.View {

    private var mRec = null;

    function initialize(recorder as Recorder) {
        View.initialize();
        mRec = recorder;
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        // --- Estado de la banda -----------------------------------
        var ok = mRec.strapOk();
        dc.setColor(ok ? Graphics.COLOR_GREEN : Graphics.COLOR_RED, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.13,
            Graphics.FONT_TINY,
            ok ? WatchUi.loadResource(Rez.Strings.Recording)
               : WatchUi.loadResource(Rez.Strings.NoStrap),
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);

        // --- Pulso ------------------------------------------------
        var info = Activity.getActivityInfo();
        var hr = (info != null && info.currentHeartRate != null)
                 ? info.currentHeartRate.toString() : "--";
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.32, Graphics.FONT_NUMBER_HOT, hr,
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);

        // --- RMSSD y movimiento -----------------------------------
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.50, Graphics.FONT_SMALL,
            "RMSSD " + mRec.rmssd() + " ms   mov " + mRec.actIndex(),
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);

        // --- Barra de probabilidad --------------------------------
        // Solo tiene sentido cuando ya hay un modelo cargado.
        if (ModelParams.TRAINED) {
            drawBar(dc, cx, h * 0.62, w * 0.6, h * 0.035, mRec.pStress());
        }

        // --- Contadores -------------------------------------------
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.74, Graphics.FONT_TINY,
            mRec.marks() + " " + WatchUi.loadResource(Rez.Strings.Marks)
            + "  ·  " + mRec.beats() + " lat",
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);

        dc.drawText(cx, h * 0.84, Graphics.FONT_TINY, hhmmss(mRec.elapsed()),
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }

    private function drawBar(dc, cx, y, bw, bh, pct) as Void {
        var x0 = cx - bw / 2;
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(x0, y, bw, bh);
        var c = Graphics.COLOR_GREEN;
        if (pct >= 80) { c = Graphics.COLOR_RED; }
        else if (pct >= 50) { c = Graphics.COLOR_ORANGE; }
        dc.setColor(c, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(x0, y, bw * pct / 100, bh);
    }

    private function hhmmss(s as Lang.Number) as Lang.String {
        var hh = s / 3600;
        var mm = (s % 3600) / 60;
        var ss = s % 60;
        return hh.format("%d") + ":" + mm.format("%02d") + ":" + ss.format("%02d");
    }
}
