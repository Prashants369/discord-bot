import os
import sys
import asyncio
import discord
from dotenv import load_dotenv
from bot import TicketButtonView

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))

intents = discord.Intents.default()
intents.guilds = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"[PANEL] Logged in as {client.user.name}")
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("[ERROR] Guild not found!")
        await client.close()
        return

    ticket_chan = discord.utils.get(guild.text_channels, name="open-ticket")
    if not ticket_chan:
        print("[ERROR] #open-ticket channel not found!")
        await client.close()
        return

    # Purge old messages in #open-ticket
    print("[PANEL] Purging old messages in #open-ticket...")
    async for msg in ticket_chan.history(limit=50):
        try:
            await msg.delete()
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"[WARN] Could not delete msg: {e}")

    embed = discord.Embed(
        title="🎫 ── H A V E N  V E R I F I C A T I O N ──",
        description=(
            "Welcome to **HAVEN**!\n\n"
            "To protect our community, all channels remain locked until you complete verification.\n\n"
            "**How to Verify:**\n"
            "1️⃣ Choose your application type below (Female, Male, or Couple).\n"
            "2️⃣ Fill out the pop-up form (Email, Date of Birth, Bio details).\n"
            "3️⃣ Inside your private ticket, upload a selfie holding paper with **HAVEN + Today's Date**.\n"
            "4️⃣ A moderator will review and approve your application!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.from_rgb(46, 204, 113)
    )
    embed.set_footer(text="HAVEN Verification System • Safe & Secure")
    
    await ticket_chan.send(embed=embed, view=TicketButtonView())
    print("[PANEL] Fresh #open-ticket panel published successfully!")

    await client.close()

client.run(TOKEN)
