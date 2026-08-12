//! Inferencia en el reloj y política de cuándo preguntar (fase 4).
//!
//! El modelo que corre aquí es una regresión logística sobre features
//! normalizadas contra tu línea base móvil. Son cinco multiplicaciones y
//! una suma: cabe de sobra en el reloj y, sobre todo, es exactamente el
//! mismo cálculo que hace scikit-learn en el PC, así que se puede
//! verificar bit a bit (tests/test_parity.py).
//!
//! La política de avisos merece más atención de la que parece. El
//! instinto es avisar cuando el modelo está MUY seguro de que hay
//! estrés, pero para APRENDER eso es justo lo que menos información
//! aporta: si el modelo ya está seguro, tu respuesta no le enseña casi
//! nada. Los casos que más enseñan son los que caen cerca de la frontera
//! de decisión (muestreo por incertidumbre). Por eso repartimos el
//! presupuesto de preguntas entre las dos cosas: alertas útiles para ti
//! y preguntas dudosas útiles para el modelo.

using Toybox.Math;
using Toybox.Lang;

//! Motivos por los que se pide confirmación.
module Reason {
    const NONE = 0;
    const ALERT = 1;        //! el modelo cree que estás estresado
    const UNCERTAIN = 2;    //! el modelo no lo tiene claro
}

class Detector {

    private var mStats = null;         // Array<RunningStat>, uno por feature
    private var mLastPromptS = -99999;
    private var mPrompts = 0;
    private var mReason = 0;
    private var mP = 0.0;              // probabilidad 0..1

    function initialize() {
        mStats = new [Features.COUNT];
        for (var i = 0; i < Features.COUNT; i++) {
            mStats[i] = new RunningStat(ModelParams.MU0[i], ModelParams.SD0[i]);
        }
    }

    //! Se llama una vez por segundo. Devuelve la probabilidad en 0..100
    //! para escribirla en el FIT.
    function update(f as Lang.Dictionary, actIndex as Lang.Number,
                    quiet as Lang.Boolean, elapsedS as Lang.Number) as Lang.Number {

        var x = new [Features.COUNT];
        x[Features.MEAN_HR]   = f[:meanHr];
        x[Features.SDNN]      = f[:sdnn];
        x[Features.LOG_RMSSD] = f[:logRmssd];
        x[Features.PNN50]     = f[:pnn50];
        x[Features.ACT]       = actIndex.toFloat();

        // --- Normalización ---
        var z = new [Features.COUNT];
        var ready = true;
        for (var i = 0; i < Features.COUNT; i++) {
            if (ModelParams.USE_Z[i]) {
                z[i] = mStats[i].z(x[i]);
                if (!mStats[i].ready()) { ready = false; }
            } else {
                var sd = ModelParams.SD0[i];
                var v = (sd > 1e-6) ? (x[i] - ModelParams.MU0[i]) / sd : 0.0;
                // Mismo recorte que en RunningStat.z(): un rato andando
                // deprisa dispara el acelerómetro a z=8 y, con un peso
                // grande, satura la sigmoide él solo.
                if (v > Config.Z_CLIP)  { v = Config.Z_CLIP;  }
                if (v < -Config.Z_CLIP) { v = -Config.Z_CLIP; }
                z[i] = v;
            }
        }

        // --- Modelo ---
        if (ModelParams.TRAINED) {
            var acc = ModelParams.B0;
            for (var i = 0; i < Features.COUNT; i++) {
                acc += ModelParams.W[i] * z[i];
            }
            mP = sigmoid(acc);
        } else {
            mP = 0.0;
        }

        // --- Línea base ---
        // Solo se actualiza cuando estás quieto y el modelo no cree que
        // estés estresado. Si dejásemos que la base siguiera al estrés,
        // en veinte minutos consideraría normal estar tenso y dejaría de
        // detectar nada.
        if (quiet && mP < 0.5) {
            for (var i = 0; i < Features.COUNT; i++) {
                mStats[i].update(x[i], 1);
            }
        }

        // --- ¿Preguntamos? ---
        mReason = Reason.NONE;
        if (ModelParams.TRAINED && ready && quiet && budgetLeft(elapsedS)) {
            if (mP >= ModelParams.P_ALERT) {
                mReason = Reason.ALERT;
            } else if (mP >= ModelParams.P_UNC_LO && mP <= ModelParams.P_UNC_HI) {
                mReason = Reason.UNCERTAIN;
            }
        }

        return Math.round(mP * 100.0).toNumber();
    }

    private function budgetLeft(elapsedS as Lang.Number) as Lang.Boolean {
        if (mPrompts >= Config.PROMPT_MAX_PER_SESSION) { return false; }
        return (elapsedS - mLastPromptS) >= Config.PROMPT_REFRACTORY_MIN * 60;
    }

    //! Motivo por el que habría que preguntar ahora (0 = ninguno).
    function promptReason() as Lang.Number { return mReason; }

    //! Registra que acabamos de preguntar (o que el usuario se ha
    //! adelantado marcando a mano, que cuenta igual).
    function notePrompted(elapsedS as Lang.Number) as Void {
        mLastPromptS = elapsedS;
        mPrompts++;
        mReason = Reason.NONE;
    }

    function probability() as Lang.Float { return mP; }
    function promptsUsed() as Lang.Number { return mPrompts; }

    private function sigmoid(v as Lang.Float) as Lang.Float {
        // Recortado para que Math.pow no desborde con entradas absurdas.
        if (v >  30.0) { return 1.0; }
        if (v < -30.0) { return 0.0; }
        return 1.0 / (1.0 + Math.pow(2.718281828459045, -v));
    }
}
