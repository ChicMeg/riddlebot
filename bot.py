import os
import json
import time
import threading
import asyncio
import random
from flask import Flask
from dotenv import load_dotenv
import discord
from discord.ext import commands

# NEW: For text normalization
import nltk
from nltk.stem import WordNetLemmatizer

# Download required NLTK data
nltk.download("wordnet")
nltk.download("omw-1.4")

lemmatizer = WordNetLemmatizer()

STOP_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "and", "or"}

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.environ.get("PORT", 4000))

# Channel IDs
RIDDLE_CHANNEL_ID = 1365773539495645215
ADMIN_CHANNEL_ID = 1361523942829068468
TICKET_DISPLAY_CHANNEL_ID = 444444444444444444  # Replace with your ticket channel ID
CLOSED_TICKETS_CHANNEL_ID = 333333333333333333

# Topic to Role mapping
TOPIC_MAP = {
    "account upgrades": 111111111111111111,
    "event information": 222222222222222222
}

CLAIMED_TICKETS = {}  # channel_id: mod_user_id

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# File paths
SCORES_FILE = "scores.json"
RIDDLES_FILE = "riddles.json"

COOLDOWN = 10

def load_json(file, default):
    if os.path.exists(file):
        with open(file, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return default
    return default

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f)

scores = load_json(SCORES_FILE, {})
riddles = load_json(RIDDLES_FILE, {})
guess_timestamps = {}
current_riddle = {"question": None, "answer": None}

def save_data():
    save_json(SCORES_FILE, scores)
    save_json(RIDDLES_FILE, riddles)

def normalize(text):
    words = text.lower().split()
    filtered = [word for word in words if word not in STOP_WORDS]
    lemmatized = [lemmatizer.lemmatize(word) for word in filtered]
    return " ".join(lemmatized)

@app.route("/")
def index():
    return "Riddle bot is running!"

def run_web():
    app.run(host="0.0.0.0", port=PORT)

threading.Thread(target=run_web).start()

class ClaimButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Claim Ticket", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only moderators can claim tickets.", ephemeral=True)
            return

        if interaction.channel.id in CLAIMED_TICKETS:
            claimer = interaction.guild.get_member(CLAIMED_TICKETS[interaction.channel.id])
            await interaction.response.send_message(f"This ticket is already claimed by {claimer.mention}.", ephemeral=True)
            return

        CLAIMED_TICKETS[interaction.channel.id] = interaction.user.id
        await interaction.channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
        await interaction.channel.edit(overwrites={key: val for key, val in interaction.channel.overwrites.items() if key != interaction.guild.default_role and key != interaction.guild.me})
        await interaction.channel.send(f"🔒 Ticket claimed by {interaction.user.mention}")
        await interaction.response.defer()

class CloseButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Close Ticket", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        channel = interaction.channel
        claimer_id = CLAIMED_TICKETS.get(channel.id)

        if interaction.user.id != claimer_id and not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only the claimer or a moderator can close this ticket.", ephemeral=True)
            return

        closed_log_channel = interaction.guild.get_channel(CLOSED_TICKETS_CHANNEL_ID)
        log_embed = discord.Embed(title="🎫 Ticket Closed", description=f"**Channel:** {channel.name}\n**Closed by:** {interaction.user.mention}", color=discord.Color.red())
        await closed_log_channel.send(embed=log_embed)

        await interaction.response.send_message("Closing ticket...", ephemeral=True)
        await channel.delete()

class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Account Upgrades", description="Hero gear, Chief gear, Stats, etc."),
            discord.SelectOption(label="Event Information", description="Ask questions about in-game events")
        ]
        super().__init__(placeholder="Choose your support topic...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        topic_label = self.values[0]
        topic_key = topic_label.lower()
        role_id = TOPIC_MAP.get(topic_key)

        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.get_role(role_id): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        channel_name = f"ticket-{interaction.user.name}-{topic_key.replace(' ', '-')}"
        channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites, reason=f"Support ticket: {topic_label}")

        view = discord.ui.View()
        view.add_item(ClaimButton())
        view.add_item(CloseButton())

        await channel.send(f"{interaction.user.mention} has created a ticket for **{topic_label}**.\n{guild.get_role(role_id).mention}, please assist.", view=view)
        await interaction.response.send_message(f"Your ticket has been created: {channel.mention}", ephemeral=True)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(TicketSelect())

@bot.command()
async def ticket(ctx):
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("❌ This command must be used in the admin channel.")
        return

    ticket_channel = bot.get_channel(TICKET_DISPLAY_CHANNEL_ID)
    if not ticket_channel:
        await ctx.send("❌ Ticket display channel not found.")
        return

    await ticket_channel.send("📬 Please select the topic for your ticket:", view=TicketView())
    await ctx.send(f"✅ Ticket interface sent to {ticket_channel.mention}.")

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.competing, name="in the riddle Olympics"))
    if riddles and not current_riddle["question"]:
        question, answer = random.choice(list(riddles.items()))
        current_riddle["question"] = question
        current_riddle["answer"] = answer
        print(f"🧩 Loaded riddle: {question}")

@bot.command(name="riddle")
async def riddle(ctx):
    if current_riddle["question"]:
        await ctx.send(f"🧠 **Current Riddle:**\n{current_riddle['question']}")
    elif riddles:
        question, answer = random.choice(list(riddles.items()))
        current_riddle["question"] = question
        current_riddle["answer"] = answer
        await ctx.send(f"🧠 **Here’s a random riddle:**\n{question}")
    else:
        await ctx.send("📭 No riddles available.")

@bot.command(name="leaderboard")
async def leaderboard(ctx):
    if not scores:
        await ctx.send("No scores yet.")
        return
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    msg = "\n".join(f"**{i+1}.** {user} - {score}" for i, (user, score) in enumerate(sorted_scores[:10]))
    await ctx.send(f"🏆 **Leaderboard:**\n{msg}")

@bot.event
async def on_message(message):
    await bot.process_commands(message)
    if message.author == bot.user or isinstance(message.channel, discord.DMChannel):
        return
    if message.channel.id != RIDDLE_CHANNEL_ID:
        return
    user_id = message.author.id
    content = message.content.strip()
    if current_riddle["question"] is None or content.startswith("!"):
        return
    now = time.time()
    last_guess = guess_timestamps.get(user_id, 0)
    if now - last_guess < COOLDOWN:
        remaining = int(COOLDOWN - (now - last_guess))
        await message.channel.send(f"⏳ {message.author.mention}, wait {remaining}s to guess again.")
        return
    guess_timestamps[user_id] = now
    guess = normalize(content)
    correct = normalize(current_riddle["answer"])
    if guess == correct:
        await message.add_reaction("✅")
        scores[str(message.author)] = scores.get(str(message.author), 0) + 1
        save_data()
        await message.channel.send(f"🎉 {message.author.mention} got it right! The answer was: **{current_riddle['answer']}**")
        del riddles[current_riddle["question"]]
        save_data()
        if riddles:
            question, answer = random.choice(list(riddles.items()))
            current_riddle["question"] = question
            current_riddle["answer"] = answer
            await message.channel.send(f"🧠 **Next Riddle:**\n{question}")
        else:
            current_riddle["question"] = None
            current_riddle["answer"] = None
            await message.channel.send("📭 No more riddles left.")
    else:
        await message.add_reaction("❌")

if not TOKEN:
    print("❌ DISCORD_TOKEN is not set.")
else:
    print("✅ Starting bot...")
    bot.run(TOKEN)
