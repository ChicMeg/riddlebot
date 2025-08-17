import os
import json
import random
import asyncio
import io
import time as time_module
from datetime import time
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button, Select
import nltk
from nltk.corpus import stopwords 
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") or "YOUR_BOT_TOKEN"
PORT = int(os.getenv("PORT", 4000))

# Game files
RIDDLES_FILE = 'riddles.json'
SCORES_FILE = 'scores.json'
CONFIG_FILE = 'config.json'
SCOREBOARD_FILE = 'scoreboard.json'
COOLDOWN = 5
# Load words
with open('words.json') as f:
    words = json.load(f)['words']

# NLTK setup
try:
    nltk.data.find('corpora/wordnet')
except LookupError:
    nltk.download('wordnet')
    nltk.download('omw-1.4')
    nltk.download("stopwords")
    nltk.download("punkt_tab")
lemmatizer = WordNetLemmatizer()
stop_words = set(stopwords.words('english'))

# Load/save helpers
def load_json(path, default):
    if os.path.exists(path):
        with open(path, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                 return default
    return default
    
def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

# Global state
riddles = load_json(RIDDLES_FILE, [])
scores = load_json(SCORES_FILE, {})
config = load_json(CONFIG_FILE, {})
scoreboard = load_json(SCOREBOARD_FILE, {})
last_riddle_command_time = None

# Word guessing game state
game_running = False
game_channel = None
current_word = ""
display_word = ""
guessed_letters = []
attempts_remaining = 15
guess_timestamps = {}
current_riddle = {"question": None, "answer": None}
# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix=commands.when_mentioned_or('!'), intents=intents)
tree = bot.tree
client = discord.Client(intents=intents)

# Utility for word game
def update_display_word():
    return ' '.join([c if c.lower() in guessed_letters or not c.isalpha() else '\_' for c in current_word])

def pick_new_word():
    global current_word, guessed_letters, attempts_remaining, display_word
    current_word = random.choice(words)
    guessed_letters = []
    attempts_remaining = 15
    display_word = update_display_word()

def save_data():
    save_json(SCORES_FILE, scores)
    save_json(RIDDLES_FILE, riddles)
    save_json(LISTENED_FILE, LISTENED_CHANNELS)

def save_game_state():
    with open("gamestate.json", "w") as f:
        json.dump({
            "current_word": current_word,
            "guessed_letters": guessed_letters,
            "attempts_remaining": attempts_remaining,
            "game_running": game_running
        }, f)

def load_game_state():
    global current_word, guessed_letters, attempts_remaining, game_running, display_word
    try:
        with open("gamestate.json", "r") as f:
            data = json.load(f)
            current_word = data.get("current_word", "")
            guessed_letters = data.get("guessed_letters", [])
            attempts_remaining = data.get("attempts_remaining", 15)
            game_running = data.get("game_running", False)
            display_word = update_display_word()
    except FileNotFoundError:
        pass

def lemmatized_word_set(text):
    return {
        lemmatizer.lemmatize(word.lower())
        for word in text.split()
        if word.lower() not in stop_words
    }
class RiddleSelect(discord.ui.Select):
    def __init__(self, inter: discord.Interaction):
        options = [
            discord.SelectOption(label=f"{i+1}. {r['question'][:50]}", value=str(i))
            for i, r in enumerate(riddles)
        ]
        super().__init__(placeholder="Select a riddle to delete...", min_values=1, max_values=1, options=options)
        self.inter = inter

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.inter.user:
            return await interaction.response.send_message("❌ Only the command user can select.", ephemeral=True)
        index = int(self.values[0])
        removed = riddles.pop(index)
        save_json(RIDDLES_FILE, riddles)
        await interaction.response.edit_message(content=f"🗑️ Deleted: {removed['question']}", view=None)

class RiddleSelectView(View):
    def __init__(self, inter):
        super().__init__(timeout=60)
        self.add_item(RiddleSelect(inter))
        
def nltk_similarity(a, b):
    # Tokenize and lowercase
    tokens_a = word_tokenize(a.lower())
    tokens_b = word_tokenize(b.lower())

    # Remove stopwords
    tokens_a = [t for t in tokens_a if t.isalpha() and t not in stop_words]
    tokens_b = [t for t in tokens_b if t.isalpha() and t not in stop_words]

    # Lemmatize
    lemmas_a = [lemmatizer.lemmatize(token) for token in tokens_a]
    lemmas_b = [lemmatizer.lemmatize(token) for token in tokens_b]

    # Join back into strings
    lemma_str_a = " ".join(lemmas_a)
    lemma_str_b = " ".join(lemmas_b)

    # Edit distance similarity
    if not lemma_str_a or not lemma_str_b:
        return 0.0  # Avoid division by zero if nothing left after stopword removal

    return 1 - nltk.edit_distance(lemma_str_a, lemma_str_b) / max(len(lemma_str_a), len(lemma_str_b))

# Ticket System UI
class TicketPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Account Questions", style=discord.ButtonStyle.primary, custom_id="ticket_account")
    async def account(self, interaction: discord.Interaction, button: Button):
        await self.create_ticket(interaction, "account questions")

    @discord.ui.button(label="Event Information", style=discord.ButtonStyle.primary, custom_id="ticket_event")
    async def event(self, interaction: discord.Interaction, button: Button):
        await self.create_ticket(interaction, "event information")

    async def create_ticket(self, interaction, topic):
        role_id = config.get("TOPIC_MAP", {}).get(topic.replace(" ", "_"))
        guild = interaction.guild

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }

        if role_id:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True)

        category = discord.utils.get(guild.categories, name="Tickets") or await guild.create_category("Tickets")
        channel = await category.create_text_channel(name=f"ticket-{interaction.user.name}", overwrites=overwrites)
        await channel.send(f"{interaction.user.mention}, your ticket has been created.", view=ClaimView())
        await interaction.response.send_message(f"✅ Created ticket: {channel.mention}", ephemeral=True)

class ClaimView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, custom_id="claim_ticket")
    async def claim(self, interaction: discord.Interaction, button: Button):
        await interaction.channel.set_permissions(interaction.user, send_messages=True, read_messages=True)
        await interaction.channel.edit(name=f"{interaction.channel.name}-claimed")
        await interaction.response.send_message(f"✅ Claimed by {interaction.user.mention}")

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("🛑 Closing ticket in 15 seconds...")
        await asyncio.sleep(15)

        transcript = []
        async for message in interaction.channel.history(limit=None, oldest_first=True):
            timestamp = message.created_at.strftime('%Y-%m-%d %H:%M')
            transcript.append(f"[{timestamp}] {message.author.display_name}: {message.content}")

        transcript_text = "\n".join(transcript) or "(No messages in ticket)"
        transcript_file = discord.File(
            fp=io.StringIO(transcript_text),
            filename=f"transcript-{interaction.channel.name}.txt"
        )

        config = load_json(CONFIG_FILE, {})
        closed_log_channel_id = config.get("CLOSED_TICKETS_CHANNEL_ID")
        archive_channel_id = config.get("TICKET_ARCHIVE_CHANNEL_ID")

        closed_log_channel = interaction.guild.get_channel(closed_log_channel_id) if closed_log_channel_id else None
        archive_channel = interaction.guild.get_channel(archive_channel_id) if archive_channel_id else None

        if closed_log_channel:
            embed = discord.Embed(
                title="🗃️ Ticket Closed",
                description=f"Channel: `{interaction.channel.name}`\nClosed by: {interaction.user.mention}",
                color=discord.Color.red()
            )
            await closed_log_channel.send(embed=embed)

        if archive_channel:
            await archive_channel.send(
                content=f"📎 Transcript for `{interaction.channel.name}`",
                file=transcript_file
            )
        await interaction.channel.delete()


# Riddle Commands
@tree.command(name="setup", description="Set riddle and ticket panel channels")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    riddle_channel="Channel for daily riddles",
    ticket_channel="Channel to post the ticket panel"
)
async def setup(interaction: discord.Interaction, riddle_channel: discord.TextChannel, ticket_channel: discord.TextChannel):
    config["RIDDLE_CHANNEL_ID"] = riddle_channel.id
    guild_id = str(interaction.guild_id)
    if guild_id not in config:
        config[guild_id] = {}
    config[guild_id]["ticket_display"] = ticket_channel.id
    save_json(CONFIG_FILE, config)
    await interaction.response.send_message(f"✅ Setup complete:\n- Riddle Channel: {riddle_channel.mention}\n- Ticket Panel Channel: {ticket_channel.mention}", ephemeral=True)

@tree.command(name="current", description="Show the current riddle")
async def current(interaction: discord.Interaction):
    config = load_json(CONFIG_FILE, {})
    riddle = config.get("CURRENT_RIDDLE")
    if not riddle:
        return await interaction.response.send_message("❌ No active riddle.", ephemeral=True)
    await interaction.response.send_message(f"🧩 **Current Riddle:** {riddle['question']}")

@tree.command(name="delriddle", description="Delete a riddle by selecting from the list")
@app_commands.checks.has_permissions(administrator=True)
async def delriddle(inter: discord.Interaction):
    if not riddles:
        return await inter.response.send_message("❌ No riddles to delete.", ephemeral=True)
    await inter.response.send_message("🧩 Select a riddle to delete:", view=RiddleSelectView(inter), ephemeral=True)

@tree.command(name="score", description="Check your riddle score.")
async def score(interaction: discord.Interaction):
    score = scores.get(str(interaction.user.id), 0)
    await interaction.response.send_message(f"🏆 Your score is: **{score}**", ephemeral=True)

@tree.command(name="addriddle", description="Add a new riddle (admin only)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(prompt="The riddle question", answer="The correct answer to the riddle")
async def addriddle(interaction: discord.Interaction, prompt: str, answer: str):
    riddles.append({"question": prompt, "answer": answer})
    save_json(RIDDLES_FILE, riddles)
    await interaction.response.send_message("✅ Riddle added.", ephemeral=True)

@tree.command(name="leaderboard", description="Show top 10 riddle masters")
async def leaderboard(inter: discord.Interaction):
    if not scores:
        return await inter.response.send_message("🏆 No scores yet.", ephemeral=True)
    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = [f"{i+1}. <@{uid}> — {pts} pts" for i, (uid, pts) in enumerate(top)]
    await inter.response.send_message("**🏆 Top 10 Riddle Masters**\n" + "\n".join(lines))

@tree.command(name="post_riddle", description="Post a new riddle immediately (admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def post_riddle(interaction: discord.Interaction):
    global last_riddle_command_time
    now = time_module.time()
    if last_riddle_command_time and now - last_riddle_command_time < 5:
        return await interaction.response.send_message("⏳ Please wait before trying again.", ephemeral=True)

    last_riddle_command_time = now
    config = load_json(CONFIG_FILE, {})
    channel = bot.get_channel(config.get("RIDDLE_CHANNEL_ID"))
    if not channel or not riddles:
        return await interaction.response.send_message("❌ Can't post riddle. Channel or riddles missing.", ephemeral=True)

    riddle = random.choice(riddles)
    riddle["solved_by"] = None
    config["CURRENT_RIDDLE"] = riddle
    config["LAST_RIDDLE_TIME"] = discord.utils.utcnow().isoformat()
    save_json(CONFIG_FILE, config)

    role = 1395573526823440464
    mention = f"<@&{role}>" if role else ""
    await channel.send(f"{mention} 🧠 **Riddle of the Day:** {riddle['question']}")
    await interaction.response.send_message("✅ Riddle posted.", ephemeral=True)

# Combined on_message

@bot.event
async def on_message(message):
    global guessed_letters, attempts_remaining, game_running, current_word, display_word

    if message.author.bot:
        return

    await bot.process_commands(message)

    current_riddle = config.get("CURRENT_RIDDLE")
    riddle_channel_id = 1378486916407758888
    if current_riddle and message.channel.id == riddle_channel_id:
        expected_answer = current_riddle["answer"]
        similarity = nltk_similarity(expected_answer, message.content)

@bot.event
async def on_message(message):
    global guessed_letters, attempts_remaining, game_running, current_word, display_word, riddles, config

    if message.author.bot:
        return

    await bot.process_commands(message)

    current_riddle = config.get("CURRENT_RIDDLE")
    riddle_channel_id = 1378486916407758888  # still hardcoded — consider moving to config
    if current_riddle and message.channel.id == riddle_channel_id:
        expected_answer = current_riddle["answer"]
        similarity = nltk_similarity(expected_answer, message.content)

        if similarity >= 1.0:
            # ✅ Exact or full match
            if current_riddle.get("solved_by"):
                await message.channel.send(f"✅ That’s correct, but {current_riddle['solved_by']} already solved it!")
            else:
                current_riddle["solved_by"] = message.author.name
                config["CURRENT_RIDDLE"] = current_riddle
                save_json(CONFIG_FILE, config)

                uid = str(message.author.id)
                scores[uid] = scores.get(uid, 0) + 1
                save_json(SCORES_FILE, scores)

                # Remove solved riddle from list and save
                riddles = [r for r in riddles if r.get("question") != current_riddle.get("question")]
                save_json(RIDDLES_FILE, riddles)

                # Clear current riddle
                config["CURRENT_RIDDLE"] = None
                save_json(CONFIG_FILE, config)

                await message.channel.send(f"🎉 Correct, {message.author.mention}! You've been awarded a point.")

            try:
                await message.add_reaction("🤏")
            except:
                pass
        else:
            try:
                await message.add_reaction("❌")
            except:
                pass

    # Word guessing game mode
    if game_running and message.channel == game_channel:
        guess = message.content.lower().strip()

        if guess == current_word.lower():
            uid = str(message.author.id)
            scoreboard[uid] = scoreboard.get(uid, 0) + 1
            save_json(SCOREBOARD_FILE, scoreboard)
            await message.channel.send(f"🎉 {message.author.mention} guessed the word correctly! +1 point.")
            pick_new_word()
            await message.channel.send(f"🔄 New word:\n{display_word}\nAttempts remaining: {attempts_remaining}")
            save_game_state()
        elif len(guess) == 1 and guess.isalpha():
            if guess in guessed_letters:
                await message.reply(f"⚠️ {guess} has already been guessed.")
                return
            guessed_letters.append(guess)
            if guess in current_word.lower():
                display_word = update_display_word()
                await message.reply(f"✅ {guess} is in the word!\n{display_word}\nAttempts: {attempts_remaining}")
                if '\_' not in display_word:
                    uid = str(message.author.id)
                    scoreboard[uid] = scoreboard.get(uid, 0) + 1
                    save_json(SCOREBOARD_FILE, scoreboard)
                    await message.channel.send(f"🎉 {message.author.mention} completed the word! +1 point.")
                    pick_new_word()
                    await message.channel.send(f"🔄 New word:\n{display_word}\nAttempts remaining: {attempts_remaining}")
            else:
                attempts_remaining -= 1
                await message.reply(f"❌ {guess} is not in the word.\n{display_word}\nAttempts: {attempts_remaining}")
                if attempts_remaining <= 0:
                    await message.channel.send("💀 Out of attempts! Moving to the next word...")
                    pick_new_word()
                    await message.channel.send(f"🔄 New word:\n{display_word}\nAttempts remaining: {attempts_remaining}")
            save_game_state()

@tasks.loop(time=time(0, 0))
async def riddle_loop():
    config = load_json(CONFIG_FILE, {})
    channel = 1378486916407758888
    if not channel:
        return

    if not riddles:
        return await channel.send("❌ No riddles available.")

    prev = config.get("CURRENT_RIDDLE")
    if prev:
        await channel.send(f"⏱️ Time's up! The correct answer was: **{prev['answer']}**")

    riddle = random.choice(riddles)
    riddle["solved_by"] = None
    config["CURRENT_RIDDLE"] = riddle
    config["LAST_RIDDLE_TIME"] = discord.utils.utcnow().isoformat()
    save_json(CONFIG_FILE, config)

    role = 1395573526823440464
    mention = f"<@&{role}>" if role else ""
    await channel.send(f"{mention} 🧠 **Riddle of the Day:** {riddle['question']}")
    await channel.send("You have 24 hours to solve it!")


# Additional Commands
@tree.command(name="ticketpanel", description="Post the ticket panel (admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def ticketpanel(inter: discord.Interaction):
    cfg = config.get(str(inter.guild_id), {})
    channel_id = cfg.get("ticket_display")
    channel = bot.get_channel(channel_id) if channel_id else None

    if not channel:
        return await inter.response.send_message("❌ No valid ticket display channel configured.", ephemeral=True)

    embed = discord.Embed(
        title="🎟️ Open a Support Ticket",
        description="Click a button below for help. A private channel will be created.",
        color=discord.Color.blue(),
    )
    await channel.send(embed=embed, view=TicketPanelView())
    await inter.response.send_message(f"✅ Ticket panel posted in {channel.mention}", ephemeral=True)

@tree.command(name="startgame", description="Start the word guessing game")
@app_commands.checks.has_permissions(administrator=True)
async def startgame(inter: discord.Interaction):
    global game_running, game_channel
    if game_running:
        await inter.response.send_message("⚠️ The game is already running.", ephemeral=True)
    else:
        game_running = True
        game_channel = inter.channel
        pick_new_word()
        await inter.response.send_message(f"✅ Game started!\n{display_word}\nAttempts: {attempts_remaining}")
        save_game_state()

@tree.command(name="stopgame", description="Stop the word guessing game")
@app_commands.checks.has_permissions(administrator=True)
async def stopgame(inter: discord.Interaction):
    global game_running
    if not game_running:
        await inter.response.send_message("⚠️ No game is running.", ephemeral=True)
    else:
        game_running = False
        await inter.response.send_message("🛑 Game stopped.")
        save_game_state()

@tree.command(name="scoreboard", description="Show the word guessing scoreboard")
async def scoreboard_command(inter: discord.Interaction):
    if not scoreboard:
        await inter.response.send_message("📭 No scores yet.")
        return

    sorted_scores = sorted(scoreboard.items(), key=lambda x: x[1], reverse=True)
    lines = []
    for i, (uid, score) in enumerate(sorted_scores[:10], 1):
        user = await bot.fetch_user(int(uid))
        lines.append(f"{i}. {user.name}: {score}")

    await inter.response.send_message("🏆 **Top Word Guessers:**\n" + "\n".join(lines))

# Error Handling
@startgame.error
@stopgame.error
@ticketpanel.error
@post_riddle.error
async def admin_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("⛔ You must be an admin to use this command.", ephemeral=True)

# Bot Ready
@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')

    # Set a custom status
    await client.change_presence(activity=discord.Game(name="Solving Riddles!"))
    
@bot.event
async def on_ready():
    load_game_state()
    await tree.sync()
    bot.add_view(TicketPanelView())
    bot.add_view(ClaimView())
    print(f"✅ Logged in as {bot.user}")

# Run bot
if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN not set.")
    else:
        print("✅ Starting bot...")
        bot.run(TOKEN)
