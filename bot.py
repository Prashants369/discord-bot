import os
import sys
import re
import asyncio
import datetime
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
from dotenv import load_dotenv

import store

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HEAVEN — Verification + Roles Bot (Phase 1)
#   • JSON application store (survives restarts)
#   • Live mod queue in #verification-queue
#   • Staff slash: /verify /unverify /trust /untrust /vstatus /queue
#   • Age gate, verified-only role menus, restart-safe buttons
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

load_dotenv()
store.ensure_store()

TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')

if not TOKEN or TOKEN == 'your_bot_token_here':
    print("[ERROR] Set DISCORD_TOKEN in .env")
    exit(1)
if not GUILD_ID or GUILD_ID == 'your_server_id_here':
    print("[ERROR] Set GUILD_ID in .env")
    exit(1)
GUILD_ID = int(GUILD_ID)

VERIFIED_ACCESS_ROLES = {"Verified", "Verified Female", "Verified Male", "Verified Couple"}
GENDER_VERIFY_ROLES = {"Verified Female", "Verified Male", "Verified Couple"}
STALE_HOURS = 72  # flag (not auto-delete) applications older than this

EXCLUSIVE_ROLE_GROUPS = {
    "heaven_age": ["18-24", "25-34", "35-44", "45+"],
    "heaven_gender": ["Woman", "Man", "Non-binary", "Trans", "Femme", "Masc"],
    "heaven_location": ["Americas", "Europe / Africa", "Asia / Oceania"],
    "heaven_status_primary": [
        "Single", "Couple", "Open Relationship / ENM", "Polyamorous", "Monogamous",
    ],
    "heaven_comfort_level": [
        "SFW Only / Casual", "Flirty & Playful", "Open Minded / Flexible", "Explicit Friendly",
    ],
    "heaven_dm_boundary": ["Open DMs", "Ask Before DMing", "No DMs Allowed"],
}

VERIFY_AS_CHOICES = [
    app_commands.Choice(name="Verified Female", value="Verified Female"),
    app_commands.Choice(name="Verified Male", value="Verified Male"),
    app_commands.Choice(name="Verified Couple", value="Verified Couple"),
]


def is_verified(member: discord.Member | discord.User | None) -> bool:
    if not member:
        return False
    roles = getattr(member, "roles", []) or []
    return bool({r.name for r in roles} & VERIFIED_ACCESS_ROLES)


def is_staff(member: discord.Member | discord.User | None) -> bool:
    if not member:
        return False
    perms = getattr(member, "guild_permissions", None)
    if perms and perms.administrator:
        return True
    roles = getattr(member, "roles", []) or []
    names = {r.name for r in roles}
    return bool(names & {"Moderator", "Owner"})


def ticket_channel_name(member: discord.Member | int) -> str:
    if isinstance(member, discord.Member):
        clean_name = re.sub(r'[^a-zA-Z0-9_-]', '', member.name).lower() or "user"
        return f"ticket-{clean_name[:18]}"
    return f"ticket-{member}"


def parse_ticket_user_id(channel) -> int | None:
    if getattr(channel, "name", None) and channel.name.startswith("ticket-"):
        tail = channel.name[len("ticket-"):]
        if tail.isdigit():
            return int(tail)
    topic = getattr(channel, "topic", None) or ""
    m = re.search(r"applicant[_-]?id[:=]\s*(\d+)", topic, re.I)
    if m:
        return int(m.group(1))
    return None


async def fetch_ticket_channel(guild: discord.Guild, ch_id: int) -> discord.Thread | discord.TextChannel | None:
    chan = guild.get_thread(ch_id)
    if chan:
        return chan
    chan = guild.get_channel(ch_id)
    if chan:
        return chan
    try:
        return await guild.fetch_channel(ch_id)
    except discord.HTTPException:
        pass
    return None


def parse_ticket_role_user_id(interaction: discord.Interaction) -> int | None:
    uid = parse_ticket_user_id(interaction.channel)
    if uid:
        return uid
    if interaction.message and interaction.message.embeds:
        emb = interaction.message.embeds[0]
        m = re.search(r"\(`(\d+)`\)", emb.description or "")
        if m:
            return int(m.group(1))
    return None


def account_flags(member: discord.Member) -> list[str]:
    flags = []
    age = datetime.datetime.now(datetime.timezone.utc) - member.created_at
    if age.days < 7:
        flags.append(f"⚠️ Account only **{age.days}d** old")
    if age.days < 1:
        flags.append("⚠️ Account created **today**")
    if member.display_avatar.is_animated() is False and member.avatar is None:
        flags.append("⚠️ Default avatar")
    return flags


async def resolve_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.HTTPException):
        return None


async def get_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    return discord.utils.get(guild.text_channels, name="verification-log")


async def get_or_create_queue_channel(guild: discord.Guild) -> discord.ForumChannel | discord.TextChannel | None:
    """Find #verification-queue or create it as a ForumChannel under 🛡️ MOD ZONE (never deletes)."""
    # Check cache first
    ch = discord.utils.get(guild.channels, name="verification-queue")
    if ch and isinstance(ch, (discord.ForumChannel, discord.TextChannel)):
        return ch
    # Fallback to fetching all channels to bypass cache delay
    try:
        all_ch = await guild.fetch_channels()
        ch = discord.utils.get(all_ch, name="verification-queue")
        if ch and isinstance(ch, (discord.ForumChannel, discord.TextChannel)):
            return ch
    except Exception:
        pass

    cat = discord.utils.get(guild.categories, name="🛡️ MOD ZONE")
    mod_role = discord.utils.get(guild.roles, name="Moderator")
    owner_role = discord.utils.get(guild.roles, name="Owner")
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True, create_public_threads=True, create_private_threads=True
        ),
    }
    if mod_role:
        overwrites[mod_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    if owner_role:
        overwrites[owner_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    try:
        return await guild.create_forum(
            "verification-queue",
            category=cat,
            overwrites=overwrites,
            topic="Live pending verification queue — auto-updated by the bot",
            reason="Phase 1 forum mod queue",
        )
    except Exception as e:
        print(f"[WARN] Could not create verification-queue forum channel: {e}", flush=True)
        try:
            return await guild.create_text_channel(
                "verification-queue",
                category=cat,
                overwrites=overwrites,
                topic="Live pending verification queue — auto-updated by the bot",
                reason="Phase 1 text mod queue fallback",
            )
        except Exception as e2:
            print(f"[WARN] Could not create verification-queue text channel: {e2}", flush=True)
            return await get_log_channel(guild)


async def get_or_create_tickets_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """Find #verification-tickets or create it under 🎫 VERIFICATION TICKETS category."""
    # Check cache first
    ch = discord.utils.get(guild.text_channels, name="verification-tickets")
    if ch:
        return ch
    # Fallback to fetching all channels to bypass cache delay
    try:
        all_ch = await guild.fetch_channels()
        ch = discord.utils.get(all_ch, name="verification-tickets")
        if isinstance(ch, discord.TextChannel):
            return ch
    except Exception:
        pass

    cat = discord.utils.get(guild.categories, name="🎫 VERIFICATION TICKETS")
    mod_role = discord.utils.get(guild.roles, name="Moderator")
    owner_role = discord.utils.get(guild.roles, name="Owner")
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            create_public_threads=False,
            create_private_threads=False,
            send_messages_in_threads=True,
            read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            manage_threads=True,
            read_message_history=True
        )
    }
    if mod_role:
        overwrites[mod_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_messages=True,
            manage_threads=True,
            read_message_history=True
        )
    if owner_role:
        overwrites[owner_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_messages=True,
            manage_threads=True,
            read_message_history=True
        )
    try:
        return await guild.create_text_channel(
            "verification-tickets",
            category=cat,
            overwrites=overwrites,
            topic="Open your verification ticket here. Conversations are private.",
            reason="Verification tickets parent channel",
        )
    except Exception as e:
        print(f"[WARN] Could not create verification-tickets channel: {e}", flush=True)
        return None


def build_queue_embed() -> discord.Embed:
    open_apps = store.list_open()
    embed = discord.Embed(
        title="📬 Verification Queue",
        description=(
            f"**{len(open_apps)}** open application(s)\n"
            f"Oldest first · Staff: `/verify` `/vstatus` `/queue`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.orange() if open_apps else discord.Color.green(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if not open_apps:
        embed.add_field(name="All clear", value="No pending tickets ✨", inline=False)
    else:
        lines = []
        now = datetime.datetime.now(datetime.timezone.utc)
        for app in open_apps[:15]:
            uid = app.get("user_id")
            status = app.get("status", "?")
            age = app.get("age", "?")
            gender = (app.get("gender") or "?")[:40]
            ch_id = app.get("ticket_channel_id")
            created = app.get("created_at", "")
            stale = ""
            try:
                created_dt = datetime.datetime.fromisoformat(created)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
                hours = (now - created_dt).total_seconds() / 3600
                if hours >= STALE_HOURS:
                    stale = " ⏰ STALE"
            except (TypeError, ValueError):
                hours = 0
            jump = f"<#{ch_id}>" if ch_id else "`no channel`"
            lines.append(
                f"• <@{uid}> (`{uid}`) · **{status}** · age `{age}` · {gender}\n"
                f"  → {jump}{stale}"
            )
        embed.add_field(name="Pending", value="\n".join(lines)[:1024], inline=False)
        if len(open_apps) > 15:
            embed.add_field(name="…", value=f"+{len(open_apps) - 15} more", inline=False)
    embed.set_footer(text="HEAVEN queue panel · auto-refreshes")
    return embed


async def refresh_mod_queue(guild: discord.Guild) -> None:
    queue_ch = await get_or_create_queue_channel(guild)
    if not queue_ch or isinstance(queue_ch, discord.ForumChannel):
        return
    embed = build_queue_embed()
    mid = store.get_queue_message_id()
    if mid:
        try:
            msg = await queue_ch.fetch_message(mid)
            await msg.edit(embed=embed)
            return
        except (discord.NotFound, discord.HTTPException):
            pass
    # Try find existing panel
    try:
        async for msg in queue_ch.history(limit=20):
            if msg.author == guild.me and msg.embeds:
                foot = msg.embeds[0].footer.text if msg.embeds[0].footer else ""
                if "HEAVEN queue panel" in (foot or ""):
                    await msg.edit(embed=embed)
                    store.set_queue_message_id(msg.id)
                    return
    except discord.HTTPException:
        pass
    msg = await queue_ch.send(embed=embed)
    store.set_queue_message_id(msg.id)


async def archive_ticket_snapshot(guild, channel, action: str, mod: discord.Member, extra: str = ""):
    log_chan = await get_log_channel(guild)
    if not log_chan:
        return
    applicant_id = parse_ticket_user_id(channel)
    lines = []
    try:
        async for msg in channel.history(limit=30, oldest_first=True):
            if msg.embeds:
                for emb in msg.embeds:
                    if emb.title:
                        lines.append(f"**Embed:** {emb.title}")
                    if emb.description:
                        lines.append(emb.description[:500])
                    for f in emb.fields:
                        lines.append(f"**{f.name}:** {f.value}")
            if msg.content and not msg.author.bot:
                lines.append(f"{msg.author}: {msg.content[:200]}")
    except discord.HTTPException:
        lines.append("(Could not read ticket history)")

    body = "\n".join(lines)[:3800] or "(empty)"
    embed = discord.Embed(
        title=f"📁 Ticket Archive — {action}",
        description=body,
        color=discord.Color.dark_grey(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(name="Channel", value=channel.name, inline=True)
    embed.add_field(name="Applicant ID", value=str(applicant_id or "?"), inline=True)
    embed.add_field(name="Moderator", value=mod.mention, inline=True)
    if extra:
        embed.add_field(name="Notes", value=extra[:1000], inline=False)
    # Attach store snapshot
    if applicant_id:
        app = store.get_app(applicant_id)
        if app:
            embed.add_field(
                name="Store record",
                value=(
                    f"status=`{app.get('status')}` age=`{app.get('age')}` "
                    f"gender=`{app.get('gender', '')[:40]}`"
                )[:1024],
                inline=False,
            )
    await log_chan.send(embed=embed)


async def close_ticket_later(channel: discord.TextChannel, seconds: int, reason: str):
    await asyncio.sleep(seconds)
    try:
        await channel.delete(reason=reason)
    except discord.HTTPException:
        pass


async def garden_channel_mentions(guild: discord.Guild) -> dict:
    """Resolve the three main garden paths for welcome copy."""
    names = ("general-chat", "introductions", "roles-self-assign", "arrivals-chat", "open-ticket")
    out = {}
    for n in names:
        ch = discord.utils.get(guild.text_channels, name=n)
        out[n] = ch.mention if ch else f"#{n}"
    return out


class WelcomeInteractionView(ui.View):
    def __init__(self, target_member_id: int | None = None):
        super().__init__(timeout=None)
        self.target_member_id = target_member_id

    @ui.button(label="👋 Wave Hello", style=discord.ButtonStyle.primary, custom_id="ivy_welcome_wave")
    async def wave_btn(self, interaction: discord.Interaction, button: ui.Button):
        target = interaction.guild.get_member(self.target_member_id) if self.target_member_id else None
        target_str = target.mention if target else "our new member"
        await interaction.response.send_message(f"👋 {interaction.user.mention} waved hello to {target_str}! Welcome to the HAVEN garden! 🌿")

    @ui.button(label="🤗 Warm Hug", style=discord.ButtonStyle.success, custom_id="ivy_welcome_hug")
    async def hug_btn(self, interaction: discord.Interaction, button: ui.Button):
        target = interaction.guild.get_member(self.target_member_id) if self.target_member_id else None
        target_str = target.mention if target else "our new member"
        await interaction.response.send_message(f"🤗 {interaction.user.mention} gave a warm welcome hug to {target_str}! 💚")

    @ui.button(label="🥂 Cheers", style=discord.ButtonStyle.secondary, custom_id="ivy_welcome_cheers")
    async def cheers_btn(self, interaction: discord.Interaction, button: ui.Button):
        target = interaction.guild.get_member(self.target_member_id) if self.target_member_id else None
        target_str = target.mention if target else "our new member"
        await interaction.response.send_message(f"🥂 {interaction.user.mention} raised a glass to welcome {target_str}! 🥂✨")


async def garden_arrival_ritual(guild: discord.Guild, member: discord.Member, verification_role_name: str):
    """
    Garden arrival: guest is *received*, not only unlocked.
    1) DM (if open)  2) Public wave in #general-chat  3) Announcement Shoutout  4) Soft invite in #introductions
    """
    ch = await garden_channel_mentions(guild)
    couple_note = ""
    if "Couple" in verification_role_name:
        couple_note = (
            "\n\n💑 **Couples on one account are fully welcome here.** "
            "Just be clear you’re a *we* when you introduce yourselves."
        )

    # --- 1) DM (may fail if closed) ---
    try:
        dm_embed = discord.Embed(
            title="🌿 Welcome into the garden",
            description=(
                f"Hey {member.display_name} — you’re in as **{verification_role_name}**.\n\n"
                "HAVEN is a calm, open-minded place to meet like-minded adults. "
                "**No pressure. No activity scores. Lurk as long as you want.**\n\n"
                "**Just three gentle next steps (all optional):**\n"
                f"1️⃣ Sit on the bench → {ch['general-chat']}\n"
                f"2️⃣ Say hi when ready → {ch['introductions']}\n"
                f"3️⃣ Optional tags → {ch['roles-self-assign']}\n\n"
                "We’re glad you’re here. Take your time."
                f"{couple_note}"
            ),
            color=discord.Color.from_rgb(46, 204, 113),
        )
        dm_embed.set_footer(text="HAVEN garden · social first · nothing required of you")
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass
    except discord.HTTPException:
        pass

    # --- 2) Announcement Shoutout ---
    ann_chan = discord.utils.get(guild.text_channels, name="announcements")
    if ann_chan:
        try:
            ann_embed = discord.Embed(
                title="🎉 New Verified Member Shoutout!",
                description=(
                    f"✨ Everyone please welcome {member.mention} — verified as **{verification_role_name}**! 🌿\n\n"
                    "We’re thrilled to have you in our community tribe! Take your time, say hi, and meet everyone.\n\n"
                    "**Tap a button below to break the ice and say hello!**"
                ),
                color=discord.Color.from_rgb(46, 204, 113),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            ann_embed.set_thumbnail(url=member.display_avatar.url)
            ann_embed.set_footer(text="Ivy 🌿 · HAVEN Garden Tribe")
            await ann_chan.send(content=f"🎉 Welcome {member.mention}!", embed=ann_embed, view=WelcomeInteractionView(member.id))
        except discord.HTTPException as e:
            print(f"[WARN] Announcement shoutout failed: {e}", flush=True)

    # --- 3) Public wave in general-chat (always — DMs often fail) ---
    general = discord.utils.get(guild.text_channels, name="general-chat")
    if general:
        try:
            wave = discord.Embed(
                title="🌿 Someone just walked into the garden",
                description=(
                    f"Please welcome {member.mention} — verified as **{verification_role_name}**.\n\n"
                    "If you’re around, say **hi** or drop a 👋 — even one word makes this place feel alive.\n"
                    f"New friends: the bench is {ch['general-chat']}. "
                    f"Intros (optional): {ch['introductions']}."
                ),
                color=discord.Color.from_rgb(26, 188, 156),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
            wave.set_thumbnail(url=member.display_avatar.url)
            wave.set_footer(text="HAVEN · wave hello · no pressure")
            await general.send(content=member.mention, embed=wave, view=WelcomeInteractionView(member.id))
        except discord.HTTPException as e:
            print(f"[WARN] garden public wave failed: {e}", flush=True)

    # --- 3) Soft intro invite (in-server backup if DMs closed) ---
    intros = discord.utils.get(guild.text_channels, name="introductions")
    if intros:
        try:
            invite = discord.Embed(
                title="🌱 When you’re ready — optional intro",
                description=(
                    f"{member.mention} you’re welcome to share a short intro here anytime "
                    "(or skip and just chat in general).\n\n"
                    "Use the **Intro template** button in this channel if you want a simple format.\n"
                    "Hosts try to reply to every intro — you won’t speak into the void."
                ),
                color=discord.Color.from_rgb(155, 89, 182),
            )
            invite.set_footer(text="HAVEN garden · intro optional")
            await intros.send(embed=invite)
        except discord.HTTPException:
            pass


# ═════════════════════════════════════════════════════════
#  APPROVAL / ROLE HELPERS
# ═════════════════════════════════════════════════════════
async def approve_member_verification(guild, member, verification_role_name, mod_user):
    role_map = {r.name: r for r in guild.roles}
    verified_role = role_map.get("Verified")
    target_role = role_map.get(verification_role_name)

    if not verified_role or not target_role:
        return False, f"Role `{verification_role_name}` or `Verified` not found."

    roles_to_remove = [
        role_map[name]
        for name in GENDER_VERIFY_ROLES
        if name != verification_role_name and name in role_map and role_map[name] in member.roles
    ]
    if roles_to_remove:
        await member.remove_roles(*roles_to_remove, reason="Switching verification type")

    roles_to_add = [r for r in (verified_role, target_role) if r not in member.roles]
    if roles_to_add:
        await member.add_roles(*roles_to_add, reason=f"Verified by {mod_user.name}")

    store.set_status(
        member.id,
        "approved",
        by=mod_user.id,
        note=verification_role_name,
        verified_as=verification_role_name,
        ticket_channel_id=None,
    )

    log_chan = await get_log_channel(guild)
    if log_chan:
        await log_chan.send(
            embed=discord.Embed(
                title="✅ Member Verified",
                description=(
                    f"{member.mention} (`{member.id}`) → **{verification_role_name}** "
                    f"by {mod_user.mention}"
                ),
                color=discord.Color.green(),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
        )

    await garden_arrival_ritual(guild, member, verification_role_name)
    await refresh_mod_queue(guild)
    return True, "Success"


async def strip_verification_roles(guild, member, mod_user, reason: str = "Unverified"):
    role_map = {r.name: r for r in guild.roles}
    to_remove = [
        role_map[n] for n in VERIFIED_ACCESS_ROLES
        if n in role_map and role_map[n] in member.roles
    ]
    if to_remove:
        await member.remove_roles(*to_remove, reason=f"{reason} by {mod_user.name}")
    store.set_status(member.id, "denied", by=mod_user.id, note=reason)
    await refresh_mod_queue(guild)


async def set_trusted(guild, member, mod_user, give: bool):
    role = discord.utils.get(guild.roles, name="Trusted")
    if not role:
        return False, "Role `Trusted` not found."
    if give:
        if role not in member.roles:
            await member.add_roles(role, reason=f"Trusted by {mod_user.name}")
        store.add_history(member.id, "trusted", by=mod_user.id)
    else:
        if role in member.roles:
            await member.remove_roles(role, reason=f"Untrusted by {mod_user.name}")
        store.add_history(member.id, "untrusted", by=mod_user.id)
    return True, "Success"


# ═════════════════════════════════════════════════════════
#  TICKET MOD BUTTONS
# ═════════════════════════════════════════════════════════
class TicketActionView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _require_mod(self, interaction: discord.Interaction) -> discord.Member | None:
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            try:
                member = await interaction.guild.fetch_member(interaction.user.id)
            except discord.HTTPException:
                await interaction.followup.send("❌ Could not resolve your profile.", ephemeral=True)
                return None
        if not is_staff(member):
            await interaction.followup.send("❌ Staff only.", ephemeral=True)
            return None
        return member

    async def _get_applicant(self, interaction: discord.Interaction) -> discord.Member | None:
        user_id = parse_ticket_role_user_id(interaction)
        if not user_id:
            await interaction.followup.send("❌ Could not parse applicant user ID.", ephemeral=True)
            return None
        member = await resolve_member(interaction.guild, user_id)
        if not member:
            await interaction.followup.send("❌ Applicant left the server.", ephemeral=True)
        return member

    async def _delete_queue_card(self, interaction: discord.Interaction, target_id: int):
        app = store.get_app(target_id) or {}
        thread_id = app.get("queue_thread_id")
        if thread_id:
            try:
                thread = interaction.guild.get_thread(thread_id)
                if not thread:
                    thread = await interaction.guild.fetch_thread(thread_id)
                if thread:
                    await thread.delete()
                    return
            except Exception:
                pass
        msg_id = app.get("queue_card_message_id")
        if msg_id:
            queue_ch = await get_or_create_queue_channel(interaction.guild)
            if queue_ch and not isinstance(queue_ch, discord.ForumChannel):
                try:
                    msg = await queue_ch.fetch_message(msg_id)
                    await msg.delete()
                except Exception:
                    pass

    async def _approve(self, interaction: discord.Interaction, role_name: str):
        mod = await self._require_mod(interaction)
        if not mod:
            return
        target = await self._get_applicant(interaction)
        if not target:
            return

        ok, msg = await approve_member_verification(interaction.guild, target, role_name, mod)
        if not ok:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            return

        app = store.get_app(target.id) or {}
        ch_id = app.get("ticket_channel_id")
        ticket_chan = await fetch_ticket_channel(interaction.guild, ch_id) if ch_id else None

        await self._delete_queue_card(interaction, target.id)

        if ticket_chan:
            await archive_ticket_snapshot(interaction.guild, ticket_chan, f"APPROVED → {role_name}", mod)
            await ticket_chan.send(f"✅ Verified {target.mention} as **{role_name}**. Ticket remains open.")

        await interaction.followup.send(f"✅ Verified {target.display_name} as **{role_name}**.", ephemeral=True)

    @ui.button(label="Verify Female", style=discord.ButtonStyle.success, custom_id="heaven:t:vf", row=0)
    async def verify_female(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self._approve(interaction, "Verified Female")

    @ui.button(label="Verify Male", style=discord.ButtonStyle.primary, custom_id="heaven:t:vm", row=0)
    async def verify_male(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self._approve(interaction, "Verified Male")

    @ui.button(label="Verify Couple", style=discord.ButtonStyle.secondary, custom_id="heaven:t:vc", row=0)
    async def verify_couple(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self._approve(interaction, "Verified Couple")

    @ui.button(label="Need More Info", style=discord.ButtonStyle.blurple, custom_id="heaven:t:info", row=1)
    async def need_info(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        mod = await self._require_mod(interaction)
        if not mod:
            return
        target = await self._get_applicant(interaction)
        if not target:
            return

        store.set_status(target.id, "needs_info", by=mod.id, note="More details requested")
        await refresh_mod_queue(interaction.guild)

        app = store.get_app(target.id) or {}
        thread_id = app.get("queue_thread_id")
        if thread_id:
            try:
                thread = interaction.guild.get_thread(thread_id)
                if not thread:
                    thread = await interaction.guild.fetch_thread(thread_id)
                if thread:
                    card = await thread.fetch_message(thread_id)
                    if card and card.embeds:
                        new_emb = card.embeds[0].copy()
                        new_emb.description = new_emb.description.replace("⏳ Pending Selfie", "ℹ️ Needs Info").replace("📸 Selfie Uploaded! Ready for review.", "ℹ️ Needs Info")
                        await card.edit(embed=new_emb)
            except Exception:
                pass
        else:
            queue_card_id = app.get("queue_card_message_id")
            if queue_card_id:
                queue_ch = await get_or_create_queue_channel(interaction.guild)
                if queue_ch and not isinstance(queue_ch, discord.ForumChannel):
                    try:
                        card = await queue_ch.fetch_message(queue_card_id)
                        if card and card.embeds:
                            new_emb = card.embeds[0].copy()
                            new_emb.description = new_emb.description.replace("⏳ Pending Selfie", "ℹ️ Needs Info").replace("📸 Selfie Uploaded! Ready for review.", "ℹ️ Needs Info")
                            await card.edit(embed=new_emb)
                    except Exception:
                        pass

        ch_id = app.get("ticket_channel_id")
        ticket_chan = await fetch_ticket_channel(interaction.guild, ch_id) if ch_id else None
        if ticket_chan:
            await ticket_chan.send(
                f"ℹ️ {mod.mention} requested more details.\n"
                f"{target.mention}: Please reply in this channel with any additional information requested by the moderators."
            )

        await interaction.followup.send(f"ℹ️ Requested more info from {target.display_name}.", ephemeral=True)

    @ui.button(label="Deny (keep ticket)", style=discord.ButtonStyle.secondary, custom_id="heaven:t:deny", row=1)
    async def deny(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        mod = await self._require_mod(interaction)
        if not mod:
            return
        target = await self._get_applicant(interaction)
        if not target:
            return

        store.set_status(target.id, "denied", by=mod.id, note="Denied — ticket kept")
        await refresh_mod_queue(interaction.guild)
        await self._delete_queue_card(interaction, target.id)

        ch_id = (store.get_app(target.id) or {}).get("ticket_channel_id")
        ticket_chan = await fetch_ticket_channel(interaction.guild, ch_id) if ch_id else None
        if ticket_chan:
            await ticket_chan.send(f"❌ Denied by {mod.mention}. Ticket stays open for questions.")
        
        try:
            await target.send("❌ HEAVEN verification denied. You can ask in your ticket.")
        except discord.Forbidden:
            pass

        await interaction.followup.send(f"❌ Denied {target.display_name}'s application (ticket kept open).", ephemeral=True)

    @ui.button(label="Reject & Kick", style=discord.ButtonStyle.danger, custom_id="heaven:t:kick", row=2)
    async def reject_kick(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        mod = await self._require_mod(interaction)
        if not mod:
            return
        target = await self._get_applicant(interaction)
        if not target:
            return

        store.set_status(target.id, "kicked", by=mod.id, note="Reject + kick", ticket_channel_id=None)
        await self._delete_queue_card(interaction, target.id)

        ch_id = (store.get_app(target.id) or {}).get("ticket_channel_id")
        ticket_chan = await fetch_ticket_channel(interaction.guild, ch_id) if ch_id else None
        if ticket_chan:
            await archive_ticket_snapshot(interaction.guild, ticket_chan, "REJECT + KICK", mod)
            await ticket_chan.send(f"👢 Kicked **{target}**. Closing in 3s…")
            await close_ticket_later(ticket_chan, 3, "Verification rejected — kick")

        try:
            await target.send("❌ Verification rejected — removed from HEAVEN.")
        except discord.Forbidden:
            pass
        try:
            await target.kick(reason=f"Verification rejected by {mod.name}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Missing kick permission.", ephemeral=True)
            return

        await interaction.followup.send(f"👢 Kicked {target.display_name}.", ephemeral=True)

    @ui.button(label="Reject & Ban", style=discord.ButtonStyle.danger, custom_id="heaven:t:ban", row=2)
    async def reject_ban(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        mod = await self._require_mod(interaction)
        if not mod:
            return
        target = await self._get_applicant(interaction)
        if not target:
            return

        store.set_status(target.id, "banned", by=mod.id, note="Reject + ban", ticket_channel_id=None)
        await self._delete_queue_card(interaction, target.id)

        ch_id = (store.get_app(target.id) or {}).get("ticket_channel_id")
        ticket_chan = await fetch_ticket_channel(interaction.guild, ch_id) if ch_id else None
        if ticket_chan:
            await archive_ticket_snapshot(interaction.guild, ticket_chan, "REJECT + BAN", mod)
            await ticket_chan.send(f"🔨 Banned **{target}**. Closing in 3s…")
            await close_ticket_later(ticket_chan, 3, "Verification rejected — ban")

        try:
            await target.send("❌ Verification rejected — banned from HEAVEN.")
        except discord.Forbidden:
            pass
        try:
            await target.ban(reason=f"Verification rejected by {mod.name}", delete_message_days=0)
        except discord.Forbidden:
            await interaction.followup.send("❌ Missing ban permission.", ephemeral=True)
            return

        await interaction.followup.send(f"🔨 Banned {target.display_name}.", ephemeral=True)

    @ui.button(label="Close Ticket", style=discord.ButtonStyle.grey, custom_id="heaven:t:close", row=2)
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        mod = await self._require_mod(interaction)
        if not mod:
            return
        target = await self._get_applicant(interaction)
        if not target:
            return

        store.set_status(target.id, "closed", by=mod.id, note="Ticket closed", ticket_channel_id=None)
        await self._delete_queue_card(interaction, target.id)

        ch_id = (store.get_app(target.id) or {}).get("ticket_channel_id")
        ticket_chan = await fetch_ticket_channel(interaction.guild, ch_id) if ch_id else None
        if ticket_chan:
            await archive_ticket_snapshot(interaction.guild, ticket_chan, "CLOSED", mod)
            await ticket_chan.send("🔒 Closing in 3s…")
            await close_ticket_later(ticket_chan, 3, f"Closed by {mod.name}")

        await interaction.followup.send(f"🔒 Closed ticket channel for {target.display_name}.", ephemeral=True)


# ═════════════════════════════════════════════════════════
#  DOB PARSER & TICKET CREATION
# ═════════════════════════════════════════════════════════
def parse_dob_and_calculate_age(dob_str: str) -> tuple[int | None, str]:
    dob_str = dob_str.strip()
    normalized = re.sub(r'[\s\-\./]+', '-', dob_str)
    
    match_dmy = re.match(r'^(\d{1,2})\-(\d{1,2})\-(\d{4})$', normalized)
    match_ymd = re.match(r'^(\d{4})\-(\d{1,2})\-(\d{1,2})$', normalized)
    
    dt = None
    if match_dmy:
        day, month, year = map(int, match_dmy.groups())
        try:
            dt = datetime.datetime(year, month, day)
        except ValueError:
            pass
    elif match_ymd:
        year, month, day = map(int, match_ymd.groups())
        try:
            dt = datetime.datetime(year, month, day)
        except ValueError:
            pass
            
    if not dt:
        return None, f"Could not parse '{dob_str}' (use DD/MM/YYYY)"
        
    today = datetime.date.today()
    age = today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
    return age, dt.strftime("%d %B %Y")


async def create_verification_ticket(
    interaction: discord.Interaction,
    email: str,
    dob_text: str,
    calculated_age_text: str,
    applicant_type: str,
    about_text: str,
    looking: str,
    region: str,
    dob_p2_text: str = None,
    calculated_age_p2_text: str = None
):
    guild = interaction.guild
    member = interaction.user
    
    tname = ticket_channel_name(member)
    ticket_cat = discord.utils.get(guild.categories, name="🎫 VERIFICATION TICKETS")
    if not ticket_cat:
        ticket_cat = await guild.create_category("🎫 VERIFICATION TICKETS")

    # Check if existing ticket channel already open
    app = store.get_app(member.id)
    if app and app.get("status") in store.OPEN_STATUSES:
        ch_id = app.get("ticket_channel_id")
        if ch_id:
            existing = guild.get_channel(ch_id)
            if existing:
                await interaction.followup.send(f"📩 You already have an open ticket: {existing.mention}", ephemeral=True)
                return

    mod_role = discord.utils.get(guild.roles, name="Moderator")
    owner_role = discord.utils.get(guild.roles, name="Owner")
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True,
            embed_links=True, read_message_history=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True, read_message_history=True,
        ),
    }
    if mod_role:
        overwrites[mod_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_messages=True,
            manage_channels=True, read_message_history=True,
        )
    if owner_role:
        overwrites[owner_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_messages=True,
            manage_channels=True, read_message_history=True,
        )

    ticket_channel = await guild.create_text_channel(
        tname,
        category=ticket_cat,
        overwrites=overwrites,
        topic=f"applicant_id:{member.id} | email:{email} | pending verification",
        reason=f"Verification ticket for {member.name}",
    )

    flags = account_flags(member)
    flag_text = ("\n" + "\n".join(flags)) if flags else ""

    gender_store_str = f"{applicant_type}"
    if applicant_type == "Couple":
        gender_store_str = f"Couple (P1: {calculated_age_text}, P2: {calculated_age_p2_text})"

    embed = discord.Embed(
        title=f"📋 Premium Verification Application — {member.display_name}",
        description=(
            f"**Applicant:** {member.mention} (`{member.id}`)\n"
            f"**Type:** **{applicant_type}**\n"
            f"**Account created:** <t:{int(member.created_at.timestamp())}:D>\n"
            f"**Joined:** "
            f"{'<t:' + str(int(member.joined_at.timestamp())) + ':R>' if member.joined_at else 'unknown'}\n"
            f"**Submitted:** <t:{int(datetime.datetime.now().timestamp())}:F>\n"
            f"{flag_text}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.from_rgb(26, 188, 156),
    )
    embed.add_field(name="📧 Email Address", value=f"`{email}`", inline=False)
    
    if applicant_type == "Couple":
        embed.add_field(name="🎂 Partner 1 DOB / Age", value=f"DOB: `{dob_text}`\nAge: **{calculated_age_text}**", inline=True)
        embed.add_field(name="🎂 Partner 2 DOB / Age", value=f"DOB: `{dob_p2_text}`\nAge: **{calculated_age_p2_text}**", inline=True)
        embed.add_field(name="ℹ️ Partner Names & Bio", value=about_text[:1024], inline=False)
    else:
        embed.add_field(name="🎂 Date of Birth / Age", value=f"DOB: `{dob_text}`\nAge: **{calculated_age_text}**", inline=True)
        embed.add_field(name="⚧️ Gender Identity", value=f"`{applicant_type}`", inline=True)
        embed.add_field(name="ℹ️ About Applicant / Bio", value=about_text[:1024], inline=False)

    embed.add_field(name="💘 Looking for", value=looking[:1024], inline=False)
    if region:
        embed.add_field(name="🌍 Region / Location", value=region[:1024], inline=False)
    embed.set_footer(text="Moderator Review Panel · Review selfie photo & details")

    # 1. Post details to the applicant's ticket channel (CLEAN — NO buttons for applicant)
    await ticket_channel.send(content=member.mention, embed=embed)

    # 2. Post Mod Review Card to staff-only #verification-log (WITH action buttons)
    log_ch = await get_log_channel(guild)
    queue_card_id = None
    
    if log_ch:
        queue_embed = embed.copy()
        queue_embed.title = f"🔍 MOD REVIEW CARD — {member.display_name}"
        queue_embed.description = (
            f"**Applicant:** {member.mention} (`{member.id}`)\n"
            f"**Ticket Channel:** {ticket_channel.mention}\n"
            f"**Type:** **{applicant_type}**\n"
            f"**Status:** ⏳ Pending Selfie\n"
            f"{flag_text}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        try:
            card = await log_ch.send(embed=queue_embed, view=TicketActionView())
            queue_card_id = card.id
        except Exception as e:
            print(f"[WARN] Failed to send mod review card to #verification-log: {e}", flush=True)

    # Store data
    store.upsert_app(
        member.id,
        status="pending",
        age=calculated_age_text,
        gender=gender_store_str[:80],
        looking_for=looking[:300],
        region=(region or "Not specified")[:200],
        ticket_channel_id=ticket_channel.id,
        ticket_name=tname,
        display_name=member.display_name,
        username=str(member),
        flags=flags,
        queue_card_message_id=queue_card_id,
    )
    store.add_history(member.id, "submitted", by=member.id)

    selfie_embed = discord.Embed(
        title="📸 Selfie Verification Required",
        description=(
            f"{member.mention} Please upload a selfie photo holding a paper note with:\n\n"
            "• **HEAVEN**\n"
            "• **Today's Date**\n"
            "• **Your Discord Username**\n\n"
            "*(Face must be visible. If applying as a Couple, please include both partners in the photo or post 2 selfies! No government ID required.)*"
        ),
        color=discord.Color.orange(),
    )
    await ticket_channel.send(embed=selfie_embed)

    log_chan = await get_log_channel(guild)
    if log_chan:
        await log_chan.send(
            embed=discord.Embed(
                title="📩 New verification ticket opened",
                description=f"{member.mention} (`{member.id}`) · {applicant_type} · {ticket_channel.mention}",
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
        )

    await refresh_mod_queue(guild)
    await interaction.followup.send(
        f"✅ Ticket opened: {ticket_channel.mention}\n"
        "Please head to your ticket and upload your selfie photo.",
        ephemeral=True,
    )


# ═════════════════════════════════════════════════════════
#  TAILORED MODAL CLASSES
# ═════════════════════════════════════════════════════════
class IndividualVerificationModal(ui.Modal):
    def __init__(self, gender: str):
        super().__init__(title=f"📋 Individual ({gender}) Application")
        self.gender = gender

    email_input = ui.TextInput(
        label="1. Email Address",
        placeholder="e.g. alex@gmail.com",
        min_length=5, max_length=100, required=True,
    )
    dob_input = ui.TextInput(
        label="2. Date of Birth (DD/MM/YYYY)",
        placeholder="e.g. 15/08/1998 (Must be 18+)",
        min_length=6, max_length=20, required=True,
    )
    bio_input = ui.TextInput(
        label="3. About Yourself / Bio",
        placeholder="Tell us a little bit about yourself...",
        style=discord.TextStyle.paragraph,
        min_length=5, max_length=300, required=True,
    )
    looking_input = ui.TextInput(
        label="4. What are you looking for?",
        placeholder="Friends, dating, chatting, couples, etc...",
        style=discord.TextStyle.paragraph,
        min_length=5, max_length=300, required=True,
    )
    region_input = ui.TextInput(
        label="5. Region / Location (Optional)",
        placeholder="e.g. Americas, Europe, Asia...",
        required=False, max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        dob_val = self.dob_input.value.strip()
        age, parsed_dob = parse_dob_and_calculate_age(dob_val)
        
        if age is None:
            await interaction.followup.send(f"❌ {parsed_dob}", ephemeral=True)
            return
            
        if age < 18:
            await interaction.followup.send(f"❌ Verification denied. You must be 18+ (parsed age: {age}).", ephemeral=True)
            return

        await create_verification_ticket(
            interaction=interaction,
            email=self.email_input.value.strip(),
            dob_text=parsed_dob,
            calculated_age_text=str(age),
            applicant_type=self.gender,
            about_text=self.bio_input.value.strip(),
            looking=self.looking_input.value.strip(),
            region=self.region_input.value or "",
        )


class CoupleVerificationModal(ui.Modal):
    def __init__(self):
        super().__init__(title="📋 Couple Verification Application")

    email_input = ui.TextInput(
        label="1. Email Address",
        placeholder="e.g. couple@example.com",
        min_length=5, max_length=100, required=True,
    )
    dob_p1_input = ui.TextInput(
        label="2. Partner 1: DOB (DD/MM/YYYY)",
        placeholder="e.g. 12/04/1996 (Must be 18+)",
        min_length=6, max_length=20, required=True,
    )
    dob_p2_input = ui.TextInput(
        label="3. Partner 2: DOB (DD/MM/YYYY)",
        placeholder="e.g. 23/11/1997 (Must be 18+)",
        min_length=6, max_length=20, required=True,
    )
    details_input = ui.TextInput(
        label="4. Partner Names & Bio",
        placeholder="e.g. Sarah & Alex. Tell us about yourselves...",
        style=discord.TextStyle.paragraph,
        min_length=5, max_length=300, required=True,
    )
    looking_input = ui.TextInput(
        label="5. What are you looking for?",
        placeholder="Couples, singles, friends, etc...",
        style=discord.TextStyle.paragraph,
        min_length=5, max_length=300, required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        dob1_val = self.dob_p1_input.value.strip()
        dob2_val = self.dob_p2_input.value.strip()
        
        age1, parsed_dob1 = parse_dob_and_calculate_age(dob1_val)
        age2, parsed_dob2 = parse_dob_and_calculate_age(dob2_val)
        
        if age1 is None:
            await interaction.followup.send(f"❌ Partner 1: {parsed_dob1}", ephemeral=True)
            return
        if age2 is None:
            await interaction.followup.send(f"❌ Partner 2: {parsed_dob2}", ephemeral=True)
            return
            
        if age1 < 18 or age2 < 18:
            await interaction.followup.send(f"❌ Verification denied. Both partners must be 18+ (ages: {age1} and {age2}).", ephemeral=True)
            return

        await create_verification_ticket(
            interaction=interaction,
            email=self.email_input.value.strip(),
            dob_text=parsed_dob1,
            calculated_age_text=str(age1),
            applicant_type="Couple",
            about_text=self.details_input.value.strip(),
            looking=self.looking_input.value.strip(),
            region="",
            dob_p2_text=parsed_dob2,
            calculated_age_p2_text=str(age2)
        )


# ═════════════════════════════════════════════════════════
#  TICKET BUTTON VIEW
# ═════════════════════════════════════════════════════════
class TicketButtonView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _handle_open_ticket(self, interaction: discord.Interaction, applicant_type: str, modal_factory):
        try:
            guild = interaction.guild
            member = interaction.user
            if guild and not isinstance(member, discord.Member):
                member = guild.get_member(member.id) or await resolve_member(guild, member.id) or interaction.user

            if is_verified(member):
                await interaction.response.send_message("✅ You are already verified!", ephemeral=True)
                return
            if store.is_banned_record(member.id):
                await interaction.response.send_message("🚫 Ban record on file. Contact staff.", ephemeral=True)
                return
            if store.has_open_application(member.id):
                app = store.get_app(member.id)
                ch_id = app.get("ticket_channel_id") if app else None
                mention = f"<#{ch_id}>" if ch_id else "your ticket"
                await interaction.response.send_message(f"📩 You already have an open application: {mention}", ephemeral=True)
                return
            await interaction.response.send_modal(modal_factory())
        except Exception as e:
            print(f"[ERROR] Ticket open failed for {interaction.user}: {e}", flush=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ Could not open form: {e}", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Could not open form: {e}", ephemeral=True)
            except Exception:
                pass

    @ui.button(
        label="👩 Female Verification",
        style=discord.ButtonStyle.success,
        custom_id="heaven_opt_female",
    )
    async def open_female_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await self._handle_open_ticket(interaction, "Female", lambda: IndividualVerificationModal("Female"))

    @ui.button(
        label="👨 Male Verification",
        style=discord.ButtonStyle.primary,
        custom_id="heaven_opt_male",
    )
    async def open_male_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await self._handle_open_ticket(interaction, "Male", lambda: IndividualVerificationModal("Male"))

    @ui.button(
        label="👩‍❤️‍👨 Couple Verification",
        style=discord.ButtonStyle.secondary,
        custom_id="heaven_opt_couple",
    )
    async def open_couple_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await self._handle_open_ticket(interaction, "Couple", lambda: CoupleVerificationModal())


# ═════════════════════════════════════════════════════════
#  ROLE MENUS
# ═════════════════════════════════════════════════════════
async def sync_roles(interaction, selected_values, all_option_values, exclusive_group=None):
    if not is_verified(interaction.user):
        await interaction.response.send_message(
            "🔒 Role menus unlock **after verification**.", ephemeral=True
        )
        return

    member = interaction.user
    role_map = {r.name: r for r in interaction.guild.roles}
    selected = set(selected_values)
    all_opts = set(all_option_values)
    clear_pool = set(all_opts)
    if exclusive_group and exclusive_group in EXCLUSIVE_ROLE_GROUPS:
        clear_pool |= set(EXCLUSIVE_ROLE_GROUPS[exclusive_group])

    to_add, to_remove = [], []
    protected = VERIFIED_ACCESS_ROLES | {"Owner", "Moderator", "Trusted", "Weekly Featured", "Event Winner"}

    for name in clear_pool:
        role = role_map.get(name)
        if not role or name in protected:
            continue
        if name in selected and role not in member.roles:
            to_add.append(role)
        elif name not in selected and role in member.roles:
            to_remove.append(role)

    try:
        if to_add:
            await member.add_roles(*to_add, reason="Self-assign via role menu")
        if to_remove:
            await member.remove_roles(*to_remove, reason="Self-assign via role menu")
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ Bot can’t assign roles — check role hierarchy (bot above those roles).",
            ephemeral=True,
        )
        return

    parts = []
    if to_add:
        parts.append(f"✅ Added: {', '.join(r.name for r in to_add)}")
    if to_remove:
        parts.append(f"❌ Removed: {', '.join(r.name for r in to_remove)}")
    if not parts:
        parts.append("✨ Already up to date.")
    await interaction.response.send_message("\n".join(parts), ephemeral=True)


class IdentityRolesView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.select(
        placeholder="💍 Relationship status (up to 2)",
        custom_id="heaven_status", min_values=0, max_values=2,
        options=[
            discord.SelectOption(label="Single", value="Single"),
            discord.SelectOption(label="Couple", value="Couple"),
            discord.SelectOption(label="Open Relationship / ENM", value="Open Relationship / ENM"),
            discord.SelectOption(label="Polyamorous", value="Polyamorous"),
            discord.SelectOption(label="Monogamous", value="Monogamous"),
            discord.SelectOption(label="Wife", value="Wife"),
            discord.SelectOption(label="Husband", value="Husband"),
            discord.SelectOption(label="Exploring / Curious", value="Exploring / Curious"),
            discord.SelectOption(label="Experienced", value="Experienced"),
            discord.SelectOption(label="Shy / New Here", value="Shy / New Here"),
        ],
    )
    async def status_select(self, interaction, select):
        await sync_roles(interaction, select.values, [o.value for o in select.options])

    @ui.select(
        placeholder="💘 Looking for (up to 3)",
        custom_id="heaven_dating", min_values=0, max_values=3,
        options=[
            discord.SelectOption(label="Looking for Friends", value="Looking for Friends"),
            discord.SelectOption(label="Looking for Dating", value="Looking for Dating"),
            discord.SelectOption(label="Looking for Couples", value="Looking for Couples"),
            discord.SelectOption(label="Looking for Singles", value="Looking for Singles"),
            discord.SelectOption(label="Just Chatting", value="Just Chatting"),
            discord.SelectOption(label="Swinger", value="Swinger"),
            discord.SelectOption(label="Monogamish", value="Monogamish"),
            discord.SelectOption(label="Poly-Curious", value="Poly-Curious"),
            discord.SelectOption(label="Relationship-First", value="Relationship-First"),
            discord.SelectOption(label="Play-First", value="Play-First"),
        ],
    )
    async def dating_select(self, interaction, select):
        await sync_roles(interaction, select.values, [o.value for o in select.options])

    @ui.select(
        placeholder="⚧️ Gender presentation (pick 1)",
        custom_id="heaven_gender", min_values=0, max_values=1,
        options=[
            discord.SelectOption(label="Woman", value="Woman"),
            discord.SelectOption(label="Man", value="Man"),
            discord.SelectOption(label="Non-binary", value="Non-binary"),
            discord.SelectOption(label="Trans", value="Trans"),
            discord.SelectOption(label="Femme", value="Femme"),
            discord.SelectOption(label="Masc", value="Masc"),
        ],
    )
    async def gender_select(self, interaction, select):
        await sync_roles(
            interaction, select.values, [o.value for o in select.options], exclusive_group="heaven_gender"
        )

    @ui.select(
        placeholder="🌈 Orientation (up to 2)",
        custom_id="heaven_orientation", min_values=0, max_values=2,
        options=[
            discord.SelectOption(label="Straight", value="Straight"),
            discord.SelectOption(label="Bisexual", value="Bisexual"),
            discord.SelectOption(label="Bicurious", value="Bicurious"),
            discord.SelectOption(label="Lesbian", value="Lesbian"),
            discord.SelectOption(label="Gay", value="Gay"),
            discord.SelectOption(label="Pansexual", value="Pansexual"),
            discord.SelectOption(label="Queer", value="Queer"),
        ],
    )
    async def orientation_select(self, interaction, select):
        await sync_roles(interaction, select.values, [o.value for o in select.options])

    @ui.select(
        placeholder="🎂 Age range (pick 1)",
        custom_id="heaven_age", min_values=0, max_values=1,
        options=[
            discord.SelectOption(label="18-24", value="18-24"),
            discord.SelectOption(label="25-34", value="25-34"),
            discord.SelectOption(label="35-44", value="35-44"),
            discord.SelectOption(label="45+", value="45+"),
        ],
    )
    async def age_select(self, interaction, select):
        await sync_roles(
            interaction, select.values, [o.value for o in select.options], exclusive_group="heaven_age"
        )


class VibesRolesView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.select(
        placeholder="✨ Vibes (up to 5)",
        custom_id="heaven_vibes", min_values=0, max_values=5,
        options=[
            discord.SelectOption(label="Exhibitionist", value="Exhibitionist"),
            discord.SelectOption(label="Voyeur", value="Voyeur"),
            discord.SelectOption(label="Soft & Sweet", value="Soft & Sweet"),
            discord.SelectOption(label="Kinky", value="Kinky"),
            discord.SelectOption(label="Switch", value="Switch"),
            discord.SelectOption(label="Dominant", value="Dominant"),
            discord.SelectOption(label="Submissive", value="Submissive"),
            discord.SelectOption(label="Just Looking", value="Just Looking"),
            discord.SelectOption(label="Content Sharer", value="Content Sharer"),
            discord.SelectOption(label="Chatty", value="Chatty"),
        ],
    )
    async def vibes_select(self, interaction, select):
        await sync_roles(interaction, select.values, [o.value for o in select.options])

    @ui.select(
        placeholder="⛓️ Dynamics (up to 3)",
        custom_id="heaven_dynamics", min_values=0, max_values=3,
        options=[
            discord.SelectOption(label="Hotwife", value="Hotwife"),
            discord.SelectOption(label="Cuckold", value="Cuckold"),
            discord.SelectOption(label="Cuckquean", value="Cuckquean"),
            discord.SelectOption(label="Bull", value="Bull"),
            discord.SelectOption(label="Top", value="Top"),
            discord.SelectOption(label="Bottom", value="Bottom"),
            discord.SelectOption(label="Vers", value="Vers"),
            discord.SelectOption(label="Sadist", value="Sadist"),
            discord.SelectOption(label="Masochist", value="Masochist"),
        ],
    )
    async def dynamics_select(self, interaction, select):
        await sync_roles(interaction, select.values, [o.value for o in select.options])

    @ui.select(
        placeholder="💪 Body & lifestyle (up to 3)",
        custom_id="heaven_body", min_values=0, max_values=3,
        options=[
            discord.SelectOption(label="MILF", value="MILF"),
            discord.SelectOption(label="Dadbod", value="Dadbod"),
            discord.SelectOption(label="Naturist / Nudist", value="Naturist / Nudist"),
            discord.SelectOption(label="Body Positive", value="Body Positive"),
            discord.SelectOption(label="Photographer", value="Photographer"),
            discord.SelectOption(label="Voice Note Lover", value="Voice Note Lover"),
        ],
    )
    async def body_select(self, interaction, select):
        await sync_roles(interaction, select.values, [o.value for o in select.options])

    @ui.select(
        placeholder="🌍 Location (pick 1)",
        custom_id="heaven_location", min_values=0, max_values=1,
        options=[
            discord.SelectOption(label="Americas", value="Americas"),
            discord.SelectOption(label="Europe / Africa", value="Europe / Africa"),
            discord.SelectOption(label="Asia / Oceania", value="Asia / Oceania"),
        ],
    )
    async def location_select(self, interaction, select):
        await sync_roles(
            interaction, select.values, [o.value for o in select.options], exclusive_group="heaven_location"
        )

    @ui.select(
        placeholder="⏰ Availability (up to 2)",
        custom_id="heaven_availability", min_values=0, max_values=2,
        options=[
            discord.SelectOption(label="Night Owl", value="Night Owl"),
            discord.SelectOption(label="Early Bird", value="Early Bird"),
            discord.SelectOption(label="Weekend Warrior", value="Weekend Warrior"),
        ],
    )
    async def availability_select(self, interaction, select):
        await sync_roles(interaction, select.values, [o.value for o in select.options])


class ComfortRolesView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.select(
        placeholder="💬 Conversation Comfort Level (pick 1)",
        custom_id="heaven_comfort_level", min_values=0, max_values=1,
        options=[
            discord.SelectOption(label="SFW Only / Casual", value="SFW Only / Casual", description="Prefers normal, non-explicit, friendly chat", emoji="🟢"),
            discord.SelectOption(label="Flirty & Playful", value="Flirty & Playful", description="Open to light flirtation and playful banter", emoji="🟡"),
            discord.SelectOption(label="Open Minded / Flexible", value="Open Minded / Flexible", description="Comfortable with casual to deeper/spicy talk", emoji="🟠"),
            discord.SelectOption(label="Explicit Friendly", value="Explicit Friendly", description="Fully comfortable with adult & explicit talk", emoji="🔴"),
        ],
    )
    async def comfort_select(self, interaction, select):
        await sync_roles(
            interaction, select.values, [o.value for o in select.options], exclusive_group="heaven_comfort_level"
        )

    @ui.select(
        placeholder="✉️ Direct Message (DM) Boundaries (pick 1)",
        custom_id="heaven_dm_boundary", min_values=0, max_values=1,
        options=[
            discord.SelectOption(label="Open DMs", value="Open DMs", description="Feel free to DM me directly", emoji="📬"),
            discord.SelectOption(label="Ask Before DMing", value="Ask Before DMing", description="Please ask in chat before sending a DM", emoji="✉️"),
            discord.SelectOption(label="No DMs Allowed", value="No DMs Allowed", description="Do not send private messages", emoji="🚫"),
        ],
    )
    async def dm_boundary_select(self, interaction, select):
        await sync_roles(
            interaction, select.values, [o.value for o in select.options], exclusive_group="heaven_dm_boundary"
        )


# ═════════════════════════════════════════════════════════
#  INTRO TEMPLATE (optional — garden bench)
# ═════════════════════════════════════════════════════════
class IntroModal(ui.Modal, title="Optional garden intro"):
    who = ui.TextInput(
        label="Who are you? (single / couple names)",
        placeholder="e.g. Alex, or Alex & Sam",
        max_length=80,
        required=True,
    )
    vibe = ui.TextInput(
        label="Vibe in a few words",
        placeholder="e.g. chill, curious, night owl",
        max_length=100,
        required=True,
    )
    looking = ui.TextInput(
        label="What kind of company do you enjoy?",
        placeholder="friends, deep chat, couples hang…",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=True,
    )
    fun = ui.TextInput(
        label="One easy question for the room (optional)",
        placeholder="e.g. coffee or tea?",
        max_length=150,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_verified(interaction.user):
            await interaction.response.send_message(
                "🌿 Intros unlock after verification — no rush.",
                ephemeral=True,
            )
            return
        fun_line = f"\n**Question for the room:** {self.fun.value}" if self.fun.value else ""
        embed = discord.Embed(
            title=f"🌱 Intro — {interaction.user.display_name}",
            description=(
                f"{interaction.user.mention}\n\n"
                f"**Who:** {self.who.value}\n"
                f"**Vibe:** {self.vibe.value}\n"
                f"**Enjoys:** {self.looking.value}"
                f"{fun_line}\n\n"
                "_Say hi if you’re around — hosts try to reply to every intro._"
            ),
            color=discord.Color.from_rgb(46, 204, 113),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="HAVEN garden intro · optional · no pressure")
        await interaction.response.send_message(embed=embed)
        # Nudge greeters/staff gently
        greeter = discord.utils.get(interaction.guild.roles, name="Greeter")
        mod = discord.utils.get(interaction.guild.roles, name="Moderator")
        ping_bits = []
        if greeter:
            ping_bits.append(greeter.mention)
        elif mod:
            ping_bits.append(mod.mention)
        if ping_bits:
            try:
                await interaction.followup.send(
                    f"{' '.join(ping_bits)} — new intro above when you have a moment 👋",
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )
            except discord.HTTPException:
                pass


class IntroTemplateView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="🌱 Optional intro template",
        style=discord.ButtonStyle.green,
        custom_id="haven_intro_template",
    )
    async def open_intro(self, interaction: discord.Interaction, button: ui.Button):
        if not is_verified(interaction.user):
            await interaction.response.send_message(
                "🌿 Verify first, then introduce yourself anytime — no rush.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(IntroModal())


# ═════════════════════════════════════════════════════════
#  BOT + SLASH COMMANDS
# ═════════════════════════════════════════════════════════
class IvyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(TicketButtonView())
        self.add_view(TicketActionView())
        self.add_view(IdentityRolesView())
        self.add_view(VibesRolesView())
        self.add_view(ComfortRolesView())
        self.add_view(IntroTemplateView())
        self.add_view(WouldYouRatherView())
        self.add_view(WelcomeInteractionView())
        self.tree.add_command(BlogGroup())
        self.tree.add_command(BirthdayGroup())
        # Sync slash commands to this guild and globally
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        g_cmds = await self.tree.sync(guild=guild)
        glob_cmds = await self.tree.sync()
        print(f"[BOT] Slash commands synced: {len(g_cmds)} guild, {len(glob_cmds)} global.", flush=True)


Ivy = IvyBot
HeavenBot = IvyBot
bot = IvyBot()


def staff_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
            if not member and interaction.guild:
                try:
                    member = await interaction.guild.fetch_member(interaction.user.id)
                except discord.HTTPException:
                    member = None
        if not member or not is_staff(member):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


@bot.tree.command(name="verify", description="Staff: verify a member as Female / Male / Couple")
@app_commands.describe(member="Who to verify", as_role="Access role to grant")
@app_commands.choices(as_role=VERIFY_AS_CHOICES)
@app_commands.default_permissions(manage_guild=True)
@staff_check()
async def cmd_verify(
    interaction: discord.Interaction,
    member: discord.Member,
    as_role: app_commands.Choice[str],
):
    await interaction.response.defer(ephemeral=True)
    ok, msg = await approve_member_verification(
        interaction.guild, member, as_role.value, interaction.user
    )
    if ok:
        # Keep ticket channel open if any
        tch = discord.utils.get(interaction.guild.text_channels, name=ticket_channel_name(member.id))
        if tch:
            await archive_ticket_snapshot(
                interaction.guild, tch, f"APPROVED via /verify → {as_role.value}", interaction.user
            )
            await tch.send(f"✅ Verified {member.mention} as **{as_role.value}**. Ticket remains open.")
        await interaction.followup.send(
            f"✅ {member.mention} verified as **{as_role.value}**.", ephemeral=True
        )
    else:
        await interaction.followup.send(f"❌ {msg}", ephemeral=True)


@bot.tree.command(name="unverify", description="Staff: remove verification access roles")
@app_commands.describe(member="Who to unverify", reason="Reason (logged)")
@app_commands.default_permissions(manage_guild=True)
@staff_check()
async def cmd_unverify(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "Unverified by staff",
):
    await interaction.response.defer(ephemeral=True)
    try:
        await strip_verification_roles(interaction.guild, member, interaction.user, reason)
    except discord.Forbidden:
        await interaction.followup.send("❌ Missing permission / role hierarchy.", ephemeral=True)
        return
    log_chan = await get_log_channel(interaction.guild)
    if log_chan:
        await log_chan.send(
            f"↩️ {member.mention} unverified by {interaction.user.mention}: {reason}"
        )
    await interaction.followup.send(f"✅ Removed verification from {member.mention}.", ephemeral=True)


@bot.tree.command(name="trust", description="Staff: give Trusted (Elite lounge)")
@app_commands.describe(member="Member to trust")
@app_commands.default_permissions(manage_guild=True)
@staff_check()
async def cmd_trust(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    ok, msg = await set_trusted(interaction.guild, member, interaction.user, True)
    if not ok:
        await interaction.followup.send(f"❌ {msg}", ephemeral=True)
        return
    await interaction.followup.send(f"💎 {member.mention} is now **Trusted**.", ephemeral=True)


@bot.tree.command(name="untrust", description="Staff: remove Trusted role")
@app_commands.describe(member="Member to untrust")
@app_commands.default_permissions(manage_guild=True)
@staff_check()
async def cmd_untrust(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    ok, msg = await set_trusted(interaction.guild, member, interaction.user, False)
    if not ok:
        await interaction.followup.send(f"❌ {msg}", ephemeral=True)
        return
    await interaction.followup.send(f"✅ Trusted removed from {member.mention}.", ephemeral=True)


@bot.tree.command(name="vstatus", description="Staff: show verification store record")
@app_commands.describe(member="Member to look up")
@app_commands.default_permissions(manage_guild=True)
@staff_check()
async def cmd_vstatus(interaction: discord.Interaction, member: discord.Member):
    app = store.get_app(member.id)
    if not app:
        await interaction.response.send_message(
            f"No store record for {member.mention}.", ephemeral=True
        )
        return
    hist = app.get("history") or []
    hist_lines = [
        f"• `{h.get('at', '')[:19]}` **{h.get('event')}**"
        + (f" — {h.get('note')}" if h.get("note") else "")
        for h in hist[-8:]
    ]
    embed = discord.Embed(
        title=f"Verification record — {member.display_name}",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Status", value=f"`{app.get('status')}`", inline=True)
    embed.add_field(name="Age", value=f"`{app.get('age', '—')}`", inline=True)
    embed.add_field(name="Verified as", value=f"`{app.get('verified_as', '—')}`", inline=True)
    embed.add_field(name="Gender (form)", value=f"`{app.get('gender', '—')}`"[:256], inline=False)
    embed.add_field(name="Looking for", value=(app.get("looking_for") or "—")[:500], inline=False)
    if hist_lines:
        embed.add_field(name="History", value="\n".join(hist_lines)[:1024], inline=False)
    ch_id = app.get("ticket_channel_id")
    if ch_id:
        embed.add_field(name="Ticket", value=f"<#{ch_id}>", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="vpanel", description="Staff: post or refresh verification action buttons in current ticket channel")
@app_commands.default_permissions(manage_guild=True)
@staff_check()
async def cmd_vpanel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not interaction.channel.name.startswith("ticket-"):
        await interaction.followup.send("❌ This command must be used inside a verification ticket channel.", ephemeral=True)
        return
    await interaction.channel.send(
        embed=discord.Embed(
            title="🛡️ Moderator Control Panel",
            description="Use the buttons below to review and approve or deny this verification application:",
            color=discord.Color.gold()
        ),
        view=TicketActionView()
    )
    await interaction.followup.send("✅ Moderator control panel posted below.", ephemeral=True)


def get_blog_owner(thread_id: int) -> int | None:
    data = store._read()
    for user_id_str, app in data["applications"].items():
        if app.get("blog_thread_id") == thread_id:
            return int(user_id_str)
    return None


# ═════════════════════════════════════════════════════════
#  XP & LEVELING SYSTEM
# ═════════════════════════════════════════════════════════
import random

xp_cooldowns = {}

def get_xp_for_level(level: int) -> int:
    return 5 * (level ** 2) + 50 * level + 100

def draw_xp_bar(current: int, needed: int, length: int = 15) -> str:
    if needed <= 0:
        return "░" * length
    ratio = min(current / needed, 1.0)
    filled_len = int(ratio * length)
    unfilled_len = length - filled_len
    return "█" * filled_len + "░" * unfilled_len

async def add_xp(member: discord.Member, channel: discord.TextChannel):
    if member.bot:
        return
        
    now = datetime.datetime.now(datetime.timezone.utc)
    cooldown = xp_cooldowns.get(member.id)
    if cooldown and (now - cooldown).total_seconds() < 60:
        return
        
    xp_cooldowns[member.id] = now
    
    app = store.get_app(member.id) or {}
    current_xp = app.get("xp", 0)
    current_level = app.get("level", 0)
    
    xp_gain = random.randint(15, 25)
    new_xp = current_xp + xp_gain
    
    xp_needed = get_xp_for_level(current_level)
    if new_xp >= xp_needed:
        new_xp -= xp_needed
        new_level = current_level + 1
        
        # Level up embed
        level_embed = discord.Embed(
            title="🏆 Level Up!",
            description=f"🎉 Congratulations {member.mention}! You reached **Level {new_level}**!",
            color=discord.Color.from_rgb(155, 89, 182)
        )
        await channel.send(embed=level_embed)
        
        # Check level milestone celebrations
        LEVEL_MILESTONES = {
            5: ("⭐", "becoming a garden regular"),
            10: ("🌟", "a true garden elder"),
            15: ("💎", "earning Trusted status — Elite Lounge unlocked!"),
            20: ("👑", "becoming a garden LEGEND"),
            25: ("🏆", "reaching beyond legendary status!"),
        }
        if new_level in LEVEL_MILESTONES:
            milestones_sent = app.get("milestones_sent", [])
            key = f"level_{new_level}"
            if key not in milestones_sent:
                emoji, text = LEVEL_MILESTONES[new_level]
                m_embed = discord.Embed(
                    title=f"{emoji} Level Milestone!",
                    description=f"✨ {member.mention} just hit **Level {new_level}**, {text}!",
                    color=discord.Color.gold(),
                )
                await channel.send(embed=m_embed)
                milestones_sent.append(key)
                store.upsert_app(member.id, milestones_sent=milestones_sent)

        # Level 15 grants Trusted role
        if new_level >= 15:
            role = discord.utils.get(member.guild.roles, name="Trusted")
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Automatically reached level 15")
                    log_chan = discord.utils.get(member.guild.text_channels, name="verification-log")
                    if log_chan:
                        await log_chan.send(
                            embed=discord.Embed(
                                title="💎 Role Granted",
                                description=f"{member.mention} reached Level 15 and was automatically granted the **Trusted** role!",
                                color=discord.Color.green(),
                                timestamp=datetime.datetime.now(datetime.timezone.utc)
                            )
                        )
                except discord.Forbidden:
                    pass
        store.upsert_app(member.id, xp=new_xp, level=new_level)
    else:
        store.upsert_app(member.id, xp=new_xp)


# ═════════════════════════════════════════════════════════
#  PAGINATED TOUR VIEW
# ═════════════════════════════════════════════════════════
class TourView(ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=180)
        self.interaction = interaction
        self.current_page = 0
        
        self.pages = [
            (
                "🗺️ Welcome to HAVEN!",
                (
                    "This is the premier community and dating sanctuary.\n\n"
                    "We maintain a safe, welcoming, and verified space for all members.\n"
                    "**Step 1:** Complete verification in **#open-ticket**.\n"
                    "**Step 2:** Customize your profile in **#roles-self-assign**."
                ),
                discord.Color.from_rgb(241, 196, 15)
            ),
            (
                "💬 SFW Discussions & Connection Rooms",
                (
                    "Once verified, you unlock the main general chatting and fun areas:\n\n"
                    "• **#general-chat** — General social hub\n"
                    "• **#introductions** — Introduce yourself to others\n"
                    "• **#looking-for** — Post personal listings or matchmaking preferences\n"
                    "• **#speed-dating** — Quick flirty icebreakers"
                ),
                discord.Color.from_rgb(46, 204, 113)
            ),
            (
                "🔞 NSFW Discussions & Media Sharing",
                (
                    "Verification also grants you access to NSFW areas (only visible to appropriate roles):\n\n"
                    "• **#nsfw-general** / **#intimate-talk** — Discussions & confessions\n"
                    "• **#selfies** / **#intimate-photos** — Share content\n"
                    "• **#verified-couples** — Reserved couples lounge"
                ),
                discord.Color.from_rgb(230, 126, 34)
            ),
            (
                "🏆 Engagement XP & Trusted Role",
                (
                    "By participating in chats, you earn **XP**!\n\n"
                    "• **Level 15** automatically grants you the **Trusted** role.\n"
                    "• Trusted members gain exclusive access to the **💎 ELITE LOUNGE**!"
                ),
                discord.Color.from_rgb(155, 89, 182)
            )
        ]

    def get_embed(self) -> discord.Embed:
        title, desc, color = self.pages[self.current_page]
        embed = discord.Embed(
            title=title,
            description=desc,
            color=color
        )
        embed.set_footer(text=f"Page {self.current_page + 1} of {len(self.pages)} • HAVEN Tour Guide")
        return embed

    @ui.button(label="◀️ Previous", style=discord.ButtonStyle.grey, custom_id="tour_prev")
    async def prev_cb(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("❌ Start your own tour using `/tour`!", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_embed())
        else:
            await interaction.response.defer()

    @ui.button(label="Next ▶️", style=discord.ButtonStyle.primary, custom_id="tour_next")
    async def next_cb(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("❌ Start your own tour using `/tour`!", ephemeral=True)
            return
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_embed())
        else:
            await interaction.response.defer()


@bot.tree.command(name="level", description="Check your current level and XP progress bar")
@app_commands.describe(member="Optional member to check")
async def cmd_level(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    if target.bot:
        await interaction.response.send_message("❌ Bots don't earn XP!", ephemeral=True)
        return
        
    app = store.get_app(target.id) or {}
    current_xp = app.get("xp", 0)
    current_level = app.get("level", 0)
    needed_xp = get_xp_for_level(current_level)
    
    pct = int((current_xp / needed_xp) * 100) if needed_xp > 0 else 0
    bar = draw_xp_bar(current_xp, needed_xp)
    
    embed = discord.Embed(
        title=f"🏆 {target.display_name}'s Level & XP",
        color=discord.Color.from_rgb(155, 89, 182)
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="Level", value=f"⭐ **{current_level}**", inline=True)
    embed.add_field(name="Progress", value=f"`{current_xp} / {needed_xp} XP` ({pct}%)", inline=True)
    embed.add_field(name="XP Bar", value=f"`{bar}`", inline=False)
    
    if current_level < 15:
        left = 15 - current_level
        embed.set_footer(text=f"{left} more levels until you unlock the Trusted role!")
    else:
        embed.set_footer(text="✨ Trusted member status unlocked!")
        
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="xp", description="Alias for /level")
@app_commands.describe(member="Optional member to check")
async def cmd_xp(interaction: discord.Interaction, member: discord.Member | None = None):
    await cmd_level(interaction, member)


class BlogGroup(app_commands.Group, name="blog"):
    @app_commands.command(name="create", description="Create your personal blog page")
    async def blog_create(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        
        if not is_verified(member):
            await interaction.followup.send("❌ You must be verified to create a personal blog!", ephemeral=True)
            return
            
        blog_chan = discord.utils.get(guild.forums, name="member-blogs")
        if not blog_chan:
            await interaction.followup.send("❌ The `#member-blogs` channel is not configured yet.", ephemeral=True)
            return
            
        app = store.get_app(member.id) or {}
        old_thread_id = app.get("blog_thread_id")
        if old_thread_id:
            existing_thread = guild.get_thread(old_thread_id)
            if existing_thread:
                await interaction.followup.send(f"❌ You already have an active blog page: {existing_thread.mention}", ephemeral=True)
                return
                
        embed = discord.Embed(
            title=f"✨ {member.display_name}'s Blog Feed",
            description=(
                f"Welcome to the exclusive personal page of {member.mention}!\n\n"
                "🔒 **Only they can post text, images, and videos here.**\n"
                "💬 Everyone else can view and react with emojis!"
            ),
            color=discord.Color.from_rgb(155, 89, 182)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="HAVEN Member Blogs")
        
        try:
            thread_w_msg = await blog_chan.create_thread(
                name=f"✨│{member.display_name}'s blog",
                embed=embed
            )
            thread = thread_w_msg.thread
            
            store.upsert_app(member.id, blog_thread_id=thread.id)
            await interaction.followup.send(f"✅ Your blog feed has been created! Go check it out here: {thread.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to create blog: {e}", ephemeral=True)

    @app_commands.command(name="delete", description="Delete your personal blog page")
    async def blog_delete(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        
        app = store.get_app(member.id) or {}
        thread_id = app.get("blog_thread_id")
        if not thread_id:
            await interaction.followup.send("❌ You do not have an active blog page.", ephemeral=True)
            return
            
        thread = guild.get_thread(thread_id)
        if thread:
            try:
                await thread.delete(reason="Owner deleted their blog")
            except Exception:
                pass
                
        store.upsert_app(member.id, blog_thread_id=None)
        await interaction.followup.send("✅ Your blog page has been deleted.", ephemeral=True)

    @app_commands.command(name="title", description="Change the title of your blog page")
    @app_commands.describe(new_title="New title for your blog thread")
    async def blog_title(self, interaction: discord.Interaction, new_title: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        
        app = store.get_app(member.id) or {}
        thread_id = app.get("blog_thread_id")
        if not thread_id:
            await interaction.followup.send("❌ You do not have an active blog page.", ephemeral=True)
            return
            
        thread = guild.get_thread(thread_id)
        if not thread:
            await interaction.followup.send("❌ Your blog thread could not be found.", ephemeral=True)
            return
            
        try:
            await thread.edit(name=f"✨│{new_title}")
            await interaction.followup.send(f"✅ Blog title updated to: **✨│{new_title}**", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to update title: {e}", ephemeral=True)


@bot.tree.command(name="tour", description="Take an interactive tour of HAVEN!")
async def cmd_tour(interaction: discord.Interaction):
    view = TourView(interaction)
    await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)


@bot.tree.command(name="spotlight", description="Staff: Feature an active member in announcements")
@app_commands.describe(member="Member to spotlight", bio="Feature bio or short description")
@app_commands.default_permissions(manage_guild=True)
@staff_check()
async def cmd_spotlight(interaction: discord.Interaction, member: discord.Member, bio: str):
    await interaction.response.defer(ephemeral=True)
    
    role = discord.utils.get(interaction.guild.roles, name="Weekly Featured")
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason="Spotlighted by staff")
        except discord.Forbidden:
            pass
            
    ann_chan = discord.utils.get(interaction.guild.text_channels, name="announcements")
    if ann_chan:
        embed = discord.Embed(
            title="🌟 Member Spotlight! 🌟",
            description=(
                f"We are proud to highlight {member.mention} as our featured member this week!\n\n"
                f"**About them:**\n{bio}\n\n"
                "Show them some love and say hello!"
            ),
            color=discord.Color.from_rgb(241, 196, 15),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="HAVEN Weekly Spotlight")
        await ann_chan.send(content=member.mention, embed=embed)
        await interaction.followup.send(f"✅ Spotlighted {member.mention} successfully in {ann_chan.mention}!", ephemeral=True)
    else:
        await interaction.followup.send("❌ Channel `#announcements` not found.", ephemeral=True)


# ═════════════════════════════════════════════════════════
#  PAGINATED COMMANDS DISCOVERY VIEW
# ═════════════════════════════════════════════════════════
class CommandsView(ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=180)
        self.interaction = interaction
        self.current_page = 0
        
        self.pages = [
            (
                "🌿 Page 1: Getting Started",
                (
                    "Welcome to HAVEN! Here is how to get around:\n\n"
                    "• `/tour` — Interactive tour of the server\n"
                    "• `/commands` — Open this command directory\n"
                    "• `/rules` — Quick rules reference\n"
                    "• `/profile [@user]` — View your or another member's garden card\n"
                    "• `/level [@user]` — Check XP and level progress bar\n"
                    "• `/checkin` — Daily check-in (earn bonus XP & build streaks!)"
                ),
                discord.Color.from_rgb(46, 204, 113)
            ),
            (
                "💚 Page 2: Social Interactions",
                (
                    "Show love and connect with others in the garden:\n\n"
                    "• `/hug @member` — Give someone a warm hug\n"
                    "• `/highfive @member` — Give a high five!\n"
                    "• `/wave @member` — Wave hello\n"
                    "• `/cheers @member` — Raise a glass 🥂\n"
                    "• `/compliment @member` — Send a kind compliment\n"
                    "• `/rep @member` — Give someone a reputation point (+1 rep)\n"
                    "• `/thankhost @member` — Thank a garden host publicly\n"
                    "• `/ship @a @b` — Calculate fun compatibility %\n"
                    "• `/matchcard @a @b` — Compare shared vibes between two people"
                ),
                discord.Color.from_rgb(155, 89, 182)
            ),
            (
                "🎲 Page 3: Games & Fun",
                (
                    "Enjoy games and interactive fun:\n\n"
                    "• `/8ball <question>` — Ask the magic 8-ball 🔮\n"
                    "• `/roll [sides]` — Roll a dice (default: 6 sides)\n"
                    "• `/coinflip` — Flip a coin 🪙\n"
                    "• `/wouldyourather` — Play Would You Rather (interactive buttons)\n"
                    "• `/truthordare` — Get a random Truth question or Dare\n"
                    "• `/confess <text>` — Post an anonymous confession in #confessions\n"
                    "• `/vibecheck` — Check how active the garden is right now"
                ),
                discord.Color.from_rgb(241, 196, 15)
            ),
            (
                "🎨 Page 4: Profile & Identity",
                (
                    "Personalize your HAVEN profile:\n\n"
                    "• `/profile [@user]` — Rich garden profile card\n"
                    "• `/mood <text>` — Set your current mood (shown on profile)\n"
                    "• `/birthday set <MM/DD>` — Set your birthday (MM/DD format)\n"
                    "• `/birthday list` — View upcoming birthdays in the garden 🎂\n"
                    "• `/afk [reason]` — Set yourself as AFK (bot notifies callers)\n"
                    "• `/blog create` — Create your personal blog feed\n"
                    "• `/blog delete` — Delete your blog feed\n"
                    "• `/blog title <text>` — Update your blog title"
                ),
                discord.Color.from_rgb(230, 126, 34)
            )
        ]

        if is_staff(interaction.user):
            self.pages.append((
                "🛡️ Page 5: Staff & Moderation Commands",
                (
                    "Moderator and staff tools:\n\n"
                    "• `/verify @member <role>` — Verify member as Female/Male/Couple\n"
                    "• `/unverify @member` — Remove verification access roles\n"
                    "• `/trust @member` — Grant Trusted role (Elite Lounge)\n"
                    "• `/untrust @member` — Remove Trusted role\n"
                    "• `/vstatus @member` — View full verification record & history\n"
                    "• `/vpanel` — Post moderator control buttons in ticket\n"
                    "• `/queue` — Refresh live verification queue\n"
                    "• `/spotlight @member <bio>` — Spotlight a featured member\n"
                    "• `/warn @member <reason>` — Issue a formal warning (logged & DMed)\n"
                    "• `/warnings @member` — View member warning history"
                ),
                discord.Color.from_rgb(231, 76, 60)
            ))

    def get_embed(self) -> discord.Embed:
        title, desc, color = self.pages[self.current_page]
        embed = discord.Embed(
            title=title,
            description=desc,
            color=color
        )
        embed.set_footer(text=f"Page {self.current_page + 1} of {len(self.pages)} • HAVEN Command Directory")
        return embed

    @ui.button(label="◀️ Previous", style=discord.ButtonStyle.grey, custom_id="commands_prev")
    async def prev_cb(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("❌ Use `/commands` to open your own directory!", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.get_embed())
        else:
            await interaction.response.defer()

    @ui.button(label="Next ▶️", style=discord.ButtonStyle.primary, custom_id="commands_next")
    async def next_cb(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("❌ Use `/commands` to open your own directory!", ephemeral=True)
            return
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.get_embed())
        else:
            await interaction.response.defer()


class WouldYouRatherView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.votes_a = 0
        self.votes_b = 0
        self.voted_users = set()

    @ui.button(label="🅰️ Option A", style=discord.ButtonStyle.primary, custom_id="haven_wyr_a")
    async def opt_a(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id in self.voted_users:
            await interaction.response.send_message("❌ You have already voted on this question!", ephemeral=True)
            return
        self.voted_users.add(interaction.user.id)
        self.votes_a += 1
        await interaction.response.send_message(f"✅ You voted for **Option A**! (A: {self.votes_a} | B: {self.votes_b})", ephemeral=True)

    @ui.button(label="🅱️ Option B", style=discord.ButtonStyle.green, custom_id="haven_wyr_b")
    async def opt_b(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id in self.voted_users:
            await interaction.response.send_message("❌ You have already voted on this question!", ephemeral=True)
            return
        self.voted_users.add(interaction.user.id)
        self.votes_b += 1
        await interaction.response.send_message(f"✅ You voted for **Option B**! (A: {self.votes_a} | B: {self.votes_b})", ephemeral=True)


TRUTHS_LIST = [
    "What's the most embarrassing song on your playlist?",
    "When was the last time you cried and why?",
    "What is your biggest guilty pleasure?",
    "If you could trade lives with anyone in this server for one day, who would it be?",
    "What's the funniest misunderstanding you've ever experienced?",
    "What is something you've never told anyone online?",
    "What is your idea of a perfect cozy evening?",
    "What is your favorite quality about yourself?",
    "What's a fashion trend you secretly love or hate?",
    "What is your dream vacation destination?",
]

DARES_LIST = [
    "Change your server nickname to something funny chosen by the next person who speaks!",
    "Post a selfie or photo of your current view in chat!",
    "Send a voice note singing 5 seconds of your favorite song!",
    "Give a compliment to 3 different members in chat!",
    "Use only emojis in your next 3 messages!",
    "Share the last photo in your phone camera roll (SFW)!",
    "Tell a joke in chat — if nobody laughs, you owe another dare!",
    "Write a short 2-line poem about the garden!",
]

class TruthOrDareView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @ui.button(label="🔍 Truth", style=discord.ButtonStyle.primary, custom_id="haven_tod_truth")
    async def truth_cb(self, interaction: discord.Interaction, button: ui.Button):
        question = random.choice(TRUTHS_LIST)
        await interaction.response.send_message(
            f"🔍 **Truth Question for {interaction.user.mention}:**\n\n*{question}*",
            ephemeral=False
        )

    @ui.button(label="🎯 Dare", style=discord.ButtonStyle.danger, custom_id="haven_tod_dare")
    async def dare_cb(self, interaction: discord.Interaction, button: ui.Button):
        dare = random.choice(DARES_LIST)
        await interaction.response.send_message(
            f"🎯 **Dare for {interaction.user.mention}:**\n\n*{dare}*",
            ephemeral=False
        )


class BirthdayGroup(app_commands.Group, name="birthday"):
    @app_commands.command(name="set", description="Set your birthday (MM/DD format)")
    @app_commands.describe(date="Your birthday as MM/DD (e.g. 08/15)")
    async def birthday_set(self, interaction: discord.Interaction, date: str):
        date_str = date.strip()
        if not re.match(r"^(0[1-9]|1[0-2])/(0[1-9]|[12][0-9]|3[01])$", date_str):
            await interaction.response.send_message("❌ Invalid format! Please use **MM/DD** (e.g. `08/15`).", ephemeral=True)
            return
        store.upsert_app(interaction.user.id, birthday=date_str)
        await interaction.response.send_message(f"🎂 Birthday saved as **{date_str}**! The garden will remember 🎉", ephemeral=True)

    @app_commands.command(name="list", description="See upcoming garden birthdays 🎂")
    async def birthday_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = store._read()
        bday_list = []
        for uid_str, app in data.get("applications", {}).items():
            bday = app.get("birthday")
            if bday:
                member = interaction.guild.get_member(int(uid_str))
                name = member.display_name if member else f"User `{uid_str}`"
                bday_list.append(f"• **{name}** — `{bday}`")
        if not bday_list:
            await interaction.followup.send("🎂 No birthdays registered yet! Use `/birthday set` to add yours.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🎂 Garden Birthdays",
            description="\n".join(bday_list[:25]),
            color=discord.Color.from_rgb(241, 196, 15),
        )
        embed.set_footer(text="HAVEN Birthdays · /birthday set")
        await interaction.followup.send(embed=embed)


# ═════════════════════════════════════════════════════════
#  NEW SLASH COMMANDS (DISCOVERY, PROFILE, SOCIAL, GAMES)
# ═════════════════════════════════════════════════════════

@bot.tree.command(name="commands", description="Open the HAVEN command directory")
async def cmd_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    view = CommandsView(interaction)
    await interaction.followup.send(embed=view.get_embed(), view=view, ephemeral=True)


@bot.tree.command(name="profile", description="See your garden profile card 🌿")
@app_commands.describe(member="Optional: check someone else's profile")
async def cmd_profile(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    app = store.get_app(target.id) or {}
    
    level = app.get("level", 0)
    xp = app.get("xp", 0)
    needed = get_xp_for_level(level)
    bar = draw_xp_bar(xp, needed, 12)
    rep = app.get("reputation", 0)
    mood = app.get("mood", "Not set")
    birthday = app.get("birthday", "Not set")
    streak = app.get("checkin_streak", 0)
    total_checkins = app.get("total_checkins", 0)
    verified_as = app.get("verified_as", "Not verified")
    
    cosmetic_roles = []
    skip_roles = {"@everyone", "Verified", "Verified Female", "Verified Male", 
                   "Verified Couple", "Trusted", "Moderator", "Owner", "Greeter",
                   "Weekly Featured", "Server Booster"}
    for role in getattr(target, "roles", []):
        if role.name not in skip_roles and not role.is_default():
            cosmetic_roles.append(role.name)
    vibes = " · ".join(cosmetic_roles[:10]) if cosmetic_roles else "None yet — use #roles-self-assign"
    
    joined_ts = int(target.joined_at.timestamp()) if getattr(target, "joined_at", None) else 0
    
    embed = discord.Embed(
        title=f"🌿 {target.display_name}'s Garden Card",
        color=discord.Color.from_rgb(39, 174, 96),
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="🪪 Verified As", value=verified_as, inline=True)
    embed.add_field(name="⭐ Level", value=f"Level {level}", inline=True)
    embed.add_field(name="💚 Reputation", value=f"{rep} rep", inline=True)
    embed.add_field(name="🔥 XP", value=f"`{bar}` {xp}/{needed}", inline=False)
    embed.add_field(name="📅 Member Since", value=f"<t:{joined_ts}:R>" if joined_ts else "Unknown", inline=True)
    embed.add_field(name="🔥 Check-in Streak", value=f"{streak} days ({total_checkins} total)", inline=True)
    embed.add_field(name="🎭 Mood", value=mood, inline=True)
    embed.add_field(name="🎂 Birthday", value=birthday, inline=True)
    embed.add_field(name="🏷️ Vibes", value=vibes, inline=False)
    embed.set_footer(text="HAVEN garden card · /profile · /mood · /checkin")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rules", description="Quick HAVEN rules reference")
async def cmd_rules(interaction: discord.Interaction):
    rules_ch = discord.utils.get(interaction.guild.text_channels, name="rules")
    embed = discord.Embed(
        title="📜 HAVEN Garden Rules (Quick Reference)",
        description=(
            "1️⃣ **18+ ONLY** — no minors, verified by staff\n"
            "2️⃣ **Consent & Original Content** — only post what you own\n"
            "3️⃣ **Zero Tolerance for Minors** — instant ban + report\n"
            "4️⃣ **No Unsolicited NSFW DMs** — ask first\n"
            "5️⃣ **What's Here Stays Here** — no screenshots without permission\n"
            "6️⃣ **Report to Mods** — don't dogpile\n"
            "7️⃣ **Respect & No Selling** — no hate, no spam\n"
            "8️⃣ **Roles & Private Rooms** — verified gender roles for exclusive rooms\n"
            "9️⃣ **Couples Welcome** — clear display name, both 18+\n"
            "🔟 **Garden Manners** — be kind, lurking OK\n\n"
            f"Full rules: {rules_ch.mention if rules_ch else '#rules'}"
        ),
        color=discord.Color.from_rgb(231, 76, 60),
    )
    embed.set_footer(text="HAVEN garden rules · be kind · consent always")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="mood", description="Set your current mood (shown on your /profile card)")
@app_commands.describe(text="Your mood (e.g. 😴 sleepy but here)")
async def cmd_mood(interaction: discord.Interaction, text: str):
    mood_str = text.strip()[:50]
    store.upsert_app(interaction.user.id, mood=mood_str)
    await interaction.response.send_message(f"🎭 Mood updated to: **{mood_str}**", ephemeral=True)


@bot.tree.command(name="checkin", description="Daily garden check-in — earn bonus XP and build your streak! 🌱")
async def cmd_checkin(interaction: discord.Interaction):
    if not is_verified(interaction.user):
        await interaction.response.send_message("🌿 Verify first!", ephemeral=True)
        return
    
    app = store.get_app(interaction.user.id) or {}
    today = datetime.date.today().isoformat()
    last_checkin = app.get("last_checkin_date")
    streak = app.get("checkin_streak", 0)
    
    if last_checkin == today:
        await interaction.response.send_message("✅ You already checked in today! Come back tomorrow.", ephemeral=True)
        return
    
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    if last_checkin == yesterday:
        streak += 1
    else:
        streak = 1
    
    bonus = 50 + min(streak * 5, 100)
    current_xp = app.get("xp", 0)
    total_c = app.get("total_checkins", 0) + 1
    store.upsert_app(interaction.user.id, 
        xp=current_xp + bonus,
        last_checkin_date=today, 
        checkin_streak=streak,
        total_checkins=total_c
    )
    
    streak_emoji = "🌱"
    if streak >= 30: streak_emoji = "🌳"
    elif streak >= 14: streak_emoji = "🌿"
    elif streak >= 7: streak_emoji = "☘️"
    elif streak >= 3: streak_emoji = "🌱"
    
    embed = discord.Embed(
        title=f"{streak_emoji} Daily Check-In!",
        description=(
            f"{interaction.user.mention} checked into the garden!\n\n"
            f"**Streak:** {streak} day{'s' if streak > 1 else ''} {streak_emoji}\n"
            f"**Bonus XP:** +{bonus} XP\n"
        ),
        color=discord.Color.from_rgb(39, 174, 96),
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(text="HAVEN · /checkin daily for bonus XP")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rep", description="Give someone a reputation point 💚")
@app_commands.describe(member="Who to give rep to")
async def cmd_rep(interaction: discord.Interaction, member: discord.Member):
    if member.id == interaction.user.id:
        await interaction.response.send_message("❌ You can't rep yourself!", ephemeral=True)
        return
    if member.bot:
        await interaction.response.send_message("❌ Bots don't need rep!", ephemeral=True)
        return
    
    app = store.get_app(interaction.user.id) or {}
    rep_given = app.get("rep_given", {})
    today = datetime.date.today().isoformat()
    if rep_given.get(str(member.id)) == today:
        await interaction.response.send_message(f"⏳ You already gave {member.display_name} rep today!", ephemeral=True)
        return
    
    rep_given[str(member.id)] = today
    store.upsert_app(interaction.user.id, rep_given=rep_given)
    
    new_rep = store.increment_field(member.id, "reputation", 1)
    
    embed = discord.Embed(
        description=f"💚 {interaction.user.mention} gave {member.mention} a reputation point! (Total: **{new_rep}** rep)",
        color=discord.Color.from_rgb(39, 174, 96),
    )
    await interaction.response.send_message(embed=embed)


afk_users = {}

@bot.tree.command(name="afk", description="Set yourself as AFK 💤")
@app_commands.describe(reason="Why you're AFK")
async def cmd_afk(interaction: discord.Interaction, reason: str = "AFK"):
    afk_users[interaction.user.id] = {
        "reason": reason[:100],
        "since": datetime.datetime.now(datetime.timezone.utc)
    }
    embed = discord.Embed(
        description=f"💤 {interaction.user.mention} is now AFK: *{reason}*",
        color=discord.Color.light_grey(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="hug", description="Give someone a warm hug 🤗")
@app_commands.describe(member="Who to hug")
async def cmd_hug(interaction: discord.Interaction, member: discord.Member):
    if member.id == interaction.user.id:
        await interaction.response.send_message("🤗 You gave yourself a hug!", ephemeral=True)
        return
    embed = discord.Embed(
        description=f"🤗 {interaction.user.mention} gave {member.mention} a warm hug in the garden!",
        color=discord.Color.from_rgb(255, 182, 193),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="highfive", description="High five someone! 🖐️")
@app_commands.describe(member="Who to high five")
async def cmd_highfive(interaction: discord.Interaction, member: discord.Member):
    embed = discord.Embed(
        description=f"🖐️ {interaction.user.mention} and {member.mention} just high-fived!",
        color=discord.Color.from_rgb(255, 215, 0),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="wave", description="Wave at someone! 👋")
@app_commands.describe(member="Who to wave at")
async def cmd_wave(interaction: discord.Interaction, member: discord.Member):
    embed = discord.Embed(
        description=f"👋 {interaction.user.mention} waved at {member.mention} — wave back!",
        color=discord.Color.from_rgb(135, 206, 250),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="cheers", description="Raise a glass to someone! 🥂")
@app_commands.describe(member="Who to cheers")
async def cmd_cheers(interaction: discord.Interaction, member: discord.Member):
    embed = discord.Embed(
        description=f"🥂 {interaction.user.mention} raised a glass to {member.mention} — cheers!",
        color=discord.Color.from_rgb(218, 165, 32),
    )
    await interaction.response.send_message(embed=embed)


COMPLIMENTS_LIST = [
    "make this garden brighter just by being here.",
    "have an energy that is contagious in the best way.",
    "are a fantastic conversation partner.",
    "bring genuine warmth to this community.",
    "always know how to make people feel welcome.",
    "have great taste and an even better heart.",
    "are truly a core part of what makes HAVEN special.",
]

@bot.tree.command(name="compliment", description="Send someone a kind compliment 💜")
@app_commands.describe(member="Who to compliment")
async def cmd_compliment(interaction: discord.Interaction, member: discord.Member):
    comp = random.choice(COMPLIMENTS_LIST)
    embed = discord.Embed(
        description=f"💜 {interaction.user.mention} wants {member.mention} to know: *You {comp}*",
        color=discord.Color.from_rgb(155, 89, 182),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="thankhost", description="Thank a garden host/greeter for being welcoming 💚")
@app_commands.describe(member="Host or greeter to thank")
async def cmd_thankhost(interaction: discord.Interaction, member: discord.Member):
    roles = {r.name for r in getattr(member, "roles", [])}
    if not (roles & {"Greeter", "Moderator", "Owner"}):
        await interaction.response.send_message("❌ You can only use `/thankhost` for designated Greeters and Hosts!", ephemeral=True)
        return
    
    new_thanks = store.increment_field(member.id, "thanks_received", 1)
    general = discord.utils.get(interaction.guild.text_channels, name="general-chat")
    target_channel = general or interaction.channel
    
    embed = discord.Embed(
        description=f"💚 {interaction.user.mention} wants to thank host {member.mention} for making them feel welcome in the garden! (Total thanks: **{new_thanks}**)",
        color=discord.Color.from_rgb(46, 204, 113),
    )
    await target_channel.send(embed=embed)
    await interaction.response.send_message("✅ Your thanks have been delivered!", ephemeral=True)


@bot.tree.command(name="ship", description="Calculate compatibility between two members 💘")
@app_commands.describe(member_a="First person", member_b="Second person")
async def cmd_ship(interaction: discord.Interaction, member_a: discord.Member, member_b: discord.Member):
    score = abs(hash(f"{min(member_a.id, member_b.id)}-{max(member_a.id, member_b.id)}")) % 101
    filled = score // 10
    meter = "💕" * filled + "░" * (10 - filled)
    
    embed = discord.Embed(
        title=f"💘 Ship Meter: {member_a.display_name} × {member_b.display_name}",
        description=f"**Compatibility:** {score}%\n`{meter}`",
        color=discord.Color.from_rgb(255, 105, 180),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="matchcard", description="Compare shared vibes between two members 💘")
@app_commands.describe(member_a="First person", member_b="Second person")
async def cmd_matchcard(interaction: discord.Interaction, member_a: discord.Member, member_b: discord.Member):
    skip = {"@everyone", "Verified", "Verified Female", "Verified Male", 
            "Verified Couple", "Trusted", "Moderator", "Owner", "Greeter"}
    roles_a = {r.name for r in getattr(member_a, "roles", []) if r.name not in skip and not r.is_default()}
    roles_b = {r.name for r in getattr(member_b, "roles", []) if r.name not in skip and not r.is_default()}
    
    shared = roles_a & roles_b
    total = max(len(roles_a | roles_b), 1)
    pct = int(len(shared) / total * 100)
    
    shared_text = "\n".join(f"• {r}" for r in shared) if shared else "No shared vibes selected yet!"
    
    embed = discord.Embed(
        title=f"💘 Match Card — {member_a.display_name} & {member_b.display_name}",
        description=f"**Shared Vibes ({len(shared)}):**\n{shared_text}\n\n🎯 **Compatibility: {pct}%**",
        color=discord.Color.from_rgb(255, 105, 180),
    )
    embed.set_footer(text="HAVEN · /matchcard")
    await interaction.response.send_message(embed=embed)


RESPONSES_8BALL = [
    "🟢 Yes, absolutely.", "🟢 The garden says yes.", "🟢 Without a doubt.",
    "🟢 Count on it.", "🟢 Most likely.",
    "🟡 Ask again later.", "🟡 The wind isn't sure yet.", "🟡 Hard to say right now.",
    "🟡 Concentrate and ask again.", "🟡 Better not tell you now.",
    "🔴 Nope.", "🔴 The garden says no.", "🔴 Don't count on it.",
    "🔴 My reply is no.", "🔴 Very doubtful.",
]

@bot.tree.command(name="8ball", description="Ask the Magic 8-Ball a question 🔮")
@app_commands.describe(question="Your question")
async def cmd_8ball(interaction: discord.Interaction, question: str):
    ans = random.choice(RESPONSES_8BALL)
    embed = discord.Embed(
        title="🔮 Magic 8-Ball",
        description=f"**Q:** {question}\n**A:** {ans}",
        color=discord.Color.purple(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="roll", description="Roll a dice 🎲")
@app_commands.describe(sides="Number of sides (default: 6)")
async def cmd_roll(interaction: discord.Interaction, sides: int = 6):
    sides = max(2, min(sides, 100))
    res = random.randint(1, sides)
    await interaction.response.send_message(f"🎲 {interaction.user.mention} rolled a **{res}** (d{sides})")


@bot.tree.command(name="coinflip", description="Flip a coin 🪙")
async def cmd_coinflip(interaction: discord.Interaction):
    res = random.choice(["Heads", "Tails"])
    await interaction.response.send_message(f"🪙 {interaction.user.mention} flipped a coin — it's **{res}**!")


WYR_PAIRS = [
    ("Always know what someone is thinking", "Always know what someone is feeling"),
    ("Have a rewind button for life", "Have a pause button for life"),
    ("Live in a cozy cabin in the mountains", "Live in a quiet beach house by the sea"),
    ("Be able to talk to animals", "Be able to speak every human language"),
    ("Always be 10 minutes early", "Always be 10 minutes late"),
    ("Never need sleep again", "Never get tired or stressed again"),
]

@bot.tree.command(name="wouldyourather", description="Play Would You Rather! 🅰️/🅱️")
async def cmd_wouldyourather(interaction: discord.Interaction):
    pair = random.choice(WYR_PAIRS)
    embed = discord.Embed(
        title="🤔 Would You Rather?",
        description=f"**Option A:** {pair[0]}\n**Option B:** {pair[1]}\n\n*Vote below using the buttons!*",
        color=discord.Color.from_rgb(241, 196, 15),
    )
    view = WouldYouRatherView()
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="truthordare", description="Get a Truth question or Dare! 🔍🎯")
async def cmd_truthordare(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎯 Truth or Dare",
        description="Pick **Truth** or **Dare** below to reveal your prompt!",
        color=discord.Color.from_rgb(155, 89, 182),
    )
    view = TruthOrDareView()
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="confess", description="Post an anonymous confession in #confessions 🌙")
@app_commands.describe(text="Your anonymous confession")
async def cmd_confess(interaction: discord.Interaction, text: str):
    if not is_verified(interaction.user):
        await interaction.response.send_message("🌿 Verify first to post confessions.", ephemeral=True)
        return
    
    confessions_ch = discord.utils.get(interaction.guild.text_channels, name="confessions")
    if not confessions_ch:
        try:
            confessions_ch = await interaction.guild.create_text_channel("confessions", topic="Anonymous confessions channel")
        except Exception:
            await interaction.response.send_message("❌ #confessions channel could not be found.", ephemeral=True)
            return
    
    embed = discord.Embed(
        title="🌙 Anonymous Garden Confession",
        description=f"*{text.strip()[:1800]}*",
        color=discord.Color.from_rgb(103, 58, 183),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.set_footer(text="HAVEN · anonymous · no judgment")
    await confessions_ch.send(embed=embed)
    await interaction.response.send_message("✅ Your confession has been posted anonymously.", ephemeral=True)


@bot.tree.command(name="vibecheck", description="Check how active the garden is right now 🌿")
async def cmd_vibecheck(interaction: discord.Interaction):
    await interaction.response.defer()
    guild = interaction.guild
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=24)
    
    msg_count = 0
    unique_authors = set()
    channels_active = 0
    
    for ch in guild.text_channels:
        ch_msgs = 0
        try:
            async for msg in ch.history(after=cutoff, limit=200):
                if not msg.author.bot:
                    msg_count += 1
                    ch_msgs += 1
                    unique_authors.add(msg.author.id)
        except (discord.Forbidden, discord.HTTPException):
            continue
        if ch_msgs > 0:
            channels_active += 1
    
    if msg_count > 100:
        vibe = "🔥 The garden is BUZZING!"
    elif msg_count > 30:
        vibe = "🌿 The garden is warm and active."
    elif msg_count > 10:
        vibe = "🌱 Quiet and cozy."
    else:
        vibe = "🌙 Peaceful — perfect time to start a conversation!"
    
    embed = discord.Embed(
        title="🌿 Garden Vibe Check",
        description=(
            f"**{vibe}**\n\n"
            f"📝 **{msg_count}** messages in last 24h\n"
            f"👥 **{len(unique_authors)}** unique chatters\n"
            f"💬 **{channels_active}** active channels"
        ),
        color=discord.Color.from_rgb(39, 174, 96),
    )
    embed.set_footer(text="HAVEN garden · /vibecheck")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="warn", description="Staff: Issue a formal warning to a member")
@app_commands.describe(member="Member to warn", reason="Reason for warning")
@app_commands.default_permissions(manage_guild=True)
@staff_check()
async def cmd_warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    await interaction.response.defer(ephemeral=True)
    app = store.get_app(member.id) or {}
    warnings = app.get("warnings", [])
    warnings.append({
        "reason": reason[:200],
        "by": interaction.user.id,
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    store.upsert_app(member.id, warnings=warnings)
    
    try:
        await member.send(embed=discord.Embed(
            title="⚠️ Warning from HAVEN Staff",
            description=f"**Reason:** {reason}\n\nPlease review our rules. Repeated violations may result in moderation actions.",
            color=discord.Color.orange(),
        ))
    except (discord.Forbidden, discord.HTTPException):
        pass
    
    log_ch = await get_log_channel(interaction.guild)
    if log_ch:
        await log_ch.send(embed=discord.Embed(
            title="⚠️ Member Warned",
            description=f"{member.mention} (`{member.id}`) was warned by {interaction.user.mention}.\n**Reason:** {reason}\n**Total Warnings:** {len(warnings)}",
            color=discord.Color.orange(),
        ))
    await interaction.followup.send(f"⚠️ Warned {member.mention}. (Total: {len(warnings)} warnings)", ephemeral=True)


@bot.tree.command(name="warnings", description="Staff: Check a member's warning history")
@app_commands.describe(member="Member to check")
@app_commands.default_permissions(manage_guild=True)
@staff_check()
async def cmd_warnings(interaction: discord.Interaction, member: discord.Member):
    app = store.get_app(member.id) or {}
    warnings = app.get("warnings", [])
    if not warnings:
        await interaction.response.send_message(f"✅ {member.mention} has no warnings.", ephemeral=True)
        return
    
    lines = [f"• `{w.get('at', '')[:10]}` — **{w.get('reason')}**" for w in warnings]
    embed = discord.Embed(
        title=f"⚠️ Warning History — {member.display_name}",
        description="\n".join(lines),
        color=discord.Color.orange(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ═════════════════════════════════════════════════════════
#  ON_MESSAGE LISTENER (AFK, WELCOME-BACK, LINK PROTECTION, XP)
# ═════════════════════════════════════════════════════════
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # Dynamically fetch full message payload if message_content intent is disabled
    full_message = message
    is_media_chan = message.channel.name in {"selfies", "intimate-photos", "nsfw-videos", "naturist-media", "exclusive-media"}
    is_ticket_chan = message.channel.name.startswith("ticket-")

    if (is_media_chan or is_ticket_chan) and not bot.intents.message_content:
        try:
            full_message = await message.channel.fetch_message(message.id)
        except Exception as e:
            print(f"[WARN] Failed to fetch full message payload: {e}", flush=True)

    # Check link sharing in media channels
    if is_media_chan:
        if re.search(r"https?://", full_message.content):
            if not any(domain in full_message.content for domain in ["media.discordapp.net", "cdn.discordapp.com", "tenor.com"]):
                try:
                    await message.delete()
                    await message.channel.send(
                        embed=discord.Embed(
                            title="🔒 Content Protection Active",
                            description=(
                                f"❌ {message.author.mention} Link sharing is blocked in media channels to protect member privacy.\n"
                                "Please upload your images and videos directly from your device!"
                            ),
                            color=discord.Color.red()
                        ),
                        delete_after=10
                    )
                    return
                except discord.Forbidden:
                    pass

    # Check if this is a verification ticket channel
    if is_ticket_chan:
        if full_message.attachments:
            has_image = any(att.content_type and att.content_type.startswith("image/") for att in full_message.attachments)
            if has_image:
                uid = parse_ticket_user_id(message.channel)
                if uid and message.author.id == uid:
                    app = store.get_app(uid)
                    if app and app.get("status") in ["pending", "needs_info"]:
                        await message.channel.send(
                            embed=discord.Embed(
                                title="📸 Selfie Received!",
                                description="Thank you! Staff has been notified and will review your verification selfie shortly.",
                                color=discord.Color.green()
                            )
                        )
                        store.add_history(uid, "selfie_uploaded", by=uid, note="Selfie attachment uploaded")

                        log_ch = await get_log_channel(message.guild)
                        if log_ch:
                            try:
                                att = full_message.attachments[0]
                                file_bytes = await att.read()
                                import io
                                d_file = discord.File(io.BytesIO(file_bytes), filename=att.filename)
                                log_embed = discord.Embed(
                                    title=f"📸 SELFIE FOR REVIEW — {message.author.display_name}",
                                    description=(
                                        f"**Applicant:** {message.author.mention} (`{uid}`)\n"
                                        f"**Ticket Channel:** {message.channel.mention}\n"
                                        f"**Status:** 📸 Selfie Uploaded! Ready for review.\n"
                                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                                    ),
                                    color=discord.Color.gold()
                                )
                                await log_ch.send(
                                    embed=log_embed,
                                    file=d_file,
                                    view=TicketActionView()
                                )
                            except Exception as e:
                                print(f"[WARN] Failed to log selfie to staff channel: {e}", flush=True)

                        await refresh_mod_queue(message.guild)

    # AFK handling: author removing AFK
    if message.author.id in afk_users:
        afk_users.pop(message.author.id, None)
        try:
            await message.channel.send(
                f"Welcome back {message.author.mention}! Your AFK state has been removed.",
                delete_after=5
            )
        except Exception:
            pass

    # AFK handling: author mentioning an AFK user
    if message.mentions:
        for mentioned in message.mentions:
            if mentioned.id in afk_users:
                info = afk_users[mentioned.id]
                try:
                    await message.channel.send(
                        f"💤 **{mentioned.display_name}** is currently AFK: *{info['reason']}*",
                        delete_after=8
                    )
                except Exception:
                    pass

    # Award XP & Welcome-Back Tracking
    member = message.author
    if is_verified(member):
        await add_xp(member, message.channel)
        
        # Welcome-back detection
        app = store.get_app(member.id) or {}
        last_seen = app.get("last_seen")
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        
        if last_seen:
            try:
                last_dt = datetime.datetime.fromisoformat(last_seen)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
                gap_days = (now_utc - last_dt).total_seconds() / 86400.0
                if gap_days >= 3.0:
                    today_str = datetime.date.today().isoformat()
                    wb_key = f"wb_{today_str}"
                    milestones_sent = app.get("milestones_sent", [])
                    if wb_key not in milestones_sent:
                        milestones_sent.append(wb_key)
                        store.upsert_app(member.id, milestones_sent=milestones_sent[-50:])
                        general = discord.utils.get(message.guild.text_channels, name="general-chat")
                        if general:
                            wb_embed = discord.Embed(
                                description=f"🌿 {member.mention} is back on the bench — good to see you again!",
                                color=discord.Color.from_rgb(39, 174, 96),
                            )
                            await general.send(embed=wb_embed)
            except Exception:
                pass
        
        store.upsert_app(member.id, last_seen=now_utc.isoformat())

    await bot.process_commands(message)


STAR_THRESHOLD = 5

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if str(payload.emoji) != "⭐":
        return
    if not payload.guild_id:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    channel = guild.get_channel(payload.channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        return
    if channel.name == "starboard":
        return
    
    try:
        message = await channel.fetch_message(payload.message_id)
    except Exception:
        return
    
    star_reaction = discord.utils.get(message.reactions, emoji="⭐")
    if not star_reaction:
        return
    
    count = 0
    try:
        async for user in star_reaction.users():
            if user.id != message.author.id:
                count += 1
    except Exception:
        count = star_reaction.count
    
    if count < STAR_THRESHOLD:
        return
    
    app = store.get_app(message.author.id) or {}
    starboarded = app.get("starboarded_messages", [])
    if message.id in starboarded:
        return
    
    starboard_ch = discord.utils.get(guild.text_channels, name="starboard")
    if not starboard_ch:
        try:
            starboard_ch = await guild.create_text_channel("starboard", topic="⭐ Hall of Fame — Community starred messages")
        except Exception:
            return
    
    embed = discord.Embed(
        description=message.content[:2000] if message.content else "",
        color=discord.Color.gold(),
        timestamp=message.created_at,
    )
    embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
    embed.add_field(name="Source", value=f"[Jump to message]({message.jump_url})", inline=True)
    embed.add_field(name="⭐ Stars", value=str(count), inline=True)
    
    if message.attachments:
        att = message.attachments[0]
        if att.content_type and att.content_type.startswith("image/"):
            embed.set_image(url=att.url)
    
    embed.set_footer(text=f"⭐ {count} | #{channel.name}")
    try:
        await starboard_ch.send(embed=embed)
        starboarded.append(message.id)
        store.upsert_app(message.author.id, starboarded_messages=starboarded[-50:])
    except Exception as e:
        print(f"[WARN] Failed to post to starboard: {e}", flush=True)


@bot.tree.command(name="queue", description="Staff: refresh / show verification queue")
@app_commands.default_permissions(manage_guild=True)
@staff_check()
async def cmd_queue(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await refresh_mod_queue(interaction.guild)
    n = store.count_open()
    q = discord.utils.get(interaction.guild.text_channels, name="verification-queue")
    where = q.mention if q else "#verification-queue"
    await interaction.followup.send(
        f"📬 Queue refreshed · **{n}** open · see {where}", ephemeral=True
    )


async def post_or_refresh_panel(channel: discord.TextChannel, marker: str, embed: discord.Embed, view: ui.View | None):
    try:
        async for msg in channel.history(limit=40):
            if msg.author == bot.user and msg.embeds:
                emb = msg.embeds[0]
                hay = f"{emb.title or ''}|{emb.footer.text if emb.footer else ''}"
                if marker in hay:
                    await msg.edit(embed=embed, view=view)
                    return
    except discord.Forbidden:
        print(f"[WARN] No history in #{channel.name}", flush=True)
    except Exception as e:
        print(f"[WARN] Panel refresh #{channel.name}: {e}", flush=True)
    await channel.send(embed=embed, view=view)


@tasks.loop(minutes=30)
async def queue_refresh_loop():
    guild = bot.get_guild(GUILD_ID)
    if guild:
        try:
            await refresh_mod_queue(guild)
        except Exception as e:
            print(f"[WARN] queue refresh: {e}", flush=True)


GARDEN_PROMPTS_NEUTRAL = [
    "Who's around? Drop a 🌱 just to say you're here.",
    "The bench is open — what's on your mind today?",
    "What's one nice thing that happened recently?",
    "Share a song, a picture of your view, or just a vibe.",
    "If you could teleport anywhere right now, where would you go?",
    "What hobby or interest could you talk about for hours?",
    "Comfort food or comfort movie — what's your pick right now?",
    "What's the kindest interaction you've had online?",
    "For couples: what's a shared little joy of yours?",
    "Describe your current mood in one emoji.",
    "What kind of company do you enjoy most — quiet chat, laughs, or deeper talks?",
    "Drop a fun fact about yourself that nobody here knows yet.",
    "What's something you're looking forward to this week?",
    "What does a perfect cozy evening look like to you?",
]

@tasks.loop(hours=12)
async def daily_prompt_loop():
    """Timezone-neutral prompt for a global community (every 12 hours)."""
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    chan = discord.utils.get(guild.text_channels, name="general-chat")
    if not chan:
        chan = discord.utils.get(guild.text_channels, name="polls-and-questions")
    if not chan:
        return
    question = random.choice(GARDEN_PROMPTS_NEUTRAL)
    embed = discord.Embed(
        title="🌿 Garden prompt (optional)",
        description=(
            f"**{question}**\n\n"
            "Reply if you feel like it — or ignore completely. "
            "No pressure, the bench is always open."
        ),
        color=discord.Color.from_rgb(39, 174, 96),
    )
    embed.set_footer(text="HAVEN garden · global prompt · lurk-friendly")
    try:
        await chan.send(embed=embed)
    except discord.HTTPException as e:
        print(f"[WARN] garden prompt failed: {e}", flush=True)


@tasks.loop(hours=6)
async def milestone_check_loop():
    """Check join-date milestones (7d, 30d, 90d, 365d) and daily birthday celebrations."""
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    today_mmdd = now_utc.strftime("%m/%d")
    today_str = datetime.date.today().isoformat()
    
    general = discord.utils.get(guild.text_channels, name="general-chat")
    
    for member in guild.members:
        if member.bot or not is_verified(member):
            continue
        
        app = store.get_app(member.id) or {}
        milestones = app.get("milestones_sent", [])
        
        # 1) Birthday check
        bday = app.get("birthday")
        if bday and bday == today_mmdd:
            bday_key = f"bday_{today_str}"
            if bday_key not in milestones:
                milestones.append(bday_key)
                store.upsert_app(member.id, milestones_sent=milestones[-50:])
                if general:
                    b_embed = discord.Embed(
                        title="🎂 Happy Birthday!",
                        description=f"🎉 Happy Birthday to {member.mention}! The whole garden celebrates you today! 🌿🎁",
                        color=discord.Color.from_rgb(241, 196, 15),
                    )
                    b_embed.set_thumbnail(url=member.display_avatar.url)
                    try:
                        await general.send(embed=b_embed)
                    except Exception:
                        pass
        
        # 2) Join date milestone check
        if member.joined_at and general:
            days = (now_utc - member.joined_at).days
            checks = {
                7: ("🌿 1 Week Milestone", "has been in the garden for **1 week**. Glad you stayed!"),
                30: ("🌳 30 Days Milestone", "is a **30-day garden regular**. This place is better with you here!"),
                90: ("🌲 90 Days Milestone", "has been a garden pillar for **90 days**!"),
                365: ("🏛️ 1 Year Anniversary", "has been in the garden for **ONE WHOLE YEAR**! 🥳🎉"),
            }
            for d, (title_str, text_str) in checks.items():
                m_key = f"join_{d}d"
                if days >= d and m_key not in milestones:
                    milestones.append(m_key)
                    store.upsert_app(member.id, milestones_sent=milestones[-50:])
                    m_embed = discord.Embed(
                        title=title_str,
                        description=f"✨ {member.mention} {text_str}",
                        color=discord.Color.from_rgb(46, 204, 113),
                    )
                    try:
                        await general.send(embed=m_embed)
                    except Exception:
                        pass


_ready_once = False


@bot.event
async def on_ready():
    global _ready_once
    print(f"[BOT] Logged in as {bot.user.name} ({bot.user.id})", flush=True)
    if _ready_once:
        print("[BOT] Reconnected.", flush=True)
        return
    _ready_once = True

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("[ERROR] Server not found!", flush=True)
        return

    print(f"[BOT] Connected to: {guild.name}", flush=True)
    store.ensure_store()

    # Ensure @everyone role has use_application_commands enabled
    everyone = guild.default_role
    if everyone and not everyone.permissions.use_application_commands:
        try:
            perms = everyone.permissions
            perms.update(use_application_commands=True)
            await everyone.edit(permissions=perms, reason="Allow all members to use slash commands")
            print("[BOT] ✅ Enabled use_application_commands on @everyone role", flush=True)
        except Exception as e:
            print(f"[WARN] Failed to enable slash perms on @everyone: {e}", flush=True)

    # Register persistent views so buttons work across restarts
    bot.add_view(TicketButtonView())
    bot.add_view(IdentityRolesView())
    bot.add_view(VibesRolesView())

    # Ensure member-blogs forum channel exists
    blog_chan = discord.utils.get(guild.forums, name="member-blogs")
    if not blog_chan:
        sfw_cat = discord.utils.get(guild.categories, name="💬 SFW DISCUSSIONS")
        if sfw_cat:
            try:
                await guild.create_forum(
                    name="member-blogs",
                    category=sfw_cat,
                    reason="For personal member blogs"
                )
                print("[BOT] ✅ Created #member-blogs forum channel", flush=True)
            except Exception as e:
                print(f"[WARN] Failed to create #member-blogs forum channel: {e}", flush=True)

    try:
        ticket_chan = discord.utils.get(guild.text_channels, name="open-ticket")
        if ticket_chan:
            embed = discord.Embed(
                title="🎫 ── H A V E N  V E R I F I C A T I O N ──",
                description=(
                    "Click the button below to open a **private verification ticket**.\n"
                    "Your application will be reviewed by our moderation team.\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=discord.Color.from_rgb(46, 204, 113),
            )
            embed.add_field(
                name="📋 Form Requirements",
                value=(
                    "1️⃣ Email Address\n"
                    "2️⃣ Date of Birth (18+ required)\n"
                    "3️⃣ Single / Couple & Partner Details\n"
                    "4️⃣ What you are looking for\n"
                    "5️⃣ Region / Location\n\n"
                    "📸 **Selfie Verification:** Upload a selfie holding a note with **HEAVEN + Date + Username** inside your private ticket."
                ),
                inline=False,
            )
            embed.set_footer(text="HEAVEN verify panel • private human review")
            
            # Delete old messages in open-ticket to force fresh binding
            async for old_m in ticket_chan.history(limit=20):
                try:
                    await old_m.delete()
                except Exception:
                    pass
            await ticket_chan.send(embed=embed, view=TicketButtonView())
            print("[BOT] ✅ #open-ticket fresh panel posted & bound", flush=True)

        roles_chan = discord.utils.get(guild.text_channels, name="roles-self-assign")
        if roles_chan:
            embed1 = discord.Embed(
                title="🎭 ── CUSTOMIZE YOUR PROFILE ──",
                description=(
                    "**Verified only.** Tags are cosmetic — they do **not** unlock "
                    "women/men/couples rooms.\n\n**Part 1 — Status & preferences**"
                ),
                color=discord.Color.from_rgb(155, 89, 182),
            )
            embed1.set_footer(text="HEAVEN roles panel 1")
            await post_or_refresh_panel(roles_chan, "HEAVEN roles panel 1", embed1, IdentityRolesView())

            embed2 = discord.Embed(
                title="✨ ── VIBES & LIFESTYLE ──",
                description="**Part 2** — vibes, dynamics, region. Be honest.",
                color=discord.Color.from_rgb(230, 126, 34),
            )
            embed2.set_footer(text="HEAVEN roles panel 2")
            await post_or_refresh_panel(roles_chan, "HEAVEN roles panel 2", embed2, VibesRolesView())

            embed3 = discord.Embed(
                title="💬 ── CHAT COMFORT & DM BOUNDARIES ──",
                description="**Part 3** — Select your preferred conversation comfort level and DM rules so others know how to interact with you.",
                color=discord.Color.from_rgb(46, 204, 113),
            )
            embed3.set_footer(text="HEAVEN roles panel 3")
            await post_or_refresh_panel(roles_chan, "HEAVEN roles panel 3", embed3, ComfortRolesView())
            print("[BOT] ✅ Role menus ready", flush=True)

        # Intro template on the garden bench path
        intros_chan = discord.utils.get(guild.text_channels, name="introductions")
        if intros_chan:
            intro_embed = discord.Embed(
                title="🌱 Introductions — the garden path",
                description=(
                    "Share who you are **when you feel like it** — or just lurk. Both are welcome.\n\n"
                    "• Singles and **couples on one account** — say so clearly.\n"
                    "• Keep it kind; no pressure to be spicy.\n"
                    "• **Hosts reply to intros** so nobody speaks into the void.\n\n"
                    "Tap the button for a simple optional template."
                ),
                color=discord.Color.from_rgb(39, 174, 96),
            )
            intro_embed.set_footer(text="HAVEN intro panel · optional")
            await post_or_refresh_panel(
                intros_chan, "HAVEN intro panel", intro_embed, IntroTemplateView()
            )
            print("[BOT] ✅ Intro template ready in #introductions", flush=True)

        # Ensure Greeter role exists (hosts — human warmth, not a power role)
        if not discord.utils.get(guild.roles, name="Greeter"):
            try:
                await guild.create_role(
                    name="Greeter",
                    colour=discord.Colour.from_rgb(26, 188, 156),
                    hoist=False,
                    mentionable=True,
                    reason="Garden hosts who welcome new guests",
                )
                print("[BOT] ✅ Created Greeter role", flush=True)
            except discord.HTTPException as e:
                print(f"[WARN] Greeter role: {e}", flush=True)

        # Mod queue + health ping
        await refresh_mod_queue(guild)
        print(f"[BOT] ✅ Queue ready ({store.count_open()} open)", flush=True)

        mod_chat = discord.utils.get(guild.text_channels, name="mod-chat")
        if mod_chat:
            try:
                await mod_chat.send(
                    embed=discord.Embed(
                        title="🌿 Ivy is Online",
                        description=(
                            f"Store: `data/verifications.json`\n"
                            f"Open applications: **{store.count_open()}**\n"
                            f"Staff commands: `/verify` `/unverify` `/trust` `/untrust` `/vstatus` `/queue`"
                        ),
                        color=discord.Color.from_rgb(46, 204, 113),
                        timestamp=datetime.datetime.now(datetime.timezone.utc),
                    )
                )
            except discord.HTTPException:
                pass

        if not queue_refresh_loop.is_running():
            queue_refresh_loop.start()
        if not daily_prompt_loop.is_running():
            daily_prompt_loop.start()
        if not milestone_check_loop.is_running():
            milestone_check_loop.start()

    except Exception as e:
        print(f"[ERROR] on_ready setup failed: {e}", flush=True)

@bot.event
async def on_member_join(member: discord.Member):
    """Gate hospitality — kind first, verify second. Never treat guests like suspects."""
    if member.bot:
        return
    guild = member.guild
    ch = await garden_channel_mentions(guild)

    # Server member count milestone check
    count = guild.member_count
    if count in {25, 50, 75, 100, 150, 200, 250, 500, 1000}:
        ann_chan = discord.utils.get(guild.text_channels, name="announcements")
        if ann_chan:
            m_embed = discord.Embed(
                title="🌱 Garden Milestone Reached!",
                description=f"🎉 The HAVEN garden just grew to **{count} members**! Every single one of you makes this place warm and alive.",
                color=discord.Color.gold(),
            )
            try:
                await ann_chan.send(embed=m_embed)
            except Exception:
                pass

    # 1) Soft DM (optional; often closed)
    try:
        dm_embed = discord.Embed(
            title="🌿 Welcome to the garden gate",
            description=(
                f"Hey {member.display_name} — glad you found **HAVEN**.\n\n"
                "This is a calm, open-minded space for adults to meet like-minded people. "
                "**We want nothing from you** except that you feel welcome.\n\n"
                "A short verification keeps the garden safe (18+). It only takes a few minutes.\n\n"
                f"• Start when ready → {ch['open-ticket']}\n"
                f"• Chat while you wait → {ch['arrivals-chat']}\n\n"
                "Singles and **couples on one account** are both welcome. "
                "Take your time — no rush."
            ),
            color=discord.Color.from_rgb(155, 89, 182),
        )
        if guild.icon:
            dm_embed.set_thumbnail(url=guild.icon.url)
        dm_embed.set_footer(text="HAVEN · gate is kind · lurk OK")
        await member.send(embed=dm_embed)
    except (discord.Forbidden, discord.HTTPException):
        pass

    # 2) Human-feeling hello in arrivals (hosts should also reply in person)
    arrivals_chan = discord.utils.get(guild.text_channels, name="arrivals-chat")
    if arrivals_chan:
        embed = discord.Embed(
            title="🌿 Someone’s at the gate",
            description=(
                f"Hey {member.mention} — welcome.\n\n"
                f"Pull up a seat in this lounge. Verify anytime in {ch['open-ticket']} "
                "(we only check so everyone stays safe).\n\n"
                "**Hosts:** if you’re around, say hi — waiting shouldn’t feel lonely.\n"
                "Couples sharing one Discord ID are fully welcome 💑"
            ),
            color=discord.Color.from_rgb(46, 204, 113),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="HAVEN arrivals · no pressure to verify instantly")
        try:
            greeter = discord.utils.get(guild.roles, name="Greeter")
            content = member.mention
            if greeter:
                content = f"{member.mention} · {greeter.mention}"
            await arrivals_chan.send(
                content=content,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
        except discord.HTTPException as e:
            print(f"[WARN] arrivals greeter failed: {e}", flush=True)


@bot.event
async def on_member_remove(member: discord.Member):
    guild = member.guild
    log_ch = await get_log_channel(guild)
    app = store.get_app(member.id)
    status_text = app.get("status") if app else "Unverified / No Record"
    
    if log_ch:
        joined_str = f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown"
        embed = discord.Embed(
            title="📤 Member Left Server",
            description=(
                f"**User:** {member.mention} (`{member.name}`)\n"
                f"**User ID:** `{member.id}`\n"
                f"**Verification Status:** `{status_text}`\n"
                f"**Joined Server:** {joined_str}"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="HAVEN Audit & Leave Log")
        try:
            await log_ch.send(embed=embed)
        except Exception as e:
            print(f"[WARN] Failed to log member leave: {e}", flush=True)

    # Public farewell for verified members only
    if status_text == "approved":
        general = discord.utils.get(guild.text_channels, name="general-chat")
        if general:
            farewell = discord.Embed(
                description=f"🍂 {member.display_name} has left the garden. We hope they carry some warmth with them.",
                color=discord.Color.from_rgb(149, 165, 166),
            )
            try:
                await general.send(embed=farewell)
            except Exception:
                pass


if __name__ == "__main__":
    bot.run(TOKEN)
