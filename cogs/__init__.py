def __init__(self, bot):
        self.bot = bot
        self.song_queue = []
        self.preloaded_player = None  # Aquí guardaremos el audio ya descargado
        self.preloaded_query = None   # Para saber qué canción es la que está lista


# self.sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
#     client_id=os.getenv('SPOTIPY_CLIENT_ID'),
#     client_secret=os.getenv('SPOTIPY_CLIENT_SECRET')
# ))