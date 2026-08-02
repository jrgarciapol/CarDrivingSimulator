"""Configuración del simulador.

Todos los ajustes del juego están en este archivo, agrupados por secciones.
Cada parámetro indica sus unidades, su efecto y el rango razonable entre
paréntesis [mín .. máx]. Tras editar, basta reiniciar el simulador.
"""

# ===========================================================================
# VENTANA Y BUCLE
# ===========================================================================
WINDOW_WIDTH = 1280          # px, ancho de la ventana [800 .. 1920]
WINDOW_HEIGHT = 720          # px, alto de la ventana [600 .. 1080]
WINDOW_TITLE = b"Car Driving Simulator - Thrustmaster"
TARGET_FPS = 60              # objetivo de imágenes por segundo (informativo)
PHYSICS_HZ = 240             # Hz del paso de física; más alto = más precisa
                             # y más CPU [120 .. 480]

# ===========================================================================
# VOLANTE Y PEDALES (mapeo DirectInput/SDL)
#
# Pulsa F1 dentro del simulador para ver los valores en crudo de cada eje
# y el número de cada botón al pulsarlo, y ajusta aquí los índices.
# ===========================================================================
# Subcadenas para elegir el dispositivo si hay varios conectados
WHEEL_NAME_HINTS = ("thrustmaster", "t300", "t150", "tmx", "t248", "tx", "t-gt")

AXIS_STEERING = 0        # eje de la dirección (casi siempre 0)
AXIS_THROTTLE = 2        # eje del acelerador (T300RS: 2)
AXIS_BRAKE = 1           # eje del freno (T300RS: 1)
AXIS_CLUTCH = 3          # eje del embrague; si no existe se ignora

PEDALS_INVERTED = True   # True si los pedales reposan en +32767 y bajan al
                         # pisar (lo normal en Thrustmaster)

WHEEL_ROTATION_DEG = 900.0   # grados de giro configurados en el panel de
                             # control de Thrustmaster; deben coincidir para
                             # que la dirección sea realista [180 .. 1080]

BUTTON_SHIFT_UP = 1      # leva derecha, subir marcha (T300RS: 1)
BUTTON_SHIFT_DOWN = 0    # leva izquierda, bajar marcha (T300RS: 0)
BUTTON_TOGGLE_AUTO = 2   # alternar cambio automático/manual (tecla G)
BUTTON_TOGGLE_VIEW = 3   # cambiar de vista (tecla C)
BUTTON_ENGINE = 9        # arrancar/parar el motor (tecla E)
BUTTON_RESET = 8         # recolocar el coche en pista (tecla R)

STEERING_DEADZONE = 0.005    # zona muerta del volante [0 .. 0.05]

AUTO_GEAR = True         # True = arrancar con cambio automático
VIEW_MODE = 0            # vista inicial: 0 = sin coche (cámara interior),
                         # 1 = trasera cercana, 2 = coche completo

# ===========================================================================
# FORCE FEEDBACK
#
# El par del volante se calcula desde la física (autoalineado del
# neumático). Regla general: FFB_GAIN da el volumen global y
# FFB_MAX_TORQUE_NM la dureza; el resto son efectos concretos.
# ===========================================================================
FFB_ENABLED = True
FFB_GAIN = 0.9           # ganancia global del par [0 .. 1]
FFB_INVERT = False       # True si el volante empuja hacia FUERA de la
                         # curva en vez de autocentrarse
FFB_MAX_TORQUE_NM = 40.0 # Nm de columna que saturan el volante; BAJARLO
                         # endurece el volante en apoyo y hace más evidente
                         # el aligeramiento al subvirar [20 .. 60]
FFB_COLUMN_DAMPING = 1.3 # Nm por rad/s de giro del volante; amortigua las
                         # oscilaciones autoexcitadas en recta (se escala
                         # además con la velocidad) [0 .. 4]
FFB_SMOOTHING_S = 0.04   # s, suavizado del par enviado al volante; sube a
                         # 0.06-0.08 si el volante da bandazos en recta,
                         # baja a 0.02 si lo notas "gomoso" [0 .. 0.1]
FFB_KICK_GAIN = 0.0015   # sacudida por baches asimétricos delanteros, en
                         # Nm por N de diferencia de carga; 0 la elimina
                         # [0 .. 0.005]
FFB_SPRING_LOWSPEED = 0.35   # muelle de centrado al aparcar [0 .. 1]
FFB_DAMPER_LOWSPEED = 0.55   # pesadez del volante parado [0 .. 1]
FFB_DAMPER_HIGHSPEED = 0.16  # amortiguación residual en marcha; sube si
                             # el volante vibra en recta [0 .. 0.4]
FFB_ROAD_TEXTURE = 0.05      # vibración fina del asfalto [0 .. 0.3]
FFB_KERB_MAGNITUDE = 0.45    # vibración al pisar pianos [0 .. 1]
FFB_GRASS_MAGNITUDE = 0.35   # vibración sobre hierba [0 .. 1]
FFB_ENGINE_IDLE = 0.06       # vibración del motor al ralentí [0 .. 0.3]
FFB_SHIFT_JOLT = 0.35        # sacudida al cambiar de marcha [0 .. 1]

# ===========================================================================
# VEHÍCULO — masas y geometría (ficha técnica)
# ===========================================================================
CAR_MASS = 1250.0            # kg, masa total [800 .. 2500]
CAR_INERTIA_Z = 1900.0       # kg·m², inercia de guiñada; más alta = coche
                             # más "perezoso" al girar [1200 .. 4000]
CAR_INERTIA_PITCH = 2100.0   # kg·m², inercia de cabeceo [1500 .. 4500]
CAR_INERTIA_ROLL = 550.0     # kg·m², inercia de balanceo [350 .. 1200]
WHEELBASE = 2.60             # m, batalla (distancia entre ejes) [2.2 .. 3.2]
WEIGHT_DIST_FRONT = 0.546    # fracción del peso sobre el eje delantero,
                             # como en la ficha técnica; 0.5 = 50/50
                             # [0.40 .. 0.65]
CAR_CG_HEIGHT = 0.52         # m, altura del centro de gravedad; más alto =
                             # más transferencias de carga [0.35 .. 0.75]
CAR_TRACK_WIDTH = 1.55       # m, vía (separación entre ruedas) [1.4 .. 1.8]
CAR_WHEEL_RADIUS = 0.31      # m, radio de rueda [0.25 .. 0.40]
CAR_WHEEL_INERTIA = 1.4      # kg·m² por rueda [0.8 .. 2.5]
STEER_RATIO = 12.0           # relación volante:rueda; más baja = dirección
                             # más directa [10 .. 20]
STEER_SCRUB_RADIUS = 0.04    # m, radio de pivotamiento: cuánto "tiran" del
                             # volante las fuerzas de frenada/tracción
                             # asimétricas [0 .. 0.08]

# Derivados de la geometría (no editar: se calculan del reparto)
CAR_CG_TO_FRONT = WHEELBASE * (1.0 - WEIGHT_DIST_FRONT)
CAR_CG_TO_REAR = WHEELBASE * WEIGHT_DIST_FRONT

# ===========================================================================
# TRANSMISIÓN Y TRACCIÓN
# ===========================================================================
DRIVE_TYPE = "RWD"           # "RWD" propulsión trasera | "FWD" delantera |
                             # "AWD" total
AWD_FRONT_SPLIT = 0.40       # en AWD, fracción del par al eje delantero
                             # [0.2 .. 0.6]
DIFF_TYPE = "lsd"            # diferencial del eje motriz: "open" abierto
                             # (pierde tracción por la rueda interior),
                             # "lsd" autoblocante, "locked" bloqueado
DIFF_LSD_COEFF = 18.0        # Nm·s/rad de acoplamiento del autoblocante
                             # [5 .. 40]

# ===========================================================================
# MOTOR
#
# La curva de par se genera a partir de estos dos valores: sube desde el
# ralentí hasta el par máximo y cae un 25 % hacia el corte. La potencia
# máxima resultante se muestra en la consola al arrancar (~230 CV con
# los valores por defecto).
# ===========================================================================
ENGINE_MAX_TORQUE_NM = 320.0     # Nm de par máximo [150 .. 700]
ENGINE_TORQUE_PEAK_RPM = 4200.0  # rpm del par máximo [3000 .. 6000]
ENGINE_IDLE_RPM = 900.0          # rpm de ralentí [600 .. 1200]
ENGINE_REDLINE_RPM = 6800.0      # rpm de zona roja [5500 .. 9000]
ENGINE_LIMITER_RPM = 7000.0      # rpm del corte de inyección
ENGINE_BRAKE_COEFF = 45.0        # Nm de freno motor a régimen máximo
                                 # [20 .. 90]
GEAR_RATIOS = [3.62, 2.19, 1.51, 1.17, 0.95, 0.81]  # desarrollos 1a..6a
FINAL_DRIVE = 3.70               # relación del grupo final [3.0 .. 4.5]
REVERSE_RATIO = 3.40             # relación de la marcha atrás
DRIVELINE_EFF = 0.90             # rendimiento de la transmisión [0.85 .. 0.95]

# ===========================================================================
# NEUMÁTICOS
# ===========================================================================
TIRE_MU = 1.05               # agarre en asfalto seco; 0.7 simula lluvia
                             # [0.5 .. 1.4]
TIRE_MU_GRASS = 0.80         # agarre en hierba; alto = salidas de pista
                             # recuperables [0.3 .. 0.9]
TIRE_B = 2.07                # rigidez de la curva combinada (pico en rho=1)
TIRE_C = 1.4                 # forma de la curva: pasado el pico el agarre
                             # cae a sin(C*pi/2) (~81 % con 1.4) [1.2 .. 1.6]
TIRE_PEAK_SLIP_ANGLE_DEG = 7.0   # deriva del pico de agarre lateral
                                 # [5 .. 10]
TIRE_PEAK_SLIP_RATIO = 0.12      # deslizamiento longitudinal del pico
                                 # [0.08 .. 0.18]
TIRE_LOAD_SENS = 0.10        # caída de mu por unidad de sobrecarga sobre
                             # la carga estática de esa rueda; hace que
                             # transferir peso reste agarre [0 .. 0.2]
TIRE_LONG_GRIP_RATIO = 1.10  # elipse de fricción: capacidad longitudinal
                             # extra respecto a la lateral [1.0 .. 1.2]
TIRE_RELAX_LENGTH = 0.6      # m, retardo de respuesta lateral de la
                             # carcasa [0.3 .. 1.2]
TIRE_REAR_GRIP_FACTOR = 1.04 # agarre relativo del eje trasero: >1 subvira
                             # en el límite (estable), <1 sobrevira (drift)
                             # [0.90 .. 1.15]
TIRE_TRAIL = 0.045           # m, avance neumático+mecánico: escala del par
                             # de autoalineado del volante [0.02 .. 0.08]
TIRE_TRAIL_SAT_DEG = 7.0     # deriva a la que el avance cae (el volante se
                             # aligera al saturar) [5 .. 10]

# ===========================================================================
# SUSPENSIÓN (por rueda)
#
# Frecuencia propia ~1.6 Hz con los valores por defecto (tarado deportivo).
# Muelles más duros = reacciones más rápidas y menos balanceo.
# ===========================================================================
SUSP_SPRING_FRONT = 32000.0  # N/m por rueda delantera [15000 .. 60000]
SUSP_SPRING_REAR = 26000.0   # N/m por rueda trasera [15000 .. 60000]
SUSP_DAMPER = 4300.0         # N·s/m por rueda [2000 .. 8000]
ARB_FRONT = 23000.0          # estabilizadora delantera (N/m de diferencia
                             # entre lados). MÁS dura delante = más
                             # subviraje [0 .. 40000]
ARB_REAR = 14000.0           # estabilizadora trasera; subirla acerca el
                             # coche al sobreviraje [0 .. 40000]

# ===========================================================================
# AERODINÁMICA Y RESISTENCIAS
# ===========================================================================
AERO_DRAG = 0.38             # N/(m/s)², resistencia al avance (0.5*rho*Cd*A)
                             # [0.25 .. 0.6]
AERO_DOWNFORCE = 0.55        # N/(m/s)², carga aerodinámica total (~1700 N a
                             # 200 km/h); 0 = turismo sin apéndices, 3+ =
                             # fórmula [0 .. 5]
AERO_DF_FRONT_SHARE = 0.42   # fracción de la carga aero al eje delantero;
                             # subirla da más mordiente a alta velocidad
                             # [0.3 .. 0.55]
ROLLING_RESIST = 210.0       # N, resistencia a la rodadura [100 .. 400]

# ===========================================================================
# FRENOS
# ===========================================================================
BRAKE_FORCE_MAX = 15000.0    # N con el pedal a fondo; por encima del agarre
                             # (~14100 N con la elipse) para poder bloquear
                             # en un pisotón; bajarlo da más recorrido útil
                             # de pedal [10000 .. 20000]
BRAKE_BIAS_FRONT = 0.72      # reparto de frenada al eje delantero; acorde a
                             # la carga dinámica en frenada fuerte. Menos =
                             # riesgo de trompo frenando [0.55 .. 0.80]
ABS_ENABLED = True           # False = frenada sin ayudas (bloqueos reales)
ABS_SLIP_TARGET = 0.14       # deslizamiento al que actúa el ABS [0.10 .. 0.20]

# ===========================================================================
# CIRCUITO / CARRETERA
# ===========================================================================
# Circuito a cargar: "" = circuito de pruebas integrado (con colinas), o un
# circuito real importado: "tracks/silverstone.csv" | "tracks/spa.csv"
# (eje central real del racetrack-database de la TU München; sin altimetría).
# Importa más con: python tools/import_track.py <in.csv> simulator/tracks/<out>.csv
TRACK_FILE = "tracks/silverstone.csv"
ROAD_HALF_WIDTH = 5.4        # m, semiancho del asfalto [3.5 .. 8]
KERB_WIDTH = 1.1             # m de piano a cada lado [0.5 .. 2]
SEGMENT_LENGTH = 4.0         # m por segmento (no cambiar si se usan
                             # circuitos importados)
DRAW_DISTANCE = 220          # segmentos dibujados; bajar si va lento
                             # [100 .. 400]
CAMERA_HEIGHT = 1.55         # m, altura de la cámara en las vistas bajas
                             # [1.1 .. 2.5]
CAMERA_DEPTH = 0.84          # proyección (1/tan(fov/2)); subir = teleobjetivo
CAMERA_YAW_GAIN = 1.6        # cuánto sigue la cámara el rumbo del coche
                             # respecto a la carretera: 1.0 = geométrico
                             # exacto, más alto = giro de vista más
                             # perceptible al derrapar o girar [1.0 .. 2.5]
RACING_LINE = True           # trazada ideal (tecla L): verde = margen,
                             # ámbar = al límite, rojo = no llegas a frenar
TRACK_POLES = True           # balizas de colores en los bordes (amarillo =
                             # izquierda, azul = derecha)
CAR_BODY_MOTION_EXAG = 3.0   # exageración visual del cabeceo/balanceo de la
                             # carrocería en pantalla; 1 = real [1 .. 5]

# ===========================================================================
# SONIDO
# ===========================================================================
AUDIO_ENABLED = True
AUDIO_RATE = 22050           # Hz de muestreo
AUDIO_VOLUME = 0.5           # volumen general [0 .. 1]
SCREECH_VOLUME = 0.8         # volumen del chirrido de neumáticos [0 .. 1]
