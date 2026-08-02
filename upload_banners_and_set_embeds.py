import os
import sys
import json
import asyncio
import discord
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))

# Paths to generated banners in brain directory
BANNERS = {
    "about_us": r"C:\Users\ASUS\.gemini\antigravity-ide\brain\2c528d6a-3993-4071-88c7-04e60fe2574f\haven_about_us_banner_1785644983481.png",
    "rules": r"C:\Users\ASUS\.gemini\antigravity-ide\brain\2c528d6a-3993-4071-88c7-04e60fe2574f\haven_rules_banner_1785645001161.png",
    "verify": r"C:\Users\ASUS\.gemini\antigravity-ide\brain\2c528d6a-3993-4071-88c7-04e60fe2574f\haven_verify_banner_1785645017416.png",
    "roles": r"C:\Users\ASUS\.gemini\antigravity-ide\brain\2c528d6a-3993-4071-88c7-04e60fe2574f\haven_roles_banner_1785645034050.png",
}

intents = discord.Intents.default()
intents.guilds = True

client = discord.Client(intents=intents)

async def upsert_premium_embed(channel, marker: str, embed: discord.Embed):
    async for msg in channel.history(limit=50):
        if msg.author == client.user and msg.embeds:
            emb = msg.embeds[0]
            hay = f"{emb.title or ''}|{(emb.footer.text if emb.footer else '')}"
            if marker in hay:
                await msg.edit(embed=embed)
                return
    embed.set_footer(text=marker)
    await channel.send(embed=embed)

@client.event
async def on_ready():
    print(f"[BANNERS] Logged in as {client.user.name}")
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("[ERROR] Guild not found!")
        await client.close()
        return

    # Find audit logs channel to upload images
    audit_chan = discord.utils.get(guild.text_channels, name="audit-logs")
    if not audit_chan:
        # Fallback to mod-chat
        audit_chan = discord.utils.get(guild.text_channels, name="mod-chat")
    
    if not audit_chan:
        print("[ERROR] Audit logs or mod chat channel not found!")
        await client.close()
        return

    urls = {}
    print(f"[BANNERS] Uploading banner assets to #{audit_chan.name}...")
    for key, path in BANNERS.items():
        if os.path.exists(path):
            try:
                file = discord.File(path, filename=f"{key}_banner.png")
                msg = await audit_chan.send(content=f"⚙️ Uploaded banner: **{key}**", file=file)
                # Extract attachment URL
                attachment_url = msg.attachments[0].url
                urls[key] = attachment_url
                print(f"  [SUCCESS] {key} banner uploaded: {attachment_url}")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"  [ERROR] Failed to upload {key}: {e}")
        else:
            print(f"  [ERROR] File missing: {path}")

    # Write URLs to config
    with open("banner_urls.json", "w", encoding="utf-8") as f:
        json.dump(urls, f, indent=2)

    # Now let's apply the images to the embeds!
    about_chan = discord.utils.get(guild.text_channels, name="about-us")
    rules_chan = discord.utils.get(guild.text_channels, name="rules")
    welcome_chan = discord.utils.get(guild.text_channels, name="welcome-and-verify")
    roles_chan = discord.utils.get(guild.text_channels, name="roles-self-assign")
    ticket_chan = discord.utils.get(guild.text_channels, name="open-ticket")

    # 1. About Us
    if about_chan and "about_us" in urls:
        embed = discord.Embed(
            title="🗺️ ── H A V E N  M A P ──",
            description="Premium guide to navigate the sanctuary. Access unlocks automatically after verification.",
            color=discord.Color.from_rgb(241, 196, 15)
        )
        embed.set_image(url=urls["about_us"])
        embed.add_field(
            name="📍 KEY DEPARTMENTS",
            value=(
                f"• **Rules & Guidelines** → {rules_chan.mention if rules_chan else '#rules'}\n"
                f"• **Get Verified** → {ticket_chan.mention if ticket_chan else '#open-ticket'}\n"
                f"• **Assign Profile Roles** → {roles_chan.mention if roles_chan else '#roles-self-assign'}"
            ),
            inline=False
        )
        await upsert_premium_embed(about_chan, "HEAVEN about panel", embed)
        print("[BANNERS] Updated #about-us embed image")

    # 2. Rules
    if rules_chan and "rules" in urls:
        embed = discord.Embed(
            title="📜 ── S E R V E R  R U L E S ──",
            description="Please read and follow these rules. Staff actions are final.",
            color=discord.Color.from_rgb(231, 76, 60)
        )
        embed.set_image(url=urls["rules"])
        embed.add_field(name="🔞 1 — 18+ ONLY", value="No minors. Age-verified through our mod team. Lying about age = permanent ban.", inline=False)
        embed.add_field(name="🤝 2 — CONSENT & ORIGINAL CONTENT", value="Only post what you own or have clear permission to share. No exes, no stolen, no deepfakes.", inline=False)
        embed.add_field(name="🛑 3 — MINORS (ZERO TOLERANCE)", value="Any sexual content involving minors = instant ban + report to Discord and authorities.", inline=False)
        embed.add_field(name="🚫 4 — NO UNSOLICITED NSFW DMs", value="Ask first. Unsolicited NSFW DMs = harassment → ban.", inline=False)
        embed.add_field(name="🔒 5 — WHAT’S HERE STAYS HERE", value="No screenshots/reposts of members without permission.", inline=False)
        embed.add_field(name="⚠️ 6 — RESPECT & NO SELLING", value="No hate, harassment, or commercial spam / selling.", inline=False)
        await upsert_premium_embed(rules_chan, "HEAVEN rules panel", embed)
        print("[BANNERS] Updated #rules embed image")

    # 3. Welcome/Verify
    if welcome_chan and "verify" in urls:
        embed = discord.Embed(
            title="🔓 ── V E R I F I C A T I O N ──",
            description="Verification unlocks all NSFW discussions, media sharing, and lounge categories.",
            color=discord.Color.from_rgb(46, 204, 113)
        )
        embed.set_image(url=urls["verify"])
        embed.add_field(
            name="📋 HOW TO START",
            value=(
                f"1️⃣ Go to {ticket_chan.mention if ticket_chan else '#open-ticket'} and choose your verification type.\n"
                "2️⃣ Complete the pop-up application form.\n"
                "3️⃣ Upload your photo selfie inside your private ticket channel.\n"
                "4️⃣ Wait for a moderator to approve."
            ),
            inline=False
        )
        await upsert_premium_embed(welcome_chan, "HEAVEN welcome panel", embed)
        print("[BANNERS] Updated #welcome-and-verify embed image")

    # 4. Roles
    if roles_chan and "roles" in urls:
        embed = discord.Embed(
            title="🎭 ── P R O F I L E  R O L E S ──",
            description=(
                "**Verified only.** Customize your profile to let others know who you are and what you're looking for.\n\n"
                "**Choose your details from the dropdown menus below!**"
            ),
            color=discord.Color.from_rgb(155, 89, 182)
        )
        embed.set_image(url=urls["roles"])
        await upsert_premium_embed(roles_chan, "HEAVEN roles panel 1", embed)
        print("[BANNERS] Updated #roles-self-assign embed image")

    print("[BANNERS] All banners uploaded and embedded!")
    await client.close()

client.run(TOKEN)
