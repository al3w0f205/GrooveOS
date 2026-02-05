# musicbot/views.py
from __future__ import annotations

import discord
from typing import Optional

from cogs.utilidad import THEME, build_embed, clean_query, fmt_time, short_queue_preview


def build_player_embed(guild: discord.Guild, player) -> discord.Embed:
    connected = player.is_connected()
    playing = player.is_playing()
    paused = player.is_paused()
    channel = player.voice.channel.name if player.voice else "—"

    embed = build_embed(
        "🎶 GrooveOS Player",
        f"connected={connected} playing={playing} paused={paused} channel={channel}",
        color=THEME["primary"]
    )

    cur = player.current
    if cur:
        status = "▶️ Reproduciendo" if playing else ("⏸️ Pausado" if paused else "⏹️ Detenido")
        embed.add_field(
            name=status,
            value=f"**{clean_query(cur.title)}**\n" + (f"<{cur.webpage_url}>" if cur.webpage_url else ""),
            inline=False
        )
        embed.add_field(name="⏱️ Duración", value=fmt_time(cur.duration) if cur.duration else "—", inline=True)
        embed.add_field(name="🙋 Pedido por", value=cur.requester_name or "—", inline=True)

        if cur.thumbnail:
            embed.set_thumbnail(url=cur.thumbnail)
    else:
        embed.add_field(name="—", value="No hay nada sonando.", inline=False)

    upcoming = [t.title for t in list(player.queue)]
    embed.add_field(name="📜 Próximas", value=short_queue_preview(upcoming, limit=3), inline=False)

    loop_state = "🎵" if player.loop_track else ("📜" if player.loop_queue else "OFF")
    embed.set_footer(text=f"Loop: {loop_state} • Prefetch: ON")
    return embed


class MusicControls(discord.ui.View):
    """
    View persistente (timeout=None).
    Usa custom_id fijos para que Discord reconozca los botones.
    """

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog  # cogs.musica.Musica

    async def _player(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("❌ Solo en servidores.", ephemeral=True)
            return None
        return self.cog.service.get_player(interaction.guild.id)

    @discord.ui.button(label="Pausa/Resume", style=discord.ButtonStyle.primary, emoji="⏯️", custom_id="music:pause_resume")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self._player(interaction)
        if not player:
            return
        ok, msg = await player.toggle_pause()
        await interaction.response.send_message(("✅ " if ok else "ℹ️ ") + msg, ephemeral=True)
        await self.cog.refresh_panel(interaction.guild)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️", custom_id="music:skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self._player(interaction)
        if not player:
            return
        ok, msg = await player.skip()
        await interaction.response.send_message(("✅ " if ok else "ℹ️ ") + msg, ephemeral=True)
        await self.cog.refresh_panel(interaction.guild)

    @discord.ui.button(label="Loop", style=discord.ButtonStyle.secondary, emoji="🔁", custom_id="music:loop")
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self._player(interaction)
        if not player:
            return
        state = player.toggle_loop_mode()
        await interaction.response.send_message("🔁 " + state, ephemeral=True)
        await self.cog.refresh_panel(interaction.guild)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", custom_id="music:stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = await self._player(interaction)
        if not player:
            return
        ok, msg = await player.stop()
        await interaction.response.send_message(("✅ " if ok else "ℹ️ ") + msg, ephemeral=True)
        await self.cog.refresh_panel(interaction.guild)