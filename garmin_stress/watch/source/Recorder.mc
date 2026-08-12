//! Grabador: sesión FIT, campos personalizados y lectura de sensores.
//!
//! El reloj hace de datalogger y de interfaz, nada más. Aquí no se
//! entrena nada: se registran los intervalos R-R crudos, un índice de
//! movimiento derivado del acelerómetro y las marcas del usuario.
//!
//! El cuello de botella importante: los mensajes "record" de un fichero
//! FIT se escriben como mucho a 1 Hz, y un campo escalar por registro
//! solo puede guardar un valor por segundo. Por encima de 60 ppm eso
//! perdería latidos, que es justo lo que no nos podemos permitir (el
//! RMSSD se calcula sobre diferencias entre latidos consecutivos: un
//! latido perdido no es ruido, es una diferencia inventada). Por eso los
//! R-R van a un campo array de Config.RR_SLOTS huecos, alimentado desde
//! una cola: en un segundo caben hasta 4 latidos y sobra.

using Toybox.ActivityRecording;
using Toybox.Activity;
using Toybox.FitContributor;
using Toybox.Sensor;
using Toybox.System;
using Toybox.Timer;
using Toybox.Math;
using Toybox.Lang;
using Toybox.Attention;
using Toybox.WatchUi;

class Recorder {

    // --- Sesión y campos FIT -------------------------------------
    private var mSession = null;
    private var mFldRr = null;               // array uint16[RR_SLOTS]
    private var mFldRrScalar = null;         // plan B: 4 campos escalares
    private var mFldRrN = null;
    private var mFldRrLost = null;
    private var mFldAct = null;
    private var mFldMark = null;
    private var mFldMarkSeq = null;
    private var mFldOnset = null;
    private var mFldRmssd = null;
    private var mFldPStress = null;
    private var mFldAx = null;
    private var mFldAy = null;
    private var mFldAz = null;

    // Resumen de sesión
    private var mFldSMarks = null;
    private var mFldSBeats = null;
    private var mFldSLost = null;
    private var mFldSModelV = null;

    // --- Estado --------------------------------------------------
    private var mTimer = null;
    private var mRrQueue = [];               // cola FIFO de R-R pendientes
    private var mHrv = null;                 // HrvWindow
    private var mDetector = null;            // Detector
    private var mListening = false;

    private var mBeats = 0;
    private var mLostBeats = 0;
    private var mMarks = 0;
    private var mElapsedS = 0;

    private var mActIndex = 0;               // mg
    private var mAx = 0;
    private var mAy = 0;
    private var mAz = 0;

    private var mMarkLevel = Config.MARK_NONE;
    private var mMarkSeq = 0;
    private var mMarkOnset = Config.ONSET_NOW;
    private var mMarkLatch = 0;              // ticks que quedan pegada

    private var mLastRmssd = 0;
    private var mPStress = 0;                // 0..100
    private var mOnPrompt = null;            // callback a la interfaz

    function initialize() {
        mHrv = new HrvWindow();
        mDetector = new Detector();
    }

    // -----------------------------------------------------------------
    // Ciclo de vida
    // -----------------------------------------------------------------

    //! Arranca la sesión. Devuelve true si se pudo crear.
    function start() as Lang.Boolean {
        if (mSession != null) { return true; }

        // SPORT_GENERIC a propósito: una "actividad" de 8 horas todos los
        // días con otro tipo de deporte le destroza a Garmin Connect el
        // estado de entrenamiento, la carga aguda y el Body Battery.
        // Genérico no computa como entrenamiento.
        mSession = ActivityRecording.createSession({
            :name => "EMA Estres",
            :sport => Activity.SPORT_GENERIC,
            :subSport => Activity.SUB_SPORT_GENERIC
        });
        if (mSession == null) { return false; }

        createFields();

        Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE]);
        Sensor.registerSensorDataListener(method(:onSensorData), {
            :period => Config.SENSOR_PERIOD_S,
            :heartBeatIntervals => { :enabled => true },
            :accelerometer => { :enabled => true, :sampleRate => Config.ACCEL_HZ }
        });
        mListening = true;

        mSession.start();

        mTimer = new Timer.Timer();
        mTimer.start(method(:onTick), 1000, true);
        return true;
    }

    //! Para la sesión. save=true la guarda en /GARMIN/ACTIVITY/.
    function stop(save as Lang.Boolean) as Void {
        if (mTimer != null) { mTimer.stop(); mTimer = null; }
        if (mListening) {
            Sensor.unregisterSensorDataListener();
            mListening = false;
        }
        if (mSession != null) {
            // El resumen se escribe ANTES de parar: los campos ya están
            // creados desde el arranque y solo hay que darles su valor.
            writeSessionSummary();
            if (mSession.isRecording()) { mSession.stop(); }
            if (save) { mSession.save(); } else { mSession.discard(); }
            mSession = null;
        }
    }

    //! La interfaz registra aquí qué hacer cuando el detector quiere
    //! preguntar. El grabador no sabe nada de vistas.
    function setPromptCallback(cb as Lang.Method) as Void {
        mOnPrompt = cb;
    }

    function shutdown() as Void {
        // Al salir de la app guardamos siempre: perder medio día de datos
        // por cerrar sin querer sería doloroso.
        stop(true);
    }

    private function createFields() as Void {
        if (Config.RR_ARRAY_FIELD) {
            mFldRr = mSession.createField("rr", Config.FLD_RR,
                FitContributor.DATA_TYPE_UINT16,
                { :mesgType => FitContributor.MESG_TYPE_RECORD,
                  :units => "ms", :count => Config.RR_SLOTS });
        } else {
            // Plan B: un campo escalar por hueco. Ocupa más en el fichero
            // pero no depende de que :count esté soportado.
            mFldRrScalar = new [Config.RR_SLOTS];
            for (var i = 0; i < Config.RR_SLOTS; i++) {
                mFldRrScalar[i] = mSession.createField("rr" + i,
                    Config.FLD_RR_SCALAR_BASE + i,
                    FitContributor.DATA_TYPE_UINT16,
                    { :mesgType => FitContributor.MESG_TYPE_RECORD, :units => "ms" });
            }
        }

        mFldRrN     = record("rr_n",    Config.FLD_RR_N,    FitContributor.DATA_TYPE_UINT8,  "");
        mFldRrLost  = record("rr_lost", Config.FLD_RR_LOST, FitContributor.DATA_TYPE_UINT8,  "");
        mFldAct     = record("act",     Config.FLD_ACT,     FitContributor.DATA_TYPE_UINT16, "mg");
        mFldMark    = record("mark",    Config.FLD_MARK,    FitContributor.DATA_TYPE_UINT8,  "");
        mFldMarkSeq = record("mark_seq",Config.FLD_MARK_SEQ,FitContributor.DATA_TYPE_UINT8,  "");
        mFldOnset   = record("onset",   Config.FLD_ONSET,   FitContributor.DATA_TYPE_UINT8,  "");
        mFldRmssd   = record("rmssd",   Config.FLD_RMSSD,   FitContributor.DATA_TYPE_UINT16, "ms");
        mFldPStress = record("p_stress",Config.FLD_PSTRESS, FitContributor.DATA_TYPE_UINT8,  "%");
        mFldAx      = record("ax",      Config.FLD_AX,      FitContributor.DATA_TYPE_SINT16, "mg");
        mFldAy      = record("ay",      Config.FLD_AY,      FitContributor.DATA_TYPE_SINT16, "mg");
        mFldAz      = record("az",      Config.FLD_AZ,      FitContributor.DATA_TYPE_SINT16, "mg");

        mFldSMarks  = summaryField("n_marks", Config.FLD_S_MARKS,  FitContributor.DATA_TYPE_UINT16);
        mFldSBeats  = summaryField("n_beats", Config.FLD_S_BEATS,  FitContributor.DATA_TYPE_UINT32);
        mFldSLost   = summaryField("n_lost",  Config.FLD_S_LOST,   FitContributor.DATA_TYPE_UINT32);
        mFldSModelV = summaryField("model_v", Config.FLD_S_MODELV, FitContributor.DATA_TYPE_UINT16);
    }

    private function record(name, id, type, units) {
        return mSession.createField(name, id, type,
            { :mesgType => FitContributor.MESG_TYPE_RECORD, :units => units });
    }

    private function summaryField(name, id, type) {
        return mSession.createField(name, id, type,
            { :mesgType => FitContributor.MESG_TYPE_SESSION });
    }

    //! Vuelca los contadores a los campos de resumen.
    //!
    //! Los campos se crearon al arrancar, no aquí: crear campos FIT con
    //! la sesión ya parada no es de fiar, y el resumen es justo lo que
    //! querrías tener si algo ha ido mal durante la grabación.
    private function writeSessionSummary() as Void {
        if (mFldSMarks == null) { return; }
        mFldSMarks.setData(mMarks);
        mFldSBeats.setData(mBeats);
        mFldSLost.setData(mLostBeats);
        mFldSModelV.setData(ModelParams.MODEL_VERSION);
    }

    // -----------------------------------------------------------------
    // Sensores
    // -----------------------------------------------------------------

    //! Llega una vez por Config.SENSOR_PERIOD_S con TODO lo acumulado.
    //! Este es el único sitio del que salen intervalos R-R: el campo
    //! Activity.Info.currentHeartRate es una media a 1 Hz y no sirve.
    function onSensorData(data as Sensor.SensorData) as Void {
        if (data has :heartRateData && data.heartRateData != null) {
            var iv = data.heartRateData.heartBeatIntervals;
            if (iv != null) {
                for (var i = 0; i < iv.size(); i++) {
                    var rr = iv[i];
                    if (rr != null && rr > 0) {
                        mBeats++;
                        mHrv.push(rr);
                        if (mRrQueue.size() < 4 * Config.RR_SLOTS) {
                            mRrQueue.add(rr);
                        } else {
                            // No debería pasar nunca (haría falta >240 ppm
                            // sostenidos). Lo contamos para enterarnos.
                            mLostBeats++;
                        }
                    }
                }
            }
        }

        if (data has :accelerometerData && data.accelerometerData != null) {
            updateMovement(data.accelerometerData);
        }
    }

    //! Reduce 25 muestras/s de 3 ejes a cuatro números. El acelerómetro
    //! crudo no cabe en el FIT ni haría falta: lo que necesitamos es
    //! distinguir "quieto y tenso" de "subiendo escaleras".
    private function updateMovement(acc) as Void {
        var x = acc.x; var y = acc.y; var z = acc.z;
        if (x == null || x.size() == 0) { return; }
        var n = x.size();

        var sum = 0.0; var sum2 = 0.0;
        var sx = 0.0; var sy = 0.0; var sz = 0.0;
        for (var i = 0; i < n; i++) {
            var xi = x[i].toFloat();
            var yi = y[i].toFloat();
            var zi = z[i].toFloat();
            var m = Math.sqrt(xi * xi + yi * yi + zi * zi);
            sum += m; sum2 += m * m;
            sx += xi; sy += yi; sz += zi;
        }
        var mean = sum / n;
        // Desviación típica del módulo: inmune a la orientación del reloj,
        // que es lo que la hace un buen índice de movimiento.
        var v = sum2 / n - mean * mean;
        if (v < 0.0) { v = 0.0; }
        mActIndex = Math.round(Math.sqrt(v)).toNumber();
        if (mActIndex > 65535) { mActIndex = 65535; }

        // La media de cada eje da la dirección de la gravedad, o sea la
        // postura. Un cambio brusco = te has levantado, y levantarse tira
        // el RMSSD tanto como un disgusto.
        mAx = Math.round(sx / n).toNumber();
        mAy = Math.round(sy / n).toNumber();
        mAz = Math.round(sz / n).toNumber();
    }

    // -----------------------------------------------------------------
    // Tick de 1 Hz: vuelca a los campos FIT
    // -----------------------------------------------------------------

    function onTick() as Void {
        mElapsedS++;

        // --- Intervalos R-R pendientes ---
        var take = mRrQueue.size();
        if (take > Config.RR_SLOTS) { take = Config.RR_SLOTS; }

        if (Config.RR_ARRAY_FIELD) {
            var slots = new [Config.RR_SLOTS];
            for (var i = 0; i < Config.RR_SLOTS; i++) {
                slots[i] = (i < take) ? mRrQueue[i] : 0;
            }
            mFldRr.setData(slots);
        } else {
            for (var i = 0; i < Config.RR_SLOTS; i++) {
                mFldRrScalar[i].setData((i < take) ? mRrQueue[i] : 0);
            }
        }
        mRrQueue = mRrQueue.slice(take, null);
        mFldRrN.setData(take);
        mFldRrLost.setData(mLostBeats > 255 ? 255 : mLostBeats);

        // --- Movimiento ---
        mFldAct.setData(mActIndex);
        mFldAx.setData(clampS16(mAx));
        mFldAy.setData(clampS16(mAy));
        mFldAz.setData(clampS16(mAz));

        // --- HRV en vivo y modelo ---
        var f = mHrv.features();
        if (f != null) {
            mLastRmssd = f[:rmssd].toNumber();
            mFldRmssd.setData(mLastRmssd);
            var quiet = (mActIndex < Config.MOVE_THRESHOLD_MG);
            mPStress = mDetector.update(f, mActIndex, quiet, mElapsedS);
        } else {
            mFldRmssd.setData(0);
        }
        mFldPStress.setData(mPStress);

        // --- ¿Toca preguntar? ---
        // El callback de un Timer corre en el hilo de la interfaz, así
        // que se puede empujar una vista desde aquí sin problemas.
        var reason = mDetector.promptReason();
        if (reason != Reason.NONE && mOnPrompt != null) {
            mDetector.notePrompted(mElapsedS);
            mOnPrompt.invoke(reason);
        }

        // --- Marca (pegada unos segundos y luego se suelta) ---
        mFldMark.setData(mMarkLevel);
        mFldMarkSeq.setData(mMarkSeq);
        mFldOnset.setData(mMarkOnset);
        if (mMarkLatch > 0) {
            mMarkLatch--;
            if (mMarkLatch == 0) { mMarkLevel = Config.MARK_NONE; }
        }

        WatchUi.requestUpdate();
    }

    private function clampS16(v as Lang.Number) as Lang.Number {
        if (v > 32767)  { return 32767;  }
        if (v < -32768) { return -32768; }
        return v;
    }

    // -----------------------------------------------------------------
    // Marcas
    // -----------------------------------------------------------------

    //! Inyecta una marca en el registro FIT actual.
    //! El número de secuencia es lo que permite a Python separar dos
    //! marcas seguidas del mismo nivel sin depender de la latencia con
    //! la que el sistema escribe los registros.
    function mark(level as Lang.Number, onset as Lang.Number) as Void {
        mMarkLevel = level;
        mMarkOnset = onset;
        mMarkSeq = (mMarkSeq + 1) % 256;
        mMarkLatch = Config.MARK_LATCH_S;
        mMarks++;
        // Cualquier marca cuenta como interacción: acabas de decirnos lo
        // que pasa, no tiene sentido preguntártelo treinta segundos
        // después.
        mDetector.notePrompted(mElapsedS);
        buzz(level);
    }

    private function buzz(level as Lang.Number) as Void {
        if (!(Attention has :vibrate)) { return; }
        var n = Config.stressLevel(level);
        if (n < 1) { n = 1; }
        var profile = [];
        for (var i = 0; i < n; i++) {
            profile.add(new Attention.VibeProfile(50, 120));
            profile.add(new Attention.VibeProfile(0, 80));
        }
        Attention.vibrate(profile);
    }

    // -----------------------------------------------------------------
    // Consultas para la interfaz
    // -----------------------------------------------------------------

    function isRecording() as Lang.Boolean {
        return mSession != null && mSession.isRecording();
    }

    function elapsed()   as Lang.Number { return mElapsedS; }
    function beats()     as Lang.Number { return mBeats; }
    function marks()     as Lang.Number { return mMarks; }
    function rmssd()     as Lang.Number { return mLastRmssd; }
    function pStress()   as Lang.Number { return mPStress; }
    function actIndex()  as Lang.Number { return mActIndex; }
    function detector()               { return mDetector; }

    //! ¿Está llegando señal de la banda? Sin esto es fácil grabar dos
    //! horas de nada y no enterarte hasta que abres el fichero.
    function strapOk() as Lang.Boolean {
        var info = Activity.getActivityInfo();
        return info != null && info.currentHeartRate != null;
    }
}
