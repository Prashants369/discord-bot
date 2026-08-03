import os
import sys
import asyncio
import discord
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))

from bot import bot

@bot.event
async def on_ready():
    print(f"[SYNC] Logged in as {bot.user.name} ({bot.user.id})", flush=True)
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    guild_cmds = await bot.tree.sync(guild=guild)
    print(f"[SYNC] ✅ Synced {len(guild_cmds)} commands to GUILD ({GUILD_ID}):", flush=True)
    for cmd in guild_cmds:
        print(f"  • /{cmd.name} — {cmd.description}", flush=True)
        
    global_cmds = await bot.tree.sync()
    print(f"[SYNC] ✅ Synced {len(global_cmds)} commands GLOBALLY:", flush=True)
    for cmd in global_cmds:
        print(f"  • /{cmd.name} — {cmd.description}", flush=True)
        
    await bot.close()

if __name__ == "__main__":
    bot.run(TOKEN)
