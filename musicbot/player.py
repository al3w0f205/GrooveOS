# musicbot/player.py
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
import time
from dataclasses import dataclass, field
from collections import deque
from typing import Optional, Deque, Callable, Awaitable, List

import discord

from .downloader import YTDLDownloader


@dataclass
class Track:
    query: str
    source: str = "youtube"  # youtube|spotify
    title: str = "Cargando..."
    webpage_url: str = ""
    duration: int = 0
    thumbnail: str = ""
    requester_id: int = 0
    requester_name: str = ""
    text_channel_id: int = 0          # <- para stats/avisos
    temp_file: Optional[str] = None
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)


class GuildMusicPlayer:
    """
    Player por servidor.
    - Descarga local, reproduce, borra
    - Prefetch N+1
    - Contabiliza segundos reales escuchados (incluye skips/pausas)
    """

    def __init__(
        self,
        bot: discord.Client,
        guild_id: int,
        downloader: YTDLDownloader,
        ffmpeg_path: str,
        temp_root: str,
        on_state_change: Optional[Callable[[int], Awaitable[None]]] = None,
        on_track_started: Optional[Callable[[int, Track], Awaitable[None]]] = None,
        on_track_finished: Optional[Callable[[int, Track, int, bool], Awaitable[None]]] = None,  # played_seconds, ended_naturally
    ):
        self.bot = bot
        self.guild_id = guild_id
        self.downloader = downloader
        self.ffmpeg_path = ffmpeg_path

        self.temp_dir = os.path.join(temp_root, str(guild_id))
        os.makedirs(self.temp_dir, exist_ok=True)

        self.on_state_change = on_state_change
        self.on_track_started = on_track_started
        self.on_track_finished = on_track_finished

        self.voice: Optional[discord.VoiceClient] = None
        self.queue: Deque[Track] = deque()
        self.current: Optional[Track] = None

        self.loop_track = False
        self.loop_queue = False

        self._download_lock = asyncio.Lock()
        self._play_lock = asyncio.Lock()
        self._prefetch_task: Optional[asyncio.Task] = None
        self._stopping = False

        # ---- tiempo real ----
        self._track_started_at: Optional[float] = None          # monotonic
        self._pause_started_at: Optional[float] = None          # monotonic
        self._paused_accum: float = 0.0
        self._last_end_was_skip: bool = False

    # ---------- estado ----------
    def is_connected(self) -> bool:
        return bool(self.voice and self.voice.is_connected())

    def is_playing(self) -> bool:
        return bool(self.voice and self.voice.is_playing())

    def is_paused(self) -> bool:
        return bool(self.voice and self.voice.is_paused())

    # ---------- helpers ----------
    def _safe_unlink(self, p: Optional[str]):
        if not p:
            return
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    def _wipe_temp(self):
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
        os.makedirs(self.temp_dir, exist_ok=True)

    def _ffmpeg_source(self, file_path: str) -> discord.FFmpegPCMAudio:
        before = "-nostdin -hide_banner -loglevel error"
        opts = "-vn -af loudnorm=I=-16:TP=-1.5:LRA=11 -ac 2 -ar 48000"
        return discord.FFmpegPCMAudio(
            executable=self.ffmpeg_path,
            source=file_path,
            before_options=before,
            options=opts,
        )

    async def _notify_state(self):
        if self.on_state_change:
            try:
                await self.on_state_change(self.guild_id)
            except Exception:
                pass

    async def ensure_voice(self, channel: discord.VoiceChannel):
        if self.voice and self.voice.is_connected():
            if self.voice.channel.id != channel.id:
                await self.voice.move_to(channel)
            return
        self.voice = await channel.connect(self_deaf=True)
        await self._notify_state()

    # ---------- tiempo ----------
    def _time_reset(self):
        self._track_started_at = None
        self._pause_started_at = None
        self._paused_accum = 0.0
        self._last_end_was_skip = False

    def _time_start(self):
        self._track_started_at = time.monotonic()
        self._pause_started_at = None
        self._paused_accum = 0.0
        self._last_end_was_skip = False

    def _time_pause(self):
        if self._pause_started_at is None:
            self._pause_started_at = time.monotonic()

    def _time_resume(self):
        if self._pause_started_at is not None:
            self._paused_accum += (time.monotonic() - self._pause_started_at)
            self._pause_started_at = None

    def _time_played_seconds(self) -> int:
        """
        Devuelve segundos “reales” escuchados de la pista actual.
        """
        if self._track_started_at is None:
            return 0
        now = time.monotonic()
        paused_extra = 0.0
        if self._pause_started_at is not None:
            paused_extra = now - self._pause_started_at
        played = (now - self._track_started_at) - (self._paused_accum + paused_extra)
        return max(0, int(played))

    # ---------- cola ----------
    async def enqueue(self, tracks: List[Track]):
        for t in tracks:
            self.queue.append(t)
        await self._notify_state()

        if not self.current and not self.is_playing() and not self.is_paused():
            await self._start()

    async def _start(self):
        async with self._play_lock:
            if self._stopping:
                return
            if not self.current:
                if not self.queue:
                    return
                self.current = self.queue.popleft()

            await self._ensure_prefetch()

            if not self.current.temp_file:
                await self._prepare_track(self.current)

            await self._play_current()

    async def _ensure_prefetch(self):
        if self._prefetch_task and not self._prefetch_task.done():
            return
        if not self.queue:
            return
        nxt = self.queue[0]
        if nxt.temp_file and os.path.exists(nxt.temp_file):
            return
        self._prefetch_task = asyncio.create_task(self._prepare_track(nxt, background=True))

    async def _prepare_track(self, track: Track, background: bool = False):
        async with self._download_lock:
            if self._stopping:
                return
            if track.temp_file and os.path.exists(track.temp_file):
                return

            # 1) resolver info
            try:
                info = await self.downloader.resolve_youtube_info(track.query)
                track.title = info.get("title") or track.title
                track.webpage_url = info.get("webpage_url") or track.webpage_url
                track.duration = int(info.get("duration") or 0)
                track.thumbnail = info.get("thumbnail") or track.thumbnail
            except Exception:
                pass

            # 2) descargar
            url = track.webpage_url or track.query
            try:
                res = await self.downloader.download_audio(url, self.temp_dir, track.uid)
                track.temp_file = res.file_path
            except Exception:
                track.temp_file = None

            await self._notify_state()

    async def _play_current(self):
        if self._stopping:
            return
        if not self.voice or not self.voice.is_connected():
            return
        if not self.current:
            return

        if not self.current.temp_file or not os.path.exists(self.current.temp_file):
            failed = self.current
            self.current = None
            self._time_reset()
            await self._notify_state()
            await self._advance_after_fail(failed)
            return

        src = self._ffmpeg_source(self.current.temp_file)

        def _after(err: Optional[Exception]):
            fut = asyncio.run_coroutine_threadsafe(self._on_track_end(err), self.bot.loop)
            try:
                fut.result()
            except Exception:
                pass

        self._time_start()
        self.voice.play(src, after=_after)

        if self.on_track_started:
            try:
                await self.on_track_started(self.guild_id, self.current)
            except Exception:
                pass

        await self._notify_state()
        await self._ensure_prefetch()

    async def _advance_after_fail(self, failed: Track):
        if self.loop_queue:
            self.queue.append(failed)

        if self.queue:
            self.current = self.queue.popleft()
            if not self.current.temp_file:
                await self._prepare_track(self.current)
            await self._play_current()
        else:
            self.current = None
            await self._notify_state()

    async def _on_track_end(self, err: Optional[Exception]):
        if self._stopping:
            return
        if not self.current:
            return

        finished = self.current

        played_seconds = self._time_played_seconds()
        ended_naturally = not self._last_end_was_skip

        # callback de stats (siempre, incluso si fue skip)
        if self.on_track_finished:
            try:
                await self.on_track_finished(self.guild_id, finished, played_seconds, ended_naturally)
            except Exception:
                pass

        # decidir siguiente
        next_track: Optional[Track] = None

        if self.loop_track:
            next_track = finished  # no borramos archivo
        else:
            # borrar archivo del track que terminó
            self._safe_unlink(finished.temp_file)
            finished.temp_file = None

            if self.loop_queue:
                self.queue.append(finished)

        # avanzar
        if next_track:
            self.current = next_track
        else:
            self.current = self.queue.popleft() if self.queue else None

        self._time_reset()
        await self._notify_state()
        await self._ensure_prefetch()

        if self.current and self.voice and self.voice.is_connected():
            if not self.current.temp_file:
                await self._prepare_track(self.current)
            await self._play_current()

    # ---------- controles ----------
    async def toggle_pause(self):
        if not self.voice or not self.voice.is_connected():
            return False, "No conectado a voz."

        if self.voice.is_playing():
            self.voice.pause()
            self._time_pause()
            await self._notify_state()
            return True, "Pausado."

        if self.voice.is_paused():
            self.voice.resume()
            self._time_resume()
            await self._notify_state()
            return True, "Reanudado."

        return False, "No hay reproducción activa."

    async def skip(self):
        if not self.voice or not self.voice.is_connected():
            return False, "No conectado a voz."
        if not (self.voice.is_playing() or self.voice.is_paused()):
            return False, "Nada que saltar."

        self._last_end_was_skip = True
        try:
            self.voice.stop()  # dispara _on_track_end()
        except Exception:
            pass
        return True, "Saltado."

    async def stop(self):
        self._stopping = True
        try:
            if self._prefetch_task and not self._prefetch_task.done():
                self._prefetch_task.cancel()
        except Exception:
            pass

        # detener
        try:
            if self.voice and self.voice.is_connected():
                self.voice.stop()
        except Exception:
            pass

        self.queue.clear()
        self.current = None
        self._time_reset()

        # desconectar
        try:
            if self.voice and self.voice.is_connected():
                await self.voice.disconnect(force=True)
        except Exception:
            pass

        self._wipe_temp()

        self._stopping = False
        await self._notify_state()
        return True, "Detenido y limpiado."

    def toggle_loop_mode(self) -> str:
        if not self.loop_track and not self.loop_queue:
            self.loop_track = True
            self.loop_queue = False
            return "Loop: Canción"
        elif self.loop_track and not self.loop_queue:
            self.loop_track = False
            self.loop_queue = True
            return "Loop: Cola"
        else:
            self.loop_track = False
            self.loop_queue = False
            return "Loop: OFF"


class MusicService:
    def __init__(
        self,
        bot: discord.Client,
        downloader: YTDLDownloader,
        ffmpeg_path: str = "ffmpeg",
        temp_root: str = "tmp_audio",
        on_state_change: Optional[Callable[[int], Awaitable[None]]] = None,
        on_track_started: Optional[Callable[[int, Track], Awaitable[None]]] = None,
        on_track_finished: Optional[Callable[[int, Track, int, bool], Awaitable[None]]] = None,
    ):
        self.bot = bot
        self.downloader = downloader
        self.ffmpeg_path = ffmpeg_path
        self.temp_root = temp_root

        self.on_state_change = on_state_change
        self.on_track_started = on_track_started
        self.on_track_finished = on_track_finished

        os.makedirs(self.temp_root, exist_ok=True)
        self.players: dict[int, GuildMusicPlayer] = {}

    def get_player(self, guild_id: int) -> GuildMusicPlayer:
        if guild_id not in self.players:
            self.players[guild_id] = GuildMusicPlayer(
                bot=self.bot,
                guild_id=guild_id,
                downloader=self.downloader,
                ffmpeg_path=self.ffmpeg_path,
                temp_root=self.temp_root,
                on_state_change=self.on_state_change,
                on_track_started=self.on_track_started,
                on_track_finished=self.on_track_finished,
            )
        return self.players[guild_id]