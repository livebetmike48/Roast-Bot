import os
import random
import time
import logging
from datetime import datetime, timedelta, timezone, time as dtime

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

import storage
import roasts
import glaze

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("roast_bot")

# Message Content intent is PRIVILEGED -- must be turned on manually in
# the Discord Developer Portal (this app -> Bot tab -> "Message Content
# Intent" toggle), or the bot will connect but never see message text.
intents = discord.Intents.default()
intents.message_content = True


def _generate_roast_for(user_id: str, display_name: str) -> str:
    """Pure template generation -- no API call, no cost. The 'remembers
    months of history' payoff comes from storage.get_random_message,
    which draws from the person's ENTIRE message history (never pruned),
    not just recent activity. Records whatever was delivered so future
    picks avoid repeating the same line too soon."""
    stats = storage.get_user_stats(user_id)
    recent_lines = storage.get_recent_lines(user_id, limit=3)
    flashback = storage.get_random_message(user_id)

    line = roasts.build_roast(display_name, stats, recent_lines=recent_lines, flashback_quote=flashback)
    storage.record_roast_line(user_id, line)
    return line


# Per-user cooldown (seconds) so pinging/replying to the bot repeatedly
# can't be used to farm instant roasts on demand.
COUNTER_ROAST_COOLDOWN = int(os.getenv("COUNTER_ROAST_COOLDOWN", "30"))
_last_counter_roast: dict[str, float] = {}


def _generate_glaze_for(user_id: str, display_name: str) -> str:
    """Pure template + real-compliment generation, no cost, same pattern
    as _generate_roast_for but positive."""
    stats = storage.get_user_stats(user_id)
    recent_lines = storage.get_recent_lines(user_id, limit=3, kind="glaze")
    candidates = storage.get_compliment_candidates(user_id, display_name)
    compliment = glaze.find_compliment(candidates)

    line = glaze.build_glaze(display_name, stats.get("count", 0), recent_lines=recent_lines, compliment=compliment)
    storage.record_roast_line(user_id, line, kind="glaze")
    return line


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

        backfill_cmd = app_commands.Command(
            name="backfill",
            description="ADMIN: pull this channel's real message history into the roast bot's memory",
            callback=self._backfill_callback,
        )
        self.tree.add_command(backfill_cmd)

        glaze_cmd = app_commands.Command(
            name="glaze",
            description="The opposite of /roast -- tell someone (default: Derb) they're the GOAT",
            callback=self._glaze_callback,
        )
        self.tree.add_command(glaze_cmd)

        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands", len(synced))
        except Exception as e:
            log.error("Slash command sync failed: %s", e)

    async def _roast_callback(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        if target.bot:
            await interaction.response.send_message(
                f"**{target.display_name}** is a bot — it doesn't talk, it just works. "
                f"Not much to roast there. Try a real person."
            )
            return
        line = _generate_roast_for(str(target.id), target.display_name)
        await interaction.response.send_message(line)

    async def _glaze_callback(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member
        if target is None:
            # No target given -- best-effort default to Derb, since
            # that's the whole point of this feature. Falls back to
            # asking for a mention if nobody matching is in the cache.
            target = next(
                (m for m in interaction.guild.members if "derb" in m.display_name.lower()),
                None,
            ) if interaction.guild else None
            if target is None:
                await interaction.response.send_message(
                    "Couldn't find Derb automatically -- try `/glaze @Derb` directly."
                )
                return
        if target.bot:
            await interaction.response.send_message(f"**{target.display_name}** is a bot, but sure, it's doing great.")
            return
        line = _generate_glaze_for(str(target.id), target.display_name)
        await interaction.response.send_message(line)

    async def _setchannel_callback(self, interaction: discord.Interaction):
        storage.set_config("announce_channel_id", str(interaction.channel_id))
        await interaction.response.send_message(f"✅ Daily roast will post in {interaction.channel.mention}.")

    async def _backfill_callback(self, interaction: discord.Interaction, limit: int = 2000):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return
        await interaction.response.defer()

        recorded = 0
        skipped = 0
        try:
            async for message in interaction.channel.history(limit=limit):
                if message.author.bot or not message.content:
                    skipped += 1
                    continue
                is_new = storage.record_message(
                    str(message.author.id),
                    message.author.display_name,
                    message.content,
                    message.created_at.astimezone(timezone.utc).hour,
                    message_id=str(message.id),
                )
                if is_new:
                    recorded += 1
                else:
                    skipped += 1
        except discord.Forbidden:
            await interaction.followup.send(
                "Missing permission to read this channel's history -- the bot needs "
                "**Read Message History** here."
            )
            return
        except Exception as e:
            log.error("Backfill failed: %s", e)
            await interaction.followup.send(f"Backfill hit an error partway through: {e}")
            return

        await interaction.followup.send(
            f"✅ Backfill complete for #{interaction.channel.name}: **{recorded}** new messages added to memory "
            f"({skipped} skipped -- bots, empty, or already recorded). Run this again in other channels you "
            f"want included, or with a higher `limit` for channels with more history."
        )

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
            message_id=str(message.id),
        )

        # Counter-roast: fires when someone @mentions the bot or replies
        # directly to one of its own messages -- talk to Roast Bot, get
        # roasted back. Not sentiment-checked (no reliable way to tell
        # "insult" from "compliment" from raw text without false
        # positives) -- any direct engagement counts, cooldown-limited so
        # it can't be spammed for on-demand roasts.
        is_direct_engagement = self.user in message.mentions
        if not is_direct_engagement and message.reference:
            replied = message.reference.resolved
            if replied is not None and getattr(replied, "author", None) == self.user:
                is_direct_engagement = True

        if is_direct_engagement:
            now = time.monotonic()
            last = _last_counter_roast.get(str(message.author.id), 0)
            if now - last >= COUNTER_ROAST_COOLDOWN:
                _last_counter_roast[str(message.author.id)] = now
                try:
                    line = _generate_roast_for(str(message.author.id), message.author.display_name)
                    await message.channel.send(line, reference=message)
                except Exception as e:
                    log.error("Counter-roast failed for %s: %s", message.author.display_name, e)

    async def on_ready(self):
        log.info("Logged in as %s", self.user)
        if not daily_roast.is_running():
            daily_roast.start(self)


client = RoastBot()


# 8:10pm/9:10pm/10:10pm ET = 00:10/01:10/02:10 UTC during EDT (UTC-4, in
# effect now). NOTE: like the other bots' ET handling in this project, this
# doesn't auto-adjust for EST in the off-season -- it'll fire an hour
# earlier ET during standard time. Override via DAILY_ROAST_HOURS_UTC
# (comma-separated hours; minute is fixed at :10) if that ever needs
# correcting.
_hours_env = os.getenv("DAILY_ROAST_HOURS_UTC", "0,1,2")
DAILY_ROAST_HOURS_UTC = [int(h.strip()) for h in _hours_env.split(",") if h.strip()]


@tasks.loop(time=[dtime(hour=h, minute=10) for h in DAILY_ROAST_HOURS_UTC])
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
        line = _generate_roast_for(target["user_id"], target["username"])

        await channel.send(f"🔥 **Roast of the Day** 🔥\n{line}")
        storage.mark_roasted(target["user_id"])
        log.info("Posted daily roast for %s", target["username"])
    except Exception as e:
        log.error("daily_roast cycle failed, will retry tomorrow: %s", e)


@daily_roast.before_loop
async def before_daily_roast():
    await client.wait_until_ready()


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set DISCORD_TOKEN in your .env file.")
    client.run(TOKEN)
