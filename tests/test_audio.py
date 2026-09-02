"""Pruebas del sintetizador de sonido y del laboratorio que lo afina.

El sonido no es una grabacion: se calcula muestra a muestra desde el regimen,
la carga y el deslizamiento. Y desde el laboratorio el usuario puede llevar
cualquier parametro a su extremo. Lo que se comprueba aqui es que eso NO
puede producir un ruido roto: nada de NaN, nada de saturacion dura (que suena
a chasquido), y ningun parametro capaz de reventar el generador.

Se captura el audio interceptando SDL_QueueAudio, asi que se examina
exactamente lo que se le mandaria a la tarjeta.

    python tests/test_audio.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np                                   # noqa: E402
import sdl2                                          # noqa: E402

from simulator import audio                          # noqa: E402
from simulator import audio_lab                      # noqa: E402
from simulator import config as cfg                  # noqa: E402


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


class _Captura:
    """Se pone en lugar de SDL_QueueAudio y guarda lo que se le manda."""

    def __init__(self):
        self.bloques = []

    def __call__(self, dev, buf, largo):
        self.bloques.append(np.frombuffer(buf[:largo], dtype=np.int16))
        return 0

    @property
    def muestras(self):
        return np.concatenate(self.bloques) if self.bloques else np.array([])


def _generar(motor, cap, **kw):
    """Fuerza a generar un bloque: la cola de audio siempre 'vacia'."""
    cap.bloques.clear()
    motor.update(**kw)
    return cap.muestras


def main():
    r = []
    sdl2.SDL_Init(sdl2.SDL_INIT_AUDIO)

    cap = _Captura()
    audio.sdl2.SDL_QueueAudio = cap
    audio.sdl2.SDL_GetQueuedAudioSize = lambda dev: 0

    motor = audio.EngineSound()
    if not motor.ok:
        print("[AVISO] sin dispositivo de audio: no se puede probar")
        return 0

    # --- genera sonido y no se sale del rango -------------------------
    s = _generar(motor, cap, rpm=3500, throttle=0.6, engine_on=True,
                 speed=30.0)
    r.append(check("el motor genera un bloque de 1024 muestras",
                   len(s) == 1024, f"son {len(s)}"))
    r.append(check("con el motor parado hay silencio, no ruido",
                   np.abs(_generar(motor, cap, rpm=0, throttle=0.0,
                                   engine_on=False, speed=0.0)).max() == 0))

    # --- cada fuente suena por separado --------------------------------
    quieto = dict(rpm=0, throttle=0.0, engine_on=False, speed=0.0)
    for nombre, kw in (("chirrido lateral", dict(scrub=0.8)),
                       ("patinaje de traccion", dict(spin=0.8)),
                       ("bloqueo de frenada", dict(lock=0.8)),
                       ("viento", dict(speed=45.0))):
        d = dict(quieto)
        d.update(kw)
        # dos pasadas: los niveles van suavizados y el primero arranca de cero
        _generar(motor, cap, **d)
        pico = np.abs(_generar(motor, cap, **d)).max()
        r.append(check(f"{nombre} suena solo", pico > 200, f"pico {pico}"))

    # --- los sonidos nuevos, apagados de fabrica -----------------------
    r.append(check("transmision, turbo y valvula vienen apagados",
                   cfg.SND_TRANSMISION == 0.0 and cfg.SND_TURBO == 0.0
                   and cfg.SND_VALVULA == 0.0))
    guardado = (cfg.SND_TRANSMISION, cfg.SND_TURBO, cfg.SND_VALVULA)
    cfg.SND_TRANSMISION = 0.8
    _generar(motor, cap, **dict(quieto, speed=30.0))
    pico = np.abs(_generar(motor, cap, **dict(quieto, speed=30.0))).max()
    r.append(check("la transmision canta al subirla", pico > 200,
                   f"pico {pico}"))
    cfg.SND_TRANSMISION = 0.0
    cfg.SND_TURBO, cfg.SND_VALVULA = 0.9, 0.9
    for th in (1.0, 1.0, 1.0, 0.0):        # acelerar y levantar de golpe
        s = _generar(motor, cap, rpm=6000, throttle=th, engine_on=True,
                     speed=40.0)
    r.append(check("la valvula sopla al levantar el pie",
                   np.abs(s).max() > 200, f"pico {np.abs(s).max()}"))
    cfg.SND_TRANSMISION, cfg.SND_TURBO, cfg.SND_VALVULA = guardado

    # --- NINGUN ajuste puede romper el sonido --------------------------
    # El laboratorio deja llevar cada parametro a su extremo (y mas alla:
    # el rango es una guia). Ninguno debe producir NaN ni saturar a tope,
    # que es lo que se oye como chasquido.
    editables = [e for _s, ents in audio_lab._parametros() for e in ents]
    r.append(check("el laboratorio encuentra los parametros de sonido",
                   len(editables) > 25, f"{len(editables)}"))
    sin_rango = [e["name"] for e in editables
                 if not e["is_bool"] and not e.get("is_enum")
                 and e["lo"] is None]
    r.append(check("todos llevan documentado su rango normal",
                   not sin_rango, ", ".join(sin_rango)))

    roto = []
    saturados = []
    originales = {e["name"]: getattr(cfg, e["name"]) for e in editables}
    for e in editables:
        if e["is_bool"] or e.get("is_enum"):
            continue
        for v in (e["lo"], e["hi"]):
            setattr(cfg, e["name"], int(v) if e["is_int"] else float(v))
            try:
                _generar(motor, cap, rpm=5000, throttle=0.9, engine_on=True,
                         speed=50.0, scrub=0.7, spin=0.7, lock=0.7,
                         understeer=0.9, oversteer=0.3)
                s = _generar(motor, cap, rpm=5000, throttle=0.9,
                             engine_on=True, speed=50.0, scrub=0.7, spin=0.7,
                             lock=0.7, understeer=0.9, oversteer=0.3)
            except Exception as exc:                # noqa: BLE001
                roto.append(f"{e['name']}={v} ({exc})")
                continue
            if len(s) and np.abs(s).max() >= 32767:
                saturados.append(f"{e['name']}={v}")
        setattr(cfg, e["name"], originales[e["name"]])
    r.append(check("ningun valor extremo revienta el generador",
                   not roto, "; ".join(roto[:3])))
    r.append(check("ningun valor extremo satura la salida",
                   not saturados, "; ".join(saturados[:3])))

    # --- el filtro se puede cambiar en caliente sin clic ---------------
    f = audio._Cont(8)
    x = np.ones(64)
    f(x)
    f.ajustar(20)
    y = f(x)
    r.append(check("cambiar la longitud del filtro no da un salto",
                   abs(float(y[0]) - 1.0) < 0.5, f"{float(y[0]):.3f}"))
    f.ajustar(1)
    r.append(check("un filtro de longitud 1 deja pasar la senal tal cual",
                   np.allclose(f(x), x)))

    # --- el banco de pruebas del laboratorio ---------------------------
    b = audio_lab._Banco()
    ralenti = b.rpm
    for _ in range(60):
        b.paso(1.0, 1.0 / 60.0)
    subido = b.rpm
    for _ in range(300):                    # cinco segundos soltando
        b.paso(0.0, 1.0 / 60.0)
    r.append(check("con gas el motor de pruebas sube de vueltas",
                   subido > ralenti + 1000, f"{ralenti:.0f} -> {subido:.0f}"))
    r.append(check("al soltar vuelve al ralenti",
                   abs(b.rpm - ralenti) < 60, f"{b.rpm:.0f}"))
    b.viento = True
    for _ in range(240):
        b.paso(0.0, 1.0 / 60.0)
    r.append(check("el interruptor de viento da velocidad al banco",
                   b.velocidad > 50.0, f"{b.velocidad:.0f} m/s"))

    llamadas = []
    b.scrub, b.spin, b.lock = True, False, True

    class _Falso:
        def update(self, rpm, gas, **kw):
            llamadas.append(kw)

    b.sonar(_Falso())
    r.append(check("los interruptores llegan al sintetizador",
                   llamadas and llamadas[0]["scrub"] > 0
                   and llamadas[0]["spin"] == 0
                   and llamadas[0]["lock"] > 0, str(llamadas[:1])))

    motor.close()
    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
