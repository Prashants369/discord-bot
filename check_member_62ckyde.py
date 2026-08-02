import os
import asyncio
import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))

intents = discord.Intents.default()
intents.members = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    guild = client.get_guild(GUILD_ID)
    print(f"=== CHECKING MEMBER LIST FOR GUILD {guild.name} ===")
    async for m in guild.fetch_members(limit=100):
        print(f"• {m.display_name} (@{m.name}) | ID: {m.id} | Roles: {[r.name for r in m.roles if r.name != '@everyone']}")

    await client.close()

client.run(TOKEN)
