import discord
import datetime

# =========================
# 🎨 TEMA GLOBAL (Estilo A)
# =========================
THEME = {
    "primary": discord.Color.blurple(),
    "success": discord.Color.green(),
    "danger": discord.Color.red(),
    "warning": discord.Color.orange(),
    "neutral": discord.Color.dark_grey(),
}

def user_footer(ctx, extra: str | None = None):
    """
    Footer consistente con avatar del usuario.
    Compatible con comandos de prefijo y comandos híbridos (Slash).
    """
    base = f"Solicitado por {ctx.author}"
    text = f"{base} • {extra}" if extra else base
    
    # Obtenemos el avatar de forma segura
    icon_url = ctx.author.display_avatar.url if ctx.author.display_avatar else None
    
    return {"text": text, "icon_url": icon_url}

def clean_query(text: str) -> str:
    """Evita que el texto rompa embeds o se vea gigante."""
    text = (text or "").strip()
    if not text:
        return "Desconocido"
    return text[:200] + "…" if len(text) > 200 else text

def fmt_time(seconds: int) -> str:
    """Convierte segundos a formato reloj -> 0:00 / 1:23:45"""
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def progress_bar(elapsed: float, total: float, length: int = 18):
    """Barra minimalista tipo Spotify: ▬▬▬🔘▬▬▬ + porcentaje."""
    if total <= 0:
        return "🔘" + "▬" * (length - 1), 0

    elapsed = max(0.0, min(float(elapsed), float(total)))
    ratio = elapsed / total
    pos = min(int(ratio * length), length - 1)

    bar = "▬" * pos + "🔘" + "▬" * (length - 1 - pos)
    return bar, int(ratio * 100)

def short_queue_preview(queue: list[str], limit: int = 3) -> str:
    """Preview elegante de próximas canciones para embeds."""
    if not queue:
        return "—"
    items = queue[:limit]
    lines = [f"`{i+1}.` {clean_query(q)}" for i, q in enumerate(items)]
    extra = len(queue) - limit
    if extra > 0:
        lines.append(f"*…y **{extra}** más.*")
    return "\n".join(lines)

def build_embed(title: str, desc: str = "", color: discord.Color | None = None):
    """Constructor base para embeds consistentes en todo GrooveOS."""
    e = discord.Embed(
        title=title,
        description=desc,
        color=color or THEME["primary"],
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    return e