import os
import sys
import asyncio
import discord
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))

intents = discord.Intents.default()
intents.guilds = True
intents.members = False

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"[FIX] Logged in as {client.user.name}")
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("[ERROR] Guild not found!")
        await client.close()
        return

    # Fetch owner explicitly
    try:
        owner = await guild.fetch_member(guild.owner_id)
    except Exception as e:
        print(f"[ERROR] Could not fetch owner: {e}")
        await client.close()
        return

    print(f"[FIX] Cleaning up roles for server owner: {owner.name}")
    
    # Roles to remove from owner
    roles_to_remove_names = {"Verified Female", "Verified Couple", "Verified Male"}
    roles_to_remove = [r for r in owner.roles if r.name in roles_to_remove_names]

    if roles_to_remove:
        await owner.remove_roles(*roles_to_remove, reason="Cleaning up conflicting testing roles")
        print(f"[FIX] Removed {', '.join(r.name for r in roles_to_remove)} from owner profile.")
    else:
        print("[FIX] Owner profile is already clean!")

    await client.close()

client.run(TOKEN)
