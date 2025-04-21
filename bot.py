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

# Flask web server setup
app = Flask(__name__)

@app.route("/")
def index():
    return "Riddle bot is alive!"

def run_web():
    app.run(host="0.0.0.0", port=PORT)

threading.Thread(target=run_web).start()

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Data files
SCORES_FILE = "scores.json"
RIDDLES_FILE = "riddles.json"
COOLDOWN = 300  # 5 minutes

# Load or initialize data
if os.path.exists(SCORES_FILE):
    with open(SCORES_FILE, "r") as f:
        scores = json.load(f)
else:
    scores = {}

if os.path.exists(RIDDLES_FILE):
    with open(RIDDLES_FILE, "r") as f:
        riddles = json.load(f)
else:
    riddles = {}

guess_timestamps = {}  # cooldown tracking
current_riddle = {"question": None, "answer": None}

# Utility to save data
def save_data():
    with open(SCORES_FILE, "w") as f:
        json.dump(scores, f)
    with open(RIDDLES_FILE, "w") as f:
        json.dump(riddles, f)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.command(name="addriddle")
@commands.has_permissions(administrator=True)
async def addriddle(ctx, *, arg):
    try:
        question, answer = arg.split("|")
        riddles[question.strip()] = answer.strip().lower()
        save_data()
        await ctx.send("✅ Riddle added!")
    except ValueError:
        await ctx.send("❌ Usage: `!addriddle What has keys but can't open locks? | A piano`")

@bot.command(name="riddle")
async def riddle(ctx):
    if not riddles:
        await ctx.send("⚠️ No riddles available.")
        return
    question = next(iter(riddles))
    answer = riddles[question]
    current_riddle["question"] = question
    current_riddle["answer"] = answer
    guess_timestamps.clear()
    await ctx.send(f"🧩 **Riddle:** {question}")

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

    if (
        message.author == bot.user
        or current_riddle["question"] is None
        or message.content.startswith("!")
    ):
        return

    user_id = str(message.author.id)
    now = time.time()
    last_guess = guess_timestamps.get(user_id, 0)

    if now - last_guess < COOLDOWN:
        time_left = int(COOLDOWN - (now - last_guess))
        mins, secs = divmod(time_left, 60)
        await message.channel.send(
            f"⏳ {message.author.mention}, wait {mins}m {secs}s before guessing again."
        )
        return

    guess_timestamps[user_id] = now
    guess = message.content.lower().strip()
    correct = current_riddle["answer"]

    if guess == correct:
        await message.add_reaction("✅")
        scores[str(message.author)] = scores.get(str(message.author), 0) + 1
        save_data()
    else:
        await message.add_reaction("❌")

bot.run(TOKEN)
