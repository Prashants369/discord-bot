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
    print(f"Guild: {guild.name} (Total Members: {guild.member_count})")
    
    print("\n--- Current Cached Members ---")
    for m in guild.members:
        print(f"• {m.display_name} (@{m.name}) | ID: {m.id} | Roles: {[r.name for r in m.roles if r.name != '@everyone']}")

    print("\n--- Recent Audit Logs ---")
    try:
        async for entry in guild.audit_logs(limit=50):
            print(f"• Action: {entry.action} | Target: {entry.target} | Mod: {entry.user} | Reason: {entry.reason}")
    except Exception as e:
        print(f"Audit log error: {e}")

    print("\n--- Store Data ---")
    store_path = os.path.join("data", "verifications.json")
    if os.path.exists(store_path):
        with open(store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            apps = data.get("applications", {})
            print(f"Total apps in store: {len(apps)}")
            for uid, app in apps.items():
                print(f"• UID: {uid} | Name: {app.get('display_name')} (@{app.get('username')}) | Status: {app.get('status')}")

    await client.close()

client.run(TOKEN)
