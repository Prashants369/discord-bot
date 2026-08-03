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
intents.members = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}", flush=True)
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("Guild not found!", flush=True)
        await client.close()
        return

    print(f"Checking permissions for server: {guild.name}", flush=True)
    
    # 1. Check @everyone role permissions
    everyone = guild.default_role
    print(f"@everyone use_application_commands: {everyone.permissions.use_application_commands}", flush=True)
    
    if not everyone.permissions.use_application_commands:
        print("Enabling use_application_commands on @everyone role...", flush=True)
        perms = everyone.permissions
        perms.update(use_application_commands=True)
        try:
            await everyone.edit(permissions=perms, reason="Allow all members to use slash commands")
            print("✅ Enabled use_application_commands on @everyone!", flush=True)
        except Exception as e:
            print(f"❌ Failed to edit @everyone permissions: {e}", flush=True)

    # 2. Check all text channels for overwrites blocking use_application_commands
    for ch in guild.text_channels:
        overwrites = ch.overwrites
        if everyone in overwrites:
            ow = overwrites[everyone]
            if ow.use_application_commands is False:
                print(f"Fixing channel #{ch.name} where @everyone was denied slash commands...", flush=True)
                ow.use_application_commands = True
                try:
                    await ch.set_permissions(everyone, overwrite=ow, reason="Fix slash command access")
                    print(f"✅ Fixed #{ch.name}", flush=True)
                except Exception as e:
                    print(f"❌ Failed to fix #{ch.name}: {e}", flush=True)

    print("Checking complete!", flush=True)
    await client.close()

client.run(TOKEN)
