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

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.environ.get("PORT", 4000))

# Mapping topic to role IDs for ticketing
TOPIC_MAP = {
    "account upgrades": 111111111111111111,   # Replace with actual role ID
    "event information": 222222222222222222,  # Replace with actual role ID
}

# Channel ID where closed ticket logs go
CLOSED_TICKETS_CHANNEL_ID = 333333333333333333  # Replace with your closed tickets log channel ID

# In-memory storage for claimed tickets (channel_id: moderator_user_id)
CLAIMED_TICKETS = {}

# Flask server for health checks
app = Flask(__name__)

@app.route("/")
def index():
    return "Riddle bot is running!"

def run_web():
    app.run(host="0.0.0.0", port=PORT)

threading.Thread(target=run_web).start()

# Discord bot intents and setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# File paths for riddles and scores
SCORES_FILE = "scores.json"
RIDDLES_FILE = "riddles.json"

COOLDOWN = 10  # seconds cooldown between guesses

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

# IDs for your channels
RIDDLE_CHANNEL_ID = 1365773539495645215  # Your riddle channel ID
ADMIN_CHANNEL_ID = 1361523942829068468   # Your admin command channel ID

# --- Ticketing system classes ---

class ClaimButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Claim Ticket", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only moderators can claim tickets.", ephemeral=True)
            return

        channel = interaction.channel

        if channel.id in CLAIMED_TICKETS:
            claimer = interaction.guild.get_member(CLAIMED_TICKETS[channel.id])
            await interaction.response.send_message(f"This ticket is already claimed by {claimer.mention}.", ephemeral=True)
            return

        # Save claimer info
        CLAIMED_TICKETS[channel.id] = interaction.user.id
        claimer = interaction.user

        # Try to identify ticket creator from recent messages
        messages = [msg async for msg in channel.history(limit=10)]
        ticket_creator = None
        for msg in messages:
            if msg.mentions:
                ticket_creator = msg.mentions[0]
                break

        if not ticket_creator:
            await interaction.response.send_message("Unable to determine the ticket creator.", ephemeral=True)
            return

        # Update channel permissions to be private to claimer and ticket creator only
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            claimer: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            ticket_creator: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        await channel.edit(overwrites=overwrites)
        await channel.send(
            f"🔒 Ticket claimed by {claimer.mention}. This ticket is now private between you and {ticket_creator.mention}."
        )
        await interaction.response.defer()

class CloseButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Close Ticket", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        channel = interaction.channel
        claimer_id = CLAIMED_TICKETS.get(channel.id)

        if (
            interaction.user.id != claimer_id and
            not interaction.user.guild_permissions.manage_messages and
            not interaction.user.permissions_in(channel).manage_channels
        ):
            await interaction.response.send_message("Only the claimer or a moderator can close this ticket.", ephemeral=True)
            return

        # Log ticket close
        closed_log_channel = interaction.guild.get_channel(CLOSED_TICKETS_CHANNEL_ID)
        log_embed = discord.Embed(
            title="🎫 Ticket Closed",
            description=f"**Channel:** {channel.name}\n**Closed by:** {interaction.user.mention}",
            color=discord.Color.red()
        )
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

        if not role_id:
            await interaction.response.send_message("Something went wrong. Please try again later.", ephemeral=True)
            return

        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.get_role(role_id): discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        channel_name = f"ticket-{interaction.user.name}-{topic_key.replace(' ', '-')}"
        channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            reason=f"Support ticket: {topic_label}"
        )

        view = discord.ui.View()
        view.add_item(ClaimButton())
        view.add_item(CloseButton())

        await channel.send(
            f"{interaction.user.mention} has created a ticket for **{topic_label}**.\n"
            f"{guild.get_role(role_id).mention}, please assist.",
            view=view
        )
        await interaction.response.send_message(f"✅ Your ticket has been created: {channel.mention}", ephemeral=True)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(TicketSelect())

class Ticketing(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ticket(self, ctx):
        """Open a support ticket."""
        await ctx.send("📩 Please select the topic for your ticket:", view=TicketView())

# --- End Ticketing system ---

# --- Riddle bot commands and logic ---

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

@bot.command(name="addriddle")
@commands.has_permissions(administrator=True)
@admin_channel_only()
async def addriddle(ctx):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    question_prompt = await ctx.send("📝 Please enter the **question**:")

    try:
        question_msg = await bot.wait_for("message", check=check, timeout=60)
        question = question_msg.content.strip()

        answer_prompt = await ctx.send("✅ Got it. Now please enter the **answer**:")

        answer_msg = await bot.wait_for("message", check=check, timeout=60)
        answer = answer_msg.content.strip().lower()

        riddles[question] = answer
        save_json(RIDDLES_FILE, riddles)

        await ctx.send(f"🆕 Riddle added!\n**Q:** {question}\n**A:** {answer}")

        if not current_riddle["question"]:
            current_riddle["question"] = question
            current_riddle["answer"] = answer

    except asyncio.TimeoutError:
        await ctx.send("⏰ Timeout. Please try adding the riddle again.")

@bot.command(name="riddle")
async def riddle(ctx):
    if ctx.channel.id != RIDDLE_CHANNEL_ID:
        await ctx.send("❌ Please use this command in the designated riddle channel.")
        return

    if not current_riddle["question"]:
        await ctx.send("⚠️ No riddle loaded currently.")
        return

    await ctx.send(f"🧩 **Riddle:** {current_riddle['question']}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Check if message is in riddle channel and answer is expected
    if message.channel.id == RIDDLE_CHANNEL_ID and current_riddle["answer"]:
        now = time.time()
        last_guess = guess_timestamps.get(message.author.id, 0)
        if now - last_guess < COOLDOWN:
            # Ignore guesses if in cooldown
            return

        guess_timestamps[message.author.id] = now

        guess_norm = normalize(message.content)
        answer_norm = normalize(current_riddle["answer"])

        if guess_norm == answer_norm:
            # Award point to user
            user_id_str = str(message.author.id)
            scores[user_id_str] = scores.get(user_id_str, 0) + 1
            save_json(SCORES_FILE, scores)

            await message.channel.send(f"🎉 Congratulations {message.author.mention}! You got the correct answer. Your score is now {scores[user_id_str]}.")

            # Pick a new riddle randomly
            question, answer = random.choice(list(riddles.items()))
            current_riddle["question"] = question
            current_riddle["answer"] = answer
            await message.channel.send(f"🧩 New riddle: {question}")

        else:
            # Optional: you can provide hints or ignore
            pass

    await bot.process_commands(message)

@bot.command(name="score")
async def score(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_id_str = str(member.id)
    user_score = scores.get(user_id_str, 0)
    await ctx.send(f"📊 {member.display_name}'s score: {user_score}")

@bot.command(name="scores")
async def scores_cmd(ctx):
    if not scores:
        await ctx.send("No scores recorded yet.")
        return
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    lines = []
    for user_id, score in sorted_scores[:10]:
        user = ctx.guild.get_member(int(user_id))
        name = user.display_name if user else "Unknown User"
        lines.append(f"{name}: {score}")
    await ctx.send("🏆 Top scores:\n" + "\n".join(lines))

# Add the ticketing cog
bot.add_cog(Ticketing(bot))

# Run the bot
bot.run(TOKEN)
