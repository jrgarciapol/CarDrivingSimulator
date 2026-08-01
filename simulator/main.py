"""Punto de entrada del simulador.

Uso:  python -m simulator.main [--frames N]

Controles con volante Thrustmaster (configurables en simulator/config.py):
  volante        direccion
  pedales        acelerador / freno
  levas          subir / bajar marcha
Teclado (siempre activo):
  flechas        conducir (si no hay volante)
  A / Z          subir / bajar marcha
  R              recolocar el coche
  F1             diagnostico de ejes y botones
  F2             telemetria: circulo de friccion por rueda
  L              mostrar/ocultar la trazada ideal
  G              alternar cambio automatico/manual
  C              alternar vista cercana / coche completo
  E              arrancar / parar el motor
  ESC            salir
"""

import argparse
import ctypes
import math
import sys

import sdl2

from . import config as cfg
from .audio import EngineSound
from .physics import Car
from .render import Hud, Renderer
from .track import Track
from .wheel import ForceFeedback, WheelInput


def main(argv=None):
    parser = argparse.ArgumentParser(description="Car Driving Simulator")
    parser.add_argument("--frames", type=int, default=0,
                        help="salir tras N frames (pruebas automatizadas)")
    args = parser.parse_args(argv)

    if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_JOYSTICK |
                     sdl2.SDL_INIT_HAPTIC | sdl2.SDL_INIT_AUDIO |
                     sdl2.SDL_INIT_EVENTS) != 0:
        print("Error al iniciar SDL:", sdl2.SDL_GetError().decode())
        return 1

    window = sdl2.SDL_CreateWindow(
        cfg.WINDOW_TITLE,
        sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED,
        cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT, sdl2.SDL_WINDOW_SHOWN)
    if not window:
        print("Error al crear la ventana:", sdl2.SDL_GetError().decode())
        return 1
    renderer = sdl2.SDL_CreateRenderer(
        window, -1, sdl2.SDL_RENDERER_ACCELERATED | sdl2.SDL_RENDERER_PRESENTVSYNC)
    if not renderer:
        renderer = sdl2.SDL_CreateRenderer(window, -1, 0)
    sdl2.SDL_SetRenderDrawBlendMode(renderer, sdl2.SDL_BLENDMODE_BLEND)

    wheel = WheelInput()
    ffb = ForceFeedback(wheel)
    sound = EngineSound()
    track = Track()
    car = Car()
    scene = Renderer(renderer)
    hud = Hud(renderer)

    if wheel.connected:
        print(f"Volante detectado: {wheel.name} "
              f"({wheel.num_axes} ejes, {wheel.num_buttons} botones)")
        print("Force feedback:", "activo" if ffb.ok else "no disponible")
    else:
        print("No se ha detectado ningun volante: usando teclado (flechas).")

    perf_freq = sdl2.SDL_GetPerformanceFrequency()
    last = sdl2.SDL_GetPerformanceCounter()
    physics_dt = 1.0 / cfg.PHYSICS_HZ
    accumulator = 0.0

    lap_time = 0.0
    best_lap = None
    lap_count = 1
    show_debug = False
    show_telemetry = False
    show_line = cfg.RACING_LINE
    auto_gear = cfg.AUTO_GEAR
    chase_view = cfg.CHASE_VIEW
    surface = "road"
    frame = 0
    event = sdl2.SDL_Event()
    running = True

    while running:
        # ------------------------------------------------ eventos
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            if event.type == sdl2.SDL_QUIT:
                running = False
            elif event.type == sdl2.SDL_KEYDOWN and not event.key.repeat:
                sym = event.key.keysym.sym
                if sym == sdl2.SDLK_ESCAPE:
                    running = False
                elif sym == sdl2.SDLK_F1:
                    show_debug = not show_debug
                elif sym == sdl2.SDLK_F2:
                    show_telemetry = not show_telemetry
                elif sym == sdl2.SDLK_l:
                    show_line = not show_line
                elif sym == sdl2.SDLK_g:
                    auto_gear = not auto_gear
                elif sym == sdl2.SDLK_c:
                    chase_view = not chase_view
                elif sym == sdl2.SDLK_e:
                    car.toggle_engine()
                elif sym == sdl2.SDLK_r:
                    car.reset(car.state.s)
                elif sym == sdl2.SDLK_a:
                    if car.shift_up():
                        ffb.notify_gear_shift()
                elif sym == sdl2.SDLK_z:
                    if car.shift_down():
                        ffb.notify_gear_shift()

        keys = sdl2.SDL_GetKeyboardState(None)
        wheel.update(keys)

        # levas del volante
        if wheel.button_pressed_edge(cfg.BUTTON_SHIFT_UP):
            if car.shift_up():
                ffb.notify_gear_shift()
        if wheel.button_pressed_edge(cfg.BUTTON_SHIFT_DOWN):
            if car.shift_down():
                ffb.notify_gear_shift()
        if wheel.button_pressed_edge(cfg.BUTTON_TOGGLE_AUTO):
            auto_gear = not auto_gear
        if wheel.button_pressed_edge(cfg.BUTTON_TOGGLE_VIEW):
            chase_view = not chase_view
        if wheel.button_pressed_edge(cfg.BUTTON_ENGINE):
            car.toggle_engine()
        if wheel.button_pressed_edge(cfg.BUTTON_RESET):
            car.reset(car.state.s)

        # cambio automático (las levas siguen funcionando en manual)
        if auto_gear and car.auto_shift(wheel.throttle):
            ffb.notify_gear_shift()

        # ------------------------------------------------ tiempo
        now = sdl2.SDL_GetPerformanceCounter()
        frame_dt = (now - last) / perf_freq
        last = now
        frame_dt = min(frame_dt, 0.1)
        accumulator += frame_dt

        # ------------------------------------------------ física
        while accumulator >= physics_dt:
            st = car.state
            surface, _ = track.surface_at(st.n, st.s)
            prev_s = st.s
            car.step(physics_dt, wheel.steering, wheel.throttle, wheel.brake,
                     track)
            # cronometraje de vueltas
            lap_time += physics_dt
            if prev_s % track.length > st.s % track.length and st.vx > 1.0:
                if best_lap is None or lap_time < best_lap:
                    best_lap = lap_time
                lap_time = 0.0
                lap_count += 1
            accumulator -= physics_dt

        # ------------------------------------------------ force feedback
        ffb.update(frame_dt, car.state, surface, abs(car.state.vx))

        # chirrido de neumáticos: cuánto excede del pico de agarre la
        # rueda que más desliza (la hierba no chirría)
        st = car.state
        over = 0.0
        if abs(st.vx) > 4.0:
            peak_a = math.radians(cfg.TIRE_PEAK_SLIP_ANGLE_DEG)
            for i in range(4):
                if st.wheel_surface[i] == "grass":
                    continue
                over = max(over,
                           abs(st.slip_ratio[i]) / cfg.TIRE_PEAK_SLIP_RATIO,
                           abs(st.slip_angle[i]) / peak_a)
        screech = max(0.0, min(1.0, (over - 1.05) * 1.2))
        sound.update(st.rpm, wheel.throttle, screech, st.engine_on)

        # ------------------------------------------------ render
        sdl2.SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255)
        sdl2.SDL_RenderClear(renderer)
        base_seg = track.segment_at(car.state.s)
        scene.draw_background(cfg.WINDOW_HEIGHT // 2,
                              car.state.psi + base_seg.kappa * 40.0)
        cam_h = 3.0 if chase_view else cfg.CAMERA_HEIGHT
        scene.draw_road(track, car.state, show_line, cam_h)
        if chase_view:
            scene.draw_car_chase(car.state, wheel.steering)
        else:
            scene.draw_car(car.state, wheel.steering)
        hud.draw(car.state, lap_time, best_lap, lap_count, ffb.ok, wheel.name,
                 auto_gear)
        if show_debug:
            hud.draw_debug(wheel, car.state, surface)
        if show_telemetry:
            hud.draw_telemetry(car.state)
        sdl2.SDL_RenderPresent(renderer)

        frame += 1
        if args.frames and frame >= args.frames:
            running = False

    sound.close()
    ffb.close()
    wheel.close()
    sdl2.SDL_DestroyRenderer(renderer)
    sdl2.SDL_DestroyWindow(window)
    sdl2.SDL_Quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
