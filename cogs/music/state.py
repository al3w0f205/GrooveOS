# cogs/music/state.py
from dataclasses import dataclass, field
import asyncio
from collections import deque

@dataclass
class GuildMusicState:
    # queue / playback
    song_queue: list[str] = field(default_factory=list)
    loop_enabled: bool = False
    current_track: str | None = None

    # preload
    preloaded_player: object | None = None
    preloaded_query: str | None = None

    # panel
    barra_task: asyncio.Task | None = None
    panel_msg: object | None = None
    panel_start_time: float | None = None
    panel_duration: int = 0
    panel_data: dict | None = None
    panel_ctx: object | None = None
    panel_view: object | None = None

    # autoplay
    autoplay_enabled: bool = True
    _autoplay_flip: bool = False
    autoplay_history: list[str] = field(default_factory=list)
    autoplay_fingerprints: set[str] = field(default_factory=set)
    autoplay_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_autoplay_time: float = 0.0

    # paranoid buffers
    autoplay_core_fingerprints: set[str] = field(default_factory=set)
    autoplay_recent_core_titles: deque = field(default_factory=deque)