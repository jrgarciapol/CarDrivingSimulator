//! Ventana deslizante de intervalos R-R y métricas HRV en el reloj.
//!
//! IMPORTANTE: la limpieza de artefactos y las fórmulas de este fichero
//! tienen que ser idénticas a las de pipeline/rr.py y pipeline/features.py.
//! Si el reloj calcula el RMSSD de una manera y el entrenamiento de otra,
//! el modelo estará viendo en producción unas features distintas de las
//! que aprendió y no habrá forma de saber por qué falla.
//! El test tests/test_parity.py comprueba que coinciden.

using Toybox.System;
using Toybox.Math;
using Toybox.Lang;

//! Orden canónico del vector de features en vivo. ModelParams.W viene en
//! este mismo orden y export_monkeyc.py lo verifica al generarlo.
//!
//! Son cinco y no siete a propósito. Estaban también MEAN_NN y RMSSD, y
//! sobran: MEAN_NN es exactamente 60000/MEAN_HR y RMSSD es exp(LOG_RMSSD).
//! Meter las dos versiones de la misma magnitud no añade información, y
//! sí rompe los coeficientes: la regresión reparte el peso entre features
//! colineales de forma arbitraria y salen signos absurdos (RMSSD alto
//! prediciendo estrés). Con features independientes, el signo de cada
//! coeficiente se puede leer y comprobar contra la fisiología.
module Features {
    const MEAN_HR   = 0;   //! ppm
    const SDNN      = 1;   //! ms
    const LOG_RMSSD = 2;   //! ln(ms) — más simétrico que el RMSSD crudo
    const PNN50     = 3;   //! 0..1
    const ACT       = 4;   //! mg
    const COUNT     = 5;
}

class HrvWindow {

    private var mRr = null;      // ms
    private var mT = null;       // System.getTimer() de recepción, ms
    private var mHead = 0;       // siguiente hueco a escribir
    private var mCount = 0;

    function initialize() {
        mRr = new [Config.RR_BUFFER_SIZE];
        mT = new [Config.RR_BUFFER_SIZE];
    }

    function push(rr as Lang.Number) as Void {
        mRr[mHead] = rr;
        mT[mHead] = System.getTimer();
        mHead = (mHead + 1) % Config.RR_BUFFER_SIZE;
        if (mCount < Config.RR_BUFFER_SIZE) { mCount++; }
    }

    function size() as Lang.Number { return mCount; }

    //! Métricas de la ventana de los últimos Config.HRV_WINDOW_MS.
    //! Devuelve null si no hay latidos suficientes o hay demasiados
    //! artefactos: es preferible no dar un número a dar uno inventado.
    function features() as Lang.Dictionary or Null {
        if (mCount < Config.HRV_MIN_BEATS) { return null; }

        var now = System.getTimer();
        var cutoff = now - Config.HRV_WINDOW_MS;

        // Recorremos del más antiguo al más nuevo aplicando el mismo
        // filtro que rr.py: rango fisiológico + Malik contra el último
        // latido válido.
        var sum = 0.0;      // suma de NN válidos
        var sum2 = 0.0;     // suma de NN^2
        var n = 0;          // NN válidos
        var total = 0;      // latidos en ventana (válidos o no)
        var sumDiff2 = 0.0; // suma de (NN_i+1 - NN_i)^2 de pares seguidos
        var nDiff = 0;
        var nn50 = 0;

        var prevValid = null;   // último NN válido
        var prevWasAdjacent = false;

        var start = (mHead - mCount + Config.RR_BUFFER_SIZE) % Config.RR_BUFFER_SIZE;
        for (var k = 0; k < mCount; k++) {
            var i = (start + k) % Config.RR_BUFFER_SIZE;
            if (mT[i] < cutoff) { continue; }
            var rr = mRr[i].toFloat();
            total++;

            var ok = (rr >= Config.RR_MIN_MS && rr <= Config.RR_MAX_MS);
            if (ok && prevValid != null) {
                var d = rr - prevValid;
                if (d < 0) { d = -d; }
                if (d > Config.RR_MALIK_PCT * prevValid) { ok = false; }
            }

            if (!ok) {
                // Un latido descartado rompe la cadena: la diferencia con
                // el siguiente cruzaría el hueco y no sería una diferencia
                // entre latidos consecutivos reales.
                prevWasAdjacent = false;
                continue;
            }

            sum += rr;
            sum2 += rr * rr;
            n++;

            if (prevValid != null && prevWasAdjacent) {
                var dd = rr - prevValid;
                sumDiff2 += dd * dd;
                nDiff++;
                if (dd > 50.0 || dd < -50.0) { nn50++; }
            }
            prevValid = rr;
            prevWasAdjacent = true;
        }

        if (n < Config.HRV_MIN_BEATS || nDiff < 2) { return null; }
        var artifacts = (total > 0) ? (total - n).toFloat() / total : 1.0;
        if (artifacts > Config.HRV_MAX_ARTIFACT) { return null; }

        var meanNn = sum / n;
        var variance = sum2 / n - meanNn * meanNn;
        if (variance < 0.0) { variance = 0.0; }
        var sdnn = Math.sqrt(variance);
        var rmssd = Math.sqrt(sumDiff2 / nDiff);
        var pnn50 = nn50.toFloat() / nDiff;

        return {
            :meanNn => meanNn,
            :meanHr => 60000.0 / meanNn,
            :sdnn => sdnn,
            :rmssd => rmssd,
            :pnn50 => pnn50,
            :logRmssd => Math.ln(rmssd > 1.0 ? rmssd : 1.0),
            :n => n,
            :artifacts => artifacts
        };
    }
}

//! Línea base personal: lote de arranque y después media móvil.
//!
//! Un umbral absoluto de RMSSD no vale para nada aquí. El RMSSD sano de
//! una persona puede ser 20 ms y el de otra 90 ms, y el de la misma
//! persona cambia a lo largo del día. Lo que detecta estrés es la caída
//! RELATIVA a tu propia base reciente.
//!
//! Los primeros BASELINE_WARMUP_S segundos se acumulan para calcular
//! media y varianza por lotes; después se sigue con una media móvil
//! exponencial. Arrancar la varianza directamente en la exponencial
//! desde un valor a priori NO funciona: con tau = 30 min, una varianza
//! inicial equivocada tarda más de una hora en corregirse y mientras
//! tanto los z-scores salen mal escalados (medido: la separación de
//! log_rmssd caía de AUC 0,67 a 0,48). Ver la clase gemela en
//! pipeline/dataset.py.
class RunningStat {

    private var mMean = 0.0;
    private var mVar = 0.0;
    private var mVarFloor = 0.0;
    private var mAge = 0;        // segundos de datos incorporados
    private var mN = 0;
    private var mSum = 0.0;
    private var mSum2 = 0.0;
    private var mBurned = false;

    function initialize(mean0 as Lang.Float, sd0 as Lang.Float) {
        mMean = mean0;
        mVar = sd0 * sd0;
        // Suelo permanente de la varianza, no solo al cerrar el lote de
        // arranque: la varianza exponencial DECAE cuando la entrada es
        // muy estable, y sin suelo acabaría en cero. A partir de ahí,
        // cualquier fluctuación normal daría un z-score enorme y el
        // reloj vibraría sin motivo. Aparece justo después de un rato
        // largo sentado y tranquilo, que es el caso de uso.
        var floor = Config.BASELINE_SD_FLOOR * sd0;
        mVarFloor = floor * floor;
    }

    //! dt = segundos transcurridos desde la última actualización.
    function update(x as Lang.Float, dt as Lang.Number) as Void {
        mAge += dt;

        if (!mBurned) {
            mN++;
            mSum += x;
            mSum2 += x * x;
            mMean = mSum / mN;
            if (mAge >= Config.BASELINE_WARMUP_S && mN >= Config.BASELINE_MIN_SAMPLES) {
                var v = mSum2 / mN - mMean * mMean;
                mVar = (v > mVarFloor) ? v : mVarFloor;
                mBurned = true;
            }
            return;
        }

        var alpha = dt / Config.BASELINE_TAU_S;
        if (alpha > 1.0) { alpha = 1.0; }
        var d = x - mMean;
        mMean += alpha * d;
        mVar += alpha * (d * d - mVar);
    }

    function ready() as Lang.Boolean { return mBurned; }

    function z(x as Lang.Float) as Lang.Float {
        var sd = Math.sqrt(mVar > mVarFloor ? mVar : mVarFloor);
        if (sd < 1e-9) { return 0.0; }
        var v = (x - mMean) / sd;
        if (v > Config.Z_CLIP)  { return Config.Z_CLIP;  }
        if (v < -Config.Z_CLIP) { return -Config.Z_CLIP; }
        return v;
    }

    function mean() as Lang.Float { return mMean; }
}
