//! GENERADO — no editar a mano.
//!
//! Este fichero lo reescribe pipeline/export_monkeyc.py a partir del
//! modelo entrenado. Lo que ves ahora es el estado inicial de la fase 1:
//! TRAINED = false, o sea, el reloj solo graba y nunca pregunta.
//!
//! Ciclo: grabas -> entrenas en el PC -> regeneras este fichero ->
//! recompilas la app -> el reloj ya infiere y pregunta.

using Toybox.Lang;

module ModelParams {

    //! Sube con cada reentrenamiento. Se guarda en el resumen de la
    //! sesión FIT para saber después qué modelo generó qué avisos.
    const MODEL_VERSION = 0;

    //! Mientras sea false el detector no infiere ni pregunta.
    const TRAINED = false;

    //! Pesos de la regresión logística, en el orden de module Features:
    //! mean_hr, sdnn, log_rmssd, pnn50, act.
    const W = [0.0, 0.0, 0.0, 0.0, 0.0];

    //! Término independiente.
    const B0 = 0.0;

    //! ¿Normalizar contra la línea base móvil personal (true) o contra
    //! una media/desviación fija (false)? El movimiento va en absoluto:
    //! "quieto" es quieto para cualquiera.
    const USE_Z = [true, true, true, true, false];

    //! Valores iniciales de la línea base. Son a priori razonables para
    //! un adulto en reposo; en cuanto arranca la sesión se van ajustando
    //! solos a los tuyos.
    const MU0 = [70.0, 45.0, 3.5, 0.12, 30.0];
    const SD0 = [10.0, 20.0, 0.5, 0.10, 40.0];

    //! Umbral de alerta: por encima, el reloj cree que hay estrés.
    //! Lo fija el entrenamiento para no pasar de N falsas alarmas al día.
    const P_ALERT = 0.80;

    //! Banda de incertidumbre para el aprendizaje activo.
    const P_UNC_LO = 0.35;
    const P_UNC_HI = 0.65;
}
