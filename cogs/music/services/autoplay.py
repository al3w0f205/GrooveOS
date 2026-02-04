# cogs/music/services/autoplay.py
import time
import re
import difflib
import yt_dlp

from ..config import (
    AUTOPLAY_MAX_DURATION, AUTOPLAY_MIN_DURATION, AUTOPLAY_MIN_OVERLAP,
    AUTOPLAY_PARANOID, AUTOPLAY_DUP_SIM_THRESHOLD, AUTOPLAY_DUP_TOKEN_OVERLAP,
    AUTOPLAY_COOLDOWN, YTDL_OPTIONS
)

class AutoplayService:
    def __init__(self, mgr):
        self.mgr = mgr

    def _history_has(self, st, key: str) -> bool:
        return key in st.autoplay_history

    def _history_add(self, st, key: str, cap: int = 250):
        if not key:
            return
        if key in st.autoplay_history:
            return
        st.autoplay_history.append(key)
        if len(st.autoplay_history) > cap:
            st.autoplay_history = st.autoplay_history[-cap:]

    def _duration_ok(self, entry: dict) -> bool:
        if not entry:
            return False
        if entry.get("is_live") or entry.get("live_status") in ("is_live", "live"):
            return False
        dur = entry.get("duration", None)
        if dur is None:
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

    def _normalize_text(self, s: str) -> str:
        s = (s or "").lower()
        trash = [
            "official video", "official music video", "official audio", "audio",
            "lyrics", "lyric video", "video oficial", "videoclip", "visualizer",
            "explicit", "clean", "hq", "4k", "hd", "mv", "m/v"
        ]
        for t in trash:
            s = s.replace(t, "")

        s = s.replace("feat.", "feat").replace("ft.", "ft").replace("featuring", "feat")
        s = re.sub(r"\([^)]*\)", " ", s)
        s = re.sub(r"\[[^\]]*\]", " ", s)

        for ch in "{}|.,!?:;\"'`~@#$%^&*_+=<>/\\-":
            s = s.replace(ch, " ")

        return " ".join(s.split())

    def _core_title(self, title: str) -> str:
        t = self._normalize_text(title)
        drop = {
            "official", "video", "music", "audio", "lyrics", "lyric", "visualizer",
            "remix", "edit", "version", "ver", "mix", "extended", "radio", "live",
            "performance", "sped", "up", "slowed", "reverb", "bass", "boosted",
            "instrumental", "karaoke", "clean", "explicit", "tiktok",
            "prod", "producer", "produced",
        }
        tokens = [w for w in t.split() if w not in drop and len(w) > 1]
        return (" ".join(tokens)).strip()[:120]

    def _fingerprint(self, title: str, uploader: str) -> str:
        t = self._normalize_text(title)[:90]
        u = self._normalize_text(uploader)[:50]
        return f"{t}::{u}"

    def _seed_tokens(self, title: str, uploader: str) -> set:
        base = self._normalize_text(f"{title} {uploader}")
        return set(base.split())

    def _score_candidate(self, seed_tokens: set, cand_title: str, cand_uploader: str) -> int:
        cand_tokens = set(self._normalize_text(f"{cand_title} {cand_uploader}").split())
        return len(seed_tokens & cand_tokens)

    def _passes_strictness(self, overlap: int, seed_uploader: str, cand_title: str, cand_uploader: str) -> bool:
        if overlap >= AUTOPLAY_MIN_OVERLAP:
            return True
        su = self._normalize_text(seed_uploader)
        if not su:
            return False
        ct = self._normalize_text(cand_title)
        cu = self._normalize_text(cand_uploader)
        return bool(su and (su in cu or su in ct))

    def _near_duplicate_by_core(self, st, cand_title: str) -> bool:
        if not AUTOPLAY_PARANOID:
            return False
        core = self._core_title(cand_title)
        if not core or len(core) < 4:
            return False
        if core in st.autoplay_core_fingerprints:
            return True

        cand_tokens = set(core.split())
        if not cand_tokens:
            return False

        for prev in st.autoplay_recent_core_titles:
            if not prev:
                continue
            ratio = difflib.SequenceMatcher(None, core, prev).ratio()
            if ratio >= AUTOPLAY_DUP_SIM_THRESHOLD:
                return True
            prev_tokens = set(prev.split())
            if not prev_tokens:
                continue
            inter = len(cand_tokens & prev_tokens)
            union = len(cand_tokens | prev_tokens)
            if union > 0 and (inter / union) >= AUTOPLAY_DUP_TOKEN_OVERLAP:
                return True
        return False

    def _already_used(self, st, url: str, fp: str, cand_title: str = "") -> bool:
        if not url:
            return True
        if st.current_track and url == st.current_track:
            return True
        if url in st.song_queue:
            return True
        if fp in st.autoplay_fingerprints:
            return True
        if cand_title and self._near_duplicate_by_core(st, cand_title):
            return True
        return False

    def register_now_playing(self, st, data: dict):
        try:
            if not data:
                return

            url_now = (data.get("webpage_url") or data.get("url") or "").strip()
            vid_now = (data.get("id") or "").strip()
            title_now = data.get("title") or ""
            upl_now = data.get("uploader") or data.get("channel") or ""

            key_now = str(vid_now or url_now).strip()
            if key_now:
                self._history_add(st, key_now)

            fp_now = self._fingerprint(title_now, upl_now)
            if fp_now:
                st.autoplay_fingerprints.add(fp_now)

            core = self._core_title(title_now)
            if core:
                st.autoplay_core_fingerprints.add(core)
                st.autoplay_recent_core_titles.append(core)

        except Exception as e:
            print(f"⚠️ register_now_playing error: {e}")

    async def _search_youtube(self, query: str):
        loop = self.mgr.bot.loop
        try:
            ytdl_local = yt_dlp.YoutubeDL(YTDL_OPTIONS)
            info = await loop.run_in_executor(None, lambda: ytdl_local.extract_info(query, download=False))
            return (info or {}).get("entries") or []
        except Exception as e:
            print(f"❌ Autoplay search error: {e}")
            return []

    async def get_candidate(self, st, seed_data: dict):
        if not seed_data:
            return None

        seed_title = (seed_data.get("title") or "").strip()
        seed_uploader = (seed_data.get("uploader") or "").strip()
        seed_url = (seed_data.get("webpage_url") or "").strip()
        seed_id = seed_data.get("id")

        if not seed_title and not seed_uploader:
            return None

        seed_tokens = self._seed_tokens(seed_title, seed_uploader)

        # related_videos
        if seed_url:
            try:
                ytdl_local = yt_dlp.YoutubeDL(YTDL_OPTIONS)
                info = await self.mgr.bot.loop.run_in_executor(None, lambda: ytdl_local.extract_info(seed_url, download=False))
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

                    if AUTOPLAY_PARANOID:
                        if self._near_duplicate_by_core(st, cand_title):
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

                    if self._history_has(st, key):
                        continue
                    if self._already_used(st, url, fp, cand_title=cand_title):
                        continue

                    if overlap > best_overlap:
                        best_overlap = overlap
                        best = (url, fp, key, cand_title)

                if best:
                    url, fp, key, cand_title = best
                    self._history_add(st, key)
                    st.autoplay_fingerprints.add(fp)

                    if AUTOPLAY_PARANOID:
                        core = self._core_title(cand_title)
                        if core:
                            st.autoplay_core_fingerprints.add(core)
                            st.autoplay_recent_core_titles.append(core)

                    return url

            except Exception as e:
                print(f"❌ related_videos error: {e}")

        # fallback
        st._autoplay_flip = not st._autoplay_flip

        if st._autoplay_flip:
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

                if AUTOPLAY_PARANOID:
                    if self._near_duplicate_by_core(st, cand_title):
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

                if self._history_has(st, key):
                    continue
                if self._already_used(st, url, fp, cand_title=cand_title):
                    continue

                if overlap > best_overlap:
                    best_overlap = overlap
                    best = (url, fp, key, cand_title)

        if best:
            url, fp, key, cand_title = best
            self._history_add(st, key)
            st.autoplay_fingerprints.add(fp)

            if AUTOPLAY_PARANOID:
                core = self._core_title(cand_title)
                if core:
                    st.autoplay_core_fingerprints.add(core)
                    st.autoplay_recent_core_titles.append(core)

            return url

        return None

    async def ensure(self, ctx, st, seed_data: dict, has_listeners_fn):
        if not st.autoplay_enabled:
            return
        if st.song_queue:
            return
        if not ctx.voice_client:
            return
        if not has_listeners_fn(ctx.voice_client):
            return

        async with st.autoplay_lock:
            if not st.autoplay_enabled or st.song_queue or not ctx.voice_client:
                return
            if not has_listeners_fn(ctx.voice_client):
                return

            now = time.time()
            if now - st.last_autoplay_time < AUTOPLAY_COOLDOWN:
                return
            st.last_autoplay_time = now

            candidate = await self.get_candidate(st, seed_data)
            if not candidate:
                return

            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                return

            await self.mgr.player.play_music(ctx, st, candidate)
