# cogs/music/services/state.py
from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
import asyncio

@dataclass
class MusicState:
    queue: list[str] = field(default_factory=list)
    loop_enabled: bool = False
    autoplay_enabled: bool = True
    current_track: str | None = None

    # preload
    preloaded_player: object | None = None
    preloaded_query: str | None = None

    # autoplay anti repetidos
    autoplay_history: list[str] = field(default_factory=list)
    autoplay_fingerprints: set[str] = field(default_factory=set)
    autoplay_core_fingerprints: set[str] = field(default_factory=set)
    autoplay_recent_core_titles: deque = field(default_factory=lambda: deque(maxlen=30))
    autoplay_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    last_autoplay_time: float = 0.0