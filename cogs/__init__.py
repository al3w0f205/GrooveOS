def __init__(self, bot):
        self.bot = bot
        self.song_queue = []
        self.preloaded_player = None  # Aquí guardaremos el audio ya descargado
        self.preloaded_query = None   # Para saber qué canción es la que está lista
        self.loop_enabled = False       # Interruptor del bucle
        self.current_track = None


# self.sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
#     client_id=os.getenv('SPOTIPY_CLIENT_ID'),
#     client_secret=os.getenv('SPOTIPY_CLIENT_SECRET')
# ))

def __init__(self, bot):
        self.bot = bot
        self.song_queue = []
        self.loop_enabled = False
        self.current_track = None
        
        # --- AGREGA ESTA LÍNEA ---
        self.progress_task = None  # Para controlar la barra en movimiento
        # -------------------------
        
        self.preloaded_player = None 
        # ... resto del código ...