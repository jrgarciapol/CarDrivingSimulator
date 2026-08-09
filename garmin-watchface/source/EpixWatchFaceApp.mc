using Toybox.Application as App;
using Toybox.WatchUi as Ui;

//! Aplicación de la esfera de reloj para el Garmin Epix Pro 51 mm.
//! Estilo digital moderno: fondo oscuro, acento azul, hora grande,
//! con día de la semana y fecha.
class EpixWatchFaceApp extends App.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    //! Se llama al arrancar la app.
    function onStart(state) {
    }

    //! Se llama al cerrar la app.
    function onStop(state) {
    }

    //! Devuelve la vista inicial (la esfera).
    function getInitialView() {
        return [ new EpixWatchFaceView() ];
    }

    //! Cuando el usuario cambia los ajustes desde Garmin Connect / Connect IQ,
    //! forzamos un redibujado para que se apliquen al instante.
    function onSettingsChanged() {
        Ui.requestUpdate();
    }
}
