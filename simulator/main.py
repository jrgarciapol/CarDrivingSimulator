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
  C              cambiar vista: sin coche / trasera / coche completo
  E              arrancar / parar el motor
  T              camara lenta (1x / 0.5x / 0.25x / 0.1x)
  M              mostrar/ocultar el plano del circuito
  ESC            salir
"""

import argparse
import ctypes
import math
import sys

import sdl2

from . import config as cfg
from . import garage
from . import render as render_mod
from .audio import EngineSound
from .menu import run_menu
from .physics import Car
from .render import Hud, Renderer
from .track import Track
from .wheel import ForceFeedback, WheelInput


def ghost_sample(data, t, track_len):
    """Interpola (s, n, psi) de la vuelta grabada en el tiempo t."""
    if not data:
        return None
    if t <= data[0][0]:
        return data[0][1:]
    if t >= data[-1][0]:
        return data[-1][1:]
    i = min(int(t / 0.05), len(data) - 2)
    while i > 0 and data[i][0] > t:
        i -= 1
    while i < len(data) - 2 and data[i + 1][0] < t:
        i += 1
    t0, s0, n0, p0 = data[i]
    t1, s1, n1, p1 = data[i + 1]
    u = (t - t0) / max(1e-6, t1 - t0)
    if s1 - s0 < -track_len / 2.0:
        s1 += track_len          # cruce de meta dentro del tramo
    return ((s0 + (s1 - s0) * u) % track_len,
            n0 + (n1 - n0) * u, p0 + (p1 - p0) * u)


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

    # ------------------------------------------------ menú de arranque
    car_name = "DEPORTIVO"
    condition = "SECO"
    # las condiciones MULTIPLICAN estos valores: guardar la base para
    # restaurarla al volver al menú (si no, se acumularían)
    _cond_base = {k: getattr(cfg, k)
                  for k in ("TIRE_MU", "TIRE_MU_GRASS", "ROLLING_RESIST")}
    wheel = WheelInput()
    ffb = ForceFeedback(wheel)
    sound = EngineSound()

    # ESC durante el juego vuelve a este menú (elegir otro coche/circuito o
    # tocar los AJUSTES AVANZADOS) sin cerrar el programa; ESC en el menú sale.
    while True:
        if not args.frames:
            sel = run_menu(renderer)
            if sel is None:
                sound.close()
                ffb.close()
                wheel.close()
                sdl2.SDL_DestroyRenderer(renderer)
                sdl2.SDL_DestroyWindow(window)
                sdl2.SDL_Quit()
                return 0
            for k, v in _cond_base.items():
                setattr(cfg, k, v)
            if sel["car"] is not None:
                car_name = garage.load_car(sel["car"][1])
                if sel.get("wheel"):
                    wf, wr = garage.apply_wheel(sel["wheel"], sel["car"][1],
                                                sel.get("wheel_rear"))
                    print(f"Ruedas: {sel['wheel']} delante / "
                          f"{sel.get('wheel_rear') or sel['wheel']} detras")
                    print(f"  R={wf['radius']*1000:.0f}/{wr['radius']*1000:.0f} mm"
                          f"  I={wf['inertia']:.2f}/{wr['inertia']:.2f} kg*m2"
                          f"  grupo final {cfg.FINAL_DRIVE:.2f}")
            cfg.TRACK_FILE = sel["track"][1]
            condition = sel["cond"]
            garage.apply_condition(condition)
            render_mod.set_condition(condition)

        to_menu = run_session(renderer, window, wheel, ffb, sound,
                              car_name, condition, args)
        if args.frames or not to_menu:
            break

    sound.close()
    ffb.close()
    wheel.close()
    sdl2.SDL_DestroyRenderer(renderer)
    sdl2.SDL_DestroyWindow(window)
    sdl2.SDL_Quit()
    return 0


def run_session(renderer, window, wheel, ffb, sound, car_name, condition,
                args):
    """Una tanda de conducción. Devuelve True si el usuario pidió volver al
    menú (ESC) o False si cerró el programa."""
    sound.resume()
    track = Track()
    car = Car()
    scene = Renderer(renderer)
    hud = Hud(renderer)

    print(f"Car Driving Simulator {cfg.VERSION}")
    print(f"Coche: {car_name} | Asfalto: {condition}")
    print(f"Circuito: {track.name} ({track.length:.0f} m)")
    from .physics import engine_peak_power_cv
    print(f"Motor: {cfg.ENGINE_MAX_TORQUE_NM:.0f} Nm de par maximo, "
          f"~{engine_peak_power_cv():.0f} CV")
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
    best_lap = garage.record_get(track.name, car_name, condition)
    lap_count = 1
    record_banner_until = -1.0
    # fantasma de la mejor vuelta de la sesión + partículas
    particles = render_mod.Particles()
    ghost_rec = []        # vuelta en curso: (t, s, n, psi) cada 50 ms
    ghost_best = None     # mejor vuelta grabada de la sesión
    ghost_next = 0.0
    lap_valid = False     # la primera vuelta (parcial) no se graba
    show_debug = False
    show_telemetry = False
    show_line = cfg.RACING_LINE
    auto_gear = cfg.AUTO_GEAR
    view_mode = cfg.VIEW_MODE   # 0 sin coche, 1 trasera, 2 coche completo
    time_idx = 0                # indice en TIME_SCALES (camara lenta)
    show_minimap = cfg.MINIMAP
    sim_time = 0.0              # tiempo de simulacion (para la telemetria)
    surface = "road"
    frame = 0
    event = sdl2.SDL_Event()
    running = True
    to_menu = False

    while running:
        # ------------------------------------------------ eventos
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            if event.type == sdl2.SDL_QUIT:
                running = False
            elif event.type == sdl2.SDL_KEYDOWN and not event.key.repeat:
                sym = event.key.keysym.sym
                if sym == sdl2.SDLK_ESCAPE:
                    to_menu = True      # ESC: volver al menu, no cerrar
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
                    view_mode = (view_mode + 1) % 3
                elif sym == sdl2.SDLK_e:
                    car.toggle_engine()
                elif sym == sdl2.SDLK_t:
                    time_idx = (time_idx + 1) % len(cfg.TIME_SCALES)
                elif sym == sdl2.SDLK_m:
                    show_minimap = not show_minimap
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
            view_mode = (view_mode + 1) % 3
        if wheel.button_pressed_edge(cfg.BUTTON_ENGINE):
            car.toggle_engine()
        if wheel.button_pressed_edge(cfg.BUTTON_SLOWMO):
            time_idx = (time_idx + 1) % len(cfg.TIME_SCALES)
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
        time_scale = cfg.TIME_SCALES[time_idx]
        accumulator += frame_dt * time_scale

        # ------------------------------------------------ física
        while accumulator >= physics_dt:
            st = car.state
            surface, _ = track.surface_at(st.n, st.s)
            prev_s = st.s
            car.step(physics_dt, wheel.steering, wheel.throttle, wheel.brake,
                     track)
            # cronometraje de vueltas
            lap_time += physics_dt
            sim_time += physics_dt
            # grabación del fantasma: estado curvilíneo cada ~50 ms
            if cfg.GHOST_ENABLED and lap_valid and lap_time >= ghost_next:
                ghost_rec.append((lap_time, st.s % track.length, st.n,
                                  st.psi))
                ghost_next = lap_time + 0.05
            if prev_s % track.length > st.s % track.length and st.vx > 1.0:
                new_best = best_lap is None or lap_time < best_lap
                if new_best:
                    best_lap = lap_time
                    if garage.record_save(track.name, car_name, condition,
                                          lap_time):
                        record_banner_until = sim_time + 5.0
                # el fantasma pasa a reproducir la vuelta recién batida
                if lap_valid and new_best and len(ghost_rec) > 4:
                    ghost_rec.append((lap_time, st.s % track.length,
                                      st.n, st.psi))
                    ghost_best = ghost_rec
                ghost_rec = []
                ghost_next = 0.0
                lap_valid = True
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
        # el chirrido arranca justo en el pico de agarre: también suena
        # el empuje de subviraje, no solo los derrapes grandes (onset a
        # 0.92 con pendiente firme: el subviraje al límite ya canta)
        screech = max(0.0, min(1.0, (over - 0.92) * 2.1))
        # ADAS: alimenta los avisos con el balance de la física, pero solo
        # en pista (fuera, en la hierba, todo desliza y no es un aviso útil)
        adas_u = st.understeer
        adas_o = st.oversteer
        if abs(st.n) > track.half_at(st.s) + cfg.KERB_WIDTH:
            adas_u = adas_o = 0.0
        sound.update(st.rpm, wheel.throttle, screech, st.engine_on,
                     abs(st.vx), adas_u, adas_o)

        # ------------------------------------------------ render
        sdl2.SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255)
        sdl2.SDL_RenderClear(renderer)
        base_seg = track.segment_at(car.state.s)
        horizon_px = cfg.WINDOW_HEIGHT // 2
        if view_mode < 2:
            horizon_px += int(render_mod.camera_pitch_px(car.state))
        scene.draw_background(horizon_px,
                              car.state.psi * cfg.CAMERA_YAW_GAIN
                              + base_seg.kappa * 40.0)
        # vistas: 0 = sin coche (camara interior), 1 = trasera cercana,
        # 2 = coche completo 3D con camara de persecucion
        cam_fwd = 0.0
        if view_mode == 2:
            cam_h, cam_back, ygain = 2.5, 6.5, 0.35
        else:
            # vista interior: ojo del conductor (altura y adelantamiento
            # dependen del coche); vista trasera: cámara elevada tras el coche
            cam_h = (cfg.CAMERA_HEIGHT, cfg.CAMERA_HEIGHT_REAR)[view_mode]
            cam_back, ygain = 0.0, None
            if view_mode == 0:
                cam_fwd = cfg.CAMERA_FORWARD
        scene.draw_road(track, car.state, show_line, cam_h, cam_back, ygain,
                        cam_fwd)
        # fantasma de la mejor vuelta de la sesión
        if cfg.GHOST_ENABLED and ghost_best is not None:
            g = ghost_sample(ghost_best, lap_time, track.length)
            if g is not None:
                scene.draw_ghost(track, g[0], g[1], g[2])
        if view_mode == 1:
            scene.draw_car(car.state, wheel.steering)
        elif view_mode == 2:
            scene.draw_car_3d(car.state, wheel.steering, cam_h, cam_back, 0.35)
        # partículas: humo (asfalto), chispas (piano), polvo (hierba)
        if cfg.PARTICLES_ENABLED:
            st = car.state
            if abs(st.vx) > 3.0:
                peak_a = math.radians(cfg.TIRE_PEAK_SLIP_ANGLE_DEG)
                for i in range(4):
                    over_i = max(abs(st.slip_ratio[i]) / cfg.TIRE_PEAK_SLIP_RATIO,
                                 abs(st.slip_angle[i]) / peak_a)
                    if over_i > 0.9 and st.fz[i] > 100.0:
                        kind = {"road": "smoke", "kerb": "spark",
                                "grass": "dust"}[st.wheel_surface[i]]
                        particles.emit(kind,
                                       (st.s + car.X_POS[i]) % track.length,
                                       st.n + car.Y_POS[i], abs(st.vx))
            particles.update(frame_dt * time_scale)
            particles.draw(renderer, scene, track)
        if show_minimap:
            hud.draw_minimap(track, car.state)
        if sim_time < record_banner_until:
            from . import font as font_mod
            txt = "NUEVO RECORD"
            font_mod.draw_text(renderer, txt,
                               cfg.WINDOW_WIDTH // 2 - font_mod.text_width(txt, 4) // 2,
                               150, 4, (120, 255, 120, 255))
        hud.draw(car.state, lap_time, best_lap, lap_count, ffb.ok, wheel.name,
                 auto_gear, time_scale, track, car_name, condition)
        if show_debug:
            hud.draw_debug(wheel, car.state, surface)
        if show_telemetry:
            hud.draw_telemetry(car.state, wheel.steering, sim_time)
        sdl2.SDL_RenderPresent(renderer)

        frame += 1
        if args.frames and frame >= args.frames:
            running = False

    # dejar el volante quieto y el motor en silencio mientras dura el menú
    sound.pause()
    ffb.still()
    return to_menu


if __name__ == "__main__":
    sys.exit(main())
