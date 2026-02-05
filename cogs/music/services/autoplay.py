# cogs/music/services/autoplay.py
from __future__ import annotations
import time
import difflib
import re
import yt_dlp

from .config import (
    YTDL_OPTIONS,
    AUTOPLAY_MIN_DURATION, AUTOPLAY_MAX_DURATION,
    AUTOPLAY_COOLDOWN,
    AUTOPLAY_PARANOID, AUTOPLAY_DUP_SIM_THRESHOLD
)

def _normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return " ".join(s.split())

def fingerprint(title: str, uploader: str) -> str:
    return f"{_normalize(title)[:90]}::{_normalize(uploader)[:50]}"

def duration_ok(entry: dict) -> bool:
    if not entry:
        return False
    if entry.get("is_live") or entry.get("live_status") in ("is_live", "live"):
        return False
    dur = entry.get("duration")
    try:
        dur = int(dur)
    except Exception:
        return False
    return AUTOPLAY_MIN_DURATION <= dur <= AUTOPLAY_MAX_DURATION

async def _search(loop, query: str):
    def extract():
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
            info = ydl.extract_info(query, download=False)
            return (info or {}).get("entries") or []
    return await loop.run_in_executor(None, extract)

def cooldown_ok(state) -> bool:
    now = time.time()
    if now - float(state.last_autoplay_time or 0.0) < AUTOPLAY_COOLDOWN:
        return False
    state.last_autoplay_time = now
    return True

async def pick_candidate(loop, state, seed_data: dict) -> str | None:
    seed_title = (seed_data.get("title") or "").strip()
    seed_uploader = (seed_data.get("uploader") or seed_data.get("channel") or "").strip()
    seed_id = seed_data.get("id")

    if not seed_title and not seed_uploader:
        return None

    query = f"ytsearch12:{seed_title} {seed_uploader} audio".strip()
    entries = await _search(loop, query)

    for e in entries:
        if not duration_ok(e):
            continue
        url = e.get("webpage_url") or e.get("url")
        vid = e.get("id")
        if not url:
            continue
        if seed_id and vid == seed_id:
            continue

        fp = fingerprint(e.get("title") or "", e.get("uploader") or e.get("channel") or "")
        key = str(vid or url)

        if key in state.autoplay_history:
            continue
        if fp in state.autoplay_fingerprints:
            continue

        if AUTOPLAY_PARANOID:
            ratio = difflib.SequenceMatcher(None, _normalize(seed_title), _normalize(e.get("title") or "")).ratio()
            if ratio >= AUTOPLAY_DUP_SIM_THRESHOLD:
                continue

        state.autoplay_history.append(key)
        state.autoplay_fingerprints.add(fp)
        if len(state.autoplay_history) > 250:
            state.autoplay_history = state.autoplay_history[-250:]

        return url

    return None