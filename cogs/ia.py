import discord
from discord.ext import commands
from discord import app_commands
import os
import sqlite3
import datetime
from groq import Groq

# Configuración de la base de datos
DB_PATH = "ia_history.db"

class IAChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = "llama-3.3-70b-versatile"
        
        # Inicializar Cliente Groq
        if not self.api_key:
            print("⚠️ ADVERTENCIA: No se encontró GROQ_API_KEY. El módulo IA_Chat no funcionará correctamente.")
            self.client = None
        else:
            self.client = Groq(api_key=self.api_key)

        # Inicializar Base de Datos
        self.init_db()

    def init_db(self):
        """Crea la tabla de historial si no existe."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def get_user_history(self, user_id, limit=10):
        """Recupera los últimos 'limit' mensajes del usuario para dar contexto."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Obtenemos los últimos X mensajes ordenados por fecha
        cursor.execute('''
            SELECT role, content 
            FROM chat_history 
            WHERE user_id = ? 
            ORDER BY id DESC LIMIT ?
        ''', (user_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        # SQLite los devuelve del más nuevo al más viejo, hay que invertirlo para la IA
        history = [{"role": row[0], "content": row[1]} for row in rows]
        return history[::-1]

    def save_interaction(self, user_id, user_content, ai_content):
        """Guarda tanto el mensaje del usuario como la respuesta de la IA."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)', (user_id, "user", user_content))
        cursor.execute('INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)', (user_id, "assistant", ai_content))
        conn.commit()
        conn.close()

    def clear_user_history(self, user_id):
        """Borra el historial de un usuario específico."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM chat_history WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

    async def enviar_respuesta_fragmentada(self, ctx, texto):
        """
        Envía respuestas largas (>2000 caracteres) en múltiples mensajes.
        Maneja tanto contextos de Slash como de Prefijo.
        """
        max_chars = 1900 # Margen de seguridad
        if len(texto) <= max_chars:
            if ctx.interaction and not ctx.interaction.response.is_done():
                await ctx.send(texto) # Si es slash y no se ha respondido
            else:
                await ctx.channel.send(texto) # Si es prefijo o slash ya diferido
        else:
            # Fragmentar
            partes = [texto[i:i+max_chars] for i in range(0, len(texto), max_chars)]
            for parte in partes:
                await ctx.channel.send(parte)

    @commands.hybrid_command(name="ia", description="Habla con la IA (Llama 3 via Groq). Recuerda la conversación.")
    @app_commands.describe(mensaje="Tu mensaje para la IA")
    async def ia(self, ctx, *, mensaje: str):
        """
        Comando principal de chat. 
        Uso: .ia Hola o /ia mensaje:Hola
        """
        if not self.client:
            return await ctx.send("❌ Error: API Key de Groq no configurada.")

        # Feedback visual de que está "pensando"
        if ctx.interaction:
            await ctx.defer() # Necesario para slash commands que tardan
        else:
            async with ctx.typing():
                pass

        try:
            # 1. Recuperar contexto histórico
            historial = self.get_user_history(ctx.author.id, limit=6) # 6 mensajes previos de contexto

            # 2. Construir la estructura de mensajes para Groq
            messages_payload = [
                {"role": "system", "content": "Eres un asistente útil, preciso y amable en Discord. Responde siempre en español. Sé conciso."}
            ]
            messages_payload.extend(historial)
            messages_payload.append({"role": "user", "content": mensaje})

            # 3. Llamada a la API (en un hilo aparte para no bloquear el bot)
            chat_completion = await self.bot.loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    messages=messages_payload,
                    model=self.model,
                    temperature=0.7,
                    max_tokens=1024
                )
            )
            
            respuesta = chat_completion.choices[0].message.content

            # 4. Guardar en base de datos
            self.save_interaction(ctx.author.id, mensaje, respuesta)

            # 5. Enviar respuesta
            await self.enviar_respuesta_fragmentada(ctx, respuesta)

        except Exception as e:
            error_msg = f"❌ Ocurrió un error al procesar tu solicitud: {e}"
            print(error_msg)
            if ctx.interaction and not ctx.interaction.response.is_done():
                await ctx.send(error_msg, ephemeral=True)
            else:
                await ctx.channel.send(error_msg)

    @commands.hybrid_command(name="ia_reset", description="Borra tu historial de conversación con la IA.")
    async def ia_reset(self, ctx):
        """Limpia la memoria de la base de datos para el usuario."""
        try:
            self.clear_user_history(ctx.author.id)
            embed = discord.Embed(
                title="🧠 Memoria borrada",
                description="He olvidado nuestra conversación anterior. Empezamos de nuevo.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error al borrar historial: {e}")

async def setup(bot):
    await bot.add_cog(IAChat(bot))