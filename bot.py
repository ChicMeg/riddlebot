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
from discord.ui import View, Button
import io  # For transcript file creation

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

# Channel IDs — replace with your actual IDs
RIDDLE_CHANNEL_ID = # riddle channel
ADMIN_CHANNEL_ID = # admin/mod channel
TICKET_DISPLAY_CHANNEL_ID = # Channel where the ticket embed is posted
CLOSED_TICKETS_CHANNEL_ID = # closed ticket log
TICKET_BUTTON_CHANNEL_ID = # Channel where users click buttons to create tickets
TICKET_ARCHIVE_CHANNEL_ID = # Channel for archived transcripts of ticket conversations

# Topic to Role mapping — replace with your actual role IDs
TOPIC_MAP = {
    "account questions": "", # role ID goes here
    "event information": # role ID goes here
}

CLAIMED_TICKETS = {}  # channel_id: mod_user_id

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# File paths
SCORES_FILE = "scores.json"
RIDDLES_FILE = "riddles.json"

COOLDOWN = 10

app = Flask(__name__)

# Data handling

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

# Text normalization

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

# Riddle checking

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    bot.add_view(TicketView())  # Register persistent TicketView

@bot.command()
async def riddle(ctx):
    if ctx.channel.id != RIDDLE_CHANNEL_ID:
        return
    if not riddles:
        await ctx.send("No riddles available.")
        return
    question, answer = random.choice(list(riddles.items()))
    current_riddle["question"] = question
    current_riddle["answer"] = answer
    await ctx.send(f"🧩 Riddle: {question}")

@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author.bot or message.channel.id != RIDDLE_CHANNEL_ID:
        return

    now = time.time()
    user_id = str(message.author.id)

    if user_id in guess_timestamps and now - guess_timestamps[user_id] < COOLDOWN:
        await message.channel.send("⏳ Please wait before guessing again.")
        return

    guess = normalize(message.content)
    answer = normalize(current_riddle.get("answer", ""))

    if guess == answer:
        scores[user_id] = scores.get(user_id, 0) + 1
        await message.channel.send(f"✅ Correct, {message.author.mention}! Your score: {scores[user_id]}")
        current_riddle["question"] = None
        current_riddle["answer"] = None
        save_data()
    else:
        await message.channel.send("❌ Incorrect. Try again!")

    guess_timestamps[user_id] = now

# Ticket system

class ClaimButton(Button):
    def __init__(self):
        super().__init__(label="Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket")

    async def callback(self, interaction: discord.Interaction):
        if interaction.channel.category and interaction.channel.category.name == "Tickets":
            if interaction.channel.id in CLAIMED_TICKETS:
                await interaction.response.send_message("⚠️ This ticket has already been claimed.", ephemeral=True)
                return

            await interaction.channel.set_permissions(interaction.user, read_messages=True, send_messages=True)
            CLAIMED_TICKETS[interaction.channel.id] = interaction.user.id
            new_name = f"ticket-{interaction.channel.name.split('-')[1]}-claimed"
            await interaction.channel.edit(name=new_name)
            await interaction.response.send_message(f"✅ {interaction.user.mention} has claimed this ticket.")
        else:
            await interaction.response.send_message("This button can only be used in ticket channels.", ephemeral=True)

class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="Account Questions", custom_id="ticket_account"))
        self.add_item(Button(label="Event Information", custom_id="ticket_event"))

@bot.command()
async def ticket(ctx):
    if ctx.channel.id != ADMIN_CHANNEL_ID:
        return await ctx.send("This command can only be used in the admin channel.")

    embed = discord.Embed(
        title="🎟️ Open a Support Ticket",
        description="Click one of the buttons below to open a ticket on that topic.",
        color=discord.Color.blue()
    )
    view = TicketView()
    display_channel = bot.get_channel(TICKET_BUTTON_CHANNEL_ID)
    if display_channel:
        await display_channel.send(embed=embed, view=view)
        await ctx.send("✅ Ticket embed posted in the designated channel.")
    else:
        await ctx.send("❌ Could not find the ticket display channel.")

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not interaction.data or not interaction.data.get("custom_id"):
        return

    custom_id = interaction.data["custom_id"]

    # Map button ID to topic
    topic = None
    if custom_id == "ticket_account":
        topic = "account questions"
    elif custom_id == "ticket_event":
        topic = "event information"
    elif custom_id == "claim_ticket":
        return await ClaimButton().callback(interaction)

    if topic is None:
        return

    role_id = TOPIC_MAP.get(topic)
    guild = interaction.guild
    member = interaction.user

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.get_role(role_id): discord.PermissionOverwrite(read_messages=True, send_messages=True),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
    }

    category = discord.utils.get(guild.categories, name="Tickets")
    if not category:
        category = await guild.create_category("Tickets")

    # Sanitize username for channel name
    safe_name = member.display_name.lower().replace(" ", "-")
    channel_name = f"ticket-{safe_name}"

    # Prevent duplicate ticket
    existing_channel = discord.utils.get(category.channels, name=channel_name)
    if existing_channel:
        await interaction.response.send_message(f"⚠️ You already have an open ticket: {existing_channel.mention}", ephemeral=True)
        return

    ticket_channel = await guild.create_text_channel(channel_name, overwrites=overwrites, category=category)

    claim_view = View()
    claim_view.add_item(ClaimButton())

    await ticket_channel.send(f"{member.mention}, your ticket for **{topic}** has been created.", view=claim_view)
    await interaction.response.send_message(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)


@bot.command()
async def close(ctx):
    if ctx.channel.category and ctx.channel.category.name == "Tickets":
        log_channel = ctx.guild.get_channel(CLOSED_TICKETS_CHANNEL_ID)
        archive_channel = ctx.guild.get_channel(TICKET_ARCHIVE_CHANNEL_ID)

        transcript = []
        async for message in ctx.channel.history(limit=100, oldest_first=True):
            author = message.author.display_name
            content = message.content
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M")
            transcript.append(f"[{timestamp}] {author}: {content}")

        transcript_text = "\n".join(transcript)

        if archive_channel:
            transcript_file = io.StringIO(transcript_text)
            await archive_channel.send(
                f"🗃️ Transcript for {ctx.channel.name}:",
                file=discord.File(fp=transcript_file, filename=f"{ctx.channel.name}_transcript.txt"),
            )

        if log_channel:
            await log_channel.send(f"📁 Ticket closed: {ctx.channel.name} by {ctx.author.mention}")
        await ctx.send("Ticket closed. This channel will be deleted shortly.")
        await asyncio.sleep(5)
        await ctx.channel.delete()
    else:
        await ctx.send("This command can only be used in ticket channels.")

# Bot startup
if not TOKEN:
    print("❌ DISCORD_TOKEN is not set.")
else:
    print("✅ Starting bot...")
    bot.run(TOKEN)
