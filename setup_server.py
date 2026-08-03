import os
import sys
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HEAVEN — Server Infrastructure (REFINE MODE)
# • Never deletes channels or categories
# • Creates only what is missing
# • Refreshes permissions + guide embeds
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')

if not TOKEN or TOKEN == 'your_bot_token_here':
    print("[ERROR] Please set your DISCORD_TOKEN in the .env file.")
    exit(1)
if not GUILD_ID or GUILD_ID == 'your_server_id_here':
    print("[ERROR] Please set your GUILD_ID in the .env file.")
    exit(1)
try:
    GUILD_ID = int(GUILD_ID)
except ValueError:
    print("[ERROR] GUILD_ID must be a valid number.")
    exit(1)

# Setup does not need privileged intents (Members / Message Content).
intents = discord.Intents.default()
intents.guilds = True
intents.guild_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Channel guide copy: name -> (title, body)
CHANNEL_GUIDES = {
    "general-chat": (
        "How to use #general-chat",
        "SFW hangout for everyone verified.\n"
        "• Be respectful — no harassment or spam\n"
        "• Keep explicit talk in NSFW categories\n"
        "• New? Say hi, then post a real intro in #introductions",
    ),
    "introductions": (
        "How to use #introductions",
        "One intro post per person (edit later if needed).\n"
        "**Template:**\n"
        "• Age range / pronouns\n"
        "• Single, couple, etc.\n"
        "• What you’re looking for\n"
        "• Fun fact or vibe\n"
        "Slowmode is on so the channel stays readable.",
    ),
    "looking-for": (
        "How to use #looking-for",
        "Post what you want — friends, dates, play partners.\n"
        "• Use a clear format (who you are + who you want)\n"
        "• No spam reposting — slowmode is intentional\n"
        "• Move private details to DMs only with consent\n"
        "• No advertising onlyfans/selling",
    ),
    "speed-dating": (
        "How to use #speed-dating",
        "Quick icebreakers and short intros.\nKeep it light; longer talks go to #general-chat or DMs.",
    ),
    "matchmaking": (
        "How to use #matchmaking",
        "Ask the community to help you connect.\nBe specific. Don’t pressure anyone who says no.",
    ),
    "flirty-chat": (
        "How to use #flirty-chat",
        "Playful, flirty conversation — still respectful.\nIf it gets explicit, move to NSFW channels.",
    ),
    "polls-and-questions": (
        "How to use #polls-and-questions",
        "Community questions and polls. Keep it civil; no baiting fights.",
    ),
    "clips-and-videos": (
        "How to use #clips-and-videos",
        "SFW clips and fun videos only. NSFW media belongs in media channels.",
    ),
    "voice-notes": (
        "How to use #voice-notes",
        "Drop short voice notes for the community. Be kind — voices are personal.",
    ),
    "truth-or-dare": (
        "How to use #truth-or-dare",
        "Play along! Consent first — skip any dare you’re not OK with. No involving third parties.",
    ),
    "never-have-i-ever": (
        "How to use #never-have-i-ever",
        "Share experiences voluntarily. No shaming. Keep illegal content out.",
    ),
    "hot-takes": (
        "How to use #hot-takes",
        "Spicy opinions welcome — personal attacks are not. Mods will step in.",
    ),
    "memes-and-humor": (
        "How to use #memes-and-humor",
        "Memes and jokes. No bigotry “as a joke.” SFW preferred here.",
    ),
    "music-lounge": (
        "How to use #music-lounge",
        "Songs, playlists, concert talk. Share links and vibes.",
    ),
    "naturist-talk": (
        "How to use #naturist-talk",
        "Naturist lifestyle discussion. Respect body diversity. Media → #naturist-media.",
    ),
    "body-love": (
        "How to use #body-love",
        "Celebrate every body. No body-shaming. Supportive space.",
    ),
    "naturist-media": (
        "How to use #naturist-media",
        "Original naturist media only, with consent.\nNo exes, no stolen content, no minors (zero tolerance).",
    ),
    "nsfw-general": (
        "How to use #nsfw-general",
        "Open adult conversation for verified members.\n• Consent culture always\n• Media dumps → media channels\n• No unsolicited DM expectations",
    ),
    "intimate-talk": (
        "How to use #intimate-talk",
        "Deeper / more personal adult talk. Be gentle with people’s boundaries.",
    ),
    "would-you-rather": (
        "How to use #would-you-rather",
        "Spicy WYR questions. Keep it fun; skip what you don’t want to answer.",
    ),
    "confessions": (
        "How to use #confessions",
        "Share confessions respectfully. Don’t dox. Illegal content = ban + report.",
    ),
    "story-time": (
        "How to use #story-time",
        "Real stories (adult). Fiction OK if labeled. No non-consensual real-person content.",
    ),
    "aftercare-corner": (
        "How to use #aftercare-corner",
        "Soft space after intense chat/play talk. Be supportive. No judgment.",
    ),
    "selfies": (
        "How to use #selfies",
        "Show yourself off — **original content you own**.\n"
        "• Consent required for anyone else in frame\n"
        "• No screenshots of other people\n"
        "• What’s posted here stays here (Rule 5)",
    ),
    "intimate-photos": (
        "How to use #intimate-photos",
        "Intimate photos you own, shared willingly.\nSame consent rules. Report stolen content immediately.",
    ),
    "nsfw-videos": (
        "How to use #nsfw-videos",
        "Original NSFW video only. No reposts / no “found online.” Mods remove violations fast.",
    ),
    "weekly-challenge": (
        "How to use #weekly-challenge",
        "Optional themed challenges. Participate only if you want — never pressure others.",
    ),
    "rate-me": (
        "How to use #rate-me",
        "Post for feedback if you want it.\n• Be constructive, not cruel\n• No means no if someone doesn’t want ratings",
    ),
    "pillow-talk": (
        "How to use #pillow-talk",
        "Soft late-night intimate conversation. Low drama, high kindness.",
    ),
    "fantasies": (
        "How to use #fantasies",
        "Fantasy discussion, judgment-free — still within Discord + server rules (18+ only).",
    ),
    "dirty-questions": (
        "How to use #dirty-questions",
        "Ask spicy questions. Anyone can skip. No targeting people who didn’t opt in.",
    ),
    "girls-only-chat": (
        "How to use #girls-only-chat",
        "**Verified Female only.** Safe space.\nDo not share screenshots outside. Mods watch this closely.",
    ),
    "girls-only-media": (
        "How to use #girls-only-media",
        "**Verified Female only.** Private media. Same consent + original-content rules.",
    ),
    "boys-only-chat": (
        "How to use #boys-only-chat",
        "**Verified Male only.** Respect the space; no brigading or leaking chat.",
    ),
    "boys-only-media": (
        "How to use #boys-only-media",
        "**Verified Male only.** Original content + consent only.",
    ),
    "verified-couples": (
        "How to use #verified-couples",
        "**Verified Couple only.** Space for couples to connect with other couples.",
    ),
    "trusted-lounge": (
        "How to use #trusted-lounge",
        "VIP chat for Trusted / featured members. Earned access — keep the quality high.",
    ),
    "exclusive-media": (
        "How to use #exclusive-media",
        "Premium media from trusted members. Same consent rules, higher trust bar.",
    ),
}


@bot.event
async def on_ready():
    print(f"[INFO] Logged in as {bot.user.name} ({bot.user.id})")

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print(f"[ERROR] Could not find server with ID: {GUILD_ID}")
        await bot.close()
        return

    print(f"[INFO] Found server: {guild.name}")
    print("[INFO] REFINE MODE — channels are never deleted, only created/updated")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    existing_roles = {role.name: role for role in guild.roles}
    existing_categories = {cat.name: cat for cat in guild.categories}

    # ═══════════════════════════════════
    #  PERMISSIONS
    # ═══════════════════════════════════
    admin_perms = discord.Permissions(administrator=True)
    mod_perms = discord.Permissions(
        manage_messages=True, kick_members=True, ban_members=True,
        moderate_members=True, view_audit_log=True, read_messages=True,
        send_messages=True, connect=True, speak=True, manage_channels=True,
        attach_files=True, embed_links=True,
    )
    # Access roles: can use the server
    verified_perms = discord.Permissions(
        read_messages=True, send_messages=True, read_message_history=True,
        connect=True, speak=True, embed_links=True, attach_files=True,
        add_reactions=True, use_external_emojis=True,
    )
    # Cosmetic / self-assign roles: NO special permissions (display only)
    display_perms = discord.Permissions.none()

    everyone_perms = discord.Permissions(
        read_messages=True, read_message_history=True,
        send_messages=False, connect=False, add_reactions=True,
    )

    try:
        await guild.default_role.edit(permissions=everyone_perms)
        print("[INFO] Updated @everyone default permissions.")
    except Exception as e:
        print(f"[WARNING] Could not update @everyone permissions: {e}")

    # ═══════════════════════════════════
    #  ROLES (create missing only)
    # ═══════════════════════════════════
    print("[INFO] Ensuring roles...")
    roles = {}

    primary_roles_data = [
        ("Owner", discord.Colour.from_rgb(231, 76, 60), admin_perms, True),
        ("Moderator", discord.Colour.from_rgb(46, 204, 113), mod_perms, True),
        ("Verified Female", discord.Colour.from_rgb(233, 30, 99), verified_perms, True),
        ("Verified Couple", discord.Colour.from_rgb(155, 89, 182), verified_perms, True),
        ("Verified Male", discord.Colour.from_rgb(52, 152, 219), verified_perms, True),
    ]

    special_roles_data = [
        ("Weekly Featured", discord.Colour.from_rgb(241, 196, 15), verified_perms, True),
        ("Event Winner", discord.Colour.from_rgb(230, 126, 34), verified_perms, True),
    ]

    # Access role (not gender-specific)
    access_secondary = ["Verified", "Trusted", "Long-time Member"]

    secondary_roles_names = [
        "Single", "Couple", "Open Relationship / ENM",
        "Exploring / Curious", "Experienced", "Shy / New Here",
        "Polyamorous", "Monogamous",
        "Looking for Friends", "Looking for Dating", "Looking for Couples",
        "Looking for Singles", "Just Chatting", "Swinger", "Monogamish",
        "Poly-Curious", "Relationship-First", "Play-First",
        "Woman", "Man", "Non-binary", "Trans", "Femme", "Masc",
        "Straight", "Bisexual", "Bicurious", "Lesbian", "Gay",
        "Pansexual", "Queer",
        "18-24", "25-34", "35-44", "45+",
        "Exhibitionist", "Voyeur", "Soft & Sweet", "Kinky", "Switch",
        "Dominant", "Submissive", "Just Looking", "Content Sharer", "Chatty",
        "Naturist / Nudist", "Body Positive",
        "Wife", "Husband", "MILF", "Dadbod",
        "Hotwife", "Cuckold", "Cuckquean", "Bull", "Top", "Bottom",
        "Vers", "Sadist", "Masochist",
        "Americas", "Europe / Africa", "Asia / Oceania",
        "Night Owl", "Early Bird", "Weekend Warrior",
        "Photographer", "Voice Note Lover",
    ]

    try:
        for name, color, perms, hoist in primary_roles_data:
            if name in existing_roles:
                roles[name] = existing_roles[name]
                print(f"  [SKIP] {name}")
            else:
                roles[name] = await guild.create_role(name=name, colour=color, permissions=perms, hoist=hoist)
                print(f"  [NEW]  {name}")
                await asyncio.sleep(0.4)

        for name, color, perms, hoist in special_roles_data:
            if name in existing_roles:
                roles[name] = existing_roles[name]
                print(f"  [SKIP] {name}")
            else:
                roles[name] = await guild.create_role(name=name, colour=color, permissions=perms, hoist=hoist)
                print(f"  [NEW]  {name}")
                await asyncio.sleep(0.4)

        for name in access_secondary:
            if name in existing_roles:
                roles[name] = existing_roles[name]
                # Ensure Verified/Trusted keep usable perms
                try:
                    await roles[name].edit(permissions=verified_perms)
                except Exception:
                    pass
            else:
                roles[name] = await guild.create_role(name=name, permissions=verified_perms, hoist=False)
                print(f"  [NEW]  {name}")
                await asyncio.sleep(0.2)

        for name in secondary_roles_names:
            if name in existing_roles:
                roles[name] = existing_roles[name]
                # Strip channel-wide perms from cosmetic roles (security)
                try:
                    if roles[name].permissions.value != 0:
                        await roles[name].edit(permissions=display_perms)
                        print(f"  [FIX]  {name} → display-only perms")
                        await asyncio.sleep(0.15)
                except Exception as e:
                    print(f"  [WARN] Could not lock down {name}: {e}")
            else:
                roles[name] = await guild.create_role(name=name, permissions=display_perms, hoist=False)
                print(f"  [NEW]  {name}")
                await asyncio.sleep(0.2)

        print("[INFO] Roles complete.")
    except Exception as e:
        print(f"[ERROR] Role creation failed: {e}")
        await bot.close()
        return

    # ═══════════════════════════════════
    #  PERMISSION OVERWRITES (secured)
    # ═══════════════════════════════════
    def staff_ow(**extra):
        base = {
            roles['Moderator']: discord.PermissionOverwrite(
                view_channel=True, read_messages=True, send_messages=True,
                manage_messages=True, **extra
            ),
        }
        if 'Owner' in roles:
            base[roles['Owner']] = discord.PermissionOverwrite(
                view_channel=True, read_messages=True, send_messages=True,
                manage_messages=True, **extra
            )
        return base

    # INFO — everyone reads, nobody types (except staff)
    ow_info = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=False),
        **staff_ow(),
    }

    # Roles self-assign — VERIFIED only (stops unverified grabbing cosmetic tags early)
    ow_roles_channel = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        roles['Verified']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=False),
        roles['Verified Female']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=False),
        roles['Verified Couple']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=False),
        roles['Verified Male']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=False),
        **staff_ow(),
    }

    # Arrivals — unverified can chat; verified hidden
    ow_arrivals = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        roles['Verified']: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        roles['Verified Female']: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        roles['Verified Couple']: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        roles['Verified Male']: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        **staff_ow(),
    }

    # SFW / NSFW — verified access roles only
    ow_verified = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        roles['Verified']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        roles['Verified Female']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        roles['Verified Couple']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        roles['Verified Male']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        **staff_ow(),
    }
    ow_sfw = ow_verified
    ow_nsfw = ow_verified

    # PRIVATE ROOMS — verified gender roles ONLY (no self-assign Woman/Man/Couple bypass)
    ow_women = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        roles['Verified Female']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        **staff_ow(),
    }
    ow_men = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        roles['Verified Male']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        **staff_ow(),
    }
    ow_couples = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        roles['Verified Couple']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        **staff_ow(),
    }

    ow_elite = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        roles['Trusted']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        roles['Weekly Featured']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        roles['Event Winner']: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True),
        **staff_ow(),
    }

    ow_tickets = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        **staff_ow(manage_channels=True),
    }

    ow_mod = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        **staff_ow(),
    }

    # ═══════════════════════════════════
    #  HELPERS — never delete channels
    # ═══════════════════════════════════
    async def get_or_create_category(name, overwrites):
        if name in existing_categories:
            cat = existing_categories[name]
            try:
                await cat.edit(overwrites=overwrites)
                print(f"  [CAT]  {name} (permissions refreshed)")
            except Exception as e:
                print(f"  [CAT]  {name} (exists, perm refresh failed: {e})")
            return cat
        cat = await guild.create_category(name, overwrites=overwrites)
        existing_categories[name] = cat
        print(f"  [CAT]  {name} (CREATED)")
        return cat

    async def ensure_text(category, name, nsfw=False, overwrites=None, topic=None, slowmode=None):
        """Create if missing; always refresh overwrites/topic/nsfw when provided. Never deletes."""
        channel = discord.utils.get(category.text_channels, name=name)
        if channel is None:
            # Also search whole guild (channel may exist outside category)
            channel = discord.utils.get(guild.text_channels, name=name)

        if channel:
            kwargs = {}
            if overwrites is not None:
                kwargs["overwrites"] = overwrites
            if topic is not None:
                kwargs["topic"] = topic
            if nsfw:
                kwargs["nsfw"] = True
            if slowmode is not None:
                kwargs["slowmode_delay"] = slowmode
            if channel.category_id != category.id:
                kwargs["category"] = category
            if kwargs:
                try:
                    await channel.edit(**kwargs)
                    print(f"  [CH]   #{name} (updated)")
                except Exception as e:
                    print(f"  [CH]   #{name} (update failed: {e})")
            return channel

        kwargs = {"nsfw": nsfw}
        if overwrites is not None:
            kwargs["overwrites"] = overwrites
        if topic is not None:
            kwargs["topic"] = topic
        if slowmode:
            kwargs["slowmode_delay"] = slowmode
        channel = await category.create_text_channel(name, **kwargs)
        print(f"  [CH]   #{name} (CREATED)")
        return channel

    async def ensure_voice(category, name, overwrites=None):
        channel = discord.utils.get(category.voice_channels, name=name)
        if channel is None:
            channel = discord.utils.get(guild.voice_channels, name=name)
        if channel:
            kwargs = {}
            if overwrites is not None:
                kwargs["overwrites"] = overwrites
            if channel.category_id != category.id:
                kwargs["category"] = category
            if kwargs:
                try:
                    await channel.edit(**kwargs)
                except Exception:
                    pass
            return channel
        kwargs = {}
        if overwrites is not None:
            kwargs["overwrites"] = overwrites
        channel = await category.create_voice_channel(name, **kwargs)
        print(f"  [VC]   {name} (CREATED)")
        return channel

    async def upsert_bot_embed(channel, marker: str, embed: discord.Embed):
        """Update existing guide/message with marker, else send. Never mass-deletes."""
        try:
            async for msg in channel.history(limit=50):
                if msg.author == bot.user and msg.embeds:
                    emb = msg.embeds[0]
                    hay = f"{emb.title or ''}|{(emb.footer.text if emb.footer else '')}"
                    if marker in hay:
                        await msg.edit(embed=embed)
                        return
        except Exception:
            pass
        embed.set_footer(text=f"{marker}")
        await channel.send(embed=embed)

    # ═══════════════════════════════════
    #  CATEGORIES & CHANNELS (refine)
    # ═══════════════════════════════════
    print("[INFO] Refining categories & channels...")

    cat_info = await get_or_create_category("📌 INFO & RULES", ow_info)
    about_chan = await ensure_text(cat_info, "about-us", overwrites=ow_info, topic="Server map + what HEAVEN is")
    rules_chan = await ensure_text(cat_info, "rules", overwrites=ow_info, topic="Read before participating")
    welcome_chan = await ensure_text(cat_info, "welcome-and-verify", overwrites=ow_info, topic="How to verify and unlock the server")
    await ensure_text(cat_info, "announcements", overwrites=ow_info, topic="Server news and updates")
    roles_chan = await ensure_text(
        cat_info, "roles-self-assign", overwrites=ow_roles_channel,
        topic="Verified only — pick profile tags (does not unlock private rooms)"
    )
    ticket_chan = await ensure_text(cat_info, "open-ticket", overwrites=ow_info, topic="Click the button to start verification")
    arrivals_chan = await ensure_text(
        cat_info, "arrivals-chat", overwrites=ow_arrivals,
        topic="Chat while you wait for verification"
    )

    cat_sfw = await get_or_create_category("💬 SFW DISCUSSIONS", ow_sfw)
    await ensure_text(cat_sfw, "general-chat", overwrites=ow_sfw, topic="SFW hangout — see pinned guide")
    await ensure_text(cat_sfw, "introductions", overwrites=ow_sfw, topic="Say hi with the intro template", slowmode=30)
    await ensure_text(cat_sfw, "polls-and-questions", overwrites=ow_sfw, topic="Community polls and questions")
    await ensure_text(cat_sfw, "clips-and-videos", overwrites=ow_sfw, topic="SFW clips only")
    await ensure_text(cat_sfw, "voice-notes", overwrites=ow_sfw, topic="Community voice notes")
    await ensure_voice(cat_sfw, "Lounge", overwrites=ow_sfw)

    cat_dating = await get_or_create_category("💘 DATING & CONNECTIONS", ow_sfw)
    await ensure_text(cat_dating, "looking-for", overwrites=ow_sfw, topic="What you’re looking for", slowmode=60)
    await ensure_text(cat_dating, "speed-dating", overwrites=ow_sfw, topic="Quick intros")
    await ensure_text(cat_dating, "matchmaking", overwrites=ow_sfw, topic="Community matchmaking help")
    await ensure_text(cat_dating, "flirty-chat", overwrites=ow_sfw, topic="Flirty but respectful")
    await ensure_voice(cat_dating, "Date Night", overwrites=ow_sfw)

    cat_games = await get_or_create_category("🎮 FUN & GAMES", ow_sfw)
    await ensure_text(cat_games, "truth-or-dare", overwrites=ow_sfw, topic="Consent-first game", slowmode=10)
    await ensure_text(cat_games, "never-have-i-ever", overwrites=ow_sfw, topic="Share experiences", slowmode=10)
    await ensure_text(cat_games, "hot-takes", overwrites=ow_sfw, topic="Opinions without personal attacks")
    await ensure_text(cat_games, "memes-and-humor", overwrites=ow_sfw, topic="Memes and laughs")
    await ensure_text(cat_games, "music-lounge", overwrites=ow_sfw, topic="Music and playlists")

    cat_naturist = await get_or_create_category("🌿 NATURISM & BODY POSITIVITY", ow_nsfw)
    await ensure_text(cat_naturist, "naturist-talk", nsfw=True, overwrites=ow_nsfw, topic="Naturist lifestyle talk")
    await ensure_text(cat_naturist, "body-love", nsfw=True, overwrites=ow_nsfw, topic="Body positive support")
    await ensure_text(cat_naturist, "naturist-media", nsfw=True, overwrites=ow_nsfw, topic="Original naturist media only")

    cat_nsfw = await get_or_create_category("🔞 NSFW DISCUSSIONS", ow_nsfw)
    await ensure_text(cat_nsfw, "nsfw-general", nsfw=True, overwrites=ow_nsfw, topic="Open NSFW chat")
    await ensure_text(cat_nsfw, "intimate-talk", nsfw=True, overwrites=ow_nsfw, topic="Deeper personal talk")
    await ensure_text(cat_nsfw, "would-you-rather", nsfw=True, overwrites=ow_nsfw, topic="Spicy WYR")
    await ensure_text(cat_nsfw, "confessions", nsfw=True, overwrites=ow_nsfw, topic="Confessions", slowmode=30)
    await ensure_text(cat_nsfw, "story-time", nsfw=True, overwrites=ow_nsfw, topic="Stories")
    await ensure_text(cat_nsfw, "aftercare-corner", nsfw=True, overwrites=ow_nsfw, topic="Aftercare / soft space")

    cat_media = await get_or_create_category("📸 NSFW MEDIA SHARING", ow_nsfw)
    await ensure_text(cat_media, "selfies", nsfw=True, overwrites=ow_nsfw, topic="Original selfies", slowmode=15)
    await ensure_text(cat_media, "intimate-photos", nsfw=True, overwrites=ow_nsfw, topic="Intimate photos you own")
    await ensure_text(cat_media, "nsfw-videos", nsfw=True, overwrites=ow_nsfw, topic="Original NSFW video only")
    await ensure_text(cat_media, "weekly-challenge", nsfw=True, overwrites=ow_nsfw, topic="Optional challenges")
    await ensure_text(cat_media, "rate-me", nsfw=True, overwrites=ow_nsfw, topic="Optional ratings", slowmode=15)

    cat_late = await get_or_create_category("🌙 LATE NIGHT LOUNGE", ow_nsfw)
    await ensure_text(cat_late, "pillow-talk", nsfw=True, overwrites=ow_nsfw, topic="Soft late-night talk")
    await ensure_text(cat_late, "fantasies", nsfw=True, overwrites=ow_nsfw, topic="Fantasy discussion")
    await ensure_text(cat_late, "dirty-questions", nsfw=True, overwrites=ow_nsfw, topic="Ask anything (within rules)")

    cat_women = await get_or_create_category("👑 WOMEN ONLY", ow_women)
    await ensure_text(cat_women, "girls-only-chat", nsfw=True, overwrites=ow_women, topic="Verified Female only")
    await ensure_text(cat_women, "girls-only-media", nsfw=True, overwrites=ow_women, topic="Verified Female media")
    await ensure_voice(cat_women, "Girl Talk", overwrites=ow_women)

    cat_men = await get_or_create_category("🤴 MEN ONLY", ow_men)
    await ensure_text(cat_men, "boys-only-chat", nsfw=True, overwrites=ow_men, topic="Verified Male only")
    await ensure_text(cat_men, "boys-only-media", nsfw=True, overwrites=ow_men, topic="Verified Male media")
    await ensure_voice(cat_men, "Bro Zone", overwrites=ow_men)

    cat_couples = await get_or_create_category("💞 COUPLES ONLY", ow_couples)
    await ensure_text(cat_couples, "verified-couples", nsfw=True, overwrites=ow_couples, topic="Verified Couple only")

    cat_elite = await get_or_create_category("💎 ELITE LOUNGE", ow_elite)
    await ensure_text(cat_elite, "trusted-lounge", nsfw=True, overwrites=ow_elite, topic="Trusted members")
    await ensure_text(cat_elite, "exclusive-media", nsfw=True, overwrites=ow_elite, topic="Trusted media")
    await ensure_voice(cat_elite, "VIP Lounge", overwrites=ow_elite)

    cat_voice = await get_or_create_category("🔊 NSFW VOICE CHANNELS", ow_nsfw)
    await ensure_voice(cat_voice, "Intimate Lounge", overwrites=ow_nsfw)
    await ensure_voice(cat_voice, "Cam Room", overwrites=ow_nsfw)

    await get_or_create_category("🎫 VERIFICATION TICKETS", ow_tickets)

    cat_mod = await get_or_create_category("🛡️ MOD ZONE", ow_mod)
    await ensure_text(cat_mod, "mod-chat", overwrites=ow_mod, topic="Staff discussion")
    await ensure_text(cat_mod, "verification-log", overwrites=ow_mod, topic="Verification + ticket archives")
    await ensure_text(cat_mod, "audit-logs", overwrites=ow_mod, topic="Mod notes / audit trail")

    print("[INFO] Categories & channels refined (nothing deleted).")

    # ═══════════════════════════════════
    #  PREMIUM + GUIDE MESSAGES
    # ═══════════════════════════════════
    print("[INFO] Upserting about/rules/welcome + channel guides...")

    about_embed = discord.Embed(
        title="🌿 ── WELCOME TO THE GARDEN ──",
        description=(
            "**A calm, open-minded garden for adults to meet like-minded people — "
            "no pressure, no judgment, just good company.**\n\n"
            "We want nothing from you except that you feel welcome.\n"
            "Singles and **couples on one account** are both at home here.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.from_rgb(39, 174, 96),
    )
    about_embed.add_field(
        name="🗺️ WHERE DO I GO? (keep it simple)",
        value=(
            f"**At the gate (not verified yet)**\n"
            f"• {rules_chan.mention} · {welcome_chan.mention}\n"
            f"• Verify → {ticket_chan.mention}\n"
            f"• Sit & chat while you wait → {arrivals_chan.mention}\n\n"
            f"**Inside the garden (after verify) — start with these three**\n"
            f"• Bench → `#general-chat`\n"
            f"• Optional intro → `#introductions`\n"
            f"• Optional tags → {roles_chan.mention}\n\n"
            f"**Side paths (explore when you want)**\n"
            f"• Looking-for · flirty · NSFW · private rooms\n"
            f"• Women / Men / Couples rooms need matching **Verified** roles\n\n"
            f"Lurk as long as you want. No activity scores."
        ),
        inline=False,
    )
    about_embed.add_field(
        name="✦ THE GARDEN PROMISE",
        value=(
            "🌿 Social first — conversation before pressure\n"
            "🤝 Consent & kindness — no unsolicited NSFW DMs\n"
            "💑 Couples on one ID welcome — just be clear you’re a *we*\n"
            "🔒 Light verify keeps the space 18+ and safer\n"
            " Quiet is allowed — speaking always gets a human reply when hosts are around"
        ),
        inline=False,
    )
    about_embed.add_field(
        name="✦ HOW TO WALK IN",
        value=(
            f"1️⃣ Skim {rules_chan.mention}\n"
            f"2️⃣ Open {ticket_chan.mention} when ready (no rush)\n"
            "3️⃣ Short form + selfie check if asked\n"
            "4️⃣ Hosts welcome you in — then the bench is open"
        ),
        inline=False,
    )
    about_embed.set_footer(text="HEAVEN about panel")
    await upsert_bot_embed(about_chan, "HEAVEN about panel", about_embed)

    rules_embed = discord.Embed(
        title="📜 ── SERVER RULES ──",
        description=(
            "By staying here you agree to these rules.\n"
            "Staff decisions are final.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.from_rgb(231, 76, 60),
    )
    rules_embed.add_field(name="🔞 1 — 18+ ONLY", value="No minors. Age-verified through our mod team. Lying about age = permanent ban.", inline=False)
    rules_embed.add_field(name="🤝 2 — CONSENT & ORIGINAL CONTENT", value="Only post what you own or have clear permission to share. No exes, no stolen, no deepfakes.", inline=False)
    rules_embed.add_field(name="🛑 3 — MINORS (ZERO TOLERANCE)", value="Any sexual content involving minors = instant ban + report to Discord and authorities.", inline=False)
    rules_embed.add_field(name="🚫 4 — NO UNSOLICITED NSFW DMs", value="Ask first. Unsolicited NSFW DMs = harassment → ban.", inline=False)
    rules_embed.add_field(name="🔒 5 — WHAT’S HERE STAYS HERE", value="No screenshots/reposts of members without permission.", inline=False)
    rules_embed.add_field(name="📨 6 — REPORT TO MODS", value="Don’t dogpile. DM a mod or use server report tools.", inline=False)
    rules_embed.add_field(name="⚠️ 7 — RESPECT & NO SELLING", value="No hate, harassment, or commercial spam / selling.", inline=False)
    rules_embed.add_field(
        name="🏷️ 8 — ROLES & PRIVATE ROOMS",
        value=(
            "Self-assign tags are cosmetic.\n"
            "**Women / Men / Couples rooms** require mod-given "
            "`Verified Female` / `Verified Male` / `Verified Couple` only."
        ),
        inline=False,
    )
    rules_embed.add_field(
        name="💑 9 — COUPLES ON ONE ACCOUNT",
        value=(
            "Fully welcome. Use a clear display name (e.g. Alex & Sam), "
            "verify as **Couple**, and both partners must be 18+ and consenting. "
            "Others may assume DMs are seen by both of you."
        ),
        inline=False,
    )
    rules_embed.add_field(
        name="🌿 10 — GARDEN MANNERS",
        value=(
            "Be kind. Reply when you can. Lurking is OK. "
            "Don’t pressure anyone to chat, date, or share. Hosts are gardeners — not police-first."
        ),
        inline=False,
    )
    rules_embed.set_footer(text="HEAVEN rules panel")
    await upsert_bot_embed(rules_chan, "HEAVEN rules panel", rules_embed)

    welcome_embed = discord.Embed(
        title="🌿 ── WALKING INTO THE GARDEN ──",
        description=(
            "Verification is only a **soft gate** so the garden stays 18+ and safer.\n"
            "We are not collecting you — we are protecting the space.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.from_rgb(46, 204, 113),
    )
    welcome_embed.add_field(
        name="📋 GENTLE STEPS",
        value=(
            f"**1.** {ticket_chan.mention} when you’re ready (no rush)\n"
            "**2.** Short form — age 18+, single or couple, what kind of company you enjoy\n"
            "**3.** Selfie + paper if a host asks (HAVEN + date + name — no ID card)\n"
            "**4.** Host approves as Female / Male / Couple\n"
            "**5.** You get a real welcome — then the bench is open"
        ),
        inline=False,
    )
    welcome_embed.add_field(
        name="🌱 AFTER YOU’RE IN (only three things)",
        value=(
            "1️⃣ `#general-chat` — the main bench\n"
            "2️⃣ `#introductions` — optional; template button available\n"
            f"3️⃣ {roles_chan.mention} — optional tags\n\n"
            "Everything else is a side path. Explore when you want."
        ),
        inline=False,
    )
    welcome_embed.add_field(
        name="⚠️ SCAM ALERT",
        value=(
            "Real verification is **never** a random DM button from strangers.\n"
            "We never ask for government ID numbers in DMs.\n"
            "Only trust tickets and staff with Moderator / Owner."
        ),
        inline=False,
    )
    welcome_embed.set_footer(text="HEAVEN welcome panel")
    await upsert_bot_embed(welcome_chan, "HEAVEN welcome panel", welcome_embed)

    arrivals_embed = discord.Embed(
        title="🌿 ── ARRIVALS LOUNGE (the gate) ──",
        description=(
            "You’re welcome to sit here while you wait.\n"
            "**Say hi. Ask questions. Lurk.** Verification can wait until you’re comfortable.\n\n"
            f"🎫 Verify when ready → {ticket_chan.mention}\n"
            f"📜 Rules → {rules_chan.mention}\n"
            f"🔓 Guide → {welcome_chan.mention}\n\n"
            "Couples sharing one account: totally fine — just tell us you’re a couple.\n"
            "After verify, this lounge hides and the main garden opens."
        ),
        color=discord.Color.from_rgb(26, 188, 156),
    )
    arrivals_embed.set_footer(text="HEAVEN arrivals panel")
    await upsert_bot_embed(arrivals_chan, "HEAVEN arrivals panel", arrivals_embed)

    # Per-channel guides (skip missing channels quietly)
    guide_count = 0
    for ch_name, (title, body) in CHANNEL_GUIDES.items():
        ch = discord.utils.get(guild.text_channels, name=ch_name)
        if not ch:
            continue
        g = discord.Embed(
            title=f"📌 {title}",
            description=body,
            color=discord.Color.from_rgb(52, 73, 94),
        )
        marker = f"HEAVEN guide:{ch_name}"
        g.set_footer(text=marker)
        await upsert_bot_embed(ch, marker, g)
        guide_count += 1
        await asyncio.sleep(0.25)

    print(f"[INFO] Channel guides upserted: {guide_count}")

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("[DONE] HEAVEN refine complete — no channels deleted.")
    print("")
    print("NEXT:")
    print("  1. Developer Portal → Bot → enable SERVER MEMBERS INTENT")
    print("  2. Reset token if it was ever shared, update .env")
    print("  3. Run:  python bot.py")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    await bot.close()


bot.run(TOKEN)
