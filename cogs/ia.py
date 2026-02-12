import discord
from discord.ext import commands
import aiohttp
import json
import asyncio

class InteligenciaArtificial(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_ip = "192.168.100.253"
        self.api_port = "11434"
        self.default_model = "llama3.2:1b"
        
        # 🧠 MEMORIA RAM
        self.historial = {} 

        # 👑 PERSONALIDAD SIMPLIFICADA (Para que el modelo 1b no se confunda)
        self.system_prompt = (
            "Eres un asistente útil llamado GrooveOS. "
            "Responde de forma corta y directa. "
            "Recuerda lo que te dice el usuario en esta conversación."
        )

    @commands.command(name="ia", aliases=["gpt", "chat"])
    async def chat_ia(self, ctx, *, prompt: str):
        """Conversación continua con memoria."""
        
        cid = ctx.channel.id

        # 1. Inicializar memoria si es nueva
        if cid not in self.historial:
            self.historial[cid] = [
                {"role": "system", "content": self.system_prompt}
            ]

        # 2. Guardar mensaje del usuario (SIN el nombre para no confundir a la IA)
        self.historial[cid].append({"role": "user", "content": prompt})

        # 🧹 Limpieza (Mantiene últimos 10 mensajes)
        if len(self.historial[cid]) > 12: 
            self.historial[cid].pop(1)
            self.historial[cid].pop(1)

        # 🔍 DEBUG: Mira tu consola para ver si la memoria crece
        print(f"📝 [Memoria Canal {cid}] Mensajes guardados: {len(self.historial[cid])}")

        async with ctx.typing():
            try:
                url = f"http://{self.api_ip}:{self.api_port}/api/chat"
                
                payload = {
                    "model": self.default_model,
                    "messages": self.historial[cid], # Enviamos TODO el historial
                    "stream": False,
                    "options": {"temperature": 0.7} # Creatividad balanceada
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=60) as response:
                        if response.status == 200:
                            data = await response.json()
                            respuesta_obj = data.get("message", {})
                            respuesta_texto = respuesta_obj.get("content", "")
                            
                            if not respuesta_texto:
                                await ctx.reply("🤔 (Sin respuesta)", mention_author=True)
                                return

                            # 3. Guardar respuesta de la IA en memoria
                            self.historial[cid].append({"role": "assistant", "content": respuesta_texto})

                            # Paginación
                            if len(respuesta_texto) > 1900:
                                chunks = [respuesta_texto[i:i+1900] for i in range(0, len(respuesta_texto), 1900)]
                                for i, chunk in enumerate(chunks):
                                    if i == 0: await ctx.reply(chunk + " ...", mention_author=True)
                                    else: await ctx.send(chunk)
                            else:
                                await ctx.reply(respuesta_texto, mention_author=True)
                        else:
                            # Si falla, borramos el último mensaje para no romper la cadena
                            self.historial[cid].pop()
                            await ctx.reply(f"⚠️ Error {response.status}", mention_author=True)
            
            except Exception as e:
                if cid in self.historial: self.historial[cid].pop()
                await ctx.reply(f"❌ Error: {e}", mention_author=True)

    @commands.command(name="reset")
    async def reset_memory(self, ctx):
        cid = ctx.channel.id
        if cid in self.historial:
            del self.historial[cid]
            await ctx.send("🧠 Memoria borrada.")
        else:
            await ctx.send("ℹ️ No había nada que borrar.")

    @commands.command(name="modelos")
    async def listar_modelos(self, ctx):
        url = f"http://{self.api_ip}:{self.api_port}/api/tags"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        names = [m['name'] for m in data.get('models', [])]
                        await ctx.send(f"🧠 Modelos: {', '.join(names)}")
        except:
            await ctx.send("❌ Sin conexión.")

async def setup(bot):
    await bot.add_cog(InteligenciaArtificial(bot))