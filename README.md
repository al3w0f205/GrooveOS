# GrooveOS

![Build Status](https://img.shields.io/badge/build-passing-brightgreen)
![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![C++ Standard](https://img.shields.io/badge/std-c%2B%2B17-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-active%20development-orange)

GrooveOS es un ecosistema operativo de alto rendimiento para la gestión de comunidades en Discord. Su arquitectura híbrida combina la velocidad de **C++** en el kernel para el procesamiento de datos con la flexibilidad de **Python** para la lógica de negocio, ofreciendo una solución escalable superior a los bots convencionales.

---

## Tabla de Contenidos

- [GrooveOS](#grooveos)
  - [Tabla de Contenidos](#tabla-de-contenidos)
  - [Características Principales](#características-principales)
  - [Arquitectura Técnica](#arquitectura-técnica)
  - [Estructura del Repositorio](#estructura-del-repositorio)

---

## Características Principales

* **Procesamiento Asíncrono Híbrido:** Delegación de tareas pesadas al núcleo de C++ para evitar bloqueos en el bucle de eventos principal de Discord.
* **Persistencia Atómica:** Sistema de base de datos SQLite con transacciones seguras (ACID) para proteger los datos de usuario ante fallos.
* **Sistema de Audio de Baja Latencia:** Motor de streaming optimizado con gestión de colas dinámicas.
* **Modularidad (Hot-Pluggable):** Capacidad de recargar módulos de Python (Cogs) sin detener el núcleo del sistema.

---

## Arquitectura Técnica

El sistema opera bajo un modelo de capas estrictas:

1.  **Kernel (C++ / `/Kernel`):**
    * Gestión de memoria y recursos del sistema.
    * Comunicación Inter-Procesos (IPC) para orquestar servicios.
2.  **Capa de Servicios (Python / `Cogs`):**
    * `musica.py`: Streaming, filtros de audio y control de voz.
    * `perfiles.py`: Algoritmo de nivelación y almacenamiento de XP.
    * `utilidad.py`: Herramientas administrativas y logs de auditoría.
3.  **Capa de Datos:**
    * SQLite3 integrado para almacenamiento local de alta velocidad.

---

## Estructura del Repositorio

```text
GrooveOS/
├── Kernel/                 # Código fuente C++ (Core)
│   ├── src/                # Implementación (.cpp)
│   └── include/            # Cabeceras (.h)
├── Cogs/                   # Módulos de Python (Lógica)
├── Data/                   # Esquemas y DB
├── Scripts/                # Automatización
├── build-toolchain.sh      # Script de compilación
├── groove.sh               # Lanzador del sistema
└── requirements.txt        # Dependencias de Python