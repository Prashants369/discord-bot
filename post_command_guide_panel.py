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
intents.guild_messages = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"[GUIDE_POSTER] Connected as {client.user.name}", flush=True)
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("[ERROR] Guild not found!", flush=True)
        await client.close()
        return

    # Find or create #bot-commands channel
    target_ch = discord.utils.get(guild.text_channels, name="bot-commands")
    if not target_ch:
        cat = discord.utils.get(guild.categories, name="💬 SFW DISCUSSIONS") or discord.utils.get(guild.categories, name="📌 WELCOME & RULES")
        try:
            target_ch = await guild.create_text_channel(
                name="bot-commands",
                category=cat,
                topic="🌿 Full list of HAVEN bot commands and usage guide",
                reason="Command guide channel"
            )
            print("[GUIDE_POSTER] Created #bot-commands channel", flush=True)
        except Exception as e:
            print(f"[WARN] Failed to create #bot-commands: {e}", flush=True)
            target_ch = discord.utils.get(guild.text_channels, name="general-chat")

    if not target_ch:
        print("[ERROR] Target channel not found!", flush=True)
        await client.close()
        return

    # Delete previous bot posts in this channel to keep it clean
    try:
        async for msg in target_ch.history(limit=20):
            if msg.author == client.user:
                await msg.delete()
    except Exception:
        pass

    # Embed 1: Introduction & How to Use
    embed1 = discord.Embed(
        title="🌿 ── H A V E N  B O T  G U I D E  &  C O M M A N D S ──",
        description=(
            "Welcome to the HAVEN Bot Directory! Our bot is designed to keep our garden safe, "
            "fun, and interactive for everyone without forcing activity or spam.\n\n"
            "💡 **How to use commands:**\n"
            "Just type `/` followed by any command name in chat (for example `/profile`, `/checkin`, `/hug`) "
            "and press Enter!\n\n"
            "Type `/commands` anytime in chat to open an interactive 5-page directory!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.from_rgb(39, 174, 96)
    )
    embed1.add_field(
        name="🌱 1. Getting Started & Identity",
        value=(
            "• `/tour` — Interactive tour of the server\n"
            "• `/rules` — Quick reference of HAVEN garden rules\n"
            "• `/profile [@user]` — View your or another member's profile card\n"
            "• `/level [@user]` — Check your level and XP progress bar\n"
            "• `/checkin` — Daily check-in (+50 bonus XP + streak tracker)\n"
            "• `/mood <text>` — Set your mood string (shown on `/profile`)\n"
            "• `/birthday set MM/DD` — Save your birthday (no year stored)\n"
            "• `/birthday list` — View upcoming community birthdays"
        ),
        inline=False
    )
    embed1.set_footer(text="HAVEN Bot Guide · Part 1")

    # Embed 2: Social Interactions & Games
    embed2 = discord.Embed(
        title="💚 Social Interactions & 🎲 Games",
        description="Connect with fellow members and have fun together!",
        color=discord.Color.from_rgb(155, 89, 182)
    )
    embed2.add_field(
        name="💚 Social Interaction Commands",
        value=(
            "• `/rep @member` — Give someone +1 reputation point (24h cooldown)\n"
            "• `/hug @member` — Send a warm hug embed 🤗\n"
            "• `/highfive @member` — High five someone! 🖐️\n"
            "• `/wave @member` — Wave hello 👋\n"
            "• `/cheers @member` — Raise a glass 🥂\n"
            "• `/compliment @member` — Send a heartwarming compliment 💜\n"
            "• `/thankhost @member` — Publicly thank a Greeter/Host 💚\n"
            "• `/ship @a @b` — Calculate fun compatibility % 💘\n"
            "• `/matchcard @a @b` — Compare shared vibe tags between two people\n"
            "• `/afk [reason]` — Set yourself as AFK (bot notifies callers)"
        ),
        inline=False
    )
    embed2.add_field(
        name="🎲 Interactive Games & Fun",
        value=(
            "• `/wouldyourather` — Interactive Would-You-Rather with voting buttons (🅰️/🅱️)\n"
            "• `/truthordare` — Interactive Truth-or-Dare generator (🔍/🎯)\n"
            "• `/8ball <question>` — Ask the Magic 8-Ball 🔮\n"
            "• `/roll [sides]` — Roll a dice (default 6, up to 100)\n"
            "• `/coinflip` — Flip a coin 🪙\n"
            "• `/confess <text>` — Post an anonymous confession in `#confessions`\n"
            "• `/vibecheck` — View server chat activity metrics over 24h"
        ),
        inline=False
    )
    embed2.set_footer(text="HAVEN Bot Guide · Part 2")

    # Embed 3: Automated Systems & Staff Tools
    embed3 = discord.Embed(
        title="⭐ Automated Features & 🛡️ Staff Commands",
        description="Features running automatically in the background and moderator tools.",
        color=discord.Color.from_rgb(241, 196, 15)
    )
    embed3.add_field(
        name="⭐ Automated Garden Features",
        value=(
            "• **Starboard:** Messages getting 5+ ⭐ reactions auto-post to `#starboard`\n"
            "• **Level Milestones:** Auto-celebrations at Level 5, 10, 15, 20, 25\n"
            "• **Join Milestones:** Anniversaries celebrated at 7d, 30d, 90d, 365d\n"
            "• **Welcome Back:** Auto-greets verified members returning after 3+ days\n"
            "• **Global Prompts:** Timezone-neutral prompts posted every 12 hours"
        ),
        inline=False
    )
    embed3.add_field(
        name="🛡️ Staff & Moderator Tools",
        value=(
            "• `/verify @member <role>` — Verify member as Female/Male/Couple\n"
            "• `/unverify @member` — Strip verification roles\n"
            "• `/trust @member` — Grant Trusted role (Elite Lounge access)\n"
            "• `/untrust @member` — Remove Trusted role\n"
            "• `/vstatus @member` — Look up verification record & history\n"
            "• `/vpanel` — Post moderator control buttons inside ticket\n"
            "• `/queue` — Refresh live verification queue\n"
            "• `/spotlight @member <bio>` — Feature a member in `#announcements`\n"
            "• `/warn @member <reason>` — Issue formal warning (logged & DMed)\n"
            "• `/warnings @member` — Check warning history"
        ),
        inline=False
    )
    embed3.set_footer(text="HAVEN Bot Guide · Type /commands in chat anytime")

    await target_ch.send(embed=embed1)
    await target_ch.send(embed=embed2)
    await target_ch.send(embed=embed3)
    print(f"[GUIDE_POSTER] ✅ Posted complete command guide to #{target_ch.name}", flush=True)

    await client.close()

if __name__ == "__main__":
    client.run(TOKEN)
