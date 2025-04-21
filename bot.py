import os
import json
import time
import threading
from flask import Flask
from dotenv import load_dotenv
import discord
from discord.ext import commands

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.environ.get("PORT", 4000))

# Flask health check server
app = Flask(__name__)

@app.route("/")
def index():
    return "Riddle bot is running!"

def run_web():
    app.run(host="0.0.0.0", port=PORT)

threading.Thread(target=run_web).start()

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# File paths
SCORES_FILE = "scores.json"
RIDDLES_FILE = "riddles.json"
IGNORED_FILE = "ignored_channels.json"
LISTENED_FILE = "listened_channels.json"

# Cooldown in seconds (5 minutes)
COOLDOWN = 300

# Load JSON helper
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

# Persistent data
scores = load_json(SCORES_FILE, {})
riddles = load_json(RIDDLES_FILE, {})
IGNORED_CHANNELS = load_json(IGNORED_FILE, [])
LISTENED_CHANNELS = load_json(LISTENED_FILE, [])

# 🔒 Fix: Ensure LISTENED_CHANNELS is a list
if not isinstance(LISTENED_CHANNELS, list):
    LISTENED_CHANNELS = [LISTENED_CHANNELS]
    save_json(LISTENED_FILE, LISTENED_CHANNELS)

# Runtime state
guess_timestamps = {}
pending_riddle_creations = {}
current_riddle = {"question": None, "answer": None}

def save_data():
    save_json(SCORES_FILE, scores)
    save_json(RIDDLES_FILE, riddles)
    save_json(LISTENED_FILE, LISTENED_CHANNELS)

def save_ignored():
    save_json(IGNORED_FILE, IGNORED_CHANNELS)

# Global check: only respond in allowed channels
@bot.check
async def globally_ignore_channels(ctx):
    return ctx.channel.id in LISTENED_CHANNELS

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    default_channel_id = 1361523942829068468
    if default_channel_id not in LISTENED_CHANNELS:
        LISTENED_CHANNELS.append(default_channel_id)
        save_data()
    await bot.tree.sync()

# Slash command: Add riddle
@bot.tree.command(name="addriddle", description="Add a riddle (admin only)")
@commands.has_permissions(administrator=True)
async def addriddle(interaction: discord.Interaction, question: str):
    user_id = interaction.user.id
    pending_riddle_creations[user_id] = question.strip()
    await interaction.response.send_message(
        f"📝 Got it! Riddle: `{question}`\nNow send the **answer** in this channel.",
        ephemeral=True
    )

# Slash command: Delete riddle
@bot.tree.command(name="deleteriddle", description="Delete a riddle")
@commands.has_permissions(administrator=True)
async def deleteriddle(interaction: discord.Interaction, question: str):
    question = question.strip()
    if question in riddles:
        del riddles[question]
        save_data()
        await interaction.response.send_message("🗑️ Riddle deleted.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Riddle not found.", ephemeral=True)

# Slash command: Cancel riddle creation
@bot.tree.command(name="cancel", description="Cancel riddle creation")
async def cancel(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in pending_riddle_creations:
        pending_riddle_creations.pop(user_id)
        await interaction.response.send_message("❌ Riddle creation cancelled.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ No riddle in progress.", ephemeral=True)

# Slash command: Add channel to listen list
@bot.tree.command(name="listen", description="Tell bot to listen to a channel")
@commands.has_permissions(administrator=True)
async def listen(interaction: discord.Interaction, channel: discord.TextChannel):
    if channel.id not in LISTENED_CHANNELS:
        LISTENED_CHANNELS.append(channel.id)
        save_data()
        await interaction.response.send_message(f"✅ Now listening to {channel.mention}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ Already listening to {channel.mention}.", ephemeral=True)

# Slash command: Ignore a channel
@bot.tree.command(name="ignore", description="Tell bot to ignore a channel")
@commands.has_permissions(administrator=True)
async def ignore(interaction: discord.Interaction, channel: discord.TextChannel):
    if channel.id not in IGNORED_CHANNELS:
        IGNORED_CHANNELS.append(channel.id)
        save_ignored()
        await interaction.response.send_message(f"✅ Now ignoring {channel.mention}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ Already ignoring {channel.mention}.", ephemeral=True)

# Slash command: Leaderboard
@bot.tree.command(name="leaderboard", description="Show top riddle solvers")
async def leaderboard(interaction: discord.Interaction):
    if not scores:
        await interaction.response.send_message("No scores yet.", ephemeral=True)
        return
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    msg = "\n".join(f"**{i+1}.** {user} - {score}" for i, (user, score) in enumerate(sorted_scores[:10]))
    await interaction.response.send_message(f"🏆 **Leaderboard:**\n{msg}", ephemeral=True)

# Handle user guesses and riddle answers
@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author == bot.user:
        return

    if not isinstance(LISTENED_CHANNELS, list):
        return

    if message.channel.id not in LISTENED_CHANNELS:
        return

    user_id = message.author.id
    content = message.content.strip()

    # Admin submits riddle answer
    if user_id in pending_riddle_creations:
        question = pending_riddle_creations.pop(user_id)
        riddles[question] = content.lower()
        save_data()
        await message.channel.send(
            f"✅ Riddle added!\n**Q:** {question}\n**A:** {content}"
        )
        return

    if current_riddle["question"] is None or content.startswith("!"):
        return

    now = time.time()
    last_guess = guess_timestamps.get(user_id, 0)
    if now - last_guess < COOLDOWN:
        remaining = int(COOLDOWN - (now - last_guess))
        mins, secs = divmod(remaining, 60)
        await message.channel.send(
            f"⏳ {message.author.mention}, wait {mins}m {secs}s to guess again."
        )
        return

    guess_timestamps[user_id] = now
    guess = content.lower()
    correct = current_riddle["answer"]

    if guess == correct:
        await message.add_reaction("✅")
        scores[str(message.author)] = scores.get(str(message.author), 0) + 1
        save_data()
    else:
        await message.add_reaction("❌")

# Start bot
if not TOKEN:
    print("❌ DISCORD_TOKEN is not set. Check your environment variables.")
else:
    print("✅ Starting bot...")
    bot.run(TOKEN)
