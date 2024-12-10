import discord
from discord.ext import tasks, commands
from config import (
    STATS_URL,
    AUTO_UPDATE_CHANNEL_ID,
    PRICES_CHANNEL_ID,
    PLAYER_NOTIFICATIONS_CHANNEL_ID,  # Add a dedicated channel for player notifications
    STATUS_UPDATE_SECONDS,
    EVENT_MONITOR_SECONDS,
    CLEANUP_INTERVAL,
    SERVER_UPDATE_MESSAGE,
)
from utils import (
    load_pinned_message_id,
    save_pinned_message_id,
    fetch_server_stats,
    fetch_economy_data,
    fetch_career_savegame_data,  # Added fetch_career_savegame_data
)
from datetime import datetime, timedelta, timezone


class Tasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pinned_message_id = load_pinned_message_id()
        self.tasks_started = False  # Flag to prevent starting tasks multiple times
        self.previous_players = set()  # Cache for player join/leave tracking

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.tasks_started:
            self.update_status.start()
            self.monitor_events.start()
            self.cleanup_messages.start()
            self.track_player_activity.start()  # Start player tracking task
            self.tasks_started = True
            print("Tüm fonksiyonlar çalışıyor.")

    def cog_unload(self):
        self.update_status.cancel()
        self.monitor_events.cancel()
        self.cleanup_messages.cancel()
        self.track_player_activity.cancel()

    @tasks.loop(seconds=STATUS_UPDATE_SECONDS)
    async def update_status(self):
        try:
            stats_data = fetch_server_stats()
            if stats_data is None:
                return

            slots = stats_data.find("Slots").attrib
            players_online = int(slots.get("numUsed", "0"))
            player_capacity = slots.get("capacity", "N/A")

            activity = discord.Activity(
                type=discord.ActivityType.playing,
                name=f"Sunucuda {players_online}/{player_capacity} Oyuncu"
            )
            await self.bot.change_presence(activity=activity)
            print(f"Online oyuncu sayısı güncellendi {players_online}/{player_capacity}.")
        except Exception as e:
            print(f"Error in update_status: {e}")

    @update_status.before_loop
    async def before_update_status(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=EVENT_MONITOR_SECONDS)
    async def monitor_events(self):
        try:
            stats_data = fetch_server_stats()
            economy_data = fetch_economy_data()
            career_data = fetch_career_savegame_data()  # Fetch career savegame data

            if stats_data is None or economy_data is None or career_data is None:
                print("Failed to fetch some data.")
                return

            # Extract server stats
            server_name = stats_data.attrib.get("name", "N/A")
            map_name = stats_data.attrib.get("mapName", "N/A")
            slots = stats_data.find("Slots").attrib
            players_online = int(slots.get("numUsed", "0"))
            player_capacity = slots.get("capacity", "N/A")
            day_time = int(stats_data.attrib.get("dayTime", 0)) // 1000
            hours = day_time // 3600
            minutes = (day_time % 3600) // 60

        # Extract career savegame data
            creation_date = career_data["creation_date"]
            last_save_date = career_data["last_save_date"]
            economic_difficulty = career_data["economic_difficulty"]
            time_scale = str(int(float(career_data["time_scale"])))  # Clean time scale
            current_money = f"${int(career_data['current_money']):,}"  # Format with commas

        # Mods
            mods = stats_data.find("Mods").findall("Mod")
            mod_list = [mod.text.strip() if mod.text else "Unknown Mod" for mod in mods]
            grouped_mods = "\n".join([", ".join(mod_list[i:i+3]) for i in range(0, len(mod_list), 3)])

        # Prepare the update message
            update_message = SERVER_UPDATE_MESSAGE.format(
                server_name=server_name,
                map_name=map_name,
                players_online=players_online,
                player_capacity=player_capacity,
                hours=hours,
                minutes=minutes,
                creation_date=creation_date,
                last_save_date=last_save_date,
                economic_difficulty=economic_difficulty,
                time_scale=time_scale,
                current_money=current_money,
                mods=grouped_mods
            )

        # Get the update channel
            channel = self.bot.get_channel(AUTO_UPDATE_CHANNEL_ID)
            if not channel:
                print(f"Channel with ID {AUTO_UPDATE_CHANNEL_ID} not found.")
                return

            if self.pinned_message_id:
            # Try to fetch the existing pinned message and edit it
                try:
                    pinned_message = await channel.fetch_message(self.pinned_message_id)
                    if pinned_message:
                        await pinned_message.edit(content=update_message)
                        return
                except discord.NotFound:
                # If the message is not found, create a new one
                    pass

        # If no valid pinned message exists, send a new one and pin it
            new_message = await channel.send(update_message)
            await new_message.pin()
            self.pinned_message_id = new_message.id
            save_pinned_message_id(self.pinned_message_id)

        except Exception as e:
            print(f"Error in monitor_events: {e}")

    @monitor_events.before_loop
    async def before_monitor_events(self):
        await self.bot.wait_until_ready()

    # Task: Track player joins and leaves
    @tasks.loop(seconds=EVENT_MONITOR_SECONDS)
    async def track_player_activity(self):
        """
        Periodically track player activity on the server, detecting joins and leaves.
        Sends notifications to the player activity channel.
        """
        try:
            # Fetch server stats
            stats_data = fetch_server_stats()
            if stats_data is None:
                print("Failed to fetch server stats.")
                return

            # Parse current players
            current_players = set()
            slots = stats_data.find("Slots")
            if slots:
                for player in slots.findall("Player"):
                    if player.attrib.get("isUsed") == "true":
                        name = player.text.strip()
                        current_players.add(name)

            # Compare with previous players
            joined_players = current_players - self.previous_players
            left_players = self.previous_players - current_players

            # Notify the dedicated player notifications channel
            notification_channel = self.bot.get_channel(PLAYER_NOTIFICATIONS_CHANNEL_ID)
            if notification_channel:
                for player in joined_players:
                    await notification_channel.send(f"👨🏼‍🌾**`  {player}`** `Giriş Yaptı`")
                    print(f"👨🏼‍🌾**`  {player}`** `Giriş Yaptı`")
                for player in left_players:
                    await notification_channel.send(f"👨🏼‍🌾**`  {player}`** `Çıkış Yaptı`")
                    print(f"👨🏼‍🌾**`  {player}`** `Çıkış Yaptı`")

            # Update the cached player list
            self.previous_players = current_players

        except Exception as e:
            print(f"Error in track_player_activity: {e}")

    @track_player_activity.before_loop
    async def before_track_player_activity(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=CLEANUP_INTERVAL)
    async def cleanup_messages(self):
        try:
            channel = self.bot.get_channel(PRICES_CHANNEL_ID)
            if channel is None:
                print(f"Prices channel with ID {PRICES_CHANNEL_ID} not found.")
                return

            time_threshold = datetime.now(timezone.utc) - timedelta(seconds=CLEANUP_INTERVAL)

            # Fetch messages from the channel
            async for message in channel.history(limit=100):
                if message.pinned:
                    continue
                if message.created_at < time_threshold:
                    await message.delete()
            #print(f"Cleaned up messages older than {CLEANUP_INTERVAL} seconds in the prices channel.")
        except Exception as e:
            print(f"Error in cleanup_messages: {e}")

    @cleanup_messages.before_loop
    async def before_cleanup_messages(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Tasks(bot))
