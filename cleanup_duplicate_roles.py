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

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"[CLEANUP] Logged in as {client.user.name}")
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("[ERROR] Guild not found!")
        await client.close()
        return

    print(f"[CLEANUP] Scanning roles in {guild.name}...")

    # Group roles by name
    roles_by_name = {}
    for role in guild.roles:
        if role.name not in roles_by_name:
            roles_by_name[role.name] = []
        roles_by_name[role.name].append(role)

    # Find duplicates
    duplicates_deleted = 0
    for name, role_list in roles_by_name.items():
        if len(role_list) > 1 and name != "@everyone":
            print(f"[CLEANUP] Found {len(role_list)} duplicates for role '{name}'. Cleaning up...")
            # Keep the first role, delete others
            master = role_list[0]
            for dup in role_list[1:]:
                try:
                    await dup.delete(reason="Removing duplicate role")
                    duplicates_deleted += 1
                    print(f"  - Deleted duplicate ID {dup.id} for '{name}'")
                    await asyncio.sleep(0.3)
                except Exception as e:
                    print(f"  - Failed to delete duplicate '{name}': {e}")

    print(f"[CLEANUP] Total duplicate roles deleted: {duplicates_deleted}")
    print("[CLEANUP] Duplicate cleanup finished!")
    await client.close()

client.run(TOKEN)
