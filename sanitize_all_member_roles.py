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
intents.members = False  # fetch via API

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"[SANITIZER] Logged in as {client.user.name}")
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("[ERROR] Guild not found!")
        await client.close()
        return

    print(f"[SANITIZER] Auditing all members in {guild.name}...")

    role_map = {r.name: r for r in guild.roles}
    verified_female = role_map.get("Verified Female")
    verified_male = role_map.get("Verified Male")
    verified_couple = role_map.get("Verified Couple")
    verified_general = role_map.get("Verified")

    conflicting_set = {r for r in [verified_female, verified_male, verified_couple] if r}

    # Clean owner and bot member specifically
    target_ids = [guild.owner_id, client.user.id]
    for mid in target_ids:
        try:
            member = await guild.fetch_member(mid)
            if member:
                member_conflicting = [r for r in member.roles if r in conflicting_set]
                if member_conflicting:
                    print(f"[SANITIZER] Stripping {len(member_conflicting)} conflicting verification roles from {member.name}...")
                    await member.remove_roles(*member_conflicting, reason="Sanitizing admin/bot profile roles")
                    print(f"  -> Successfully cleaned roles for {member.name}")
        except Exception as e:
            print(f"[WARNING] Could not fetch member {mid}: {e}")

    print("[SANITIZER] Member role sanitization COMPLETE!")
    await client.close()

client.run(TOKEN)
