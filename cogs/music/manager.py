# cogs/music/manager.py
import os
import ctypes.util
import discord
from .state import GuildMusicState
from .config import AUTOPLAY_RECENT_BUFFER

from .services.player import PlayerService
from .services.playlists import PlaylistService
from .services.autoplay import AutoplayService

class MusicManager:
    def __init__(self, bot):
        self.bot = bot
        self._states: dict[int, GuildMusicState] = {}

        # servicios
        self.playlists = PlaylistService(self)
        self.autoplay = AutoplayService(self)
        self.player = PlayerService(self)

        # opus + cache
        opus_path = ctypes.util.find_library("opus")
        if opus_path:
            try:
                discord.opus.load_opus(opus_path)
            except Exception:
                pass

        os.makedirs("cache_audio", exist_ok=True)

    def state(self, guild_id: int) -> GuildMusicState:
        st = self._states.get(guild_id)
        if not st:
            st = GuildMusicState()
            st.autoplay_recent_core_titles = __import__("collections").deque(maxlen=AUTOPLAY_RECENT_BUFFER)
            self._states[guild_id] = st
        return st