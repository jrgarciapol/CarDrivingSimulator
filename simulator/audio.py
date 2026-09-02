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
        self.k = 0
        self.ajustar(k)

    def ajustar(self, k):
        """Cambia la longitud del filtro en caliente.

        Hace falta para el laboratorio de sonido: los parámetros de grave
        y agudo SON la longitud de estos filtros, y deben poder tocarse
        mientras suena. Se conserva la cola que quepa, para que el cambio
        no meta un clic."""
        k = max(1, int(k))
        if k == self.k:
            return
        viejo = getattr(self, "tail", None)
        self.k = k
        self.kernel = np.ones(k) / k
        if k <= 1:
            self.tail = np.zeros(0)
            return
        # Al ALARGAR el filtro hacen falta muestras que no existen. Rellenar
        # con ceros daria un bajon audible (la media caeria de golpe), asi
        # que se prolonga hacia atras la muestra mas antigua que se tiene:
        # es lo mas parecido a "esto venia sonando asi".
        relleno = float(viejo[0]) if viejo is not None and len(viejo) else 0.0
        self.tail = np.full(k - 1, relleno)
        if viejo is not None and len(viejo):
            n = min(len(viejo), k - 1)
            self.tail[-n:] = viejo[-n:]

    def __call__(self, x):
        if self.k <= 1:
            return x
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
        self._ph_gear = 0.0      # fase del canto de la transmisión
        self._ph_turbo = 0.0     # fase del silbido del turbo
        self._turbo_lp = 0.0     # presión del turbo (sube con retraso)
        self._th_prev = 0.0      # gas del fotograma anterior (válvula)
        self._bov = 0.0          # soplido de la válvula de descarga
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
            # Orden de encendido: en un cuatro tiempos cada cilindro explota
            # una vez cada DOS vueltas, asi que hay cilindros/2 explosiones
            # por vuelta. De aqui sale la nota del motor.
            cil = max(1, int(getattr(cfg, "SND_CILINDROS", 4)))
            f = max(25.0, r / 60.0 * cil * 0.5)        # orden de encendido
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
            asp = cfg.SND_ASPEREZA
            cyc_var = (1.0 - asp) + asp * np.sin(2.0 * np.pi * rough)

            saw = 2.0 * (ph % 1.0) - 1.0               # fundamental áspera
            h2 = np.sin(2.0 * np.pi * ph * 2.0)        # 2º armónico
            h3 = np.sin(2.0 * np.pi * ph * 3.0)        # 3º armónico
            rumble = np.sin(2.0 * np.pi * ph_h)        # retumbo de medio orden

            # CUERPO de combustión: pulso sin^2 estrecho por cada encendido,
            # redondeado con un paso bajo -> golpe grave y cálido en vez de
            # una sierra pura. Se centra restando su ciclo de trabajo nominal
            # para que no meta continua (thump de DC).
            pw = max(0.02, cfg.SND_ANCHO_PULSO)
            z = (ph % 1.0) / pw
            comb = np.where(z < 1.0, np.sin(np.pi * np.clip(z, 0.0, 1.0)) ** 2,
                            0.0) - pw
            self._f_body.ajustar(cfg.SND_SUAVIZADO_CUERPO)
            body_pulse = self._f_body(comb)

            intake = self._f_intake(np.random.uniform(-1, 1, n)) \
                * (0.10 + cfg.SND_ADMISION * throttle)  # aspiración

            # el pulso de combustión da cuerpo, pero a bajas vueltas (fire_hz
            # ~30 Hz en 1a/2a) domina y suena a petardeo: se mantiene SUAVE y
            # se atenúa con el régimen bajo. El tono principal son los
            # armónicos, que es lo que suena "a motor".
            pulse_atten = min(1.0, r / 2600.0)
            body = ((cfg.SND_ARMONICO_1 + 0.10 * ld) * saw
                    + (cfg.SND_ARMONICO_2 + 0.10 * ld) * h2
                    + (cfg.SND_ARMONICO_3 + 0.07 * ld) * h3
                    + cfg.SND_RETUMBO * rumble
                    + (cfg.SND_CUERPO + cfg.SND_CUERPO_CARGA * ld)
                    * pulse_atten * body_pulse
                    + intake) * cyc_var
            vol = cfg.AUDIO_VOLUME * (0.20 + 0.45 * throttle + 0.10 * ld
                                      + 0.08 * min(1.0, r / 7000.0))
            wave += body * vol
            # crepitar en retención (soltar gas con el motor alto)
            if throttle < 0.08 and r > 3200.0 and cfg.SND_PETARDEO > 0.0:
                pops = np.random.uniform(0, 1, n)
                mask = (pops > 0.985).astype(float)
                wave += self._f_pop(mask * np.random.uniform(-1, 1, n)) \
                    * cfg.AUDIO_VOLUME * cfg.SND_PETARDEO
        else:
            self._load_lp *= 0.97

        # --- neumáticos: chirrido lateral (scrub) -------------------------
        self._scrub_lp += (max(0.0, min(1.0, scrub)) - self._scrub_lp) * 0.22
        sc = self._scrub_lp
        if sc > 0.01:
            # silbido agudo de fricción: dos formantes altos con vibrato
            # suave y siseo en banda alta; el tono sube al deslizar más
            pitch = 1.0 + 0.20 * sc
            vib = self._ph_vib + t * (cfg.SND_SCRUB_VIBRATO_HZ / rate)
            self._ph_vib = float(vib[-1] % 1.0)
            wob = 1.0 + 0.035 * np.sin(2 * np.pi * vib)
            f1 = cfg.SND_SCRUB_F1 * pitch
            f2 = cfg.SND_SCRUB_F2 * pitch
            ph1 = self._ph_sq1 + np.cumsum(np.full(n, f1) * wob) / rate
            ph2 = self._ph_sq2 + np.cumsum(np.full(n, f2) * wob) / rate
            self._ph_sq1 = float(ph1[-1] % 1.0)
            self._ph_sq2 = float(ph2[-1] % 1.0)
            trem = self._ph_trem + t * (cfg.SND_SCRUB_TREMOLO_HZ / rate)
            self._ph_trem = float(trem[-1] % 1.0)
            tremolo = 0.78 + 0.22 * np.sin(2 * np.pi * trem)
            tones = 0.62 * np.sin(2 * np.pi * ph1) + 0.38 * np.sin(2 * np.pi * ph2)
            raw = np.random.uniform(-1, 1, n)
            hiss = self._f_band_hi(raw) - self._f_band_lo(raw)  # siseo agudo
            sv = cfg.SCREECH_VOLUME * sc * cfg.AUDIO_VOLUME
            wave += (0.70 * tones + cfg.SND_SCRUB_SISEO * hiss) * tremolo * sv

        # --- neumáticos: patinaje de tracción (wheelspin) -----------------
        self._spin_lp += (max(0.0, min(1.0, spin)) - self._spin_lp) * 0.30
        sp = self._spin_lp
        if sp > 0.05:
            # patinaje de tracción: la goma RASGA el asfalto. No tiene "nota"
            # (los intentos con un oscilador tonal sonaban a petardeo), así
            # que es puro RUIDO de banda media-baja con un rasgado (flutter)
            # que se acelera con el patinaje. Distinto del silbido agudo del
            # scrub lateral y del "shhh" grave del bloqueo.
            self._f_spin.ajustar(cfg.SND_SPIN_SUAVIZADO)
            rip = self._f_spin(np.random.uniform(-1, 1, n))
            flut = self._ph_flut + t * ((cfg.SND_SPIN_RASGADO_HZ
                                         + 50.0 * sp) / rate)
            self._ph_flut = float(flut[-1] % 1.0)
            flutter = 0.6 + 0.4 * np.sin(2 * np.pi * flut)
            gv = cfg.SCREECH_VOLUME * sp * cfg.AUDIO_VOLUME
            wave += rip * flutter * gv * 0.95

        # --- neumáticos: bloqueo en frenada (skid) ------------------------
        self._lock_lp += (max(0.0, min(1.0, lock)) - self._lock_lp) * 0.28
        lk = self._lock_lp
        if lk > 0.01:
            # derrape de banda ancha, grave y ESTABLE (la rueda casi parada
            # arrastra la goma): un "shhhh" continuo sin el tono del chirrido.
            self._f_lock.ajustar(cfg.SND_LOCK_SUAVIZADO)
            skid = self._f_lock(np.random.uniform(-1, 1, n))
            gv = cfg.SCREECH_VOLUME * lk * cfg.AUDIO_VOLUME
            wave += skid * cfg.SND_LOCK_NIVEL * gv

        # --- viento -------------------------------------------------------
        wind_lvl = min(1.0, (speed / max(1.0, cfg.SND_VIENTO_REF)) ** 2)
        if wind_lvl > 0.02 and cfg.SND_VIENTO > 0.0:
            self._f_wind.ajustar(cfg.SND_VIENTO_SUAVIZADO)
            wind = self._f_wind(np.random.uniform(-1, 1, n))
            wave += wind * wind_lvl * cfg.AUDIO_VOLUME * cfg.SND_VIENTO

        # --- transmisión: canto de los engranajes -------------------------
        # Un tono proporcional a la VELOCIDAD, no al régimen: por eso se oye
        # igual en cada marcha y delata que viene de la transmisión y no del
        # motor. Apagado de fábrica: no todos los coches cantan.
        if cfg.SND_TRANSMISION > 0.0 and speed > 1.0:
            fg = cfg.SND_TRANSMISION_HZ * speed / 10.0
            phg = self._ph_gear + t * (min(fg, rate * 0.45) / rate)
            self._ph_gear = float(phg[-1] % 1.0)
            # dos armónicos: el tono puro suena a pitido de laboratorio
            canto = (0.70 * np.sin(2 * np.pi * phg)
                     + 0.30 * np.sin(4 * np.pi * phg))
            nivel = cfg.SND_TRANSMISION * min(1.0, speed / 18.0)
            wave += canto * nivel * cfg.AUDIO_VOLUME * 0.35

        # --- turbo: silbido y válvula de descarga -------------------------
        # El silbido sube con la carga y el régimen (el compresor gira más);
        # la válvula suelta el "pshhh" cuando se levanta el pie DE GOLPE, que
        # es justo cuando el aire comprimido no tiene por donde salir.
        soplo = max(0.0, self._th_prev - throttle)
        self._th_prev = throttle
        if cfg.SND_TURBO > 0.0 and engine_on:
            carga = throttle * min(1.0, self._rpm_lp / 4200.0)
            self._turbo_lp += (carga - self._turbo_lp) * 0.06   # el turbo
            tb = self._turbo_lp                                  # va con retraso
            if tb > 0.02:
                ft = cfg.SND_TURBO_HZ * (0.55 + 0.45 * tb)
                pht = self._ph_turbo + t * (min(ft, rate * 0.45) / rate)
                self._ph_turbo = float(pht[-1] % 1.0)
                silb = np.sin(2 * np.pi * pht) \
                    + 0.5 * self._f_pop(np.random.uniform(-1, 1, n))
                wave += silb * tb * tb * cfg.SND_TURBO \
                    * cfg.AUDIO_VOLUME * 0.30
        if cfg.SND_VALVULA > 0.0 and soplo > 0.25:
            self._bov = min(1.0, self._bov + soplo * self._turbo_lp * 2.0)
        if self._bov > 0.01:
            psh = self._f_intake(np.random.uniform(-1, 1, n))
            wave += psh * self._bov * cfg.SND_VALVULA * cfg.AUDIO_VOLUME * 1.1
            self._bov *= 0.80

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
