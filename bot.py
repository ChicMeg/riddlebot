import discord
from discord.ext import commands
import json
import os
import random
import atexit
import time
from collections import defaultdict

# Load Discord token from environment variable
TOKEN = os.getenv("DISCORD_TOKEN")

# Setup bot with message content intent
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Riddle and Score Storage ----------

riddles = {}

SCORE_FILE = "scores.json"
COOLDOWN_SECONDS = 300  # 5 minutes

# Load scores if file exists
if os.path.exists(SCORE_FILE):
    with open(SCORE_FILE, "r") as f:
        raw_scores = json.load(f)
        scores = defaultdict(int, raw_scores)
else:
    scores = defaultdict(int)

# Save scores when bot exits
@atexit.register
def save_scores():
    with open(SCORE_FILE, "w") as f:
        json.dump(scores, f)

# Track last guess timestamps per riddle
bot.last_guess_times = {}  # user_id -> timestamp

# ---------- Permissions ----------

def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

# ---------- Events & Commands ----------

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.command(name="addriddle")
@is_admin()
async def add_riddle(ctx, *, riddle_and_answer):
    try:
        riddle, answer = riddle_and_answer.split("|")
        riddles[riddle.strip()] = answer.strip().lower()
        await ctx.send("🧠 Riddle added!")
    except ValueError:
        await ctx.send("Usage: `!addriddle riddle here | answer`")

@bot.command(name="riddle")
async def post_riddle(ctx):
    if not riddles:
        await ctx.send("No riddles available.")
        return

    riddle = random.choice(list(riddles.keys()))
    bot.current_riddle = riddle
    bot.last_guess_times = {}  # Reset cooldowns per riddle
    await ctx.send(f"🧩 **Riddle:** {riddle}")

@bot.command(name="leaderboard")
async def leaderboard(ctx):
    if not scores:
        await ctx.send("No scores yet!")
        return

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = "\n".join([f"{i+1}. {user}: {score}" for i, (user, score) in enumerate(sorted_scores[:10])])
    await ctx.send(f"🏆 **Leaderboard**:\n{top}")

@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author == bot.user or not hasattr(bot, "current_riddle"):
        return

    user_id = message.author.id
    now = time.time()

    # Cooldown check
    last_guess = bot.last_guess_times.get(user_id, 0)
    if now - last_guess < COOLDOWN_SECONDS:
        time_left = int(COOLDOWN_SECONDS - (now - last_guess))
        minutes, seconds = divmod(time_left, 60)
        await message.channel.send(f"{message.author.mention}, you can guess again in {minutes}m {seconds}s.")
        return

    # Record guess time
    bot.last_guess_times[user_id] = now

    riddle = bot.current_riddle
    correct_answer = riddles.get(riddle, "").lower()
    user_answer = message.content.lower().strip()

    if user_answer == correct_answer:
        await message.add_reaction("✅")
        scores[str(message.author)] += 1

        # Save scores immediately
        with open(SCORE_FILE, "w") as f:
            json.dump(scores, f)
    else:
        await message.add_reaction("❌")
