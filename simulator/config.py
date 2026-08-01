"""Configuración del simulador.

Todos los valores ajustables están aquí: mapeo del volante/pedales,
intensidad del force feedback y parámetros físicos del coche.
"""

# ---------------------------------------------------------------------------
# Ventana
# ---------------------------------------------------------------------------
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
WINDOW_TITLE = b"Car Driving Simulator - Thrustmaster"
TARGET_FPS = 60
PHYSICS_HZ = 120  # frecuencia del paso de física (sub-pasos por frame)

# ---------------------------------------------------------------------------
# Volante y pedales (mapeo DirectInput/SDL)
#
# Si tu volante usa otros ejes/botones, pulsa F1 dentro del simulador para
# ver en pantalla los valores en crudo de cada eje y el número de cada botón,
# y ajusta estos índices.
# ---------------------------------------------------------------------------
# Subcadenas para elegir el dispositivo si hay varios conectados
WHEEL_NAME_HINTS = ("thrustmaster", "t300", "t150", "tmx", "t248", "tx", "t-gt")

AXIS_STEERING = 0        # eje de dirección
AXIS_THROTTLE = 1        # acelerador
AXIS_BRAKE = 2           # freno
AXIS_CLUTCH = 3          # embrague (si no existe, se ignora)

# Los pedales Thrustmaster reposan en +32767 y bajan al pisar.
# Si tu acelerador funciona al revés, cambia esto a False.
PEDALS_INVERTED = True

# Grados de giro configurados en el panel de control de Thrustmaster.
# Recomendado: 900. Debe coincidir para que la relación de dirección sea real.
WHEEL_ROTATION_DEG = 900.0

BUTTON_SHIFT_UP = 4      # leva derecha (subir marcha)
BUTTON_SHIFT_DOWN = 5    # leva izquierda (bajar marcha)
BUTTON_RESET = 8         # recolocar el coche en pista

STEERING_DEADZONE = 0.005

# ---------------------------------------------------------------------------
# Force feedback
# ---------------------------------------------------------------------------
FFB_ENABLED = True
FFB_GAIN = 0.9           # ganancia global 0..1 del par de autoalineado
FFB_INVERT = False       # invierte el sentido de la fuerza si "empuja" hacia
                         # fuera de la curva en lugar de centrar el volante
FFB_MAX_TORQUE_NM = 45.0 # par de columna que equivale al 100 % de fuerza

FFB_SPRING_LOWSPEED = 0.35   # muelle de centrado al aparcar (0..1)
FFB_DAMPER_LOWSPEED = 0.55   # amortiguación a baja velocidad (0..1)
FFB_DAMPER_HIGHSPEED = 0.08  # amortiguación residual en marcha (0..1)

FFB_ROAD_TEXTURE = 0.05      # vibración fina del asfalto (0..1)
FFB_KERB_MAGNITUDE = 0.45    # vibración al pisar pianos (0..1)
FFB_GRASS_MAGNITUDE = 0.35   # vibración sobre hierba (0..1)
FFB_ENGINE_IDLE = 0.06       # vibración del motor al ralentí (0..1)
FFB_SHIFT_JOLT = 0.35        # sacudida al cambiar de marcha (0..1)

# ---------------------------------------------------------------------------
# Física del vehículo (valores tipo turismo deportivo, unidades SI)
# ---------------------------------------------------------------------------
CAR_MASS = 1250.0            # kg
CAR_INERTIA_Z = 1900.0       # kg·m² (guiñada)
CAR_CG_TO_FRONT = 1.18       # m, del centro de gravedad al eje delantero
CAR_CG_TO_REAR = 1.42        # m, al eje trasero
CAR_CG_HEIGHT = 0.52         # m
CAR_WHEEL_RADIUS = 0.31      # m
STEER_RATIO = 12.0           # relación de dirección volante:rueda

TIRE_MU = 1.05               # coeficiente de fricción en asfalto
TIRE_MU_GRASS = 0.45         # en hierba
TIRE_B = 14.0                # rigidez Pacejka simplificada (pico ~7 deg)
TIRE_C = 1.5                 # forma Pacejka
TIRE_REAR_GRIP_FACTOR = 1.10 # agarre extra del eje trasero: el coche
                             # subvira en el límite (estable), como un
                             # turismo real. <1.0 lo haría sobrevirador.
TIRE_TRAIL = 0.045           # avance neumático+mecánico (m) para el par
TIRE_TRAIL_SAT_DEG = 7.0     # ángulo de deriva al que el avance cae a cero

AERO_DRAG = 0.38             # 0.5*rho*Cd*A
ROLLING_RESIST = 210.0       # N constantes
BRAKE_FORCE_MAX = 11500.0    # N con el pedal a fondo
BRAKE_BIAS_FRONT = 0.62

ENGINE_IDLE_RPM = 900.0
ENGINE_REDLINE_RPM = 6800.0
ENGINE_LIMITER_RPM = 7000.0
GEAR_RATIOS = [3.62, 2.19, 1.51, 1.17, 0.95, 0.81]
FINAL_DRIVE = 3.70
REVERSE_RATIO = 3.40
DRIVELINE_EFF = 0.90

# ---------------------------------------------------------------------------
# Circuito / carretera
# ---------------------------------------------------------------------------
ROAD_HALF_WIDTH = 4.6        # m (ancho total ~9.2 m)
KERB_WIDTH = 1.1             # m de piano a cada lado
SEGMENT_LENGTH = 4.0         # m por segmento de render
DRAW_DISTANCE = 220          # segmentos dibujados
CAMERA_HEIGHT = 1.35         # m
CAMERA_DEPTH = 0.84          # 1/tan(fov/2)

# ---------------------------------------------------------------------------
# Sonido
# ---------------------------------------------------------------------------
AUDIO_ENABLED = True
AUDIO_RATE = 22050
AUDIO_VOLUME = 0.5
