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

# Flask web server for Render
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

# Cooldown in seconds (5 minutes)
COOLDOWN = 300

# Load JSON helper
def load_json(file, default):
    if os.path.exists(file):
        with open(file, "r") as f:
            return json.load(f)
    return default

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f)

# Persistent data
scores = load_json(SCORES_FILE, {})
riddles = load_json(RIDDLES_FILE, {})
IGNORED_CHANNELS = load_json(IGNORED_FILE, [])

# Track cooldowns and pending riddle creations
guess_timestamps = {}
pending_riddle_creations = {}  # user_id: question
current_riddle = {"question": None, "answer": None}

# Save all data
def save_data():
    save_json(SCORES_FILE, scores)
    save_json(RIDDLES_FILE, riddles)

def save_ignored():
    save_json(IGNORED_FILE, IGNORED_CHANNELS)

# Global command check to skip ignored channels
@bot.check
async def globally_ignore_channels(ctx):
    return ctx.channel.id not in IGNORED_CHANNELS

# Bot is ready
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await bot.tree.sync()  # Sync the slash commands with Discord

# Flask web server route for health check
@app.route("/")
def index():
    return "Riddle bot is running!"

# Admin: Add a new riddle (step 1) via slash command
@bot.tree.command(name="addriddle")
@commands.has_permissions(administrator=True)
async def addriddle(interaction: discord.Interaction, question: str):
    user_id = interaction.user.id
    pending_riddle_creations[user_id] = question.strip()

    # Prompt the admin to send the answer in the same channel
    await interaction.response.send_message(
        f"📝 Got it! You've added a new riddle: `{question}`.\n\n"
        "Now, send the **answer** to this riddle in this same channel.",
        ephemeral=True
    )

# Admin: Delete a riddle via slash command
@bot.tree.command(name="deleteriddle")
@commands.has_permissions(administrator=True)
async def deleteriddle(interaction: discord.Interaction, question: str):
    question = question.strip()
    if question in riddles:
        del riddles[question]
        save_data()
        await interaction.response.send_message("🗑️ Riddle deleted.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Riddle not found.", ephemeral=True)

# Admin: Cancel riddle creation via slash command
@bot.tree.command(name="cancel")
async def cancel(interaction: discord.Interaction):
    user_id_
