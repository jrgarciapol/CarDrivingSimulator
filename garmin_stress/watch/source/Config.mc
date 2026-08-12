//! Constantes y ajustes de la app.
//!
//! Todo lo que puedas querer tocar sin bucear en el resto del código está
//! aquí. Los identificadores de campo FIT (FLD_*) tienen que ser únicos
//! dentro de la app y NO se deben cambiar una vez empieces a grabar datos:
//! el pipeline de Python los localiza por nombre, pero el id es lo que va
//! escrito en el fichero.

using Toybox.Lang;

module Config {

    // ---------------------------------------------------------------
    // Grabación
    // ---------------------------------------------------------------

    //! Huecos R-R por registro FIT. Los registros se escriben a 1 Hz como
    //! mucho, así que un solo hueco perdería latidos en cuanto pasases de
    //! 60 ppm. Con 4 huecos aguantamos hasta 240 ppm sin perder ninguno.
    const RR_SLOTS = 4;

    //! true  -> un único campo FIT de tipo array uint16[RR_SLOTS].
    //! false -> RR_SLOTS campos escalares rr0..rr3 (plan B si tu versión
    //!          del SDK no acepta la opción :count en createField).
    //! El pipeline de Python entiende los dos formatos.
    const RR_ARRAY_FIELD = true;

    //! Periodo del callback de sensores, en segundos. 1 s es el mínimo y
    //! el que queremos: cuanto más largo, más latidos se acumulan en cada
    //! entrega y más memoria hace falta.
    const SENSOR_PERIOD_S = 1;

    //! Frecuencia de muestreo del acelerómetro (Hz). 25 Hz sobra para un
    //! índice de movimiento; subirlo solo gasta batería.
    const ACCEL_HZ = 25;

    //! Segundos que una marca permanece "pegada" en el campo FIT. Los
    //! registros los escribe el sistema de forma asíncrona, así que hay
    //! que mantener el valor más de un tick para no perderlo por una
    //! carrera. El pipeline deduplica por número de secuencia.
    const MARK_LATCH_S = 3;

    // ---------------------------------------------------------------
    // Limpieza de artefactos (idéntica a pipeline/rr.py — no la toques
    // en un sitio sin tocarla en el otro, o el modelo verá en el reloj
    // features distintas de las que se entrenaron)
    // ---------------------------------------------------------------

    //! Intervalo R-R fisiológicamente posible, en ms (200 ppm .. 30 ppm).
    const RR_MIN_MS = 300;
    const RR_MAX_MS = 2000;

    //! Filtro de Malik: se descarta un latido si difiere del anterior
    //! válido en más de este porcentaje.
    const RR_MALIK_PCT = 0.20;

    // ---------------------------------------------------------------
    // Ventanas de análisis en vivo
    // ---------------------------------------------------------------

    //! Ventana deslizante para las métricas HRV en vivo, en ms.
    //! 60 s es el mínimo con el que el RMSSD ultra-corto sigue estando
    //! bien correlacionado con el de 5 min.
    const HRV_WINDOW_MS = 60000;

    //! Latidos que caben en el buffer circular (~5 min a 60 ppm).
    const RR_BUFFER_SIZE = 320;

    //! Mínimo de latidos válidos en la ventana para dar por buena una
    //! métrica HRV.
    const HRV_MIN_BEATS = 30;

    //! Fracción máxima de artefactos tolerada en la ventana.
    const HRV_MAX_ARTIFACT = 0.15;

    // ---------------------------------------------------------------
    // Línea base personal (media/varianza móviles exponenciales)
    // ---------------------------------------------------------------

    //! Constante de tiempo de la línea base, en segundos (~30 min).
    const BASELINE_TAU_S = 1800.0;

    //! Segundos de calentamiento antes de fiarse de la línea base. Es el
    //! lote con el que se estiman tu media y tu varianza del día.
    const BASELINE_WARMUP_S = 600;

    //! Muestras mínimas del lote de arranque (además del tiempo).
    const BASELINE_MIN_SAMPLES = 20;

    //! Suelo de la desviación típica estimada, como fracción de SD0.
    const BASELINE_SD_FLOOR = 0.2;

    //! Recorte de los valores normalizados. Un artefacto que se cuele no
    //! debe poder saturar la sigmoide él solo.
    const Z_CLIP = 5.0;

    //! Por encima de este índice de movimiento (mg) consideramos que hay
    //! actividad física: ni se actualiza la línea base ni se avisa.
    const MOVE_THRESHOLD_MG = 60;

    // ---------------------------------------------------------------
    // Política de avisos (fase 4)
    // ---------------------------------------------------------------

    //! Minutos mínimos entre dos preguntas al usuario.
    const PROMPT_REFRACTORY_MIN = 10;

    //! Tope de preguntas por sesión. Si preguntas más, dejas de contestar
    //! y los datos que recoges valen menos que los que estropeas.
    const PROMPT_MAX_PER_SESSION = 8;

    //! Segundos que espera la pantalla de confirmación antes de rendirse.
    const PROMPT_TIMEOUT_S = 45;

    //! Ventana de tiempo para contar pulsaciones múltiples, en ms.
    const MULTITAP_WINDOW_MS = 900;

    // ---------------------------------------------------------------
    // Códigos de marca (campo FIT "mark")
    // ---------------------------------------------------------------

    //! Marcas espontáneas del usuario (vía B: tú marcas cuando quieres,
    //! haya detectado algo el reloj o no).
    const MARK_NONE       = 0;
    const MARK_STRESS_1   = 1;   //! leve
    const MARK_STRESS_2   = 2;   //! moderado
    const MARK_STRESS_3   = 3;   //! intenso
    const MARK_CALM       = 4;   //! el usuario declara calma (negativo real)

    //! Respuestas a una pregunta del reloj (vía A). Van con +10 para
    //! poder distinguir "lo marqué yo" de "me lo preguntó y contesté":
    //! son estadísticamente distintos y hay que poder separarlos al
    //! entrenar (los espontáneos están sesgados hacia lo memorable, los
    //! preguntados hacia donde el modelo ya miraba).
    const MARK_PROMPT_BASE  = 10;
    const MARK_PROMPT_YES_1 = 11;
    const MARK_PROMPT_YES_2 = 12;
    const MARK_PROMPT_YES_3 = 13;
    const MARK_PROMPT_NO    = 15;  //! preguntó y dijiste que no
    const MARK_PROMPT_SKIP  = 19;  //! preguntó y no contestaste

    //! ¿La marca es respuesta a una pregunta del reloj?
    function isPromptReply(m as Lang.Number) as Lang.Boolean {
        return m >= MARK_PROMPT_BASE;
    }

    //! Nivel de estrés de una marca (0 si declara calma o dice que no).
    function stressLevel(m as Lang.Number) as Lang.Number {
        var v = m % 10;
        return (v >= 1 && v <= 3) ? v : 0;
    }

    // ---------------------------------------------------------------
    // Códigos de inicio del episodio (campo FIT "onset")
    // ---------------------------------------------------------------

    const ONSET_NOW   = 0;   //! empezó ahora mismo
    const ONSET_1MIN  = 1;
    const ONSET_3MIN  = 2;
    const ONSET_10MIN = 3;   //! 10 min o más

    //! Segundos hacia atrás que representa cada código.
    function onsetSeconds(code as Lang.Number) as Lang.Number {
        if (code == ONSET_1MIN)  { return 60;  }
        if (code == ONSET_3MIN)  { return 180; }
        if (code == ONSET_10MIN) { return 600; }
        return 0;
    }

    // ---------------------------------------------------------------
    // Identificadores de campo FIT (¡no reutilizar!)
    // ---------------------------------------------------------------

    // Por registro (1 Hz)
    const FLD_RR        = 0;   //! uint16[RR_SLOTS], ms
    const FLD_RR_N      = 1;   //! uint8, latidos válidos escritos
    const FLD_ACT       = 2;   //! uint16, índice de movimiento, mg
    const FLD_MARK      = 3;   //! uint8, código MARK_*
    const FLD_MARK_SEQ  = 4;   //! uint8, contador de marcas (deduplicación)
    const FLD_ONSET     = 5;   //! uint8, código ONSET_*
    const FLD_RMSSD     = 6;   //! uint16, ms (calculado en el reloj)
    const FLD_PSTRESS   = 7;   //! uint8, probabilidad del modelo x100
    const FLD_AX        = 8;   //! sint16, aceleración media eje x, mg
    const FLD_AY        = 9;
    const FLD_AZ        = 10;
    const FLD_RR_LOST   = 11;  //! uint8, latidos que no cupieron (debe ser 0)

    // Por sesión (resumen)
    const FLD_S_MARKS   = 20;  //! uint16, marcas totales
    const FLD_S_BEATS   = 21;  //! uint32, latidos totales
    const FLD_S_MODELV  = 22;  //! uint16, versión del modelo cargado
    const FLD_S_LOST    = 23;  //! uint32, latidos perdidos totales

    // Los primeros campos escalares del plan B (RR_ARRAY_FIELD = false)
    // ocupan 12, 13, 14, 15.
    const FLD_RR_SCALAR_BASE = 12;
}
