def __init__(self, bot):
    self.bot = bot

    # Cola / estado
    self.song_queue = []
    self.loop_enabled = False
    self.current_track = None

    # Pre-carga (buffer)
    self.preloaded_player = None
    self.preloaded_query = None

    # Panel/barra (tu código usa barra_task)
    self.barra_task = None

    # Si en tu código viejo usabas progress_task, lo dejamos por compatibilidad:
    self.progress_task = None  # (opcional) puedes no usarlo si ya usas barra_task

    # Referencias del panel
    self.panel_msg = None
    self.panel_start_time = None
    self.panel_duration = 0
    self.panel_data = None
    self.panel_ctx = None
    self.panel_view = None

    # Autoplay (Radio) — tu mix C
    self.autoplay_enabled = True
    self.autoplay_mode = "C"
    self._autoplay_flip = False
    self.autoplay_history = []
    self.autoplay_lock = asyncio.Lock()

    # ✅ Anti-duplicados + anti doble-trigger (esto DEBE ir dentro del __init__)
    self.autoplay_fingerprints = set()
    self.last_autoplay_time = 0.0
    self.autoplay_cooldown = 2.0

    # Cargar Opus (Linux/LXC)
    opus_path = ctypes.util.find_library("opus")
    if opus_path:
        try:
            discord.opus.load_opus(opus_path)
        except Exception:
            pass

    # Asegura carpeta de caché
    os.makedirs("cache_audio", exist_ok=True)