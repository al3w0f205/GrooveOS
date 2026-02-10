# musicbot/spotify.py
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from urllib import request, parse, error

# Aceptamos track, album o playlist
SPOTIFY_URL_RE = re.compile(
    r"https?://open\.spotify\.com/(?P<kind>track|album|playlist)/(?P<id>[A-Za-z0-9]+)"
)

# ====== Credenciales de App (Client Credentials) ======
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

ACCOUNTS_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

# ================== Modelo ==================
@dataclass
class SpotifyItem:
    title: str
    query: str  # query que usaremos en YouTube (artist - track)
    raw: Dict[str, Any]

# ================== Cliente Spotify API (client credentials) ==================
class _SpotifyAPI:
    """
    Cliente mínimo Spotify Web API (Client Credentials).
    Lee metadata pública (tracks, albums y playlists).
    Maneja 429 Retry-After + 401 refrescando token.
    """

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: Optional[str] = None
        self._token_exp: float = 0.0

    # --- Token handling ---
    def _have_token(self) -> bool:
        return bool(self._access_token) and (time.time() < self._token_exp - 30)

    def _fetch_token(self) -> None:
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "Faltan credenciales. Define SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET."
            )
        data = parse.urlencode({"grant_type": "client_credentials"}).encode()
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        req = request.Request(
            ACCOUNTS_TOKEN_URL,
            data=data,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        self._access_token = payload["access_token"]
        self._token_exp = time.time() + float(payload.get("expires_in", 3600))

    def _headers(self) -> Dict[str, str]:
        if not self._have_token():
            self._fetch_token()
        return {"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}

    # --- HTTP helper con reintentos 429/401 ---
    def _get_json(
        self,
        path: str,
        query: Optional[Dict[str, Any]] = None,
        _retry: int = 0
    ) -> Dict[str, Any]:
        url = f"{SPOTIFY_API_BASE}{path}"
        if query:
            url += "?" + parse.urlencode(query)
        req = request.Request(url, headers=self._headers())
        try:
            with request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as e:
            # 429 Rate-Limit → respeta Retry-After (hasta 3 reintentos)
            if e.code == 429 and _retry < 3:
                retry_after = float(e.headers.get("Retry-After", "1"))
                time.sleep(retry_after)
                return self._get_json(path, query, _retry=_retry + 1)
            # 401 (token caducado/invalidado) → renueva y reintenta 1 vez
            if e.code == 401 and _retry < 1:
                self._access_token = None
                return self._get_json(path, query, _retry=_retry + 1)
            # 403/404 u otros → propaga con detalle del cuerpo
            data = e.read().decode("utf-8") if e.fp else ""
            try:
                j = json.loads(data) if data else {}
            except Exception:
                j = {"error": {"status": e.code, "message": data or "HTTP error"}}
            # Mensaje más claro para privados/no accesibles
            if e.code in (403, 404):
                kind_hint = "recurso no accesible (privado o inexistente)"
                raise RuntimeError(f"Spotify API {e.code}: {kind_hint}. Detalle: {j}") from None
            raise RuntimeError(f"Spotify API error {e.code}: {j}") from None

    # --- Endpoints que usamos ---
    def get_track(self, track_id: str) -> Dict[str, Any]:
        return self._get_json(f"/tracks/{track_id}")

    def get_playlist_track_items(self, playlist_id: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return self._get_json(f"/playlists/{playlist_id}/tracks", {"limit": limit, "offset": offset})

    def get_all_playlist_tracks(self, playlist_id: str, page_limit: int = 100) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        offset = 0
        while True:
            page = self.get_playlist_track_items(playlist_id, page_limit, offset)
            page_items = page.get("items") or []
            items.extend(page_items)
            if not page.get("next"):
                break
            offset += page_limit
        return items

    def get_album(self, album_id: str) -> Dict[str, Any]:
        return self._get_json(f"/albums/{album_id}")

    def get_album_tracks(self, album_id: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        return self._get_json(f"/albums/{album_id}/tracks", {"limit": limit, "offset": offset})

    def get_all_album_tracks(self, album_id: str, page_limit: int = 50) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        offset = 0
        while True:
            page = self.get_album_tracks(album_id, limit=page_limit, offset=offset)
            page_items = page.get("items") or []
            items.extend(page_items)
            if not page.get("next"):
                break
            offset += page_limit
        return items

# ================== Resolver principal ==================
class SpotifyResolver:
    """
    Resuelve links de Spotify SOLO con la API (sin scraping).
    Soporta: track, album y playlist.
    Interfaz: is_spotify_url() + resolve().
    """

    def __init__(self):
        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
            raise RuntimeError(
                "SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET no definidos. "
                "Configúralos en el entorno para usar la API."
            )
        self._api = _SpotifyAPI(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)

    # ---- utilidades de parsing ----
    def is_spotify_url(self, text: str) -> Optional[str]:
        """
        Devuelve la URL si es de Spotify (track|album|playlist), None si no matchea.
        """
        m = SPOTIFY_URL_RE.search(text or "")
        return m.group(0) if m else None

    def _parse_kind_id(self, spotify_url: str) -> Optional[Tuple[str, str]]:
        m = SPOTIFY_URL_RE.search(spotify_url or "")
        if not m:
            return None
        return m.group("kind"), m.group("id")

    # ---- Resolución por API ----
    async def resolve(self, spotify_url: str) -> List[SpotifyItem]:
        """
        Devuelve una lista de SpotifyItem basados en metadata oficial (sin scraping).
        - track → 1 item
        - album → items por cada track del álbum
        - playlist → items por cada track de la playlist
        """
        kind_id = self._parse_kind_id(spotify_url)
        if not kind_id:
            return []
        kind, sid = kind_id

        if kind == "track":
            return await asyncio.to_thread(self._resolve_track_api, sid)
        elif kind == "album":
            return await asyncio.to_thread(self._resolve_album_api, sid)
        else:  # playlist
            return await asyncio.to_thread(self._resolve_playlist_api, sid)

    # -------- Implementación con Spotify API --------
    def _resolve_track_api(self, track_id: str) -> List[SpotifyItem]:
        t = self._api.get_track(track_id)
        if not t or t.get("type") != "track":
            return []
        name = t.get("name") or "Spotify Track"
        artists = ", ".join(a.get("name") for a in (t.get("artists") or []) if a and a.get("name"))
        query = f"{artists} - {name}" if artists else name
        return [SpotifyItem(title=name, query=query, raw=t)]

    def _resolve_album_api(self, album_id: str) -> List[SpotifyItem]:
        # Puedes consultar metadata del álbum si la necesitas:
        # album_info = self._api.get_album(album_id)
        tracks = self._api.get_all_album_tracks(album_id)
        out: List[SpotifyItem] = []
        for track in tracks:
            if not track or track.get("type") != "track":
                continue
            name = track.get("name") or "Spotify Track"
            artists = ", ".join(a.get("name") for a in (track.get("artists") or []) if a and a.get("name"))
            query = f"{artists} - {name}" if artists else name
            out.append(SpotifyItem(title=name, query=query, raw=track))
        return out

    def _resolve_playlist_api(self, playlist_id: str) -> List[SpotifyItem]:
        tracks = self._api.get_all_playlist_tracks(playlist_id)
        out: List[SpotifyItem] = []
        for it in tracks:
            track = (it or {}).get("track") or {}
            if not track or track.get("is_local") or track.get("type") != "track":
                continue
            name = track.get("name") or "Spotify Track"
            artists = ", ".join(a.get("name") for a in (track.get("artists") or []) if a and a.get("name"))
            query = f"{artists} - {name}" if artists else name
            out.append(SpotifyItem(title=name, query=query, raw=track))
        return out