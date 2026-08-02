import os
import sys
import asyncio
import discord
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))

# Paths to logo image
IMAGE_PATH = r"C:\Users\ASUS\.gemini\antigravity-ide\brain\2c528d6a-3993-4071-88c7-04e60fe2574f\haven_server_icon_1785606136515.png"

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

    print(f"[FIX] Connected to server: {guild.name} (ID: {guild.id})")

    # 1. SET SERVER ICON / LOGO
    if os.path.exists(IMAGE_PATH):
        try:
            with open(IMAGE_PATH, 'rb') as f:
                icon_bytes = f.read()
            await guild.edit(icon=icon_bytes)
            print("✅ Successfully uploaded and set the HAVEN server logo!")
        except Exception as e:
            print(f"❌ Failed to set server icon: {e}")
    else:
        print(f"❌ Image path not found: {IMAGE_PATH}")

    # 2. FIX ALL MEMBER ROLES
    role_map = {r.name: r for r in guild.roles}
    v_female = role_map.get("Verified Female")
    v_male = role_map.get("Verified Male")
    v_couple = role_map.get("Verified Couple")
    v_general = role_map.get("Verified")

    conflicting = [r for r in [v_female, v_male, v_couple] if r]

    # Fetch owner and bot
    members_to_check = []
    try:
        owner = await guild.fetch_member(guild.owner_id)
        if owner:
            members_to_check.append(owner)
    except Exception as e:
        print(f"Could not fetch owner: {e}")

    try:
        bot_member = await guild.fetch_member(client.user.id)
        if bot_member:
            members_to_check.append(bot_member)
    except Exception as e:
        print(f"Could not fetch bot member: {e}")

    for member in members_to_check:
        print(f"[FIX] Checking roles for member: '{member.name}' (ID: {member.id})")
        print(f"  - Current roles: {[r.name for r in member.roles]}")

        has_conflicting = [r for r in member.roles if r in conflicting]
        if has_conflicting:
            print(f"  - Found conflicting roles: {[r.name for r in has_conflicting]}")
            # Strip all 3 from owner/bot so they don't have conflicting gender roles!
            await member.remove_roles(*has_conflicting, reason="Fixing conflicting test roles")
            print(f"  - Successfully stripped {[r.name for r in has_conflicting]} from '{member.name}'!")
        else:
            print(f"  - Member '{member.name}' profile is clean!")

    print("[FIX] All operations completed successfully!")
    await client.close()

client.run(TOKEN)
