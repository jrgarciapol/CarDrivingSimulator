//! Punto de entrada de la app.

using Toybox.Application;
using Toybox.WatchUi;
using Toybox.Lang;

class StressLogApp extends Application.AppBase {

    private var mRecorder = null;

    function initialize() {
        AppBase.initialize();
        mRecorder = new Recorder();
    }

    function onStart(state as Lang.Dictionary or Null) as Void {
        // Arrancamos a grabar directamente: la app es un datalogger, no
        // tiene sentido abrirla y tener que darle a otro botón.
        mRecorder.start();
        mRecorder.setPromptCallback(method(:onDetectorPrompt));
    }

    function onStop(state as Lang.Dictionary or Null) as Void {
        mRecorder.shutdown();
    }

    function getInitialView() {
        var view = new MainView(mRecorder);
        return [view, new MainDelegate(mRecorder)];
    }

    //! El detector cree que merece la pena preguntar (fase 4).
    function onDetectorPrompt(reason as Lang.Number) as Void {
        WatchUi.pushView(new PromptMenu(reason),
                         new PromptMenuDelegate(mRecorder),
                         WatchUi.SLIDE_UP);
    }
}
