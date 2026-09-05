"""Configuración del simulador.

Todos los ajustes del juego están en este archivo, agrupados por secciones.
Cada parámetro indica sus unidades, su efecto y el rango razonable entre
paréntesis [mín .. máx]. Tras editar, basta reiniciar el simulador.
"""

# Versión del simulador: se muestra en pantalla (esquina inferior) y en la
# consola al arrancar, para comprobar qué copia estás ejecutando.
VERSION = "v3.2"

# ===========================================================================
# VENTANA Y BUCLE
# ===========================================================================
WINDOW_WIDTH = 1920          # px, ancho de la ventana [800 .. 1920]
WINDOW_HEIGHT = 1080         # px, alto de la ventana [600 .. 1080]
WINDOW_AUTO = True           # ajustar la ventana a la pantalla al arrancar.
                             # Imprescindible en portátiles: una Steam Deck
                             # es de 1280x800 y una ventana de 1920x1080 se
                             # sale. Poner False para forzar los valores de
                             # arriba
WINDOW_FULLSCREEN = False    # pantalla completa (sin bordes) al arrancar
WINDOW_TITLE = b"Car Driving Simulator - Thrustmaster"
TARGET_FPS = 60              # objetivo de imágenes por segundo (informativo)
PHYSICS_HZ = 480             # Hz del paso de física; más alto = más precisa
                             # y más CPU [120 .. 960]

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
BUTTON_MENU = 6          # VOLVER AL MENU (como ESC). Sin esto, con volante
                         # no habia forma de salir de la partida. Si en tu
                         # volante ese numero no es el que quieres, mira cual
                         # es con  ./jugar.sh --ejes  (muestra los botones
                         # pulsados) y cambialo aqui o en AJUSTES
BUTTON_TELEMETRY = 4     # telemetria F2 (circulos de friccion)
BUTTON_PLAN = 5          # planta del tramo que viene (tecla N)
BUTTON_MINIMAP = 7       # plano del circuito completo (tecla M)
BUTTON_LINE = 11         # trazada ideal (tecla L)
BUTTON_SLOWMO = 10       # cámara lenta (tecla T): cicla las velocidades
                         # de TIME_SCALES para estudiar el comportamiento

TIME_SCALES = (1.0, 0.5, 0.25, 0.1)   # velocidades de la cámara lenta

STEERING_DEADZONE = 0.005    # zona muerta del volante [0 .. 0.05]

# Cómo se lee la entrada. "auto" detecta solo (volante reconocido > mando >
# teclado). Los otros valores FUERZAN el modo, por si la deteccion falla:
# en una Steam Deck lanzada fuera de Steam, el mando NO se anuncia como
# gamepad y "auto" lo confunde con un volante (stick haciendo de direccion,
# pedales invertidos). La solucion buena es lanzar desde Steam (Steam Input
# lo convierte en un mando de Xbox); "mando" aqui es el plan B.
# Valores: "auto" | "mando" | "volante" | "teclado".
# Tambien por linea de comandos: --mando / --volante / --teclado
INPUT_MODE = "auto"

# ---------------------------------------------------------------------------
# MANDO (Steam Deck, XBox, PlayStation...)
#
# Un stick no es un volante: va de tope a tope en dos centímetros y vuelve
# al centro de golpe. Sin estas correcciones el coche es incontrolable a
# velocidad. Solo se aplican cuando NO hay volante conectado.
# ---------------------------------------------------------------------------
PAD_DEADZONE = 0.12          # zona muerta del stick; se reescala lo que
                             # queda para no perder recorrido [0 .. 0.35]
PAD_STEER_EXPO = 0.60        # curva progresiva: 0 = lineal (nervioso),
                             # 1 = muy suave en el centro. Permite hilar
                             # fino en recta sin perder tope [0 .. 1]
PAD_STEER_MAX = 1.00         # fracción del tope de dirección disponible a
                             # baja velocidad (maniobras) [0.3 .. 1]
PAD_STEER_MAX_FAST = 0.30    # ...y a alta velocidad: pedir el mismo ángulo
                             # a 200 km/h que aparcando hace trompear al
                             # menor toque [0.1 .. 0.8]
PAD_STEER_FAST_KMH = 170.0   # velocidad a la que se alcanza ese límite
                             # [80 .. 300]
PAD_STEER_RATE = 3.0         # 1/s, velocidad máxima de giro del volante:
                             # tampoco tus brazos van de tope a tope al
                             # instante [1 .. 10]
PAD_RUMBLE = 0.9             # ganancia de la vibración (sustituye al par
                             # del volante, que un mando no puede dar).
                             # 0 la desactiva [0 .. 1]
PAD_RUMBLE_SLIP = 1.4        # cuánta vibración por unidad de derrape: es el
                             # aviso de que un eje se está yendo, el
                             # equivalente al aligeramiento del volante
                             # [0 .. 3]

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
FFB_GAIN = 0.8           # ganancia global del par [0 .. 1]

# DESACTIVADO A PROPOSITO. Vía experimental: mandar la fuerza al T300RS como
# informes HID de salida por /dev/hidraw, sin driver de kernel (ver
# simulator/ffb_t300rs.py). Se probó en una Steam Deck y el volante NO se
# movió: se le apagó el LED y hubo que recuperarlo. El protocolo está copiado
# del driver hid-tmff2, pero hay un dato que NO se puede deducir sin el
# aparato delante: el identificador del informe de salida. hid-tmff2 reescribe
# el descriptor del volante para usar el 0x60, y no está claro si el que
# declara el volante de fábrica es el que hay que poner en el cable. Escribir
# con el identificador equivocado es lo que probablemente lo dejó colgado.
# No se activa hasta que esté resuelto, y aun entonces solo a mano.
FFB_HIDRAW_EXPERIMENTAL = False
FFB_INVERT = False       # True si el volante empuja hacia FUERA de la
                         # curva en vez de autocentrarse
FFB_MAX_TORQUE_NM = 66.0 # Nm de columna que saturan el volante; BAJARLO
                         # endurece el volante en apoyo y hace más evidente
                         # el aligeramiento al subvirar. Subido de 35 a 66 al
                         # separar el avance mecánico del neumático: la física
                         # entrega ahora ~88 % más par de columna (el avance
                         # mecánico real es mucho mayor que el 15 % que se
                         # suponía), así que el volante se sentiría igual de
                         # duro pero saturado casi siempre. Calibrado
                         # para que pico/umbral quede en 0.73, igual
                         # que antes del cambio [20 .. 90]
FFB_COLUMN_DAMPING = 1.3 # Nm por rad/s de giro del volante; amortigua las
                         # oscilaciones autoexcitadas en recta (se escala
                         # además con la velocidad) [0 .. 4]
FFB_SMOOTHING_S = 0.02   # s, suavizado del par enviado al volante; sube a
                         # 0.04-0.08 si el volante da bandazos en recta,
                         # baja a 0.01 si lo notas "gomoso" [0 .. 0.1]
                         # (con el sentido del FFB corregido en v2.7 basta
                         # muy poco suavizado: mas detalle del asfalto)
FFB_KICK_GAIN = 0.0015   # sacudida por baches asimétricos delanteros, en
                         # Nm por N de diferencia de carga; 0 la elimina
                         # [0 .. 0.005]
FFB_SPRING_LOWSPEED = 0.35   # muelle de centrado al aparcar [0 .. 1]
FFB_DAMPER_LOWSPEED = 0.55   # pesadez del volante parado [0 .. 1]
FFB_DAMPER_HIGHSPEED = 0.15  # amortiguación residual en marcha (efecto
                             # damper del firmware del volante): evita que
                             # el volante oscile al soltarlo en recta; con
                             # el FFB corregido basta la mitad que antes:
                             # volante mas vivo. Sube si se agita [0 .. 0.5]
FFB_ROAD_TEXTURE = 0.05      # vibración fina del asfalto [0 .. 0.3]
FFB_KERB_MAGNITUDE = 0.45    # vibración al pisar pianos [0 .. 1]
FFB_GRASS_MAGNITUDE = 0.35   # vibración sobre hierba [0 .. 1]
FFB_ENGINE_IDLE = 0.06       # vibración del motor al ralentí [0 .. 0.3]
FFB_SHIFT_JOLT = 0.35        # sacudida al cambiar de marcha [0 .. 1]

# ===========================================================================
# VEHÍCULO — masas y geometría (ficha técnica)
# ===========================================================================
CAR_COLOR = (178, 24, 30)    # color RGB de la carrocería en pantalla
CAR_MASS = 1250.0            # kg, masa total [800 .. 2500]
CAR_INERTIA_Z = 1900.0       # kg·m², inercia de guiñada; más alta = coche
                             # más "perezoso" al girar [1200 .. 4000]
CAR_INERTIA_PITCH = 2100.0   # kg·m², inercia de cabeceo [1500 .. 4500]
CAR_INERTIA_ROLL = 550.0     # kg·m², inercia de balanceo [350 .. 1200]
CHASSIS_TORSION_STIFF = 20000.0  # N·m/°, rigidez torsional del bastidor.
                             # Turismo 10-25k, GT3 ~40k, monocasco 60k+,
                             # chasis de largueros ~7k. Un chasis blando
                             # desacopla los ejes: el reparto de transferencia
                             # se acerca al de los momentos y las barras
                             # estabilizadoras pierden autoridad (cambia el
                             # BALANCE sub/sobrevirador). 0 = rígido ideal
                             # (comportamiento sin torsión). [0 .. 80000]
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
CASTER_ANGLE_DEG = 4.5       # grados, ANGULO DE AVANCE (caster): inclinación
                             # hacia atrás del eje de dirección. De él sale el
                             # avance MECANICO (t = R·tan(caster)), el efecto
                             # "carrito de la compra" que endereza el volante
                             # solo. Más avance = volante más pesado, más
                             # estable en recta y más caída negativa ganada al
                             # girar. Turismo 2-6, deportivo 5-8, fórmula
                             # 10-14 [0 .. 14]
STEER_TRAIL_OFFSET = 0.0     # m, desplazamiento longitudinal del eje de
                             # dirección respecto al centro de rueda. Permite
                             # ajustar el avance mecánico SIN tocar el caster
                             # (y con él, la caída ganada). Los fórmula lo usan
                             # NEGATIVO: mucho caster para ganar caída,
                             # pero el eje retrasado para que el volante
                             # no sea imposible [-0.05 .. 0.03]
TOE_FRONT_DEG = 0.05         # grados de CONVERGENCIA estática por rueda del
                             # eje delantero. POSITIVA = las ruedas apuntan
                             # hacia dentro (convergen). Convergencia da
                             # estabilidad en recta; DIVERGENCIA (negativa)
                             # afila la entrada en curva porque la rueda
                             # exterior ya llega girada. Siempre cuesta
                             # arrastre y desgaste: las dos ruedas tiran una
                             # contra otra. Turismo +0.05, circuito -0.1 a
                             # -0.3 [-0.5 .. 0.5]
TOE_REAR_DEG = 0.15          # ídem eje trasero. Casi siempre CONVERGENTE y
                             # más que el delantero: es lo que evita que la
                             # cola se mueva sola al levantar el pie
                             # [-0.3 .. 0.5]
CASTER_CAMBER_GAIN = 1.0     # cuánta de la caída por caster llega a la rueda
                             # (1 = geometría ideal, 0 = desactivado). Bajarlo
                             # simula una geometría que la desperdicia [0 .. 1.5]
STATIC_CAMBER_FRONT_DEG = -1.0   # grados de CAIDA ESTATICA del eje delantero,
                             # la del reglaje de alineación. NEGATIVA = la
                             # rueda abraza al coche por arriba. Se pone para
                             # que la rueda EXTERIOR quede plana cuando la
                             # carrocería se tumbe en curva: más agarre en
                             # apoyo, a cambio de menos en recta y de
                             # desgastar el hombro interior. Turismo -0.5,
                             # deportivo -1.5, circuito -3 a -4 [-5 .. 1]
STATIC_CAMBER_REAR_DEG = -1.2    # ídem eje trasero; suele ser algo MENOS
                             # negativa que la delantera porque el eje
                             # trasero balancea menos y necesita tracción
                             # [-5 .. 1]

# Derivados de la geometría (no editar: se calculan del reparto)
CAR_CG_TO_FRONT = WHEELBASE * (1.0 - WEIGHT_DIST_FRONT)
CAR_CG_TO_REAR = WHEELBASE * WEIGHT_DIST_FRONT

# ===========================================================================
# TRANSMISIÓN Y TRACCIÓN
# ===========================================================================
DRIVE_TYPE = "RWD"           # TRACCION {RWD | FWD | AWD}: "RWD" propulsión
                             # trasera | "FWD" delantera | "AWD" total
AWD_FRONT_SPLIT = 0.40       # en AWD, fracción del par al eje delantero
                             # [0.2 .. 0.6]
DIFF_TYPE = "lsd"            # diferencial {open | lsd | locked | viscous}:
                             #   "open"    abierto (pierde tracción por la
                             #             rueda interior descargada)
                             #   "lsd"     autoblocante de DISCOS con rampas
                             #             y precarga (el de los deportivos
                             #             y los coches de competición)
                             #   "viscous" acoplamiento viscoso, sensible a
                             #             la DIFERENCIA DE VELOCIDAD y no
                             #             al par: reacciona DESPUES de que
                             #             la rueda patine (tipo Ferguson)
                             #   "locked"  bloqueado
# --- autoblocante de discos ("lsd") ---------------------------------------
# El paquete de embragues se aprieta por dos vías, y de ahí salen los tres
# parámetros. Un LSD real es SENSIBLE AL PAR: bloquea en cuanto pasa par,
# antes de que la rueda llegue a patinar.
DIFF_PRELOAD = 60.0          # N·m de bloqueo que hay SIEMPRE, aunque no se
                             # pise nada: lo dan unos muelles Belleville que
                             # aprietan los discos. Manda en el punto de
                             # inflexión de la curva, con el coche soltado.
                             # Subirlo hace el coche más estable y más
                             # perezoso al girar [0 .. 200]
DIFF_RAMP_POWER = 0.45       # fracción del par que se convierte en bloqueo
                             # ACELERANDO. Alto = tracción a la salida, pero
                             # subvira al abrir gas [0 .. 0.9]
DIFF_RAMP_COAST = 0.20       # ídem RETENIENDO (pie levantado o frenando con
                             # marcha metida). Suele ser bastante menor: un
                             # bloqueo alto en retención deja el coche
                             # estable pero perezoso para entrar en curva
                             # [0 .. 0.9]
DIFF_LOCK_BAND = 0.5         # rad/s de diferencia de giro en que el bloqueo
                             # pasa de cero a su tope. Es la anchura de la
                             # transición del rozamiento seco de los discos;
                             # bajarlo lo hace más brusco [0.1 .. 2.0]
DIFF_LSD_COEFF = 18.0        # Nm·s/rad, solo para DIFF_TYPE = "viscous"
                             # [5 .. 40]
DIFF_MAX_LOCK = 500.0        # N·m, TOPE de par que el autoblocante (lsd) es
                             # capaz de transferir de una rueda a la otra: la
                             # capacidad de los discos. Con mucho par de eje el
                             # bloqueo no crece sin fin, satura aquí. Alto = casi
                             # como bloqueado a plena carga [100 .. 2000]

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
ENGINE_INERTIA = 0.15            # kg·m², inercia rotacional del motor y
                                 # volante: multiplicada por el desarrollo
                                 # al cuadrado, hace que acelerar/retener
                                 # en 1a cueste más que en 6a [0.05 .. 3]
ENGINE_MODEL = "legacy"          # opciones {legacy | inertia}.
                                 # "legacy": el régimen sigue a las ruedas con
                                 # un filtro de 0.12 s. "inertia": el cigüeñal
                                 # es un grado de libertad propio (I·dw/dt =
                                 # combustión − freno motor − embrague) con un
                                 # embrague de verdad; emergen el acelerón en
                                 # punto muerto, el patinaje del embrague en la
                                 # salida y un régimen que ya no va pegado a
                                 # las ruedas. Solo afecta si vale "inertia".
CLUTCH_CAPACITY = 400.0          # Nm, par mínimo que el embrague transmite;
                                 # el efectivo es al menos 1.5 veces el par
                                 # máximo del motor (un embrague se dimensiona
                                 # con su motor) [200 .. 800]
CLUTCH_STIFFNESS = 60.0          # Nm por rad/s de deslizamiento: rigidez del
                                 # acoplamiento. Alto = engrana firme (poco
                                 # deslizamiento en régimen) [20 .. 120]
CLUTCH_LOCK_RPM = 1200.0         # rpm de rueda-equivalente por encima del
                                 # cual el embrague queda del todo engranado
                                 # [800 .. 2000]
GEAR_RATIOS = [3.62, 2.19, 1.51, 1.17, 0.95, 0.81]  # desarrollos 1a..6a
SHIFT_CUT_TIME = 0.10            # s que dura el CORTE DE PAR en cada cambio de
                                 # marcha: durante ese instante el par a las
                                 # ruedas cae casi a cero (embrague/inyección),
                                 # dando el tirón real del cambio. 0 = cambio
                                 # instantáneo sin corte [0 .. 0.3]
FINAL_DRIVE = 3.70               # relación del grupo final [3.0 .. 4.5]
GEARING_KEEP_ON_WHEEL_CHANGE = True  # al calzar otra rueda, reescalar el
                                 # grupo final para CONSERVAR el desarrollo
                                 # (lo que haría un ingeniero al recalzar).
                                 # Desactívalo para notar el efecto puro del
                                 # cambio de radio sobre el desarrollo.
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
TIRE_MODEL = "legacy"        # opciones {legacy | brush}.
                             # "legacy": longitudinal y lateral comparten la
                             # MISMA forma de curva (B, C de arriba); solo
                             # cambia la escala de la elipse. "brush": cada eje
                             # tiene SU propia curva (los cuatro parametros de
                             # abajo) y la forma se interpola segun la
                             # direccion del deslizamiento. Solo afecta si vale
                             # "brush". Legacy = poner los pares long=lat.
TIRE_B_LONG = 2.40           # rigidez LONGITUDINAL (brush): mas alta = el pico
                             # de traccion/frenada llega antes y mas marcado
                             # [1.5 .. 3.5]
TIRE_C_LONG = 1.50           # forma LONGITUDINAL (brush): mas alta = la rueda
                             # bloqueada/patinando pierde mas agarre [1.2 .. 1.8]
TIRE_B_LAT = 1.90            # rigidez LATERAL (brush): mas baja = entrada en
                             # curva mas progresiva y avisada [1.5 .. 3.0]
TIRE_C_LAT = 1.35            # forma LATERAL (brush): baja = el agarre lateral
                             # cae poco al pasar el pico -> derrapes mas
                             # controlables [1.2 .. 1.6]
TIRE_PEAK_SLIP_ANGLE_DEG = 7.0   # deriva del pico de agarre lateral
                                 # [5 .. 10]
TIRE_PEAK_SLIP_RATIO = 0.12      # deslizamiento longitudinal del pico
                                 # [0.08 .. 0.18]
TIRE_LOAD_SENS = 0.10        # caída de mu por unidad de sobrecarga sobre
                             # la carga estática de esa rueda; hace que
                             # transferir peso reste agarre [0 .. 0.2]
TIRE_WIDTH_MM = 205.0        # mm, ancho del neumático (lo fija el
                             # WHEEL_SPEC del coche). Más ancho = más huella:
                             # algo más de mu, menos caída por sobrecarga y
                             # calentamiento más lento [125 .. 445]
GYRO_GAIN = 1.0              # precesión giroscópica de las ruedas: al girar,
                             # su momento angular genera un par de balanceo
                             # (1 = físico exacto, 0 = desactivado). En coche
                             # es sutil; en moto sería dominante [0 .. 3]
GYRO_FFB_GAIN = 1.0          # reacción giroscópica que llega al volante al
                             # balancear (peso vivo en cambios de apoyo
                             # rápidos a alta velocidad) [0 .. 3]
TIRE_LONG_GRIP_RATIO = 1.10  # elipse de fricción: capacidad longitudinal
                             # extra respecto a la lateral [1.0 .. 1.2]
TIRE_RELAX_LENGTH = 0.3      # m, retardo de respuesta lateral de la
                             # carcasa [0.3 .. 1.2]
TIRE_REAR_GRIP_FACTOR = 1.04 # agarre relativo del eje trasero: >1 subvira
                             # en el límite (estable), <1 sobrevira (drift)
                             # [0.90 .. 1.15]
TIRE_TRAIL = 0.030           # m, AVANCE NEUMATICO con deriva cero: brazo de
                             # palanca que nace de la DEFORMACION de la huella
                             # (la resultante queda retrasada). Se derrumba con
                             # la deriva. El avance MECANICO es aparte y sale
                             # del CASTER_ANGLE_DEG [0.01 .. 0.05]
TIRE_TRAIL_SAT_DEG = 7.0     # deriva a la que el avance NEUMATICO se anula
                             # (el volante se aligera al saturar) [5 .. 10]
TIRE_TRAIL_NEG_FRAC = 0.18   # cuánto llega a hacerse NEGATIVO el avance
                             # neumático pasado el pico, en fracción del
                             # valor a deriva cero. Acentúa el aviso de
                             # subviraje en el volante [0 .. 0.4]
TIRE_CAMBER_PATCH = 18.0     # pérdida de agarre por radián CUADRADO de
                             # inclinación contra el asfalto: la rueda tumbada
                             # no apoya plana, la carga se concentra en un
                             # hombro y la huella efectiva se reduce. Es
                             # CUADRATICA (1 grado no se nota, 5 arruinan):
                             # 1 deg -> 0.5 %, 2 -> 2 %, 3 -> 5 %, 5 -> 14 %.
                             # Cuadrática frente al empuje por caída, que es
                             # lineal: de ese contraste sale el ÓPTIMO de
                             # reglaje (~1 grado en la rueda cargada).
                             # 0 = desactivado [0 .. 50]
TIRE_CAMBER_HEAT = 3.0       # calentamiento extra por radián de inclinación:
                             # el hombro cargado trabaja más y sube de
                             # temperatura antes (desgaste asimétrico)
                             # [0 .. 8]
TIRE_CAMBER_THRUST = 0.6     # empuje por caída: fuerza lateral por radián
                             # de inclinación de la rueda (fracción de la
                             # carga). Al tumbarse la carrocería en curva
                             # las ruedas se inclinan hacia FUERA y restan
                             # agarre: castiga a los coches altos y blandos
                             # (autobús) y apenas a los rígidos [0 .. 1.2]
TIRE_VERT_STIFF = 250000.0   # N/m, rigidez vertical del neumático (el
                             # muelle entre asfalto y llanta); con la masa
                             # no suspendida define la frecuencia de rebote
                             # de la rueda (~14 Hz) [150000 .. 2500000]
TIRE_VERT_DAMP = 900.0       # N·s/m, amortiguación interna de la goma:
                             # sin ella la rueda rebotaría sin fin
                             # [300 .. 8000]
UNSPRUNG_MASS = 35.0         # kg de masa no suspendida por rueda (llanta +
                             # neumático + mangueta + frenos): sobre pianos
                             # agresivos la rueda "vuela" y pierde carga
                             # [18 .. 350]

# --- termodinámica del neumático -------------------------------------------
TIRE_TEMP_AMB = 25.0         # C, temperatura ambiente (y de equilibrio en
                             # parado) [5 .. 40]
TIRE_TEMP_OPT = 90.0         # C, temperatura de maximo agarre [80 .. 100]
TIRE_TEMP_SENS = 5.5e-5      # perdida de agarre por (grado de desvio)^2:
                             # con 5.5e-5, la goma fria a 25 C rinde ~77 %
                             # y a 60 C ~95 % [0 .. 1.5e-4]
TIRE_HEAT_GAIN = 0.0005      # C por julio de friccion (calienta derrapar
                             # y frenar fuerte); la tasa esta limitada a
                             # 6 C/s por la masa termica de la goma
                             # [0.0002 .. 0.002]
TIRE_COOL_COEFF = 0.0019     # refrigeracion por el aire, proporcional a
                             # la velocidad (mas un residuo en parado)
                             # [0.001 .. 0.004]

# ===========================================================================
# SUSPENSIÓN (por rueda)
#
# Frecuencia propia ~1.6 Hz con los valores por defecto (tarado deportivo).
# Muelles más duros = reacciones más rápidas y menos balanceo.
# ===========================================================================
SUSP_SPRING_FRONT = 50000.0  # N/m por rueda delantera [15000 .. 60000]
SUSP_SPRING_REAR = 44000.0   # N/m por rueda trasera [15000 .. 60000]
SUSP_DAMPER = 4300.0         # N·s/m por rueda. Valor de RESERVA: solo se
                             # usa si un coche no define los cuatro de abajo,
                             # y entonces se reparte 0.6 en compresión y 1.3
                             # en extensión [2000 .. 8000]
# AMORTIGUACION separada. Un amortiguador real NO opone lo mismo al
# comprimirse que al extenderse: la EXTENSION suele ser 2-3 veces más dura.
# La razón es que en compresión el amortiguador pelea contra el muelle (que
# ya sostiene el coche) mientras que en extensión controla la energía que el
# muelle devuelve, que es lo que hace rebotar al coche.
#
# Es el reglaje que gobierna el comportamiento TRANSITORIO —cómo entra el
# coche en curva y cómo se asienta al salir— frente a muelles y barras, que
# mandan en el estacionario. Regla práctica: subir la extensión de un eje
# hace que ese eje "aguante" la carga más tiempo, retrasando la transferencia.
SUSP_DAMPER_BUMP_F = 2600.0  # N·s/m, COMPRESION delantera [800 .. 6000]
SUSP_DAMPER_REB_F = 5600.0   # N·s/m, EXTENSION delantera [1500 .. 12000]
SUSP_DAMPER_BUMP_R = 2300.0  # N·s/m, COMPRESION trasera [800 .. 6000]
SUSP_DAMPER_REB_R = 4900.0   # N·s/m, EXTENSION trasera [1500 .. 12000]
# TOPES DE RECORRIDO (bump stops). La suspensión no se puede comprimir sin
# fin: al agotar el recorrido apoya en un tope de poliuretano y la rigidez
# se dispara. Sirven para proteger de baches y aterrizajes, pero también
# como REGLAJE: un coche con mucha carga aerodinámica se sienta en los topes
# en recta rápida, manteniendo la altura constante (que es lo que la aero
# necesita) sin muelles durísimos que arruinarían la curva lenta.
SUSP_BUMP_GAP_F = 0.070      # m de recorrido libre delante antes de tocar
                             # el tope [0.02 .. 0.15]
SUSP_BUMP_GAP_R = 0.080      # m ídem detrás [0.02 .. 0.15]
SUSP_BUMP_STIFF = 2.0e7      # N/m², rigidez CUADRATICA del tope:
                             # F = STIFF · exceso². A 10 mm de penetración
                             # son 2 000 N; a 20 mm, 8 000 N; a 30 mm,
                             # 18 000 N. 0 desactiva los topes [0 .. 8e7]
ARB_FRONT = 23000.0          # estabilizadora delantera (N/m de diferencia
                             # entre lados). MÁS dura delante = más
                             # subviraje [0 .. 40000]
ARB_REAR = 14000.0           # estabilizadora trasera; subirla acerca el
                             # coche al sobreviraje [0 .. 40000]
SUSP_ANTI_PITCH = 0.30       # geometría anti-dive/anti-squat: fracción de
                             # la fuerza longitudinal que los brazos de
                             # suspensión desvían directamente al chasis
                             # (menos cabeceo, misma transferencia de
                             # carga, plataforma más estable) [0 .. 0.5]
SUSP_CAMBER_GAIN = 0.40      # rad de caída negativa ganada por metro de
                             # compresión: la rueda exterior (comprimida)
                             # se endereza compensando el balanceo y
                             # recupera parte del agarre que roba el
                             # camber thrust. 0 = eje rígido [0 .. 2.0]

# ===========================================================================
# AERODINÁMICA Y RESISTENCIAS
# ===========================================================================
AIR_DENSITY = 1.225          # kg/m³, densidad del aire a nivel del mar y 15 °C
# Cada coche define Cd (coef. de arrastre) y AREA_FRONTAL (m²) y el simulador
# calcula AERO_DRAG = ½·ρ·Cd·A. Estos valores por defecto son la reserva si un
# coche no los trae desglosados.
AERO_DRAG = 0.38             # N/(m/s)², resistencia al avance (½·ρ·Cd·A)
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
KERB_MAX_RADIUS = 0.0        # pone PIANOS en toda curva cuyo radio sea menor
                             # o igual que este valor (m): sube el número
                             # para tener pianos también en las curvas
                             # abiertas. 0 = respetar los pianos que traiga
                             # el circuito [0 .. 1500]
ROAD_ROUGHNESS = 1.0         # rugosidad del firme: escala el microrrelieve
                             # (baches finos) del asfalto, incluidas ZONAS
                             # DAÑADAS aleatorias por tramos (parches de firme
                             # roto, más rugosos). Zarandea el coche, la cámara
                             # y el volante. 0 = firme perfectamente liso
                             # [0 .. 3]
SEGMENT_LENGTH = 4.0         # m por segmento (no cambiar si se usan
                             # circuitos importados)
DRAW_DISTANCE = 220          # segmentos dibujados; bajar si va lento
                             # [100 .. 400]
CAMERA_HEIGHT = 1.35         # m, altura del OJO del conductor en la vista
                             # interior; cada coche la redefine en su .car
                             # (formula a ras de suelo, autobus en lo alto)
                             # [0.8 .. 2.5]
CAMERA_FORWARD = 0.5         # m que el ojo del conductor va por DELANTE del
                             # punto del coche (centro), solo en la vista
                             # interior. Sitúa la cámara en el puesto de
                             # conducción y no en el centro del coche; cada
                             # coche lo redefine (autobus muy adelante sobre
                             # el eje, formula casi centrado) [0 .. 3]
CAMERA_HEIGHT_REAR = 2.5     # m, altura de la cámara de la vista trasera
                             # cercana (con el coche visto desde atrás)
                             # [1.5 .. 3.5]
CAMERA_DEPTH = 1.2           # proyección (1/tan(fov/2)); subir acerca el
                             # coche a la parte baja de la pantalla, como
                             # los juegos comerciales [0.7 .. 1.6]
CAMERA_YAW_GAIN = 1.6        # cuánto sigue la cámara el rumbo del coche
                             # respecto a la carretera: 1.0 = geométrico
                             # exacto, más alto = giro de vista más
                             # perceptible al derrapar o girar [1.0 .. 2.5]
CAMERA_LOOK_GAIN = 0.22      # MIRAR A LA CURVA: la cámara gira hacia donde
                             # gira el coche, anticipando el vértice (rad de
                             # giro extra por rad/s de guiñada, limitado a
                             # ~20°). 0 = desactivado [0 .. 1.5]
CAMERA_FOV_SPEED = 0.12      # el campo de visión se abre con la velocidad:
                             # sensación de vértigo al acelerar. 0 = fijo
                             # [0 .. 0.3]
CAMERA_GLEAN = 1.0           # la cabeza del piloto cae hacia FUERA con la
                             # fuerza g lateral (balanceo de la cabeza en
                             # curva). Solo visual. 0 = desactivado [0 .. 3]
CAMERA_SHAKE = 1.0           # temblor visual por baches y patinaje. SOLO
                             # visual: no toca la física ni las cargas.
                             # 0 = imagen quieta [0 .. 3]
RACING_LINE = True           # trazada ideal (tecla L): verde = margen,
                             # ámbar = al límite, rojo = no llegas a frenar
MINIMAP = True               # plano del circuito COMPLETO arriba a la
                             # izquierda (tecla M): da la visión de conjunto,
                             # dónde estás dentro de la vuelta
# --- PLANTA DEL TRAMO QUE VIENE (abajo a la derecha, tecla N) -------------
# Vista egocéntrica: el coche abajo mirando hacia arriba y el trazado que
# viene desenrollándose. Sustituye al antiguo indicador de "radio a 50 m",
# que daba un número sin contexto: aquí se ve la SECUENCIA de curvas, que
# es lo que permite anticipar y frenar a tiempo.
MAP_AHEAD = True             # mostrarla al arrancar
SPEEDO_DIAL = True           # velocímetro de AGUJA (tipo reloj) en vez de
                             # la cifra suelta. Se lee de un vistazo, sin
                             # tener que descifrar un número
SPEEDO_SIZE = 250            # px de diámetro del velocímetro de aguja
                             # [120 .. 460]
SPEEDO_MAX_KMH = 260         # fondo de escala del velocímetro [80 .. 400]
MAP_AHEAD_M = 1000.0         # m de circuito por delante que se dibujan
                             # [300 .. 2500]
MAP_AHEAD_PX_PER_M = 0.30    # px por metro. FIJO a propósito: con escala
                             # constante las curvas de dos circuitos se
                             # pueden comparar de un vistazo, cosa que una
                             # escala automática impediría [0.1 .. 0.8]
MAP_AHEAD_W = 430            # px de ancho del panel [240 .. 700]
MAP_AHEAD_H = 360            # px de alto del panel [180 .. 600]
MAP_AHEAD_ALPHA = 115        # transparencia del fondo (0 = invisible,
                             # 255 = opaco). Bajo a propósito: deja ver la
                             # carretera por debajo [0 .. 255]
MAP_AHEAD_LABELS = 5         # cuántas curvas se etiquetan con su radio; se
                             # eligen las MAS CERRADAS, que son las que
                             # obligan a frenar [0 .. 10]
MAP_AHEAD_R_MAX = 400.0      # m; por encima de este radio no se considera
                             # curva (no se etiqueta) [200 .. 2000]
MAP_AHEAD_SMOOTH_M = 18.0    # m de suavizado de la curvatura al detectar
                             # curvas. Los trazados importados vienen de un
                             # eje medido por GPS y su curvatura tiene picos
                             # de ruido: sin esto, un pico aislado se toma
                             # por una curva cerradísima [0 .. 60]
TRACK_POLES = False           # balizas de colores en los bordes (amarillo =
                             # izquierda, azul = derecha)
TRACK_POLE_HEIGHT = 2.2      # m de alto de las balizas: bajarlas las hace
                             # menos invasivas y da otra sensación de
                             # velocidad [0.4 .. 4]
CHEVRON_MAX_RADIUS = 200.0   # PANELES DIRECCIONALES (chevrons) en el exterior
                             # de toda curva de radio menor o igual que este
                             # valor (m): la señal real de curva peligrosa,
                             # que dice hacia dónde y cómo de cerrada es la
                             # curva antes de entrar. 0 = sin chevrons
                             # [0 .. 800]
CAR_BODY_MOTION_EXAG = 5.0   # exageración visual del cabeceo/balanceo de la
                             # carrocería en pantalla; 1 = real [1 .. 5] 3
TELEM_DOT_LOAD_GAIN = 8.0    # F2: cuánto crece el diámetro del punto del
                             # círculo de fricción con la carga de la rueda
                             # (radio px = 1 + ganancia x carga/estática);
                             # sube para hacer más patentes las
                             # transferencias de peso [3 .. 14]
LAP_MIN_FRACTION = 0.9       # fracción del circuito que hay que recorrer
                             # HACIA DELANTE para que la vuelta cuente. Evita
                             # cronometrar cruces de meta que no son vueltas
                             # (dar media vuelta antes de la línea, recolocar
                             # el coche...) [0.5 .. 1.0]
WRONG_WAY_DEG = 105.0        # grados de rumbo respecto al eje de la carretera
                             # a partir de los cuales se avisa de SENTIDO
                             # CONTRARIO. Se apaga 30 grados antes, para no
                             # parpadear en un trompo [95 .. 150]
GHOST_ENABLED = True         # coche fantasma translúcido reproduciendo tu
                             # mejor vuelta de la sesión (aparece al
                             # completar una vuelta cronometrada)
PARTICLES_ENABLED = True     # partículas de humo (derrape en asfalto),
                             # chispas (pianos) y polvo (hierba)
PARTICLES_MAX = 260          # tope de partículas vivas [60 .. 500]

# ===========================================================================
# GRAFICOS — realismo atmosferico
# ===========================================================================
GFX_FOG_DIST = 600.0         # m, alcance de la bruma atmosférica: lo lejano
                             # se funde con el cielo (perspectiva aérea, da
                             # profundidad). 0 desactiva [0 .. 2000]
GFX_SUN_SHADE = 0.16         # intensidad del sombreado del relieve por el
                             # sol (cuestas y peraltes cambian de brillo
                             # según su orientación). 0 = plano [0 .. 0.4]
GFX_SUN = True               # dibujar el sol y su halo en el cielo (se
                             # oculta solo con LLUVIA)
GFX_GPU = True               # escena 3D en la GPU (moderngl): búfer de
                             # profundidad, antialiasing, bruma por píxel y
                             # cielo fijo al mundo. Si falta moderngl o no
                             # hay OpenGL 3.3 vuelve solo al render de SDL
GFX_MSAA = 4                 # muestras de antialiasing de la GPU: 0, 2, 4
                             # u 8. Cuesta poco en cualquier GPU [0 .. 8]

# ===========================================================================
# SONIDO
# ===========================================================================
AUDIO_ENABLED = True
AUDIO_RATE = 44100           # Hz de muestreo; 44100 (calidad CD) da un
                             # siseo del chirrido y una aspiración más
                             # limpios que 22050, a coste de CPU mínimo
AUDIO_VOLUME = 0.5           # volumen general [0 .. 1]
SCREECH_VOLUME = 1.2         # volumen del chirrido de neumáticos [0 .. 1.5]

# ===========================================================================
# SONIDO: MOTOR
#
# El motor no es una grabación: se sintetiza en cada fotograma a partir del
# régimen y la carga. Estos son los mandos de su TIMBRE, y se oyen en directo
# en el LABORATORIO DE SONIDO del menú.
#
# La nota base es el orden de encendido: en un cuatro tiempos hay una
# explosión por cada dos vueltas y cilindro, o sea rpm/60 · cilindros/2 Hz.
# Sobre ella se montan armónicos (el "cuerpo" del tubo de escape), el
# retumbo de medio orden (el balanceo grave de un motor de pocos cilindros),
# el pulso de combustión (cada explosión por separado) y la aspiración.
# ===========================================================================
SND_CILINDROS = 4            # cilindros: cambia la NOTA del motor a igual
                             # régimen. 4 suena a utilitario, 6 más lleno,
                             # 8 grave y espaciado, 12 casi un zumbido
                             # [1 .. 12]
SND_ARMONICO_1 = 0.36        # fundamental áspera (sierra): el grueso del
                             # sonido. Subirlo lo hace más bronco [0 .. 1]
SND_ARMONICO_2 = 0.20        # 2º armónico: brillo medio [0 .. 1]
SND_ARMONICO_3 = 0.10        # 3º armónico: filo agudo; pasarse aquí suena
                             # metálico y cansa [0 .. 1]
SND_RETUMBO = 0.26           # medio orden: el "bum-bum" grave entre
                             # explosiones. Es lo que da carácter a un V8
                             # [0 .. 1]
SND_CUERPO = 0.14            # golpe de cada combustión en vacío [0 .. 1]
SND_CUERPO_CARGA = 0.28      # cuánto crece ese golpe a plena carga: es la
                             # diferencia entre acelerar y ir sostenido
                             # [0 .. 1]
SND_ANCHO_PULSO = 0.16       # duración de la explosión como fracción del
                             # ciclo. Corto = seco y percusivo; largo =
                             # redondo y ronco [0.04 .. 0.40]
SND_SUAVIZADO_CUERPO = 6     # redondeo del pulso de combustión. Bajo = más
                             # áspero y agudo; alto = más cálido [1 .. 24]
SND_ADMISION = 0.45          # soplido de aspiración con el gas abierto
                             # [0 .. 1.5]
SND_ASPEREZA = 0.06          # variación de ciclo a ciclo. Un motor real no
                             # repite dos explosiones iguales; a cero suena
                             # sintético [0 .. 0.25]
SND_PETARDEO = 0.9           # crepitar al soltar gas con el motor alto
                             # [0 .. 2]

# ===========================================================================
# SONIDO: NEUMATICOS
#
# Tres sonidos DISTINTOS, no uno con más volumen: el chirrido lateral de una
# curva, el rasgado del patinaje de tracción y el arrastre del bloqueo de
# frenada. Se oyen aislados en el laboratorio para poder afinarlos uno a uno.
# ===========================================================================
SND_SCRUB_F1 = 1150.0        # 1er formante del chirrido lateral, en Hz: el
                             # tono principal del "iiiih" de curva
                             # [400 .. 3000]
SND_SCRUB_F2 = 1730.0        # 2º formante: el armónico que lo hace sonar a
                             # goma y no a silbato [400 .. 4000]
SND_SCRUB_SISEO = 1.1        # siseo de banda alta mezclado con los tonos.
                             # Subirlo lo acerca a un roce; bajarlo lo deja
                             # como un silbido limpio [0 .. 3]
SND_SCRUB_TREMOLO_HZ = 30.0  # temblor de volumen del chirrido [0 .. 80]
SND_SCRUB_VIBRATO_HZ = 38.0  # temblor de tono del chirrido [0 .. 80]
SND_SPIN_RASGADO_HZ = 40.0   # rasgado base del patinaje de tracción, en Hz;
                             # se acelera al patinar más [0 .. 120]
SND_SPIN_SUAVIZADO = 8       # grave/agudo del patinaje. Bajo = rasgado y
                             # agudo; alto = zumbido sordo [1 .. 32]
SND_LOCK_SUAVIZADO = 22      # lo mismo para el bloqueo de frenada. Alto da
                             # el "shhh" oscuro de la rueda parada [1 .. 48]
SND_LOCK_NIVEL = 1.4         # volumen relativo del bloqueo [0 .. 3]

# ===========================================================================
# SONIDO: AMBIENTE Y EXTRAS
#
# El viento va siempre; los tres últimos están APAGADOS de fábrica porque no
# todos los coches los tienen. Súbelos en el laboratorio para oírlos.
# ===========================================================================
SND_VIENTO = 0.5             # volumen del viento a velocidad de referencia
                             # [0 .. 2]
SND_VIENTO_REF = 52.0        # m/s a los que el viento llega a su máximo
                             # (~187 km/h). Bajarlo lo hace notarse antes
                             # [20 .. 90]
SND_VIENTO_SUAVIZADO = 12    # gravedad del viento: alto = soplido sordo,
                             # bajo = siseo agudo [1 .. 40]
SND_TRANSMISION = 0.0        # zumbido de la transmisión, proporcional a la
                             # velocidad. Es el "canto" de los engranajes de
                             # un coche de carreras o una furgoneta con
                             # kilómetros [0 .. 1]
SND_TRANSMISION_HZ = 90.0    # Hz de ese zumbido por cada 10 m/s [30 .. 400]
SND_TURBO = 0.0              # silbido del turbo, crece con la carga y el
                             # régimen [0 .. 1]
SND_TURBO_HZ = 3800.0        # tono del silbido a pleno régimen
                             # [1500 .. 9000]
SND_VALVULA = 0.0            # soplido de la válvula de descarga al levantar
                             # el pie de golpe [0 .. 1]

# ===========================================================================
# ADAS — ayudas a la conducción
#
# Avisos acústicos del límite de adherencia: un pitido cuya frecuencia de
# repetición sube al acercarte y superar el límite. Subviraje y sobreviraje
# usan tonos distintos para diferenciarlos de oído.
# ===========================================================================
ADAS_ENABLED = True          # avisos de subviraje/sobreviraje
ADAS_VOLUME = 0.55           # volumen de los pitidos [0 .. 1]
ADAS_WARN_FROM = 0.72        # fracción del pico de agarre a la que EMPIEZA
                             # el aviso. Este es el mando del "cuándo": es
                             # el tiempo de antelación, NO la velocidad del
                             # pitido. Bajarlo (p.ej. 0.62) avisa antes,
                             # con más margen para corregir, a riesgo de
                             # pitar en cada curva rápida; subirlo (0.85)
                             # solo avisa casi encima del límite [0.55 .. 0.95]
ADAS_MIN_HZ = 2.5            # pitidos/s al ENTRAR en el aviso (tic lento).
                             # MIN/MAX_HZ controlan la VELOCIDAD del pitido
                             # según la gravedad, no cuándo empieza [1 .. 6]
ADAS_MAX_HZ = 13.0           # pitidos/s con subviraje/sobreviraje severo
                             # (casi tono continuo) [6 .. 20]
ADAS_UNDERSTEER_TONE = 620.0 # Hz del aviso de subviraje (grave, "te vas
                             # de morro") [400 .. 800]
ADAS_OVERSTEER_TONE = 1050.0 # Hz del aviso de sobreviraje (agudo y urgente,
                             # "se va la cola") [900 .. 1400]

