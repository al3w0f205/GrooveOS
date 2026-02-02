import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import ctypes.util
import requests
from bs4 import BeautifulSoup
import random
import time
import re
import difflib
from collections import deque

from .utilidad import THEME, user_footer, fmt_time, short_queue_preview, clean_query

# ==========================================
# ⚙️ CONFIGURACIÓN DE AUDIO (Proxmox-safe)
# ==========================================
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "outtmpl": "cache_audio/%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "windowsfilenames": True,
    "overwrites": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
}

# ✅ Estabilidad Discord Voice (48kHz/2ch) + reconexión
FFMPEG_OPTIONS = {
    "options": "-vn -loglevel quiet -ar 48000 -ac 2 -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

# ==========================================
# 🎧 AUTOPLAY SETTINGS (estricto)
# ==========================================
AUTOPLAY_MAX_DURATION = 10 * 60   # máx 10 min (evita mixes largos)
AUTOPLAY_MIN_DURATION = 45        # min 45s
AUTOPLAY_MIN_OVERLAP = 3          # ✅ mínimo 3 palabras en común
AUTOPLAY_COOLDOWN = 2.0           # ✅ anti doble-trigger (skip spam)

# ==========================================
# 🧨 AUTOPLAY PARANOID (anti-duplicados fuerte)
# ==========================================
AUTOPLAY_PARANOID = True

# similitud alta => se considera el mismo tema aunque otro canal/ID
AUTOPLAY_DUP_SIM_THRESHOLD = 0.92

# si comparten demasiadas palabras clave en el core title => duplicado
AUTOPLAY_DUP_TOKEN_OVERLAP = 0.78  # (0-1) más alto = más estricto

# cuántos títulos recientes recordar para bloquear repetidos cercanos
AUTOPLAY_RECENT_BUFFER = 80


# ==========================================
# 🎵 FUENTE DE AUDIO
# ==========================================
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.filename = ytdl.prepare_filename(data)

    @classmethod
    async def from_query(cls, query, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=True))
            if "entries" in data:
                data = data["entries"][0]
            filename = ytdl.prepare_filename(data)
            return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)
        except Exception as e:
            print(f"❌ Error YTDL: {e}")
            return None


# ==========================================
# 🎮 BOTONES (UI)
# ==========================================
class ControlesMusica(discord.ui.View):
    def __init__(self, ctx, cog, query):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.cog = cog
        self.query = query

        # Color inicial del botón Loop (🔁)
        for child in self.children:
            if isinstance(child, discord.ui.Button) and str(child.emoji) == "🔁":
                child.style = discord.ButtonStyle.primary if self.cog.loop_enabled else discord.ButtonStyle.secondary

    async def refresh_panel(self):
        if not self.cog.panel_msg or not self.cog.panel_data:
            return
        vc = self.ctx.voice_client
        paused = vc.is_paused() if vc else False
        embed = self.cog.build_now_playing_embed(self.ctx, paused=paused)
        try:
            await self.cog.panel_msg.edit(embed=embed, view=self)
        except Exception:
            pass

    # ✅ PAUSA / RESUME (silencioso) — fila 0
    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary, row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        vc = self.ctx.voice_client
        if not vc:
            return

        if vc.is_paused():
            vc.resume()
        elif vc.is_playing():
            vc.pause()

        await self.refresh_panel()

    # ✅ SKIP (silencioso) — fila 0
    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        vc = self.ctx.voice_client
        if vc:
            vc.stop()  # after_playing -> play_next -> autoplay si procede

    # ✅ LOOP (silencioso + cambia color) — fila 0
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=0)
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.loop_enabled = not self.cog.loop_enabled
        button.style = discord.ButtonStyle.primary if self.cog.loop_enabled else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)
        await self.refresh_panel()

    # ✅ STOP (silencioso) — fila 0
    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.secondary, row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.stop_all(self.ctx, leave_panel=True)

    # ✅ SHUFFLE (silencioso) — fila 0
    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if len(self.cog.song_queue) < 2:
            return
        random.shuffle(self.cog.song_queue)
        await self.refresh_panel()


# ==========================================
# 🎧 COG MÚSICA
# ==========================================
class Musica(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Cola / estado
        self.song_queue = []
        self.loop_enabled = False
        self.current_track = None

        # Preload
        self.preloaded_player = None
        self.preloaded_query = None

        # Panel / barra
        self.barra_task = None

        # Panel references
        self.panel_msg = None
        self.panel_start_time = None
        self.panel_duration = 0
        self.panel_data = None
        self.panel_ctx = None
        self.panel_view = None

        # ✅ Autoplay (Radio) — Mix C
        self.autoplay_enabled = True
        self._autoplay_flip = False
        self.autoplay_history = []          # ids/urls para no repetir (cap)
        self.autoplay_fingerprints = set()  # ✅ anti-repeat fuerte por "huella"
        self.autoplay_lock = asyncio.Lock()
        self.last_autoplay_time = 0.0
        self.autoplay_cooldown = AUTOPLAY_COOLDOWN

        # 🧨 Paranoid buffers (anti-repeat cross-channel/ID)
        self.autoplay_core_fingerprints = set()         # core title fingerprints (sin uploader)
        self.autoplay_recent_core_titles = deque(maxlen=AUTOPLAY_RECENT_BUFFER)

        # Cargar Opus (Linux/LXC)
        opus_path = ctypes.util.find_library("opus")
        if opus_path:
            try:
                discord.opus.load_opus(opus_path)
            except Exception:
                pass

        os.makedirs("cache_audio", exist_ok=True)

    # -------------------------
    # Utils Proxmox-safe
    # -------------------------
    def cleanup_file(self, filename):
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

    def purge_old_cache(self, folder="cache_audio", max_age_minutes=90):
        if not os.path.isdir(folder):
            return
        now = time.time()
        max_age = max_age_minutes * 60
        for fn in os.listdir(folder):
            path = os.path.join(folder, fn)
            try:
                if os.path.isfile(path) and (now - os.path.getmtime(path)) > max_age:
                    os.remove(path)
            except Exception:
                pass

    def _has_listeners(self, vc: discord.VoiceClient) -> bool:
        """True si hay humanos (no bots) en el canal de voz."""
        try:
            if not vc or not vc.channel:
                return False
            humans = [m for m in vc.channel.members if not m.bot]
            return len(humans) > 0
        except Exception:
            return False

    async def preload_next(self, query):
        try:
            if self.preloaded_query == query and self.preloaded_player:
                return

            if self.preloaded_player and getattr(self.preloaded_player, "filename", None):
                self.cleanup_file(self.preloaded_player.filename)

            player = await YTDLSource.from_query(query, loop=self.bot.loop)
            if player:
                self.preloaded_player = player
                self.preloaded_query = query
        except Exception as e:
            print(f"❌ Error en pre-carga: {e}")

    # -------------------------
    # AUTOPLAY helpers (anti repetidos + estricto)
    # -------------------------
    def _history_has(self, key: str) -> bool:
        return key in self.autoplay_history

    def _history_add(self, key: str, cap: int = 250):
        if not key:
            return
        if key in self.autoplay_history:
            return
        self.autoplay_history.append(key)
        if len(self.autoplay_history) > cap:
            self.autoplay_history = self.autoplay_history[-cap:]

    def _duration_ok(self, entry: dict) -> bool:
        """Filtra contenido largo / live / duración desconocida."""
        if not entry:
            return False

        if entry.get("is_live") or entry.get("live_status") in ("is_live", "live"):
            return False

        dur = entry.get("duration", None)
        if dur is None:
            # evitar mixes/streams sin duración
            return False

        try:
            dur = int(dur)
        except Exception:
            return False

        if dur < AUTOPLAY_MIN_DURATION:
            return False
        if dur > AUTOPLAY_MAX_DURATION:
            return False
        return True

    # ---------- Normalización fuerte ----------
    def _normalize_text(self, s: str) -> str:
        s = (s or "").lower()

        # limpiar basura típica de YouTube
        trash = [
            "official video", "official music video", "official audio", "audio",
            "lyrics", "lyric video", "video oficial", "videoclip", "visualizer",
            "explicit", "clean", "hq", "4k", "hd", "mv", "m/v"
        ]
        for t in trash:
            s = s.replace(t, "")

        # normalizar feat/ft (para no crear variantes)
        s = s.replace("feat.", "feat").replace("ft.", "ft").replace("featuring", "feat")

        # quita contenido entre paréntesis/corchetes (suele ser ruido)
        s = re.sub(r"\([^)]*\)", " ", s)
        s = re.sub(r"\[[^\]]*\]", " ", s)

        # symbols -> espacios
        for ch in "{}|.,!?:;\"'`~@#$%^&*_+=<>/\\-":
            s = s.replace(ch, " ")

        # colapsar espacios
        s = " ".join(s.split())
        return s

    def _core_title(self, title: str) -> str:
        """
        Núcleo del título para detectar misma canción aunque cambie canal/ID:
        - normaliza texto
        - quita palabras comunes que no cambian la canción
        - quita 'remix', 'edit', 'sped up', 'slowed', etc. (config paranoica)
        """
        t = self._normalize_text(title)

        # Stopwords y términos que suelen crear duplicados
        drop = {
            "official", "video", "music", "audio", "lyrics", "lyric", "visualizer",
            "remix", "edit", "version", "ver", "mix", "extended", "radio", "live",
            "performance", "sped", "up", "slowed", "reverb", "bass", "boosted",
            "instrumental", "karaoke", "clean", "explicit", "tiktok",
            "prod", "producer", "produced",
        }

        tokens = [w for w in t.split() if w not in drop and len(w) > 1]
        core = " ".join(tokens)

        # recorte defensivo
        return core.strip()[:120]

    def _fingerprint(self, title: str, uploader: str) -> str:
        """Huella para detectar misma canción aunque cambie (Audio/Video/Lyrics)."""
        t = self._normalize_text(title)[:90]
        u = self._normalize_text(uploader)[:50]
        return f"{t}::{u}"

    def _core_fingerprint(self, title: str) -> str:
        """Huella SOLO del core title (independiente del uploader/canal)."""
        return self._core_title(title)

    def _seed_tokens(self, title: str, uploader: str) -> set:
        base = self._normalize_text(f"{title} {uploader}")
        return set(base.split())

    def _score_candidate(self, seed_tokens: set, cand_title: str, cand_uploader: str) -> int:
        cand_tokens = set(self._normalize_text(f"{cand_title} {cand_uploader}").split())
        return len(seed_tokens & cand_tokens)

    def _passes_strictness(self, overlap: int, seed_uploader: str, cand_title: str, cand_uploader: str) -> bool:
        """
        Estricto:
        - mínimo 3 palabras en común
        OR
        - el uploader del seed aparece en el uploader/título candidato (radio artista)
        """
        if overlap >= AUTOPLAY_MIN_OVERLAP:
            return True

        su = self._normalize_text(seed_uploader)
        if not su:
            return False

        ct = self._normalize_text(cand_title)
        cu = self._normalize_text(cand_uploader)

        # si el artista/uploader es claramente el mismo
        if su and (su in cu or su in ct):
            return True

        return False

    def _near_duplicate_by_core(self, cand_title: str) -> bool:
        """
        Detecta duplicados por núcleo del título:
        - si core exacto ya existe => duplicado
        - si similitud SequenceMatcher alta con títulos recientes => duplicado
        - si overlap de tokens del core muy alto => duplicado
        """
        if not AUTOPLAY_PARANOID:
            return False

        core = self._core_title(cand_title)
        if not core or len(core) < 4:
            return False

        if core in self.autoplay_core_fingerprints:
            return True

        cand_tokens = set(core.split())
        if not cand_tokens:
            return False

        # comparar con recientes
        for prev in self.autoplay_recent_core_titles:
            if not prev:
                continue

            # similitud de string (tolerante a cambios leves)
            ratio = difflib.SequenceMatcher(None, core, prev).ratio()
            if ratio >= AUTOPLAY_DUP_SIM_THRESHOLD:
                return True

            # overlap por tokens
            prev_tokens = set(prev.split())
            if not prev_tokens:
                continue
            inter = len(cand_tokens & prev_tokens)
            union = len(cand_tokens | prev_tokens)
            if union > 0:
                j = inter / union
                if j >= AUTOPLAY_DUP_TOKEN_OVERLAP:
                    return True

        return False

    def _already_used(self, url: str, fp: str, cand_title: str = "") -> bool:
        if not url:
            return True

        # si coincide con el track actual (si current_track es URL real)
        if self.current_track and url == self.current_track:
            return True

        if url in self.song_queue:
            return True

        # fingerprints "clásicos"
        if fp in self.autoplay_fingerprints:
            return True

        # paranoia: bloquear por core-title aunque sea otro canal/ID
        if cand_title and self._near_duplicate_by_core(cand_title):
            return True

        return False

    def _register_now_playing_for_autoplay(self, data: dict):
        """
        Registra SIEMPRE la canción actual como "usada"
        para que autoplay no la recomiende en otra subida/canal.
        """
        try:
            if not data:
                return

            url_now = (data.get("webpage_url") or data.get("url") or "").strip()
            vid_now = (data.get("id") or "").strip()

            title_now = data.get("title") or ""
            upl_now = data.get("uploader") or data.get("channel") or ""

            # key robusto: ID primero, luego URL
            key_now = str(vid_now or url_now).strip()
            if key_now:
                self._history_add(key_now)

            # fingerprint tradicional
            fp_now = self._fingerprint(title_now, upl_now)
            if fp_now:
                self.autoplay_fingerprints.add(fp_now)

            # fingerprint paranoico (solo core title)
            core_fp = self._core_fingerprint(title_now)
            if core_fp:
                self.autoplay_core_fingerprints.add(core_fp)
                self.autoplay_recent_core_titles.append(core_fp)

        except Exception as e:
            print(f"⚠️ register_now_playing error: {e}")

    async def _search_youtube(self, query: str):
        loop = self.bot.loop
        try:
            info = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
            return (info or {}).get("entries") or []
        except Exception as e:
            print(f"❌ Autoplay search error: {e}")
            return []

    async def get_autoplay_candidate(self, seed_data: dict):
        """
        Autoplay Mix C, pero estricto:
        1) related_videos del video actual (mejor género/vibe)
        2) fallback a ytsearch alternando related/artist
        Selecciona mejor candidato por overlap y filtros.
        """
        if not seed_data:
            return None

        seed_title = (seed_data.get("title") or "").strip()
        seed_uploader = (seed_data.get("uploader") or "").strip()
        seed_url = (seed_data.get("webpage_url") or "").strip()
        seed_id = seed_data.get("id")

        if not seed_title and not seed_uploader:
            return None

        seed_tokens = self._seed_tokens(seed_title, seed_uploader)

        # --------------------------
        # 1) related_videos (mejor)
        # --------------------------
        if seed_url:
            try:
                info = await self.bot.loop.run_in_executor(None, lambda: ytdl.extract_info(seed_url, download=False))
                related = (info or {}).get("related_videos") or []

                best = None
                best_overlap = -1

                for e in related:
                    if not e or not self._duration_ok(e):
                        continue

                    url = e.get("webpage_url") or e.get("url")
                    vid = e.get("id")
                    if not url:
                        continue
                    if seed_id and vid == seed_id:
                        continue

                    cand_title = e.get("title") or ""
                    cand_uploader = e.get("uploader") or e.get("channel") or ""

                    # 🧨 paranoia: si el core title es casi igual al seed, descarta
                    if AUTOPLAY_PARANOID:
                        if self._near_duplicate_by_core(cand_title):
                            continue
                        # también evita que el seed vuelva como "otro upload"
                        if self._core_title(cand_title) and self._core_title(seed_title):
                            r = difflib.SequenceMatcher(None, self._core_title(cand_title), self._core_title(seed_title)).ratio()
                            if r >= AUTOPLAY_DUP_SIM_THRESHOLD:
                                continue

                    overlap = self._score_candidate(seed_tokens, cand_title, cand_uploader)
                    if not self._passes_strictness(overlap, seed_uploader, cand_title, cand_uploader):
                        continue

                    fp = self._fingerprint(cand_title, cand_uploader)
                    key = str(vid or url)

                    if self._history_has(key):
                        continue
                    if self._already_used(url, fp, cand_title=cand_title):
                        continue

                    if overlap > best_overlap:
                        best_overlap = overlap
                        best = (url, fp, key, cand_title)

                if best:
                    url, fp, key, cand_title = best
                    self._history_add(key)
                    self.autoplay_fingerprints.add(fp)

                    # paranoia: registra core title del candidato para bloquear clones futuros
                    if AUTOPLAY_PARANOID:
                        core_fp = self._core_fingerprint(cand_title)
                        if core_fp:
                            self.autoplay_core_fingerprints.add(core_fp)
                            self.autoplay_recent_core_titles.append(core_fp)

                    return url

            except Exception as e:
                print(f"❌ related_videos error: {e}")

        # --------------------------
        # 2) fallback: búsqueda Mix C
        # --------------------------
        self._autoplay_flip = not self._autoplay_flip

        if self._autoplay_flip:
            base = f"{seed_title} {seed_uploader}".strip()
            queries = [
                f"ytsearch15:{base} audio",
                f"ytsearch15:{seed_title} audio",
                f"ytsearch15:{base} official audio",
            ]
        else:
            base = seed_uploader or seed_title
            queries = [
                f"ytsearch15:{base} mix",
                f"ytsearch15:{base} official audio",
                f"ytsearch15:{base} topic audio",
            ]

        best = None
        best_overlap = -1

        for q in queries:
            entries = await self._search_youtube(q)
            for e in entries:
                if not e or not self._duration_ok(e):
                    continue

                url = e.get("webpage_url") or e.get("url")
                vid = e.get("id")
                if not url:
                    continue
                if seed_id and vid == seed_id:
                    continue

                cand_title = e.get("title") or ""
                cand_uploader = e.get("uploader") or e.get("channel") or ""

                # 🧨 paranoia: filtra duplicados por core title
                if AUTOPLAY_PARANOID:
                    if self._near_duplicate_by_core(cand_title):
                        continue
                    if self._core_title(cand_title) and self._core_title(seed_title):
                        r = difflib.SequenceMatcher(None, self._core_title(cand_title), self._core_title(seed_title)).ratio()
                        if r >= AUTOPLAY_DUP_SIM_THRESHOLD:
                            continue

                overlap = self._score_candidate(seed_tokens, cand_title, cand_uploader)
                if not self._passes_strictness(overlap, seed_uploader, cand_title, cand_uploader):
                    continue

                fp = self._fingerprint(cand_title, cand_uploader)
                key = str(vid or url)

                if self._history_has(key):
                    continue
                if self._already_used(url, fp, cand_title=cand_title):
                    continue

                if overlap > best_overlap:
                    best_overlap = overlap
                    best = (url, fp, key, cand_title)

        if best:
            url, fp, key, cand_title = best
            self._history_add(key)
            self.autoplay_fingerprints.add(fp)

            if AUTOPLAY_PARANOID:
                core_fp = self._core_fingerprint(cand_title)
                if core_fp:
                    self.autoplay_core_fingerprints.add(core_fp)
                    self.autoplay_recent_core_titles.append(core_fp)

            return url

        return None

    async def ensure_autoplay(self, ctx, seed_data: dict):
        """Autoplay estricto: solo si hay gente, con cooldown y sin repetir."""
        if not self.autoplay_enabled:
            return
        if self.song_queue:
            return
        if not ctx.voice_client:
            return
        if not self._has_listeners(ctx.voice_client):
            return

        async with self.autoplay_lock:
            if not self.autoplay_enabled or self.song_queue or not ctx.voice_client:
                return
            if not self._has_listeners(ctx.voice_client):
                return

            now = time.time()
            if now - self.last_autoplay_time < self.autoplay_cooldown:
                return
            self.last_autoplay_time = now

            candidate = await self.get_autoplay_candidate(seed_data)
            if not candidate:
                return

            # si todavía hay algo sonando, no forzar autoplay
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                return

            await self.play_music(ctx, candidate)

    # -------------------------
    # Panel minimalista A1 (SIN barra de progreso)
    # -------------------------
    def build_now_playing_embed(self, ctx, paused=False):
        data = self.panel_data or {}
        duracion = int(self.panel_duration or 0)
        start_time = float(self.panel_start_time or time.time())

        titulo = data.get("title", "Desconocido")
        url = data.get("webpage_url", "")
        thumbnail = data.get("thumbnail")
        uploader = data.get("uploader", "Desconocido")

        elapsed = int(time.time() - start_time)
        elapsed = max(0, min(elapsed, duracion)) if duracion else max(0, elapsed)
        remaining = max(0, duracion - elapsed) if duracion else 0

        estado = "⏸️ Pausado" if paused else "▶️ Reproduciendo"
        color = THEME["warning"] if paused else THEME["primary"]
        loop_txt = "ON ✅" if self.loop_enabled else "OFF ❌"
        auto_txt = "ON ✅" if self.autoplay_enabled else "OFF ❌"

        desc = (
            f"**{estado}**\n"
            f"👤 **Artista/Canal:** `{uploader}`\n"
            f"──────────────\n"
        )

        embed = discord.Embed(
            title=f"🎶 {titulo}",
            url=url,
            description=desc,
            color=color
        )

        # ✅ Mini portada (thumbnail)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        # ✅ Sin barra: solo tiempos (más limpio)
        embed.add_field(
            name="⏱️ Tiempo",
            value=(
                f"🕒 **Transcurrido:** `{fmt_time(elapsed)}`\n"
                f"⏳ **Duración:** `{fmt_time(duracion)}`\n"
                f"⌛ **Restante:** `{fmt_time(remaining)}`"
            ),
            inline=False
        )

        preview = short_queue_preview(self.song_queue, limit=3)
        embed.add_field(
            name="📜 Próximas",
            value=f"{preview}\n\u200b",
            inline=False
        )

        embed.set_footer(**user_footer(ctx, f"Loop: {loop_txt} • Auto: {auto_txt}"))
        return embed

    async def actualizar_panel_loop(self):
        try:
            while True:
                await asyncio.sleep(10)
                if not self.panel_msg or not self.panel_ctx or not self.panel_data:
                    break
                vc = self.panel_ctx.voice_client
                if not vc:
                    break
                embed = self.build_now_playing_embed(self.panel_ctx, paused=vc.is_paused())
                await self.panel_msg.edit(embed=embed, view=self.panel_view)

                if self.panel_duration and (time.time() - self.panel_start_time) > self.panel_duration:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error panel: {e}")

    async def enviar_panel(self, ctx, player):
        data = player.data
        self.panel_ctx = ctx
        self.panel_data = data
        self.panel_duration = int(data.get("duration", 0))
        self.panel_start_time = time.time()

        view = ControlesMusica(ctx, self, data.get("webpage_url", ""))
        self.panel_view = view

        embed = self.build_now_playing_embed(ctx, paused=False)
        msg = await ctx.send(embed=embed, view=view)
        self.panel_msg = msg

        if self.barra_task:
            self.barra_task.cancel()
        self.barra_task = self.bot.loop.create_task(self.actualizar_panel_loop())

    # -------------------------
    # Playback
    # -------------------------
    async def play_next(self, ctx, last_file=None, seed_data=None):
        if self.barra_task:
            self.barra_task.cancel()

        if last_file:
            self.cleanup_file(last_file)

        if len(self.song_queue) > 0:
            await self.play_music(ctx, self.song_queue.pop(0))
        else:
            # ✅ Autoplay también aplica al skip si se queda sin cola
            if seed_data and self.autoplay_enabled and not self.loop_enabled:
                await self.ensure_autoplay(ctx, seed_data)

    async def play_music(self, ctx, query):
        self.purge_old_cache()

        if self.preloaded_query == query and self.preloaded_player:
            player = self.preloaded_player
            self.preloaded_player = None
            self.preloaded_query = None
        else:
            msg = await ctx.send("💿 **Cargando...**")
            player = await YTDLSource.from_query(query, loop=self.bot.loop)
            if not player:
                return await msg.edit(content="❌ Error de descarga.")
            await msg.delete()

        # ✅ IMPORTANTÍSIMO: current_track debe ser URL real si existe (para compares)
        try:
            data = player.data or {}
            url_now = (data.get("webpage_url") or data.get("url") or "").strip()
            self.current_track = url_now or query

            # 🧨 paranoia: registra el tema actual para que autoplay NO lo repita en otra subida
            self._register_now_playing_for_autoplay(data)

        except Exception as e:
            print(f"⚠️ Error set current_track/register: {e}")
            self.current_track = query

        def after_playing(error):
            try:
                if self.barra_task:
                    self.barra_task.cancel()

                if error:
                    print(f"Error: {error}")

                if self.loop_enabled and self.current_track:
                    self.song_queue.insert(0, self.current_track)

                asyncio.run_coroutine_threadsafe(
                    self.play_next(ctx, player.filename, seed_data=player.data),
                    self.bot.loop
                )
            except Exception as e:
                print(f"❌ Error en after_playing: {e}")

        if not ctx.voice_client:
            return await ctx.send("🚫 No estoy conectado a voz. Usa `.join` primero.")

        ctx.voice_client.play(player, after=after_playing)
        await self.enviar_panel(ctx, player)

        if len(self.song_queue) > 0:
            self.bot.loop.create_task(self.preload_next(self.song_queue[0]))

    async def stop_all(self, ctx, leave_panel: bool = True):
        self.song_queue = []

        if self.barra_task:
            self.barra_task.cancel()
            self.barra_task = None

        if self.preloaded_player and getattr(self.preloaded_player, "filename", None):
            self.cleanup_file(self.preloaded_player.filename)
        self.preloaded_player = None
        self.preloaded_query = None

        vc = ctx.voice_client
        if vc:
            try:
                vc.stop()
            except Exception:
                pass
            try:
                await vc.disconnect()
            except Exception:
                pass

        self.purge_old_cache(max_age_minutes=10)

        # Panel "detenido" (opcional)
        if leave_panel and self.panel_msg and self.panel_ctx:
            try:
                embed = self.build_now_playing_embed(self.panel_ctx, paused=False)
                if embed.description:
                    embed.description = embed.description.replace("▶️ Reproduciendo", "🛑 Detenido")
                    embed.description = embed.description.replace("⏸️ Pausado", "🛑 Detenido")
                embed.color = THEME["neutral"]

                if self.panel_view:
                    for item in self.panel_view.children:
                        if hasattr(item, "disabled"):
                            item.disabled = True

                await self.panel_msg.edit(embed=embed, view=self.panel_view)
            except Exception:
                pass

        self.panel_data = None
        self.panel_ctx = None

    # -------------------------
    # Commands
    # -------------------------
    @commands.command(name="join")
    async def join(self, ctx):
        if ctx.author.voice:
            canal = ctx.author.voice.channel
            if ctx.voice_client:
                await ctx.voice_client.move_to(canal)
            else:
                await canal.connect()
        else:
            await ctx.send("🚫 Debes estar en un canal de voz primero.")

    @commands.command(name="p")
    async def play(self, ctx, *, query: str):
        """Reproduce música."""
        # handshake para evitar “acelerado” al entrar (LXC)
        just_joined = False
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            just_joined = True
        if not ctx.voice_client:
            return
        if just_joined:
            await asyncio.sleep(0.8)

        # Spotify/Apple scraping (simple)
        is_preloaded = (self.preloaded_query == query and self.preloaded_player is not None)

        if (not is_preloaded) and ("spotify.com" in query or "apple.com" in query):
            msg_espera = await ctx.send("🕵️ Extrayendo nombres de la playlist...")
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                res = requests.get(query, headers=headers, timeout=10)
                soup = BeautifulSoup(res.text, "html.parser")

                song_names = [
                    s.get("content")
                    for s in soup.find_all("meta", property="music:song")
                    if s.get("content")
                ]

                if not song_names:
                    await msg_espera.edit(content="⚠️ No pude leer la lista. Reproduciendo el link...")
                else:
                    song_names = list(dict.fromkeys([s for s in song_names if s]))
                    for song in song_names:
                        self.song_queue.append(song)

                    await msg_espera.edit(content=f"✅ Añadidas **{len(song_names)}** canciones a la cola.")
                    if not ctx.voice_client.is_playing():
                        await self.play_music(ctx, self.song_queue.pop(0))
                    return
            except Exception as e:
                print(f"Error scraping: {e}")

        # Normal queue
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            self.song_queue.append(query)
            await ctx.send(f"✅ En cola: `{clean_query(query)}`")

            if len(self.song_queue) == 1:
                self.bot.loop.create_task(self.preload_next(self.song_queue[0]))
        else:
            await self.play_music(ctx, query)

    @commands.command(name="autoplay", aliases=["radio"])
    async def autoplay_cmd(self, ctx):
        """Activa o desactiva Autoplay."""
        self.autoplay_enabled = not self.autoplay_enabled
        estado = "✅ ON" if self.autoplay_enabled else "❌ OFF"
        await ctx.send(f"📻 Autoplay: **{estado}**")

    @commands.command(name="stop")
    async def stop_cmd(self, ctx):
        await self.stop_all(ctx, leave_panel=True)

    @commands.command(name="skip")
    async def skip_cmd(self, ctx):
        """Salta la canción actual."""
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()
        else:
            # si lo quieres silencioso, cambia esto por "return"
            await ctx.send("🚫 No hay ninguna canción reproduciéndose.")

    @commands.command(name="shuffle", aliases=["mix", "random"])
    async def shuffle_cmd(self, ctx):
        """Mezcla la cola."""
        if len(self.song_queue) < 2:
            return await ctx.send("📉 Necesito al menos 2 canciones en la cola para mezclar.")
        random.shuffle(self.song_queue)
        await ctx.send("🔀 **Cola mezclada.**")


async def setup(bot):
    await bot.add_cog(Musica(bot))