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
}

VERIFY_AS_CHOICES = [
    app_commands.Choice(name="Verified Female", value="Verified Female"),
    app_commands.Choice(name="Verified Male", value="Verified Male"),
    app_commands.Choice(name="Verified Couple", value="Verified Couple"),
]


def is_verified(member: discord.Member) -> bool:
    return bool({r.name for r in member.roles} & VERIFIED_ACCESS_ROLES)


def is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    names = {r.name for r in member.roles}
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


async def dm_verified_welcome(member: discord.Member, verification_role_name: str):
    try:
        dm_embed = discord.Embed(
            title="🎉 You are verified in HEAVEN!",
            description=(
                f"You now have **{verification_role_name}**.\n"
                "Main channels are unlocked.\n\n"
                "**Next steps:**\n"
                "1️⃣ `#roles-self-assign` — set your profile\n"
                "2️⃣ `#introductions` — say hi\n"
                "3️⃣ `#general-chat` — start talking\n"
                "4️⃣ Read each channel’s **How to use this room** guide\n\n"
                "Private rooms need matching **Verified Female / Male / Couple**."
            ),
            color=discord.Color.green(),
        )
        await member.send(embed=dm_embed)
    except discord.Forbidden:
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

    await dm_verified_welcome(member, verification_role_name)
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
            await ticket_chan.send(f"✅ Verified {target.mention} as **{role_name}**. Closing in 5s…")
            await close_ticket_later(ticket_chan, 5, f"Verified as {role_name}")

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

    @ui.button(
        label="👩 Female Verification",
        style=discord.ButtonStyle.success,
        custom_id="heaven_opt_female",
    )
    async def open_female_ticket(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.user
        if is_verified(member):
            await interaction.response.send_message("✅ Already verified!", ephemeral=True)
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
        await interaction.response.send_modal(IndividualVerificationModal("Female"))

    @ui.button(
        label="👨 Male Verification",
        style=discord.ButtonStyle.primary,
        custom_id="heaven_opt_male",
    )
    async def open_male_ticket(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.user
        if is_verified(member):
            await interaction.response.send_message("✅ Already verified!", ephemeral=True)
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
        await interaction.response.send_modal(IndividualVerificationModal("Male"))

    @ui.button(
        label="👩‍❤️‍👨 Couple Verification",
        style=discord.ButtonStyle.secondary,
        custom_id="heaven_opt_couple",
    )
    async def open_couple_ticket(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.user
        if is_verified(member):
            await interaction.response.send_message("✅ Already verified!", ephemeral=True)
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
        await interaction.response.send_modal(CoupleVerificationModal())


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
#  BOT + SLASH COMMANDS
# ═════════════════════════════════════════════════════════
class HeavenBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.members = False
        intents.message_content = False
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(TicketButtonView())
        self.add_view(TicketActionView())
        self.add_view(IdentityRolesView())
        self.add_view(VibesRolesView())
        self.tree.add_command(BlogGroup())
        # Sync slash commands to this guild only (fast)
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("[BOT] Slash commands synced to guild.", flush=True)


bot = HeavenBot()


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
        # Close open ticket channel if any
        tch = discord.utils.get(interaction.guild.text_channels, name=ticket_channel_name(member.id))
        if tch:
            await archive_ticket_snapshot(
                interaction.guild, tch, f"APPROVED via /verify → {as_role.value}", interaction.user
            )
            await close_ticket_later(tch, 3, f"/verify {as_role.value}")
        await interaction.followup.send(
            f"✅ {member.mention} verified as **{as_role.value}**.", ephemeral=True
        )
    else:
        await interaction.followup.send(f"❌ {msg}", ephemeral=True)


@bot.tree.command(name="unverify", description="Staff: remove verification access roles")
@app_commands.describe(member="Who to unverify", reason="Reason (logged)")
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
#  ON_MESSAGE LISTENER (LINK PROTECTION + XP)
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

    # Award XP
    member = message.author
    if is_verified(member):
        await add_xp(member, message.channel)

    await bot.process_commands(message)


@bot.tree.command(name="queue", description="Staff: refresh / show verification queue")
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


ICEBREAKERS = [
    "What is your idea of a perfect first date?",
    "If you could have dinner with anyone alive or dead, who would it be?",
    "What's your biggest turn-on and biggest turn-off?",
    "Are you more of a romantic or a realist?",
    "What is the most adventurous thing you've ever done?",
    "What's your favorite way to unwind after a long day?",
    "Do you believe in love at first sight, or love over time?",
    "What is one topic you could talk about for hours?",
    "Would you prefer a cozy night in, or an exciting night out?",
    "What is the best piece of relationship advice you've ever received?",
    "If you could travel anywhere in the world tomorrow, where would you go?",
    "What's your favorite love language (touch, words, acts, gifts, time)?",
    "What is a hobby you've always wanted to try but haven't yet?",
    "What is your absolute favorite SFW or NSFW vibe?"
]

@tasks.loop(hours=24)
async def icebreaker_loop():
    guild = bot.get_guild(GUILD_ID)
    if guild:
        chan = discord.utils.get(guild.text_channels, name="speed-dating")
        if not chan:
            chan = discord.utils.get(guild.text_channels, name="polls-and-questions")
        if chan:
            question = random.choice(ICEBREAKERS)
            embed = discord.Embed(
                title="💬 Daily Icebreaker!",
                description=f"**{question}**\n\nReply below and share your thoughts!",
                color=discord.Color.from_rgb(52, 152, 219)
            )
            embed.set_footer(text="HAVEN Daily Icebreakers")
            await chan.send(embed=embed)


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

        # Mod queue + health ping
        await refresh_mod_queue(guild)
        print(f"[BOT] ✅ Queue ready ({store.count_open()} open)", flush=True)

        mod_chat = discord.utils.get(guild.text_channels, name="mod-chat")
        if mod_chat:
            try:
                await mod_chat.send(
                    embed=discord.Embed(
                        title="🟢 HEAVEN bot online",
                        description=(
                            f"Store: `data/verifications.json`\n"
                            f"Open applications: **{store.count_open()}**\n"
                            f"Staff commands: `/verify` `/unverify` `/trust` `/untrust` `/vstatus` `/queue`"
                        ),
                        color=discord.Color.green(),
                        timestamp=datetime.datetime.now(datetime.timezone.utc),
                    )
                )
            except discord.HTTPException:
                pass

        if not queue_refresh_loop.is_running():
            queue_refresh_loop.start()
        if not icebreaker_loop.is_running():
            icebreaker_loop.start()

    except Exception as e:
        print(f"[ERROR] on_ready setup failed: {e}", flush=True)

@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    # 1. Send premium welcoming private DM
    try:
        dm_embed = discord.Embed(
            title="✨ Welcome to HAVEN! ✨",
            description=(
                f"Hello {member.name}, welcome to the sanctuary!\n\n"
                "To unlock the SFW & NSFW discussions, dating lounges, and media channels, "
                "please complete our secure verification application.\n\n"
                "**How to start:**\n"
                f"1️⃣ Go to the server channel **#open-ticket**.\n"
                "2️⃣ Choose your verification type (Female, Male, or Couple).\n"
                "3️⃣ Fill out the popup application form.\n"
                "4️⃣ Follow instructions in your private ticket to upload your selfie check.\n\n"
                "We look forward to seeing you inside!"
            ),
            color=discord.Color.from_rgb(155, 89, 182)
        )
        if guild.icon:
            dm_embed.set_thumbnail(url=guild.icon.url)
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass

    # 2. Send public greeting in #arrivals-chat
    arrivals_chan = discord.utils.get(guild.text_channels, name="arrivals-chat")
    ticket_chan = discord.utils.get(guild.text_channels, name="open-ticket")
    if arrivals_chan:
        embed = discord.Embed(
            title="💫 A New Soul Has Arrived",
            description=(
                f"Welcome {member.mention} to **HAVEN**!\n\n"
                f"🎫 Head to {ticket_chan.mention if ticket_chan else '#open-ticket'} to verify and unlock the sanctuary.\n"
                "We're excited to have you join our community!"
            ),
            color=discord.Color.from_rgb(46, 204, 113),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="HAVEN Arrivals Lounge • Welcome")
        await arrivals_chan.send(content=member.mention, embed=embed)


@bot.event
async def on_member_remove(member: discord.Member):
    guild = member.guild
    log_ch = await get_log_channel(guild)
    if log_ch:
        app = store.get_app(member.id)
        status_text = app.get("status") if app else "Unverified / No Record"
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


bot.run(TOKEN)
