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

# Flask server for Render.com health checks
app = Flask(__name__)

@app.route("/")
def index():
    return "Riddle bot is running!"

def run_web():
    app.run(host="0.0.0.0", port=PORT)

threading.Thread(target=run_web).start()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# File paths
SCORES_FILE = "scores.json"
RIDDLES_FILE = "riddles.json"
IGNORED_FILE = "ignored_channels.json"
LISTENED_FILE = "listened_channels.json"

COOLDOWN = 300  # 5 minutes

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
IGNORED_CHANNELS = load_json(IGNORED_FILE, [])
LISTENED_CHANNELS = load_json(LISTENED_FILE, [])

if not isinstance(LISTENED_CHANNELS, list):
    LISTENED_CHANNELS = [LISTENED_CHANNELS]
    save_json(LISTENED_FILE, LISTENED_CHANNELS)

guess_timestamps = {}
pending_riddle_creations = {}
current_riddle = {"question": None, "answer": None}

def save_data():
    save_json(SCORES_FILE, scores)
    save_json(RIDDLES_FILE, riddles)
    save_json(LISTENED_FILE, LISTENED_CHANNELS)

def save_ignored():
    save_json(IGNORED_FILE, IGNORED_CHANNELS)

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

# Traditional commands below:

@bot.command(name="addriddle")
@commands.has_permissions(administrator=True)
async def addriddle(ctx, *, question: str):
    user_id = ctx.author.id
    pending_riddle_creations[user_id] = question.strip()
    await ctx.author.send(
        f"📝 Got your riddle: `{question}`\nPlease send the **answer** here in DM."
    )

@bot.command(name="deleteriddle")
@commands.has_permissions(administrator=True)
async def deleteriddle(ctx, *, question: str):
    if question in riddles:
        del riddles[question]
        save_data()
        await ctx.send("🗑️ Riddle deleted.")
    else:
        await ctx.send("❌ Riddle not found.")

@bot.command(name="cancel")
async def cancel(ctx):
    user_id = ctx.author.id
    if user_id in pending_riddle_creations:
        pending_riddle_creations.pop(user_id)
        await ctx.send("❌ Riddle creation cancelled.")
    else:
        await ctx.send("⚠️ No riddle in progress.")

@bot.command(name="listen")
@commands.has_permissions(administrator=True)
async def listen(ctx, channel: discord.TextChannel):
    if channel.id not in LISTENED_CHANNELS:
        LISTENED_CHANNELS.append(channel.id)
        save_data()
        await ctx.send(f"✅ Now listening to {channel.mention}.")
    else:
        await ctx.send(f"⚠️ Already listening to {channel.mention}.")

@bot.command(name="ignore")
@commands.has_permissions(administrator=True)
async def ignore(ctx, channel: discord.TextChannel):
    if channel.id not in IGNORED_CHANNELS:
        IGNORED_CHANNELS.append(channel.id)
        save_ignored()
        await ctx.send(f"✅ Now ignoring {channel.mention}.")
    else:
        await ctx.send(f"⚠️ Already ignoring {channel.mention}.")

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

    if message.author == bot.user or message.channel.id not in LISTENED_CHANNELS:
        return

    user_id = message.author.id
    content = message.content.strip()

    # Riddle answer input by admin
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

if not TOKEN:
    print("❌ DISCORD_TOKEN is not set.")
else:
    print("✅ Starting bot...")
    bot.run(TOKEN)
