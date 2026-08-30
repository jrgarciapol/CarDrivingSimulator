"""Punto de entrada del simulador.

Uso:  python -m simulator.main [--frames N] [--rendimiento]
                               [--ventana ANCHOxALTO] [--completa]

Controles con volante Thrustmaster (configurables en simulator/config.py):
  volante        direccion
  pedales        acelerador / freno
  levas          subir / bajar marcha
Controles con mando (Steam Deck, XBox, PlayStation):
  stick izqdo.   direccion
  gatillos       acelerador (derecho) / freno (izquierdo), analogicos
  L1 / R1        bajar / subir marcha
  A B X Y        motor / recolocar / vista / cambio automatico
  cruceta        ARRIBA telemetria, IZQ plano, DER planta, ABAJO trazada
  START          volver al menu

En una Steam Deck, LANZA EL JUEGO DESDE STEAM (anadelo como juego externo):
Steam Input le da un mando de Xbox y los gatillos funcionan. Fuera de Steam
el mando no se anuncia como gamepad. Se puede forzar el modo de entrada con
--mando / --volante / --teclado (o INPUT_MODE en config.py).
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
  M              mostrar/ocultar el plano del circuito completo
  N              mostrar/ocultar la planta del tramo que viene
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
from . import settings
from .timing import LapTimer
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


def ajustar_ventana():
    """Encaja la ventana en la pantalla real. En un portátil (una Steam Deck
    es de 1280x800) una ventana de 1920x1080 se sale por abajo y por la
    derecha, y no hay forma de ver el HUD ni de llegar a los botones."""
    if not getattr(cfg, "WINDOW_AUTO", False):
        return
    modo = sdl2.SDL_DisplayMode()
    if sdl2.SDL_GetCurrentDisplayMode(0, ctypes.byref(modo)) != 0:
        return
    pw, ph = int(modo.w), int(modo.h)
    if pw <= 0 or ph <= 0:
        return
    if pw >= cfg.WINDOW_WIDTH and ph >= cfg.WINDOW_HEIGHT:
        return                      # cabe de sobra: no tocar nada
    # se reduce MANTENIENDO LA PROPORCION, y a múltiplos de 2 px para que
    # los rectángulos del HUD no queden a medio píxel
    k = min(pw / cfg.WINDOW_WIDTH, ph / cfg.WINDOW_HEIGHT)
    cfg.WINDOW_WIDTH = int(cfg.WINDOW_WIDTH * k) // 2 * 2
    cfg.WINDOW_HEIGHT = int(cfg.WINDOW_HEIGHT * k) // 2 * 2
    print(f"Pantalla {pw}x{ph}: ventana ajustada a "
          f"{cfg.WINDOW_WIDTH}x{cfg.WINDOW_HEIGHT}")


def preset_rendimiento():
    """Baja la carga de CPU para equipos modestos (Steam Deck, portátiles).

    Los recortes están elegidos MIDIENDO, no a ojo. A 1280x800 con el
    render por software, el coste por fotograma se reparte así:

        bruma atmosférica ....... 22 %   <- el efecto más caro con diferencia
        alcance de dibujado ..... 12 %
        sombreado solar .......... 7 %
        trazada ideal ............ 2 %
        física a 480 Hz .......... 8 %

    Por eso NO se toca la física: cuesta poco y bajarla degradaría el force
    feedback, que es lo último que conviene sacrificar. Se apagan los dos
    efectos atmosféricos (que son barridos de numpy sobre todas las
    secciones) y se recorta el alcance, que por debajo de ~130 segmentos ya
    no da más rendimiento y sí quita visibilidad.

    El modelo físico queda INTACTO: cambia lo que se ve, no cómo se conduce.
    """
    cfg.DRAW_DISTANCE = 140
    cfg.GFX_FOG_DIST = 0.0
    cfg.GFX_SUN_SHADE = 0.0
    cfg.GHOST_ENABLED = False
    print("Preset de rendimiento: sin bruma ni sombreado, alcance 140 "
          "(la fisica NO se toca)")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Car Driving Simulator")
    parser.add_argument("--frames", type=int, default=0,
                        help="salir tras N frames (pruebas automatizadas)")
    parser.add_argument("--rendimiento", action="store_true",
                        help="preset para equipos modestos (Steam Deck)")
    parser.add_argument("--ventana", metavar="ANCHOxALTO",
                        help="forzar el tamano de ventana, p.ej. 1280x800")
    parser.add_argument("--completa", action="store_true",
                        help="arrancar en pantalla completa")
    parser.add_argument("--mando", action="store_true",
                        help="forzar lectura como MANDO (gamepad)")
    parser.add_argument("--volante", action="store_true",
                        help="forzar lectura como VOLANTE")
    parser.add_argument("--teclado", action="store_true",
                        help="forzar teclado (ignorar mando/volante)")
    parser.add_argument("--motor", choices=["legacy", "inertia"],
                        help="modelo de motor: legacy (regimen por filtro) o "
                        "inertia (cigueñal con inercia + embrague)")
    parser.add_argument("--neumatico", choices=["legacy", "brush"],
                        help="modelo de neumatico: legacy (curva compartida) o "
                        "brush (curvas long/lat separadas)")
    args = parser.parse_args(argv)

    # las banderas fuerzan el modo de entrada por encima de la deteccion
    if args.mando:
        cfg.INPUT_MODE = "mando"
    elif args.volante:
        cfg.INPUT_MODE = "volante"
    elif args.teclado:
        cfg.INPUT_MODE = "teclado"
    if args.motor:
        cfg.ENGINE_MODEL = args.motor
        print(f"Modelo de motor: {args.motor}")
    if args.neumatico:
        cfg.TIRE_MODEL = args.neumatico
        print(f"Modelo de neumatico: {args.neumatico}")

    if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_JOYSTICK |
                     sdl2.SDL_INIT_GAMECONTROLLER |
                     sdl2.SDL_INIT_HAPTIC | sdl2.SDL_INIT_AUDIO |
                     sdl2.SDL_INIT_EVENTS) != 0:
        print("Error al iniciar SDL:", sdl2.SDL_GetError().decode())
        return 1

    if args.rendimiento:
        preset_rendimiento()
    if args.ventana:
        try:
            w, h = args.ventana.lower().split("x")
            cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT = int(w), int(h)
        except ValueError:
            print("Formato de --ventana no valido; se esperaba ANCHOxALTO")
            return 1
    else:
        ajustar_ventana()
    flags = sdl2.SDL_WINDOW_SHOWN
    if args.completa or getattr(cfg, "WINDOW_FULLSCREEN", False):
        flags |= sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP

    window = sdl2.SDL_CreateWindow(
        cfg.WINDOW_TITLE,
        sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED,
        cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT, flags)
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
    # ajustes guardados de sesiones anteriores (configuracion global +
    # ultima seleccion de coche/circuito/asfalto)
    settings.load()
    wheel = WheelInput()
    ffb = ForceFeedback(wheel)
    sound = EngineSound()

    # ESC durante el juego vuelve a este menú (elegir otro coche/circuito o
    # tocar los AJUSTES AVANZADOS) sin cerrar el programa; ESC en el menú sale.
    while True:
        if not args.frames:
            sel = run_menu(renderer, wheel, settings.last)
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
            # EL REGLAJE DEL USUARIO SE APLICA AL FINAL, despues de load_car
            # y apply_condition, para que sus cambios (caster, toe, muelles)
            # GANEN a los del archivo del coche. Sin esto, load_car los pisaba.
            settings.apply_car()
            settings.apply_config()
            # recordar la seleccion para el proximo arranque
            car_ref = sel["car"][1] if sel["car"] is not None else ""
            settings.remember(car_ref, sel["track"][1], condition,
                              sel.get("wheel"), sel.get("wheel_rear"))

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
    if wheel.es_mando:
        print(f"Mando detectado: {wheel.name}")
        print("  stick izquierdo = direccion | gatillos = gas y freno")
        print("  L1/R1 = marchas | A = motor | B = recolocar | X = vista"
              " | Y = automatico")
        print("  cruceta: ARRIBA telemetria | IZQ plano | DER planta | ABAJO"
              " trazada | START menu")
        print("Vibracion:", "activa" if ffb.ok else "desactivada")
    elif wheel.connected:
        print(f"Volante detectado: {wheel.name} "
              f"({wheel.num_axes} ejes, {wheel.num_buttons} botones)")
        print("Force feedback:", "activo" if ffb.ok else "no disponible")
    else:
        print("Sin volante ni mando: usando teclado (flechas).")

    perf_freq = sdl2.SDL_GetPerformanceFrequency()
    last = sdl2.SDL_GetPerformanceCounter()
    frame_dt = 1.0 / 60.0     # la entrada lo usa antes de medirlo (mando)
    physics_dt = 1.0 / cfg.PHYSICS_HZ
    accumulator = 0.0

    timer = LapTimer(track.length,
                     garage.record_get(track.name, car_name, condition))
    record_banner_until = -1.0
    # fantasma de la mejor vuelta de la sesión + partículas
    particles = render_mod.Particles()
    ghost_rec = []        # vuelta en curso: (t, s, n, psi) cada 50 ms
    ghost_best = None     # mejor vuelta grabada de la sesión
    ghost_next = 0.0
    show_debug = False
    show_telemetry = False
    show_line = cfg.RACING_LINE
    auto_gear = cfg.AUTO_GEAR
    view_mode = cfg.VIEW_MODE   # 0 sin coche, 1 trasera, 2 coche completo
    time_idx = 0                # indice en TIME_SCALES (camara lenta)
    show_minimap = cfg.MINIMAP
    show_plan = cfg.MAP_AHEAD      # planta del tramo que viene (tecla N)
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
                elif sym == sdl2.SDLK_n:
                    show_plan = not show_plan
                elif sym == sdl2.SDLK_r:
                    car.reset(car.state.s)
                    # recolocar el coche INVALIDA la vuelta en curso: si no,
                    # se podria "arreglar" una salida de pista y cronometrar
                    # igual, que es de donde salian tiempos irreales
                    timer.invalidate()
                elif sym == sdl2.SDLK_a:
                    if car.shift_up():
                        ffb.notify_gear_shift()
                elif sym == sdl2.SDLK_z:
                    if car.shift_down():
                        ffb.notify_gear_shift()

        keys = sdl2.SDL_GetKeyboardState(None)
        # la velocidad solo la usa el MANDO, para cerrar el tope de
        # direccion a medida que se corre mas
        wheel.update(keys, car.state.speed_kmh, max(1e-4, frame_dt))

        # levas del volante
        if wheel.action_edge("shift_up"):
            if car.shift_up():
                ffb.notify_gear_shift()
        if wheel.action_edge("shift_down"):
            if car.shift_down():
                ffb.notify_gear_shift()
        if wheel.action_edge("toggle_auto"):
            auto_gear = not auto_gear
        if wheel.action_edge("toggle_view"):
            view_mode = (view_mode + 1) % 3
        if wheel.action_edge("engine"):
            car.toggle_engine()
        if wheel.action_edge("slowmo"):
            time_idx = (time_idx + 1) % len(cfg.TIME_SCALES)
        if wheel.action_edge("reset"):
            car.reset(car.state.s)
            timer.invalidate()         # igual que la tecla R
        # paneles del HUD por la CRUCETA del mando (la Deck no tiene F1/F2)
        if wheel.action_edge("telemetry"):
            show_telemetry = not show_telemetry
        if wheel.action_edge("minimap"):
            show_minimap = not show_minimap
        if wheel.action_edge("plan"):
            show_plan = not show_plan
        if wheel.action_edge("line"):
            show_line = not show_line
        if wheel.action_edge("menu"):      # START = volver al menu (como ESC)
            to_menu = True
            running = False

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
            # cronometraje de vueltas (reglas de validez en timing.py)
            sim_time += physics_dt
            # grabación del fantasma: estado curvilíneo cada ~50 ms
            if (cfg.GHOST_ENABLED and timer.valid
                    and timer.lap_time >= ghost_next):
                ghost_rec.append((timer.lap_time, st.s % track.length, st.n,
                                  st.psi))
                ghost_next = timer.lap_time + 0.05
            vuelta = timer.update(physics_dt, prev_s, st.s, st.vx, st.psi)
            if vuelta is not None and timer.last_was_best:
                if garage.record_save(track.name, car_name, condition,
                                      vuelta):
                    record_banner_until = sim_time + 5.0
                # el fantasma pasa a reproducir la vuelta recién batida
                if len(ghost_rec) > 4:
                    ghost_rec.append((vuelta, st.s % track.length,
                                      st.n, st.psi))
                    ghost_best = ghost_rec
            if vuelta is not None or timer.lap_time < physics_dt * 1.5:
                ghost_rec = []
                ghost_next = 0.0
            accumulator -= physics_dt

        # ------------------------------------------------ force feedback
        ffb.update(frame_dt, car.state, surface, abs(car.state.vx))

        # neumáticos: se separan TRES deslizamientos físicos, cada uno con
        # su propio sonido (la hierba no chirría). El scrub es lateral
        # (deriva en curva), el spin es longitudinal en la rueda MOTRIZ con
        # gas (patinaje de tracción) y el lock es longitudinal frenando
        # (bloqueo). Así el wheelspin de la salida de curva no suena igual
        # que el arrastre lateral ni que un bloqueo de frenada.
        st = car.state
        peak_a = math.radians(cfg.TIRE_PEAK_SLIP_ANGLE_DEG)
        peak_s = cfg.TIRE_PEAK_SLIP_RATIO
        driven = car._driven_wheels()
        scrub_r = spin_r = lock_r = 0.0
        if abs(st.vx) > 4.0:
            for i in range(4):
                if st.wheel_surface[i] == "grass":
                    continue
                scrub_r = max(scrub_r, abs(st.slip_angle[i]) / peak_a)
                sr = st.slip_ratio[i]
                if sr > 0.0 and i in driven and wheel.throttle > 0.15:
                    spin_r = max(spin_r, sr / peak_s)       # patina de tracción
                if sr < 0.0 and wheel.brake > 0.15:
                    lock_r = max(lock_r, -sr / peak_s)      # bloqueo en frenada
        # el sonido arranca justo en el pico de agarre (onset a 0.92): así
        # también canta el empuje al límite, no solo los derrapes grandes
        def _onset(x):
            return max(0.0, min(1.0, (x - 0.92) * 2.1))
        scrub = _onset(scrub_r)
        spin = _onset(spin_r)
        lock = _onset(lock_r)
        screech = max(scrub, spin, lock)   # compat / nivel global
        # ADAS: alimenta los avisos con el balance de la física, pero solo
        # en pista (fuera, en la hierba, todo desliza y no es un aviso útil)
        adas_u = st.understeer
        adas_o = st.oversteer
        if abs(st.n) > track.half_at(st.s) + cfg.KERB_WIDTH:
            adas_u = adas_o = 0.0
        sound.update(st.rpm, wheel.throttle, screech, st.engine_on,
                     abs(st.vx), adas_u, adas_o, gear=st.gear,
                     scrub=scrub, spin=spin, lock=lock, brake=wheel.brake)

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
            g = ghost_sample(ghost_best, timer.lap_time, track.length)
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
        if show_plan:
            hud.draw_plan_ahead(track, car.state)
        if sim_time < record_banner_until:
            from . import font as font_mod
            txt = "NUEVO RECORD"
            font_mod.draw_text(renderer, txt,
                               cfg.WINDOW_WIDTH // 2 - font_mod.text_width(txt, 4) // 2,
                               150, 4, (120, 255, 120, 255))
        hud.draw(car.state, timer.lap_time, timer.best, timer.lap_count,
                 ffb.ok, wheel.name, auto_gear, time_scale, track, car_name,
                 condition, timer.wrong_way, timer.valid)
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
