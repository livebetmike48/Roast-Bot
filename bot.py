import os
import random
import logging
from datetime import datetime, timedelta, timezone, time as dtime

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

import storage
import roasts

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("roast_bot")

# Message Content intent is PRIVILEGED -- must be turned on manually in
# the Discord Developer Portal (this app -> Bot tab -> "Message Content
# Intent" toggle), or the bot will connect but never see message text.
intents = discord.Intents.default()
intents.message_content = True


class RoastBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        storage.init_db()

        roast_cmd = app_commands.Command(
            name="roast",
            description="Roast a member based on their real activity in this server",
            callback=self._roast_callback,
        )
        self.tree.add_command(roast_cmd)

        setchannel_cmd = app_commands.Command(
            name="setchannel",
            description="Set this channel for the daily auto-roast",
            callback=self._setchannel_callback,
        )
        self.tree.add_command(setchannel_cmd)

        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands", len(synced))
        except Exception as e:
            log.error("Slash command sync failed: %s", e)

    async def _roast_callback(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        stats = storage.get_user_stats(str(target.id))
        line = roasts.build_roast(target.display_name, stats)
        await interaction.response.send_message(line)

    async def _setchannel_callback(self, interaction: discord.Interaction):
        storage.set_config("announce_channel_id", str(interaction.channel_id))
        await interaction.response.send_message(f"✅ Daily roast will post in {interaction.channel.mention}.")

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.content:
            return
        storage.record_message(
            str(message.author.id),
            message.author.display_name,
            message.content,
            message.created_at.astimezone(timezone.utc).hour,
        )

    async def on_ready(self):
        log.info("Logged in as %s", self.user)
        if not daily_roast.is_running():
            daily_roast.start(self)
        if not prune_loop.is_running():
            prune_loop.start()


client = RoastBot()


# 8pm/9pm/10pm ET = 00:00/01:00/02:00 UTC during EDT (UTC-4, in effect
# now). NOTE: like the other bots' ET handling in this project, this
# doesn't auto-adjust for EST in the off-season -- it'll fire an hour
# earlier ET during standard time. Override via DAILY_ROAST_HOURS_UTC
# (comma-separated) if that ever needs correcting.
_hours_env = os.getenv("DAILY_ROAST_HOURS_UTC", "0,1,2")
DAILY_ROAST_HOURS_UTC = [int(h.strip()) for h in _hours_env.split(",") if h.strip()]


@tasks.loop(time=[dtime(hour=h, minute=0) for h in DAILY_ROAST_HOURS_UTC])
async def daily_roast(bot: RoastBot):
    """Fires once per scheduled time in DAILY_ROAST_HOURS_UTC (default
    8pm/9pm/10pm ET). Each run logs its pick immediately via mark_roasted,
    so the same-day 3-hour spacing naturally keeps the 9pm and 10pm picks
    from repeating whoever already got hit earlier that day."""
    try:
        channel_id = storage.get_config("announce_channel_id")
        if not channel_id:
            return
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            return

        candidates = storage.get_active_users(days=7, min_messages=5)
        if not candidates:
            log.info("Daily roast: no sufficiently active users this week, skipping")
            return

        already_roasted = storage.recently_roasted_user_ids(days=3)
        pool = [c for c in candidates if c["user_id"] not in already_roasted]
        if not pool:
            pool = candidates  # everyone active got roasted recently -- just pick anyway

        target = random.choice(pool)
        stats = storage.get_user_stats(target["user_id"])
        line = roasts.build_roast(target["username"], stats)

        await channel.send(f"🔥 **Roast of the Day** 🔥\n{line}")
        storage.mark_roasted(target["user_id"])
        log.info("Posted daily roast for %s", target["username"])
    except Exception as e:
        log.error("daily_roast cycle failed, will retry tomorrow: %s", e)


@daily_roast.before_loop
async def before_daily_roast():
    await client.wait_until_ready()


@tasks.loop(hours=24)
async def prune_loop():
    try:
        storage.prune_old_messages(days=30)
    except Exception as e:
        log.error("Message prune failed: %s", e)


@prune_loop.before_loop
async def before_prune():
    await client.wait_until_ready()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set DISCORD_TOKEN in your .env file.")
    client.run(TOKEN)
