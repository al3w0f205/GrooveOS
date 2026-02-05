# cogs/music/services/panel.py
from __future__ import annotations
import time
import discord
from cogs.utilidad import THEME, user_footer, fmt_time, short_queue_preview

def build_now_playing_embed(ctx, *, data: dict, queue: list[str], loop_enabled: bool, autoplay_enabled: bool,
                           start_time: float, duration: int, paused: bool):
    dur = int(duration or 0)

    title = data.get("title", "Desconocido")
    url = data.get("webpage_url") or data.get("url") or ""
    thumb = data.get("thumbnail")
    uploader = data.get("uploader") or data.get("channel") or "Desconocido"

    elapsed = int(time.time() - float(start_time or time.time()))
    elapsed = max(0, min(elapsed, dur)) if dur else max(0, elapsed)
    remaining = max(0, dur - elapsed) if dur else 0

    estado = "⏸️ Pausado" if paused else "▶️ Reproduciendo"
    color = THEME["warning"] if paused else THEME["primary"]

    loop_txt = "ON ✅" if loop_enabled else "OFF ❌"
    auto_txt = "ON ✅" if autoplay_enabled else "OFF ❌"

    desc = (
        f"**{estado}**\n"
        f"👤 **Artista/Canal:** `{uploader}`\n"
        f"──────────────\n"
    )

    embed = discord.Embed(title=f"🎶 {title}", url=url, description=desc, color=color)
    if thumb:
        embed.set_thumbnail(url=thumb)

    embed.add_field(
        name="⏱️ Tiempo",
        value=(
            f"🕒 **Transcurrido:** `{fmt_time(elapsed)}`\n"
            f"⏳ **Duración:** `{fmt_time(dur)}`\n"
            f"⌛ **Restante:** `{fmt_time(remaining)}`"
        ),
        inline=False
    )

    embed.add_field(
        name="📜 Próximas",
        value=f"{short_queue_preview(queue, limit=3)}\n\u200b",
        inline=False
    )

    embed.set_footer(**user_footer(ctx, f"Loop: {loop_txt} • Auto: {auto_txt}"))
    return embed