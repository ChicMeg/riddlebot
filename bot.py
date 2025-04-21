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
LISTENED_FILE = "listened_channels.json"  # new file to store listened channels

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
LISTENED_CHANNELS = load_json(LISTENED_FILE, [])  # Track the channels we listen to

# Track cooldowns and pending riddle creations
guess_timestamps = {}
pending_riddle_creations = {}  # user_id: question
current_riddle = {"question": None, "answer": None}

# Save all data
def save_data():
    save_json(SCORES_FILE, scores)
    save_json(RIDDLES_FILE, riddles)
    save_json(LISTENED_FILE, LISTENED_CHANNELS)

def save_ignored():
    save_json(IGNORED_FILE, IGNORED_CHANNELS)

# Global command check to skip ignored channels
@bot.check
async def globally_ignore_channels(ctx):
    # Only listen to channels in the LISTENED_CHANNELS list
    return ctx.channel.id in LISTENED_CHANNELS

# Bot is ready
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

    # Add default channel to the list of listened channels if it's not there
    default_channel_id = 1361523942829068468
    if default_channel_id not in LISTENED_CHANNELS:
        LISTENED_CHANNELS.append(default_channel_id)
        save_data()

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
    user_id = interaction.user.id
    if user_id in pending_riddle_creations:
        pending_riddle_creations.pop(user_id)
        await interaction.response.send_message("❌ Riddle creation cancelled.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ You don't have a riddle in progress.", ephemeral=True)

# Admin: Command to make the bot listen to a specific channel
@bot.tree.command(name="listen")
@commands.has_permissions(administrator=True)
async def listen(interaction: discord.Interaction, channel: discord.TextChannel):
    if channel.id not in LISTENED_CHANNELS:
        LISTENED_CHANNELS.append(channel.id)
        save_data()
        await interaction.response.send_message(f"✅ The bot will now listen to {channel.mention}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ The bot is already listening to {channel.mention}.", ephemeral=True)

# Admin: Command to make the bot ignore a specific channel
@bot.tree.command(name="ignore")
@commands.has_permissions(administrator=True)
async def ignore(interaction: discord.Interaction, channel: discord.TextChannel):
    if channel.id not in IGNORED_CHANNELS:
        IGNORED_CHANNELS.append(channel.id)
        save_ignored()
        await interaction.response.send_message(f"✅ The bot will now ignore {channel.mention}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ The bot is already ignoring {channel.mention}.", ephemeral=True)

# Leaderboard via slash command
@bot.tree.command(name="leaderboard")
async def leaderboard(interaction: discord.Interaction):
    if not scores:
        await interaction.response.send_message("No scores yet.", ephemeral=True)
        return
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    msg = "\n".join(f"**{i+1}.** {user} - {score}" for i, (user, score) in enumerate(sorted_scores[:10]))
    await interaction.response.send_message(f"🏆 **Leaderboard:**\n{msg}", ephemeral=True)

# Handle guesses and answer input
@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author == bot.user or message.channel.id not in LISTENED_CHANNELS:
        return

    user_id = message.author.id
    content = message.content.strip()

    # Handle riddle answer in the same channel (for addriddle step 2)
    if user_id in pending_riddle_creations:
        question = pending_riddle_creations.pop(user_id)
        # The answer is the current message content
        riddles[question] = content.lower()
        save_data()

        # Confirm the riddle and its answer
        await message.channel.send(
            f"✅ Riddle added!\n**Question:** {question}\n**Answer:** {content}",
            ephemeral=True
        )
        return

    # Ignore non-guesses or if no active riddle
    if current_riddle["question"] is None or content.startswith("!"):
        return

    now = time.time()
    last_guess = guess_timestamps.get(user_id, 0)

    if now - last_guess < COOLDOWN:
        remaining = int(COOLDOWN - (now - last_guess))
        mins, secs = divmod(remaining, 60)
        await message.channel.send(
            f"⏳ {message.author.mention}, wait {mins}m {secs}s before guessing again."
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
bot.run(TOKEN)
