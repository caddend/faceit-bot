# Faceit Bot — тонкая обёртка для запуска пакета faceit_bot.
# python bot.py и python -m faceit_bot делают одно и то же.
import asyncio

from faceit_bot.__main__ import main

if __name__ == "__main__":
    asyncio.run(main())
