import os
import json
import asyncio
import random
import datetime as dt
import pytz
import nltk
from nltk.stem import WordNetLemmatizer

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button, Select

# -------------------------
# NLTK setup (optional)
# -------------------------
try:
    nltk.data.find('corpora/wordnet')
except LookupError:
    nltk.download('wordnet')
    nltk.download('omw-1.4')

lemmatizer = WordNetLemmatizer()
STOP_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "and", "or"}

# -------------------------
# Config and persistence
# -------------------------
RIDDLES_FILE = 'riddles.json'
SCORES_FILE = 'scores.json'
CONFIG_FILE = 'config.json'
DAILY_FILE = 'daily_state.json'
TIME_ZONE = pytz.timezone('America/Chicago')

def load_json(path, default):
    return json.load(open(path)) if os.path.exists(path) else default

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

riddles = load_json(RIDDLES_FILE, [])
scores = load_json(SCORES_FILE, {})
config = load_json(CONFIG_FILE, {})
daily_state = load_json(DAILY_FILE, {})
CLAIMED_TICKETS = {}  # channel_id: user_id

# -------------------------
# Discord bot setup
# -------------------------
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
tree = bot.tree

# -------------------------
# Ticket system UI components
# -------------------------
class ClaimButton(Button):
    def __init__(self):
        super().__init__(label="Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket", row=0)

    async def callback(self, interaction: discord.Interaction):
        if interaction.channel.category and interaction.channel.category.name == "Tickets":
            if interaction.channel.id in CLAIMED_TICKETS:
                await interaction.response.send_message("⚠️ Already claimed.", ephemeral=True)
                return
            await interaction.channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
            CLAIMED_TICKETS[interaction.channel.id] = interaction.user.id
            new_name = f"ticket-{interaction.channel.name.split('-')[1]}-claimed"
            await interaction.channel.edit(name=new_name)
            await interaction.response.send_message(f"✅ Claimed by {interaction.user.mention}")
        else:
            await interaction.response.send_message("Use this button in a ticket channel only.", ephemeral=True)

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view
        self.add_item(Button(label="Account Questions", style=discord.ButtonStyle.primary, custom_id="ticket_account"))
        self.add_item(Button(label="Event Information", style=discord.ButtonStyle.primary, custom_id="ticket_event"))
        self.add_item(ClaimButton())

class SetupView(View):
    def __init__(self, author: discord.User, bot_instance: commands.Bot):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.author = author
        self.bot = bot_instance
        self.config = config.setdefault(str(author.guild.id) if isinstance(author, discord.Member) else 'global', {})

        options = [
            discord.SelectOption(label="Set Riddle Channel", description="Configure the riddle channel"),
            discord.SelectOption(label="Set Admin Channel", description="Configure the admin channel"),
            discord.SelectOption(label="Set Ticket Display Channel", description="Where ticket panel is posted"),
            discord.SelectOption(label="Set Closed Tickets Channel", description="Channel for closed tickets"),
            discord.SelectOption(label="Set Archive Channel", description="Ticket archive channel"),
            discord.SelectOption(label="Set Account Role", description="Role for account questions"),
            discord.SelectOption(label="Set Event Role", description="Role for event information"),
        ]

        self.select = Select(placeholder="Select a setup option...", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Only the command invoker can use this menu.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction):
        choice = interaction.data['values'][0]  # the selected option label
        key_map = {
            "Set Riddle Channel": "riddle_channel_id",
            "Set Admin Channel": "admin_channel_id",
            "Set Ticket Display Channel": "ticket_display",
            "Set Closed Tickets Channel": "closed_tickets_channel_id",
            "Set Archive Channel": "ticket_archive_channel_id",
            "Set Account Role": "account_role_id",
            "Set Event Role": "event_role_id",
        }
        key = key_map.get(choice)
        is_role = choice in ["Set Account Role", "Set Event Role"]

        await interaction.response.send_message(f"✏️ Please mention the {'role' if is_role else 'channel'} or provide its ID.", ephemeral=True)

        def check(m: discord.Message):
            return m.author.id == self.author.id and m.channel == interaction.channel

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=300)
        except asyncio.TimeoutError:
            return await interaction.followup.send("⌛ Timed out waiting for input.", ephemeral=True)

        value = None
        if is_role:
            if msg.role_mentions:
                value = msg.role_mentions[0].id
            elif msg.content.isdigit():
                value = int(msg.content)
        else:
            if msg.channel_mentions:
                value = msg.channel_mentions[0].id
            elif msg.content.isdigit():
                value = int(msg.content)

        if value:
            self.config[key] = value
            save_json(CONFIG_FILE, config)
            await interaction.followup.send(f"✅ Set `{key}` to `{value}`", ephemeral=True)
        else:
            await interaction.followup.send("❌ Invalid input. Please try again.", ephemeral=True)

# -------------------------
# Slash commands for riddles
# -------------------------
@tree.command(name="setconfig", description="Set the riddle channel for daily riddles")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(riddle_channel="Channel where daily riddles will appear")
async def setconfig(inter: discord.Interaction, riddle_channel: discord.TextChannel):
    cfg = config.setdefault(str(inter.guild_id), {})
    cfg["riddle_channel_id"] = riddle_channel.id
    save_json(CONFIG_FILE, config)
    await inter.response.send_message(f"✅ Riddle channel set to {riddle_channel.mention}", ephemeral=True)

@tree.command(name="addriddle", description="Interactively add a riddle")
@app_commands.checks.has_permissions(administrator=True)
async def addriddle(inter: discord.Interaction):
    await inter.response.send_message("📝 **Enter the riddle question** (reply):", ephemeral=True)
    def check(m: discord.Message):
        return m.author == inter.user and m.channel == inter.channel
    try:
        q_msg = await bot.wait_for("message", check=check, timeout=60)
    except asyncio.TimeoutError:
        return await inter.followup.send("⌛ Timed out.", ephemeral=True)

    await inter.followup.send("💬 **Enter the answer** (this message will be deleted):", ephemeral=True)
    try:
        a_msg = await bot.wait_for("message", check=check, timeout=60)
        await a_msg.delete()
    except asyncio.TimeoutError:
        return await inter.followup.send("⌛ Timed out.", ephemeral=True)

    riddles.append({"question": q_msg.content.strip(), "answer": a_msg.content.strip().lower()})
    save_json(RIDDLES_FILE, riddles)
    await inter.followup.send("✅ Riddle added!", ephemeral=True)

@tree.command(name="delriddle", description="Delete a riddle by its index")
@app_commands.checks.has_permissions(administrator=True)
async def delriddle(inter: discord.Interaction, index: int):
    if 0 <= index < len(riddles):
        removed = riddles.pop(index)
        save_json(RIDDLES_FILE, riddles)
        await inter.response.send_message(f"🗑️ Deleted: {removed['question']}", ephemeral=True)
    else:
        await inter.response.send_message("❌ Invalid index.", ephemeral=True)

@tree.command(name="scoreboard", description="Show top 10 riddle masters")
async def scoreboard(inter: discord.Interaction):
    if not scores:
        return await inter.response.send_message("🏆 No scores yet.", ephemeral=True)
    top10 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = [f"{i+1}. <@{uid}> — {pts} pts" for i, (uid, pts) in enumerate(top10)]
    await inter.response.send_message("**🏆 Top 10 Riddle Masters**\n" + "\n".join(lines))

# -------------------------
# Slash commands for ticket system
# -------------------------
@tree.command(name="setup", description="Open ticket bot setup panel")
@app_commands.checks.has_permissions(administrator=True)
async def setup(inter: discord.Interaction):
    view = SetupView(inter.user, bot)
    embed = discord.Embed(
        title="🛠️ Bot Setup",
        description="Select an option from the dropdown menu to configure channels/roles. Timeout in 5 minutes.",
        color=discord.Color.orange(),
    )
    await inter.response.send_message(embed=embed, view=view, ephemeral=True)

@tree.command(name="ticketpanel", description="Post the ticket panel in the configured display channel (admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def ticketpanel(inter: discord.Interaction):
    cfg = config.get(str(inter.guild_id), {})
    channel_id = cfg.get("ticket_display")
    if not channel_id:
        return await inter.response.send_message("❌ No ticket display channel set. Use `/setup` first.", ephemeral=True)

    channel = bot.get_channel(channel_id)
    if not channel:
        return await inter.response.send_message("❌ Stored channel ID is invalid or I lack access.", ephemeral=True)

    embed = discord.Embed(
        title="🎟️ Open a Support Ticket",
        description="Click a button below based on your support topic. A private ticket channel will be created for you.",
        color=discord.Color.blue(),
    )
    view = TicketView()
    await channel.send(embed=embed, view=view)
    await inter.response.send_message(f"✅ Ticket panel posted in {channel.mention}", ephemeral=True)

# -------------------------
# Persistent view registration on startup
# -------------------------
@bot.event
async def on_ready():
    bot.add_view(TicketView())  # persist the ticket view across restarts
    print(f"✅ Logged in as {bot.user}")
    await tree.sync()

# -------------------------
# Run the bot
# -------------------------
bot.run(os.getenv("DISCORD_TOKEN"))
