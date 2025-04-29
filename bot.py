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

# Stop words to ignore in answers
STOP_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "and", "or"}

def normalize(text):
    words = text.lower().split()
    filtered = [word for word in words if word not in STOP_WORDS]
    lemmatized = [lemmatizer.lemmatize(word) for word in filtered]
    return " ".join(lemmatized)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.environ.get("PORT", 4000))

# Set your channel IDs here
RIDDLE_CHANNEL_ID = 1365773539495645215 
ADMIN_CHANNEL_ID = 1361523942829068468 

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

COOLDOWN = 10  # seconds

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

# Restrict admin commands to a specific channel
def admin_channel_only():
    async def predicate(ctx):
        return ctx.channel.id == ADMIN_CHANNEL_ID
    return commands.check(predicate)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.competing,
            name="in the riddle Olympics"
        )
    )

    if riddles and not current_riddle["question"]:
        question, answer = random.choice(list(riddles.items()))
        current_riddle["question"] = question
        current_riddle["answer"] = answer
        print(f"🧩 Loaded riddle: {question}")

# --- Commands ---

@bot.command(name="addriddle")
@commands.has_permissions(administrator=True)
@admin_channel_only()
async def addriddle(ctx):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    # Prompt for question
    question_prompt = await ctx.send("📝 Please enter the **question**:")

    try:
        question_msg = await bot.wait_for("message", check=check, timeout=60)
        question = question_msg.content.strip()

        # Prompt for answer
        answer_prompt = await ctx.send("✅ Got it. Now please enter the **answer**:")

        answer_msg = await bot.wait_for("message", check=check, timeout=60)
        answer = answer_msg.content.strip().lower()

        riddles[question] = answer
        save_data()

        await ctx.send(f"✅ Riddle added!")

        # Clean up: delete all input & prompt messages except final confirmation
        await asyncio.sleep(5)
        await question_prompt.delete()
        await question_msg.delete()
        await answer_prompt.delete()
        await answer_msg.delete()

    except asyncio.TimeoutError:
        await ctx.send("⌛ Timed out. Please try `!addriddle` again.")

@bot.command(name="deleteriddle")
@commands.has_permissions(administrator=True)
@admin_channel_only()
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

@bot.command(name="help")
@commands.has_permissions(administrator=True)
@admin_channel_only()
async def help_command(ctx):
    help_text = (
        "🛠️ **Riddle Bot Commands:**\n\n"
        "`!addriddle` - Add a new riddle (you'll be prompted for Q & A)\n"
        "`!deleteriddle` - Delete a riddle from the list\n"
        "`!riddle` - Show the current riddle (or a new one if none active)\n"
        "`!leaderboard` - Show top 10 users by score\n"
        "`!cancel` - (Deprecated)\n"
        "`!help` - Show this help message\n\n"
        "⚙️ **Bot Behavior:**\n"
        "• Only accepts riddle answers in the designated riddle channel\n"
        "• Accepts admin commands only in the admin channel\n"
        "• Ignores common words (e.g. 'a', 'the') and plurals when checking answers\n"
        "• Guess cooldown: 10 seconds per user"
    )
    await ctx.send(help_text)
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
        mins, secs = divmod(remaining, 30)
        await message.channel.send(
            f"⏳ {message.author.mention}, wait {secs}s to guess again."
        )
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
