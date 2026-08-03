"""Sonido sintetizado en tiempo real.

- Motor: tren de pulsos de encendido (4 cilindros / 4 tiempos) con varios
  armónicos, retumbo de medio orden, aspiración con el gas y crepitar en
  retención. El tono sigue a las RPM y el volumen al acelerador.
- Neumáticos: chirrido con dos formantes (~800 y ~1250 Hz) con vibrato y
  trémolo, más soplo de ruido en banda; el nivel sigue al deslizamiento.
- Viento: ruido grave que crece con el cuadrado de la velocidad.
- ADAS: pitido de aviso de subviraje/sobreviraje cuya frecuencia de
  repetición sube con la severidad (tonos distintos para cada uno).

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
        self._ph_sq1 = 0.0
        self._ph_sq2 = 0.0
        self._ph_vib = 0.0
        self._ph_trem = 0.0
        self._screech_lp = 0.0
        self._rpm_lp = 900.0
        self._adas_ph = 0.0      # fase del tono del pitido ADAS
        self._adas_rp = 0.0      # fase de repetición del pitido [0..1)
        self._adas_lvl = 0.0     # severidad suavizada del aviso
        self._adas_kind = 0      # 0 = subviraje, 1 = sobreviraje
        if not cfg.AUDIO_ENABLED or np is None:
            return
        # filtros continuos (uno por fuente de ruido)
        self._f_intake = _Cont(6)
        self._f_pop = _Cont(3)
        self._f_band_hi = _Cont(3)
        self._f_band_lo = _Cont(10)
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
               understeer: float = 0.0, oversteer: float = 0.0):
        """Encola audio si la cola se está quedando corta. Llamar cada frame."""
        if not self.ok:
            return
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
        if engine_on:
            f = max(25.0, self._rpm_lp / 60.0 * 2.0)   # orden de encendido
            ph = self._ph_fire + t * (f / rate)
            ph_h = self._ph_half + t * (f * 0.5 / rate)
            self._ph_fire = float(ph[-1] % 1.0)
            self._ph_half = float(ph_h[-1] % 1.0)

            saw = 2.0 * (ph % 1.0) - 1.0               # fundamental áspera
            h2 = np.sin(2.0 * np.pi * ph * 2.0)        # 2º armónico
            h3 = np.sin(2.0 * np.pi * ph * 3.0)        # 3º armónico
            rumble = np.sin(2.0 * np.pi * ph_h)        # retumbo de escape
            intake = self._f_intake(np.random.uniform(-1, 1, n)) \
                * (0.10 + 0.45 * throttle)             # aspiración
            body = 0.42 * saw + 0.24 * h2 + 0.12 * h3 + 0.28 * rumble + intake
            vol = cfg.AUDIO_VOLUME * (0.20 + 0.50 * throttle
                                      + 0.10 * self._rpm_lp / 7000.0)
            wave += body * vol
            # crepitar en retención (soltar gas con el motor alto)
            if throttle < 0.08 and self._rpm_lp > 3200.0:
                pops = np.random.uniform(0, 1, n)
                mask = (pops > 0.985).astype(float)
                wave += self._f_pop(mask * np.random.uniform(-1, 1, n)) \
                    * cfg.AUDIO_VOLUME * 0.9

        # --- chirrido de neumáticos ---------------------------------------
        self._screech_lp += (max(0.0, min(1.0, screech)) - self._screech_lp) * 0.22
        lvl = self._screech_lp
        if lvl > 0.01:
            # silbido agudo de fricción: dos formantes altos con vibrato
            # suave y siseo en banda alta; el tono sube al deslizar más
            pitch = 1.0 + 0.20 * lvl
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
            sv = cfg.SCREECH_VOLUME * lvl * cfg.AUDIO_VOLUME
            wave += (0.70 * tones + 1.1 * hiss) * tremolo * sv

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

        samples = np.clip(wave * 32767.0, -32767, 32767).astype(np.int16)
        buf = samples.tobytes()
        sdl2.SDL_QueueAudio(self.device, buf, len(buf))

    def close(self):
        if self.ok:
            sdl2.SDL_CloseAudioDevice(self.device)
            self.device = 0
