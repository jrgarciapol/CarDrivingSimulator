//! Menús de marcado manual (vía B).
//!
//! Se pregunta el nivel y después CUÁNDO EMPEZÓ. Lo segundo parece un
//! detalle y es lo más importante de los dos.
//!
//! Cuando marcas un episodio no lo marcas cuando empieza: lo marcas
//! cuando te das cuenta, que puede ser tres minutos después, y para
//! entonces lo que registra la banda es la cola del episodio, no su
//! comienzo. Si etiquetamos la ventana equivocada, el modelo aprende a
//! reconocer el momento en el que levantas la muñeca para pulsar un
//! botón. Preguntando el inicio aproximado, el pipeline puede desplazar
//! la ventana de etiquetado hacia atrás y quedarse con el trozo bueno.

using Toybox.WatchUi;
using Toybox.Lang;

class MarkerMenu extends WatchUi.Menu2 {
    function initialize() {
        Menu2.initialize({ :title => WatchUi.loadResource(Rez.Strings.MenuTitle) });
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.Level3), null, :s3, {}));
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.Level2), null, :s2, {}));
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.Level1), null, :s1, {}));
        // "Estoy tranquilo" no es relleno: sin negativos declarados, todo
        // lo que no marcas se supone calma, incluidos los episodios que
        // se te pasaron. Eso mete ruido en la clase negativa y es de las
        // cosas que más estropean un modelo como este.
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.LevelCalm), null, :calm, {}));
    }
}

class MarkerMenuDelegate extends WatchUi.Menu2InputDelegate {

    private var mRec = null;

    function initialize(recorder as Recorder) {
        Menu2InputDelegate.initialize();
        mRec = recorder;
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        var id = item.getId();

        if (id == :calm) {
            mRec.mark(Config.MARK_CALM, Config.ONSET_NOW);
            WatchUi.popView(WatchUi.SLIDE_DOWN);
            return;
        }

        var level = Config.MARK_STRESS_1;
        if (id == :s2) { level = Config.MARK_STRESS_2; }
        if (id == :s3) { level = Config.MARK_STRESS_3; }

        WatchUi.switchToView(new OnsetMenu(),
                             new OnsetMenuDelegate(mRec, level),
                             WatchUi.SLIDE_LEFT);
    }

    function onBack() as Void {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
    }
}

class OnsetMenu extends WatchUi.Menu2 {
    function initialize() {
        Menu2.initialize({ :title => WatchUi.loadResource(Rez.Strings.OnsetTitle) });
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.OnsetNow),   null, :now,  {}));
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.Onset1min),  null, :m1,   {}));
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.Onset3min),  null, :m3,   {}));
        addItem(new WatchUi.MenuItem(WatchUi.loadResource(Rez.Strings.Onset10min), null, :m10,  {}));
    }
}

class OnsetMenuDelegate extends WatchUi.Menu2InputDelegate {

    private var mRec = null;
    private var mLevel = 0;

    function initialize(recorder as Recorder, level as Lang.Number) {
        Menu2InputDelegate.initialize();
        mRec = recorder;
        mLevel = level;
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        var id = item.getId();
        var onset = Config.ONSET_NOW;
        if (id == :m1)  { onset = Config.ONSET_1MIN;  }
        if (id == :m3)  { onset = Config.ONSET_3MIN;  }
        if (id == :m10) { onset = Config.ONSET_10MIN; }
        mRec.mark(mLevel, onset);
        WatchUi.popView(WatchUi.SLIDE_DOWN);
    }

    function onBack() as Void {
        // Salir sin elegir inicio no debe perder la marca: guardamos con
        // el valor por defecto antes que quedarnos sin el dato.
        mRec.mark(mLevel, Config.ONSET_1MIN);
        WatchUi.popView(WatchUi.SLIDE_DOWN);
    }
}
