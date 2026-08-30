"""Sonido sintetizado en tiempo real, acoplado a la física.

- Motor: tren de pulsos de encendido (4 cilindros / 4 tiempos) con varios
  armónicos cuya amplitud sigue a la CARGA (no suena igual en vacío que a
  plena carga), un cuerpo de combustión redondeado que da el retumbo grave,
  variación de ciclo a ciclo (un motor real no repite ciclos idénticos),
  aspiración con el gas y crepitar en retención.
- Neumáticos: TRES sonidos físicos distintos, cada uno con su nivel propio
  tomado del deslizamiento real de cada rueda:
    * scrub  = chirrido lateral (deriva en curva): dos formantes agudos.
    * spin   = patinaje de tracción (rueda motriz girando de más): zumbido
               rugoso y grave con banda ancha; suena en la salida de curva.
    * lock   = bloqueo en frenada (rueda casi parada deslizando): derrape
               de banda ancha, más grave y estable.
  Así el wheelspin de una salida de curva NO suena igual que el arrastre de
  una curva rápida ni que un bloqueo de frenada.
- Viento: ruido grave que crece con el cuadrado de la velocidad.
- ADAS: pitido de aviso de subviraje/sobreviraje cuya frecuencia de
  repetición sube con la severidad (tonos distintos para cada uno).

Todos los filtros son VECTORIZADOS (media móvil continua entre bloques): sin
bucles muestra a muestra, para que sea barato también en la Steam Deck.

Si numpy o el dispositivo de audio no están disponibles, el simulador
funciona igualmente sin sonido.
"""

import sdl2

from . import config as cfg

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class _Cont:
    """Filtro de media móvil CONTINUO entre bloques: guarda la cola del
    bloque anterior para que no haya discontinuidades en las junturas
    (sin esto, cada bloque metía un clic audible ~21 veces por segundo,
    que sonaba como un golpeteo)."""

    def __init__(self, k):
        self.k = k
        self.kernel = np.ones(k) / k
        self.tail = np.zeros(k - 1)

    def __call__(self, x):
        y = np.convolve(np.concatenate([self.tail, x]), self.kernel, "valid")
        self.tail = x[-(self.k - 1):].copy()
        return y


class EngineSound:
    def __init__(self):
        self.device = 0
        self._ph_fire = 0.0      # fase del orden de encendido
        self._ph_half = 0.0      # fase del medio orden (retumbo)
        self._ph_rough = 0.0     # fase de la variación de ciclo
        self._ph_sq1 = 0.0
        self._ph_sq2 = 0.0
        self._ph_vib = 0.0
        self._ph_trem = 0.0
        self._ph_spin = 0.0      # fase del zumbido de wheelspin
        self._ph_flut = 0.0      # fase del flutter del wheelspin
        self._rpm_lp = 900.0
        self._load_lp = 0.0      # carga del motor suavizada
        self._scrub_lp = 0.0     # nivel de chirrido lateral
        self._spin_lp = 0.0      # nivel de patinaje de tracción
        self._lock_lp = 0.0      # nivel de bloqueo en frenada
        self._adas_ph = 0.0      # fase del tono del pitido ADAS
        self._adas_rp = 0.0      # fase de repetición del pitido [0..1)
        self._adas_lvl = 0.0     # severidad suavizada del aviso
        self._adas_kind = 0      # 0 = subviraje, 1 = sobreviraje
        if not cfg.AUDIO_ENABLED or np is None:
            return
        # filtros continuos (uno por fuente de ruido)
        self._f_intake = _Cont(6)
        self._f_body = _Cont(6)      # redondea el pulso de combustión (grave)
        self._f_pop = _Cont(3)
        self._f_band_hi = _Cont(3)   # scrub: siseo agudo
        self._f_band_lo = _Cont(10)
        self._f_spin = _Cont(8)      # wheelspin: banda media rugosa
        self._f_lock = _Cont(22)     # bloqueo: banda grave (derrape oscuro)
        self._f_wind = _Cont(12)
        spec = sdl2.SDL_AudioSpec(cfg.AUDIO_RATE, sdl2.AUDIO_S16, 1, 1024)
        obtained = sdl2.SDL_AudioSpec(0, 0, 0, 0)
        dev = sdl2.SDL_OpenAudioDevice(None, 0, spec, obtained, 0)
        if dev > 0:
            self.device = dev
            sdl2.SDL_PauseAudioDevice(dev, 0)

    @property
    def ok(self):
        return self.device > 0

    def update(self, rpm: float, throttle: float, screech: float = 0.0,
               engine_on: bool = True, speed: float = 0.0,
               understeer: float = 0.0, oversteer: float = 0.0, *,
               gear: int = 0, scrub: float = None, spin: float = 0.0,
               lock: float = 0.0, brake: float = 0.0):
        """Encola audio si la cola se está quedando corta. Llamar cada frame.

        Parámetros nuevos (opcionales, keyword) para acoplar el sonido de los
        neumáticos a la física por rueda: `scrub` (deriva lateral), `spin`
        (patinaje de tracción) y `lock` (bloqueo en frenada), todos 0..1. Si
        no se pasan, se usa `screech` como chirrido lateral (compatibilidad
        con la llamada antigua)."""
        if not self.ok:
            return
        if scrub is None:                 # compat: sin desglose -> todo scrub
            scrub = screech
        queued = sdl2.SDL_GetQueuedAudioSize(self.device)
        target_bytes = int(cfg.AUDIO_RATE * 0.09) * 2
        if queued >= target_bytes:
            return

        n = 1024
        rate = cfg.AUDIO_RATE
        t = np.arange(1, n + 1)
        wave = np.zeros(n)

        # --- motor -------------------------------------------------------
        # ligera inercia del tono para que no "salte" entre frames
        self._rpm_lp += (rpm - self._rpm_lp) * 0.35
        if engine_on and self._rpm_lp > 50.0:
            r = self._rpm_lp
            f = max(25.0, r / 60.0 * 2.0)              # orden de encendido
            ph = self._ph_fire + t * (f / rate)
            ph_h = self._ph_half + t * (f * 0.5 / rate)
            self._ph_fire = float(ph[-1] % 1.0)
            self._ph_half = float(ph_h[-1] % 1.0)

            # CARGA aproximada (el par no llega aquí directamente): gas más
            # régimen. Modula la mezcla de armónicos: un motor sin carga suena
            # más "limpio" que a fondo.
            load = throttle * (0.35 + 0.65 * min(1.0, r / 5000.0))
            self._load_lp += (load - self._load_lp) * 0.10
            ld = self._load_lp

            # variación ciclo a ciclo: un motor real no repite ciclos idénticos
            rough = self._ph_rough + t * (5.7 / rate)
            self._ph_rough = float(rough[-1] % 1.0)
            cyc_var = 0.94 + 0.06 * np.sin(2.0 * np.pi * rough)

            saw = 2.0 * (ph % 1.0) - 1.0               # fundamental áspera
            h2 = np.sin(2.0 * np.pi * ph * 2.0)        # 2º armónico
            h3 = np.sin(2.0 * np.pi * ph * 3.0)        # 3º armónico
            rumble = np.sin(2.0 * np.pi * ph_h)        # retumbo de medio orden

            # CUERPO de combustión: pulso sin^2 estrecho por cada encendido,
            # redondeado con un paso bajo -> golpe grave y cálido en vez de
            # una sierra pura. Se centra restando su ciclo de trabajo nominal
            # para que no meta continua (thump de DC).
            pw = 0.16
            z = (ph % 1.0) / pw
            comb = np.where(z < 1.0, np.sin(np.pi * np.clip(z, 0.0, 1.0)) ** 2,
                            0.0) - pw
            body_pulse = self._f_body(comb)

            intake = self._f_intake(np.random.uniform(-1, 1, n)) \
                * (0.10 + 0.45 * throttle)             # aspiración

            # el pulso de combustión da cuerpo, pero a bajas vueltas (fire_hz
            # ~30 Hz en 1a/2a) domina y suena a petardeo: se mantiene SUAVE y
            # se atenúa con el régimen bajo. El tono principal son los
            # armónicos, que es lo que suena "a motor".
            pulse_atten = min(1.0, r / 2600.0)
            body = ((0.36 + 0.10 * ld) * saw
                    + (0.20 + 0.10 * ld) * h2
                    + (0.10 + 0.07 * ld) * h3
                    + 0.26 * rumble
                    + (0.14 + 0.28 * ld) * pulse_atten * body_pulse
                    + intake) * cyc_var
            vol = cfg.AUDIO_VOLUME * (0.20 + 0.45 * throttle + 0.10 * ld
                                      + 0.08 * min(1.0, r / 7000.0))
            wave += body * vol
            # crepitar en retención (soltar gas con el motor alto)
            if throttle < 0.08 and r > 3200.0:
                pops = np.random.uniform(0, 1, n)
                mask = (pops > 0.985).astype(float)
                wave += self._f_pop(mask * np.random.uniform(-1, 1, n)) \
                    * cfg.AUDIO_VOLUME * 0.9
        else:
            self._load_lp *= 0.97

        # --- neumáticos: chirrido lateral (scrub) -------------------------
        self._scrub_lp += (max(0.0, min(1.0, scrub)) - self._scrub_lp) * 0.22
        sc = self._scrub_lp
        if sc > 0.01:
            # silbido agudo de fricción: dos formantes altos con vibrato
            # suave y siseo en banda alta; el tono sube al deslizar más
            pitch = 1.0 + 0.20 * sc
            vib = self._ph_vib + t * (38.0 / rate)
            self._ph_vib = float(vib[-1] % 1.0)
            wob = 1.0 + 0.035 * np.sin(2 * np.pi * vib)
            ph1 = self._ph_sq1 + np.cumsum(np.full(n, 1150.0 * pitch) * wob) / rate
            ph2 = self._ph_sq2 + np.cumsum(np.full(n, 1730.0 * pitch) * wob) / rate
            self._ph_sq1 = float(ph1[-1] % 1.0)
            self._ph_sq2 = float(ph2[-1] % 1.0)
            trem = self._ph_trem + t * (30.0 / rate)
            self._ph_trem = float(trem[-1] % 1.0)
            tremolo = 0.78 + 0.22 * np.sin(2 * np.pi * trem)
            tones = 0.62 * np.sin(2 * np.pi * ph1) + 0.38 * np.sin(2 * np.pi * ph2)
            raw = np.random.uniform(-1, 1, n)
            hiss = self._f_band_hi(raw) - self._f_band_lo(raw)  # siseo agudo
            sv = cfg.SCREECH_VOLUME * sc * cfg.AUDIO_VOLUME
            wave += (0.70 * tones + 1.1 * hiss) * tremolo * sv

        # --- neumáticos: patinaje de tracción (wheelspin) -----------------
        self._spin_lp += (max(0.0, min(1.0, spin)) - self._spin_lp) * 0.30
        sp = self._spin_lp
        if sp > 0.04:
            # patinaje de tracción: un "growl" grave con la goma rasgando el
            # asfalto. Antes era una SIERRA cruda (2*ph-1) que zumbaba muy
            # áspera al arrancar a fondo; ahora es un tono redondo (fundamental
            # + un poco de 2º armónico) apoyado sobre todo en el ruido de la
            # goma, con un flutter suave. El tono sube con el patinaje.
            fb = 90.0 + 150.0 * sp
            phb = self._ph_spin + np.cumsum(np.full(n, fb)) / rate
            self._ph_spin = float(phb[-1] % 1.0)
            phw = phb % 1.0
            buzz = np.sin(2 * np.pi * phw) + 0.3 * np.sin(4 * np.pi * phw)
            band = self._f_spin(np.random.uniform(-1, 1, n))
            flut = self._ph_flut + t * (48.0 / rate)
            self._ph_flut = float(flut[-1] % 1.0)
            flutter = 0.65 + 0.35 * np.sin(2 * np.pi * flut)
            gv = cfg.SCREECH_VOLUME * sp * cfg.AUDIO_VOLUME
            # menos zumbido y más ruido de goma: rasga, no petardea
            wave += (0.35 * buzz + 0.7 * band) * flutter * gv * 0.85

        # --- neumáticos: bloqueo en frenada (skid) ------------------------
        self._lock_lp += (max(0.0, min(1.0, lock)) - self._lock_lp) * 0.28
        lk = self._lock_lp
        if lk > 0.01:
            # derrape de banda ancha, grave y ESTABLE (la rueda casi parada
            # arrastra la goma): un "shhhh" continuo sin el tono del chirrido.
            skid = self._f_lock(np.random.uniform(-1, 1, n))
            gv = cfg.SCREECH_VOLUME * lk * cfg.AUDIO_VOLUME
            wave += skid * 1.4 * gv

        # --- viento -------------------------------------------------------
        wind_lvl = min(1.0, (speed / 52.0) ** 2)
        if wind_lvl > 0.02:
            wind = self._f_wind(np.random.uniform(-1, 1, n))
            wave += wind * wind_lvl * cfg.AUDIO_VOLUME * 0.5

        # --- ADAS: aviso de subviraje / sobreviraje -----------------------
        # pitido cuya FRECUENCIA DE REPETICIÓN sube con la severidad; el
        # sobreviraje (más urgente) tiene prioridad y un tono más agudo.
        if getattr(cfg, "ADAS_ENABLED", False):
            if oversteer >= understeer:
                sev, kind, tone_f = oversteer, 1, cfg.ADAS_OVERSTEER_TONE
            else:
                sev, kind, tone_f = understeer, 0, cfg.ADAS_UNDERSTEER_TONE
            if kind != self._adas_kind:
                self._adas_kind = kind
            self._adas_lvl += (sev - self._adas_lvl) * 0.30
            if self._adas_lvl > 0.03:
                rep = cfg.ADAS_MIN_HZ + (cfg.ADAS_MAX_HZ - cfg.ADAS_MIN_HZ) \
                    * min(1.0, self._adas_lvl)
                duty = 0.55
                # fase de repetición continua: aunque cambie el ritmo con
                # la severidad, la fase avanza suave y no hay clics
                rp = self._adas_rp + np.cumsum(np.full(n, rep / rate))
                cyc = rp % 1.0
                # envolvente de medio seno: arranca y acaba en cero -> sin
                # discontinuidades en los bordes del pitido
                env = np.where(cyc < duty,
                               np.sin(np.pi * np.clip(cyc / duty, 0, 1)), 0.0)
                ph = self._adas_ph + np.arange(1, n + 1) * (tone_f / rate)
                if kind == 1:   # sobreviraje: segundo armónico -> más brillante
                    tone = 0.7 * np.sin(2 * np.pi * ph) \
                        + 0.3 * np.sin(2 * np.pi * ph * 1.5)
                else:           # subviraje: tono simple, más grave
                    tone = np.sin(2 * np.pi * ph)
                self._adas_ph = float(ph[-1] % 1.0)
                self._adas_rp = float(rp[-1] % 1.0)
                gain = cfg.ADAS_VOLUME * cfg.AUDIO_VOLUME \
                    * (0.45 + 0.55 * self._adas_lvl)
                wave += tone * env * gain
            else:
                self._adas_rp = 0.0

        # limitador suave: la saturación dura del int16 mete distorsión
        # desagradable; tanh comprime los picos sin recortar bruscamente
        wave = np.tanh(wave * 1.1) / 1.1
        samples = np.clip(wave * 32767.0, -32767, 32767).astype(np.int16)
        buf = samples.tobytes()
        sdl2.SDL_QueueAudio(self.device, buf, len(buf))

    def pause(self):
        """Silencia el motor (menús) sin cerrar el dispositivo."""
        if self.ok:
            sdl2.SDL_ClearQueuedAudio(self.device)
            sdl2.SDL_PauseAudioDevice(self.device, 1)

    def resume(self):
        if self.ok:
            sdl2.SDL_PauseAudioDevice(self.device, 0)

    def close(self):
        if self.ok:
            sdl2.SDL_CloseAudioDevice(self.device)
            self.device = 0
