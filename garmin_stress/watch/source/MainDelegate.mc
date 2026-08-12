//! Botones de la pantalla principal.
//!
//! Dos formas de marcar, a propósito:
//!
//!   START  -> menú con los tres niveles + "estoy tranquilo". Dos
//!             pulsaciones en total, sin ambigüedad. Es la vía fiable.
//!   ABAJO  -> 1, 2 o 3 pulsaciones rápidas = nivel 1, 2 o 3, sin mirar
//!             la pantalla. Es la vía discreta, la que puedes usar en
//!             mitad de una reunión sin que se note.
//!
//! La multipulsación tiene un coste que conviene tener presente: hay que
//! esperar Config.MULTITAP_WINDOW_MS a que dejes de pulsar antes de saber
//! cuántas veces has pulsado, y con frío o con guantes se cuela alguna.
//! Por eso existe también el menú, y por eso el reloj vibra tantas veces
//! como el nivel que ha entendido: es tu confirmación de que registró lo
//! que querías.

using Toybox.WatchUi;
using Toybox.System;
using Toybox.Timer;
using Toybox.Lang;

class MainDelegate extends WatchUi.BehaviorDelegate {

    private var mRec = null;
    private var mTaps = 0;
    private var mTapTimer = null;

    function initialize(recorder as Recorder) {
        BehaviorDelegate.initialize();
        mRec = recorder;
        mTapTimer = new Timer.Timer();
    }

    //! START: menú de marcado.
    function onSelect() as Lang.Boolean {
        WatchUi.pushView(new MarkerMenu(), new MarkerMenuDelegate(mRec), WatchUi.SLIDE_UP);
        return true;
    }

    function onKey(evt as WatchUi.KeyEvent) as Lang.Boolean {
        var k = evt.getKey();
        if (k == WatchUi.KEY_DOWN) {
            tap();
            return true;
        }
        return false;
    }

    //! BACK: confirmar antes de cerrar. Una sesión de ocho horas no se
    //! tira por un botón mal dado.
    function onBack() as Lang.Boolean {
        WatchUi.pushView(
            new WatchUi.Confirmation("¿Guardar y salir?"),
            new SaveConfirmDelegate(mRec),
            WatchUi.SLIDE_UP);
        return true;
    }

    // -----------------------------------------------------------------

    private function tap() as Void {
        mTaps++;
        if (mTaps > 3) { mTaps = 3; }
        mTapTimer.stop();
        mTapTimer.start(method(:onTapTimeout), Config.MULTITAP_WINDOW_MS, false);
    }

    function onTapTimeout() as Void {
        var n = mTaps;
        mTaps = 0;
        if (n > 0) {
            // Marca rápida: asumimos que el episodio viene de hace un
            // rato, no de este mismo segundo. Si quieres precisar el
            // inicio, usa el menú de START.
            mRec.mark(n, Config.ONSET_1MIN);
        }
    }
}

//! Confirmación de guardar y salir.
class SaveConfirmDelegate extends WatchUi.ConfirmationDelegate {

    private var mRec = null;

    function initialize(recorder as Recorder) {
        ConfirmationDelegate.initialize();
        mRec = recorder;
    }

    function onResponse(response as WatchUi.Confirm) as Lang.Boolean {
        if (response == WatchUi.CONFIRM_YES) {
            mRec.stop(true);
            System.exit();
        }
        return true;
    }
}
