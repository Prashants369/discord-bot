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
    print(f"=== SEARCHING FOR 'gip' IN GUILD {guild.name} ===")
    
    # 1. Check current members
    print("\n[1] Checking Current Members...")
    found_member = False
    for m in guild.members:
        name_str = f"{m.name} | {m.display_name} | {m.global_name}"
        if "gip" in name_str.lower():
            print(f" MATCH IN MEMBERS: {m} (ID: {m.id})")
            found_member = True
    if not found_member:
        print(" No current members match 'gip'.")

    # 2. Check Bans
    print("\n[2] Checking Server Bans...")
    try:
        bans = [entry async for entry in guild.bans()]
        found_ban = False
        for b in bans:
            u = b.user
            if "gip" in f"{u.name} {u.display_name}".lower():
                print(f" MATCH IN BANS: {u} (ID: {u.id}) | Reason: {b.reason}")
                found_ban = True
        if not found_ban:
            print(" No bans match 'gip'.")
    except Exception as e:
        print(f" Ban check error: {e}")

    # 3. Check Audit Logs (Full Search)
    print("\n[3] Searching Audit Logs for 'gip'...")
    found_audit = False
    try:
        async for entry in guild.audit_logs(limit=200):
            target_str = str(entry.target) if entry.target else ""
            user_str = str(entry.user) if entry.user else ""
            reason_str = str(entry.reason) if entry.reason else ""
            combined = f"{target_str} {user_str} {reason_str}".lower()
            if "gip" in combined:
                print(f" MATCH IN AUDIT LOG: Action={entry.action} | Target={entry.target} | User={entry.user} | Reason={entry.reason}")
                found_audit = True
    except Exception as e:
        print(f" Audit log search error: {e}")
    if not found_audit:
        print(" No audit log entries match 'gip'.")

    # 4. Check verifications.json Data Store
    print("\n[4] Searching Verification Store History...")
    found_store = False
    store_path = os.path.join("data", "verifications.json")
    if os.path.exists(store_path):
        with open(store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            apps = data.get("applications", {})
            for uid, app in apps.items():
                uname = str(app.get("username", ""))
                dname = str(app.get("display_name", ""))
                hist = str(app.get("history", []))
                combined = f"{uid} {uname} {dname} {hist}".lower()
                if "gip" in combined:
                    print(f" MATCH IN STORE: UID={uid} | Username={uname} | DisplayName={dname} | Status={app.get('status')}")
                    found_store = True
    if not found_store:
        print(" No store records match 'gip'.")

    await client.close()

client.run(TOKEN)
