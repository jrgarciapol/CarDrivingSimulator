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
PHYSICS_HZ = 240  # frecuencia del paso de física (sub-pasos por frame)

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
CAR_INERTIA_PITCH = 2100.0   # kg·m² (cabeceo)
CAR_INERTIA_ROLL = 550.0     # kg·m² (balanceo)
CAR_CG_TO_FRONT = 1.18       # m, del centro de gravedad al eje delantero
CAR_CG_TO_REAR = 1.42        # m, al eje trasero
CAR_CG_HEIGHT = 0.52         # m
CAR_TRACK_WIDTH = 1.55       # m, vía (distancia entre ruedas izda/dcha)
CAR_WHEEL_RADIUS = 0.31      # m
CAR_WHEEL_INERTIA = 1.4      # kg·m² por rueda
STEER_RATIO = 12.0           # relación de dirección volante:rueda

# --- Transmisión / tracción ---
DRIVE_TYPE = "RWD"           # "RWD" propulsión | "FWD" delantera | "AWD" total
AWD_FRONT_SPLIT = 0.40       # reparto de par al eje delantero en AWD (0..1)
DIFF_TYPE = "lsd"            # "open" abierto | "lsd" autoblocante | "locked"
DIFF_LSD_COEFF = 18.0        # Nm·s/rad de acoplamiento viscoso del LSD

# --- Neumáticos ---
TIRE_MU = 1.05               # coeficiente de fricción en asfalto
TIRE_MU_GRASS = 0.45         # en hierba
TIRE_B = 2.07                # rigidez de la curva combinada (pico en rho=1)
TIRE_C = 1.4                 # forma (caída a ~81 % del pico al deslizar)
TIRE_PEAK_SLIP_ANGLE_DEG = 7.0   # deriva del pico de agarre lateral
TIRE_PEAK_SLIP_RATIO = 0.12      # deslizamiento longitudinal del pico
TIRE_LOAD_SENS = 0.10        # caída de mu por unidad de sobrecarga relativa
TIRE_RELAX_LENGTH = 0.6      # m, retardo de respuesta lateral del neumático
TIRE_REAR_GRIP_FACTOR = 1.04 # agarre extra del eje trasero (subviraje base;
                             # <1.0 haría el coche sobrevirador)
TIRE_TRAIL = 0.045           # avance neumático+mecánico (m) para el par
TIRE_TRAIL_SAT_DEG = 7.0     # ángulo de deriva al que el avance cae

# --- Suspensión (por rueda) ---
SUSP_SPRING_FRONT = 27000.0  # N/m por rueda delantera
SUSP_SPRING_REAR = 22000.0   # N/m por rueda trasera
SUSP_DAMPER = 3800.0         # N·s/m por rueda
ARB_FRONT = 26000.0          # estabilizadora delantera (N/m de diferencia)
ARB_REAR = 14000.0           # estabilizadora trasera (más rígida delante
                             # -> más transferencia delante -> subviraje)

# --- Frenos ---
AERO_DRAG = 0.38             # 0.5*rho*Cd*A
ROLLING_RESIST = 210.0       # N constantes
BRAKE_FORCE_MAX = 16000.0    # N equivalentes con el pedal a fondo (supera
                             # el agarre: sin ABS las ruedas se bloquean)
BRAKE_BIAS_FRONT = 0.62
ABS_ENABLED = True           # antibloqueo de frenos
ABS_SLIP_TARGET = 0.14       # deslizamiento a partir del cual actúa

# --- Motor / caja ---
ENGINE_IDLE_RPM = 900.0
ENGINE_REDLINE_RPM = 6800.0
ENGINE_LIMITER_RPM = 7000.0
ENGINE_BRAKE_COEFF = 45.0    # Nm de freno motor a régimen máximo
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
