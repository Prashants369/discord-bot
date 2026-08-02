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

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"[CLEANUP] Logged in as {client.user.name}")
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print("[ERROR] Guild not found!")
        await client.close()
        return

    # 1. Delete all old text channels under ticket category starting with ticket-
    ticket_cat = discord.utils.get(guild.categories, name="🎫 VERIFICATION TICKETS")
    if ticket_cat:
        for channel in ticket_cat.text_channels:
            if channel.name.startswith("ticket-"):
                print(f"[CLEANUP] Deleting old ticket channel: #{channel.name}")
                try:
                    await channel.delete()
                except Exception as e:
                    print(f"Failed to delete channel: {e}")
                await asyncio.sleep(0.3)

    # 2. Delete all threads inside #verification-tickets parent channel
    tickets_parent = discord.utils.get(guild.text_channels, name="verification-tickets")
    if tickets_parent:
        print("[CLEANUP] Cleaning threads in #verification-tickets...")
        for thread in tickets_parent.threads:
            print(f"[CLEANUP] Deleting ticket thread: {thread.name}")
            try:
                await thread.delete()
            except Exception as e:
                print(f"Failed to delete thread: {e}")
            await asyncio.sleep(0.3)
            
        async for thread in tickets_parent.archived_threads(limit=100):
            print(f"[CLEANUP] Deleting archived ticket thread: {thread.name}")
            try:
                await thread.delete()
            except Exception as e:
                print(f"Failed to delete archived thread: {e}")
            await asyncio.sleep(0.3)

    # 3. Delete all review threads inside #verification-queue forum channel
    queue_ch = discord.utils.get(guild.channels, name="verification-queue")
    if queue_ch and isinstance(queue_ch, discord.ForumChannel):
        print("[CLEANUP] Cleaning threads in #verification-queue...")
        for thread in queue_ch.threads:
            print(f"[CLEANUP] Deleting review thread: {thread.name}")
            try:
                await thread.delete()
            except Exception as e:
                print(f"Failed to delete review thread: {e}")
            await asyncio.sleep(0.3)

        async for thread in queue_ch.archived_threads(limit=100):
            print(f"[CLEANUP] Deleting archived review thread: {thread.name}")
            try:
                await thread.delete()
            except Exception as e:
                print(f"Failed to delete archived review thread: {e}")
            await asyncio.sleep(0.3)

    print("[CLEANUP] All verification test tickets & queues wiped clean!")
    await client.close()

client.run(TOKEN)
