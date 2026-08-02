"""Sonido sintetizado en tiempo real.

- Motor: tren de pulsos de encendido (4 cilindros / 4 tiempos) con varios
  armónicos, retumbo de medio orden, aspiración con el gas y crepitar en
  retención. El tono sigue a las RPM y el volumen al acelerador.
- Neumáticos: chirrido con dos formantes (~800 y ~1250 Hz) con vibrato y
  trémolo, más soplo de ruido en banda; el nivel sigue al deslizamiento.
- Viento: ruido grave que crece con el cuadrado de la velocidad.

Si numpy o el dispositivo de audio no están disponibles, el simulador
funciona igualmente sin sonido.
"""

import sdl2

from . import config as cfg

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def _smooth(x, k):
    """Media móvil simple (filtro paso-bajo barato)."""
    kernel = np.ones(k) / k
    return np.convolve(x, kernel, mode="same")


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
        if not cfg.AUDIO_ENABLED or np is None:
            return
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
               engine_on: bool = True, speed: float = 0.0):
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
            intake = _smooth(np.random.uniform(-1, 1, n), 6) \
                * (0.10 + 0.45 * throttle)             # aspiración
            body = 0.42 * saw + 0.24 * h2 + 0.12 * h3 + 0.28 * rumble + intake
            vol = cfg.AUDIO_VOLUME * (0.20 + 0.50 * throttle
                                      + 0.10 * self._rpm_lp / 7000.0)
            wave += body * vol
            # crepitar en retención (soltar gas con el motor alto)
            if throttle < 0.08 and self._rpm_lp > 3200.0:
                pops = np.random.uniform(0, 1, n)
                mask = (pops > 0.985).astype(float)
                wave += _smooth(mask * np.random.uniform(-1, 1, n), 3) \
                    * cfg.AUDIO_VOLUME * 0.9

        # --- chirrido de neumáticos ---------------------------------------
        self._screech_lp += (max(0.0, min(1.0, screech)) - self._screech_lp) * 0.22
        lvl = self._screech_lp
        if lvl > 0.01:
            pitch = 1.0 + 0.18 * lvl               # sube al deslizar más
            vib = self._ph_vib + t * (46.0 / rate)
            self._ph_vib = float(vib[-1] % 1.0)
            wob = 1.0 + 0.06 * np.sin(2 * np.pi * vib)
            ph1 = self._ph_sq1 + np.cumsum(np.full(n, 820.0 * pitch) * wob) / rate
            ph2 = self._ph_sq2 + np.cumsum(np.full(n, 1260.0 * pitch) * wob) / rate
            self._ph_sq1 = float(ph1[-1] % 1.0)
            self._ph_sq2 = float(ph2[-1] % 1.0)
            trem = self._ph_trem + t * (27.0 / rate)
            self._ph_trem = float(trem[-1] % 1.0)
            tremolo = 0.62 + 0.38 * np.sin(2 * np.pi * trem)
            tones = 0.6 * np.sin(2 * np.pi * ph1) + 0.4 * np.sin(2 * np.pi * ph2)
            raw = np.random.uniform(-1, 1, n)
            band = _smooth(raw, 4) - _smooth(raw, 18)   # ruido en banda media
            sv = cfg.SCREECH_VOLUME * lvl * cfg.AUDIO_VOLUME
            wave += (0.60 * tones + 1.6 * band) * tremolo * sv

        # --- viento -------------------------------------------------------
        wind_lvl = min(1.0, (speed / 52.0) ** 2)
        if wind_lvl > 0.02:
            wind = _smooth(np.random.uniform(-1, 1, n), 12)
            wave += wind * wind_lvl * cfg.AUDIO_VOLUME * 0.5

        samples = np.clip(wave * 32767.0, -32767, 32767).astype(np.int16)
        buf = samples.tobytes()
        sdl2.SDL_QueueAudio(self.device, buf, len(buf))

    def close(self):
        if self.ok:
            sdl2.SDL_CloseAudioDevice(self.device)
            self.device = 0
