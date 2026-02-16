# cogs/comandos.py
import discord
from discord.ext import commands
from .utilidad import THEME, user_footer, build_embed, clean_query

class Comandos(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # =============================
    # INFO
    # =============================
    @commands.hybrid_command(
        name="info",
        description="Muestra información técnica y del desarrollo de GrooveOS"
    )
    async def info(self, ctx: commands.Context):
        embed = build_embed(
            "🤖 GrooveOS 2.0",
            "Tu bot personal de música y utilidad, optimizado y modular.",
            color=THEME["primary"]
        )
        embed.add_field(name="Versión", value="2.0.0-Beta", inline=True)
        embed.add_field(name="Prefijo", value="`.`", inline=True)
        embed.add_field(name="Desarrollador", value="Alejandro", inline=False)
        embed.set_footer(**user_footer(ctx, "Proyecto personal de ingeniería"))
        await ctx.send(embed=embed)

    # =============================
    # DEBUG: lista comandos (prefijo)
    # =============================
    @commands.command(name="debugcmds")
    @commands.is_owner()
    async def debugcmds(self, ctx: commands.Context):
        """Lista todos los comandos registrados en bot.commands."""
        lines = []
        for c in self.bot.commands:
            # c puede ser commands.Command o commands.HybridCommand
            lines.append(f"- {c.qualified_name}  (cog={c.cog_name}, hidden={c.hidden}, cls={c.__class__.__name__})")

        text = "Comandos registrados:\n" + "\n".join(sorted(lines))
        # Discord tiene límite ~2000 caracteres; partimos si hace falta.
        if len(text) < 1900:
            await ctx.send(f"```\n{text}\n```")
        else:
            chunks = [text[i:i+1800] for i in range(0, len(text), 1800)]
            for ch in chunks:
                await ctx.send(f"```\n{ch}\n```")

    # =============================
    # DEBUG: lista slash globales
    # =============================
    @commands.command(name="debugslash")
    @commands.is_owner()
    async def debugslash(self, ctx: commands.Context):
        """Lista los slash commands globales registrados en app_commands."""
        cmds = await self.bot.tree.fetch_commands()  # globales
        lines = [f"- /{c.name} (type={c.type}, default_perms={c.default_member_permissions})" for c in cmds]
        text = "Slash globales:\n" + "\n".join(lines or ["(vacío)"])
        await ctx.send(f"```\n{text}\n```")

    # =============================
    # QUEUE
    # =============================
    @commands.hybrid_command(
        name="queue",
        aliases=["q", "cola"],
        description="Muestra la lista actual de canciones en espera"
    )
    async def queue(self, ctx: commands.Context):
        """Cola actual de canciones (por servidor), leyendo directamente del player."""
        try:
            # 1) Validaciones básicas
            if not ctx.guild:
                return await ctx.send("⚠️ Este comando solo funciona en servidores (no en DMs).")

            musica_cog = self.bot.get_cog("Musica")
            if not musica_cog:
                return await ctx.send("⚠️ No encontré el módulo de música cargado.")

            # 2) Obtener el player REAL del guild actual
            player = musica_cog.service.get_player(ctx.guild.id)
            if not player:
                return await ctx.send("⚠️ No pude acceder al reproductor de este servidor.")

            current = getattr(player, "current", None)
            queue_list = list(getattr(player, "queue", []))

            # 3) Si no hay nada realmente
            if not current and not queue_list:
                embed = build_embed(
                    "📭 Cola Vacía",
                    "No hay canciones en espera.\nUsa `.p <nombre/url>` para agregar música.",
                    color=THEME["warning"]
                )
                embed.set_footer(**user_footer(ctx))
                return await ctx.send(embed=embed)

            # 4) Ahora sonando
            ahora_txt = ""
            if current:
                titulo_actual = getattr(current, "title", None) or getattr(current, "query", "Desconocido")
                ahora_txt = f"🎧 **Ahora sonando:** `{clean_query(titulo_actual)}`\n\n"

            # 5) Lista de siguientes en cola (no incluye la actual)
            max_items = 10
            items = queue_list[:max_items]
            if items:
                lista_cola = "\n".join(
                    [f"**{i}.** {clean_query(getattr(t, 'title', None) or getattr(t, 'query', 'Desconocido'))}"
                     for i, t in enumerate(items, start=1)]
                )
                extra = max(len(queue_list) - max_items, 0)
                if extra > 0:
                    lista_cola += f"\n\n*…y **{extra}** canciones más.*"
            else:
                lista_cola = "_(sin más canciones en cola)_"

            embed = build_embed(
                "🎶 Cola de Reproducción",
                ahora_txt + lista_cola,
                color=THEME["success"]
            )
            embed.set_footer(**user_footer(ctx))
            await ctx.send(embed=embed)

        except Exception as e:
            # Mensaje visible en el canal para no “morir en silencio”
            try:
                await ctx.send(f"❌ Error al mostrar la cola: `{e}`")
            except:
                pass
            # Y log en consola
            import traceback
            print("[queue][ERROR]", e)
            traceback.print_exc()

async def setup(bot: commands.Bot):
    await bot.add_cog(Comandos(bot))