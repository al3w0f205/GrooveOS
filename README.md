# GrooveOS - Discord Bot - Gestión Proxmox & Música

GrooveOS es un bot de Discord desarrollado en Python con una arquitectura **modular (Cogs)**. Su función principal es permitir la gestión remota de servidores de Minecraft alojados en contenedores **LXC de Proxmox**, además de ofrecer un sistema completo de música.

## 🛠️ Tecnologías Utilizadas
* **Lenguaje:** Python 3.10+
* **Librería de Discord:** discord.py
* **Infraestructura:** Proxmox VE (API)
* **Gestión de Minecraft:** Crafty Controller API
* **Audio:** yt-dlp & FFmpeg

## 🏗️ Arquitectura del Proyecto
El bot utiliza un sistema de **Cogs** para separar las responsabilidades y facilitar el mantenimiento:
* `main.py`: El punto de entrada que carga los módulos y gestiona la conexión segura mediante variables de entorno.
* `cogs/minecraft.py`: Controla el encendido del contenedor LXC 101 en Proxmox y el arranque del servidor mediante la API de Crafty.
* `cogs/musica.py`: Maneja la reproducción de audio, colas de reproducción y streaming desde diversas plataformas.

## 🎮 Comandos Principales
* `.minecraft` o `.mc`: Despliega un panel interactivo con botones para iniciar el servidor de supervivencia.
* `.p [búsqueda/link]`: Busca y reproduce música en el canal de voz actual.
* `.stop`: Detiene la música y limpia la cola de reproducción.
* `.join`: Une al bot al canal de voz del usuario.
* `.skip` - Salta a la siguiente canción.

## 🔒 Seguridad
Este proyecto implementa buenas prácticas de seguridad mediante el uso de archivos `.env` para ocultar tokens de acceso y credenciales de servidor, los cuales están protegidos mediante el archivo `.gitignore`.
