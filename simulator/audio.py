"""Sonido de motor sintetizado en tiempo real.

Genera una onda de sierra con armónicos cuya frecuencia sigue a las RPM y
cuyo volumen sigue al acelerador. Si numpy o el dispositivo de audio no
están disponibles, el simulador funciona igualmente sin sonido.
"""

import sdl2

from . import config as cfg

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class EngineSound:
    def __init__(self):
        self.device = 0
        self._phase1 = 0.0
        self._phase2 = 0.0
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

    def update(self, rpm: float, throttle: float):
        """Encola audio si la cola se está quedando corta. Llamar cada frame."""
        if not self.ok:
            return
        queued = sdl2.SDL_GetQueuedAudioSize(self.device)
        # mantener ~90 ms en cola
        target_bytes = int(cfg.AUDIO_RATE * 0.09) * 2
        if queued >= target_bytes:
            return

        n = 1024
        rate = cfg.AUDIO_RATE
        # motor 4 cilindros 4T: 2 explosiones por vuelta
        f = max(25.0, rpm / 60.0 * 2.0)
        vol = cfg.AUDIO_VOLUME * (0.22 + 0.55 * throttle)

        t = np.arange(n)
        ph1 = self._phase1 + (t + 1) * (f / rate)
        ph2 = self._phase2 + (t + 1) * (f * 1.5 / rate)
        self._phase1 = float(ph1[-1] % 1.0)
        self._phase2 = float(ph2[-1] % 1.0)

        saw = 2.0 * (ph1 % 1.0) - 1.0
        saw2 = 2.0 * (ph2 % 1.0) - 1.0
        noise = np.random.uniform(-1.0, 1.0, n) * (0.05 + 0.10 * throttle)
        wave = (0.62 * saw + 0.28 * saw2 + noise) * vol
        samples = np.clip(wave * 32767.0, -32767, 32767).astype(np.int16)
        buf = samples.tobytes()
        sdl2.SDL_QueueAudio(self.device, buf, len(buf))

    def close(self):
        if self.ok:
            sdl2.SDL_CloseAudioDevice(self.device)
            self.device = 0
