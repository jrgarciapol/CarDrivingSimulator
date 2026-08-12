//! Pregunta del reloj al usuario (vía A, fase 4).
//!
//! Aparece cuando el detector cree que merece la pena preguntar, y
//! caduca sola: una pregunta que lleva dos minutos en pantalla ya no se
//! refiere al estado fisiológico que la disparó. Si no contestas se
//! registra MARK_PROMPT_SKIP, que también es información — un patrón de
//! preguntas ignoradas suele significar que el modelo está avisando en
//! mal momento.

using Toybox.WatchUi;
using Toybox.Timer;
using Toybox.Attention;
using Toybox.Lang;

class PromptMenu extends WatchUi.Menu2 {

    function initialize(reason as Lang.Number) {
        // El título depende de por qué se pregunta, y no es cosmético.
        // Cuando el modelo cree que hay estrés, "¿estás estresado?" es la
        // pregunta correcta. Cuando el modelo DUDA, esa misma pregunta
        // sugiere la respuesta: te está diciendo que él cree que sí, y
        // contestarías sesgado. Justo en los casos dudosos, que son los
        // que más enseñan, hay que preguntar en abierto.
        var title = (reason == Reason.UNCERTAIN)
            ? WatchUi.loadResource(Rez.Strings.PromptTitleUnsure)
            : WatchUi.loadResource(Rez.Strings.PromptTitle);
        Menu2.initialize({ :title => title });

        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.LevelCalm), null, :no, {}));
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.Level1), null, :s1, {}));
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.Level2), null, :s2, {}));
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.Level3), null, :s3, {}));

        if (Attention has :vibrate) {
            // Un patrón distinto del de confirmación de marca, para poder
            // distinguir "he registrado lo tuyo" de "te estoy preguntando"
            // sin mirar el reloj.
            Attention.vibrate([
                new Attention.VibeProfile(75, 250),
                new Attention.VibeProfile(0, 120),
                new Attention.VibeProfile(75, 250)
            ]);
        }
    }
}

class PromptMenuDelegate extends WatchUi.Menu2InputDelegate {

    private var mRec = null;
    private var mTimer = null;
    private var mDone = false;

    function initialize(recorder as Recorder) {
        Menu2InputDelegate.initialize();
        mRec = recorder;
        mTimer = new Timer.Timer();
        mTimer.start(method(:onTimeout), Config.PROMPT_TIMEOUT_S * 1000, false);
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        var id = item.getId();
        var mark = Config.MARK_PROMPT_NO;
        if (id == :s1) { mark = Config.MARK_PROMPT_YES_1; }
        if (id == :s2) { mark = Config.MARK_PROMPT_YES_2; }
        if (id == :s3) { mark = Config.MARK_PROMPT_YES_3; }
        finish(mark);
    }

    function onBack() as Void {
        finish(Config.MARK_PROMPT_SKIP);
    }

    function onTimeout() as Void {
        finish(Config.MARK_PROMPT_SKIP);
    }

    private function finish(mark as Lang.Number) as Void {
        if (mDone) { return; }
        mDone = true;
        mTimer.stop();
        // El reloj preguntó AHORA por lo que estaba viendo AHORA: el
        // episodio, si lo hay, es el de este momento.
        mRec.mark(mark, Config.ONSET_NOW);
        WatchUi.popView(WatchUi.SLIDE_DOWN);
    }
}
