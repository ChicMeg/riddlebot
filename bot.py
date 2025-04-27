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

COOLDOWN = 30 #seconds

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
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.competing,
            name="in the riddle Olympics"
        )
    )

    default_channel_id = 1361523942829068468
    if default_channel_id not in LISTENED_CHANNELS:
        LISTENED_CHANNELS.append(default_channel_id)
        save_data()

    # Set random riddle on startup
    if riddles and not current_riddle["question"]:
        question, answer = random.choice(list(riddles.items()))
        current_riddle["question"] = question
        current_riddle["answer"] = answer
        print(f"🧩 Loaded riddle: {question}")

# --- Commands ---

@bot.command(name="addriddle")
@commands.has_permissions(administrator=True)
async def addriddle(ctx):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    await ctx.send("📝 Please enter the **riddle question**:")

    try:
        question_msg = await bot.wait_for("message", check=check, timeout=60)
        question = question_msg.content.strip()

        await ctx.send("✅ Got it. Now please enter the **answer**:")

        answer_msg = await bot.wait_for("message", check=check, timeout=60)
        answer = answer_msg.content.strip().lower()

        riddles[question] = answer
        save_data()

        await ctx.send(f"✅ Riddle added!\n**Q:** {question}\")

    except asyncio.TimeoutError:
        await ctx.send("⌛ Timed out. Please try `!addriddle` again.")

@bot.command(name="deleteriddle")
@commands.has_permissions(administrator=True)
async def deleteriddle(ctx):
    if not riddles:
        await ctx.send("📭 No riddles to delete.")
        return

    questions = list(riddles.keys())
    max_display = min(10, len(questions))
    riddle_list = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions[:max_display]))

    await ctx.send(f"🗑️ **Select a riddle to delete (1-{max_display}):**\n{riddle_list}")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        msg = await bot.wait_for("message", check=check, timeout=60)
        choice = int(msg.content.strip())

        if 1 <= choice <= max_display:
            question_to_delete = questions[choice - 1]
            del riddles[question_to_delete]
            save_data()
            await ctx.send(f"✅ Deleted riddle: `{question_to_delete}`")
        else:
            await ctx.send("❌ Invalid selection number.")

    except ValueError:
        await ctx.send("❌ Please enter a valid number.")
    except asyncio.TimeoutError:
        await ctx.send("⌛ Timed out. Please try `!deleteriddle` again.")

@bot.command(name="riddle")
async def riddle(ctx):
    if current_riddle["question"]:
        await ctx.send(f"🧠 **Current Riddle:**\n{current_riddle['question']}")
    elif riddles:
        # Pick a random riddle from stored list
        question, answer = random.choice(list(riddles.items()))
        current_riddle["question"] = question
        current_riddle["answer"] = answer
        await ctx.send(f"🧠 **Here’s a random riddle:**\n{question}")
    else:
        await ctx.send("📭 No riddles available. (Admin only: Add some with `!addriddle`!)")

@bot.command(name="cancel")
async def cancel(ctx):
    await ctx.send("⚠️ Cancel functionality is no longer needed with new `!addriddle`.")

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

    if message.author == bot.user:
        return

    if isinstance(message.channel, discord.DMChannel):
        return

    if message.channel.id not in LISTENED_CHANNELS:
        return

    user_id = message.author.id
    content = message.content.strip()

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

        await message.channel.send(f"🎉 {message.author.mention} got it right! The answer was: **{correct}**")

        # Remove the correct riddle from the rotation
        del riddles[current_riddle["question"]]
        save_data()

        # Select a new riddle if available
        if riddles:
            question, answer = random.choice(list(riddles.items()))
            current_riddle["question"] = question
            current_riddle["answer"] = answer
            await message.channel.send(f"🧠 **Next Riddle:**\n{question}")
        else:
            current_riddle["question"] = None
            current_riddle["answer"] = None
            await message.channel.send("📭 No more riddles left. (Admin only: Add some with `!addriddle`!)")

    else:
        await message.add_reaction("❌")

if not TOKEN:
    print("❌ DISCORD_TOKEN is not set.")
else:
    print("✅ Starting bot...")
    bot.run(TOKEN)
