import os
import json
import asyncio
import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))

intents = discord.Intents.default()
intents.guilds = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    guild = client.get_guild(GUILD_ID)
    print(f"=== ALL USERS FOUND IN DISCORD AUDIT LOGS FOR {guild.name} ===")
    
    unique_users = set()
    async for entry in guild.audit_logs(limit=500):
        if entry.user:
            unique_users.add(f"{entry.user} (ID: {entry.user.id})")
        if entry.target and isinstance(entry.target, (discord.User, discord.Member)):
            unique_users.add(f"{entry.target} (ID: {entry.target.id})")
            
    print(f"Found {len(unique_users)} total unique users in audit log history:\n")
    for u in sorted(unique_users):
        print(f"• {u}")

    await client.close()

client.run(TOKEN)
