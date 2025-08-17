# Discord Riddle & Word Game Bot 🎮🧩

A multifunctional Discord bot built with discord.py that combines:

*🧠 Daily Riddle System* — automatic riddles, scoring, and leaderboards

*🔤 Word Guessing Game* — hangman-style guessing with per-user scoreboards

*🎟️ Ticketing System* — support tickets with transcripts and claim/close functionality

⚡ Persistent state saving for games, riddles, and tickets

## ✨ Features
### 🔹 Riddle System

Post daily riddles automatically at midnight (or manually with /post_riddle).

Intelligent answer checking using NLTK similarity (supports variations).

Tracks player scores and provides /leaderboard.

Admins can /addriddle, /delriddle, and configure channels with /setup.

### 🔹 Word Guessing Game

Classic hangman-style game: guess letters or full words.

Tracks per-player scores in a scoreboard.

Admins can start/stop with /startgame and /stopgame.

Scoreboard accessible via /scoreboard.

### 🔹 Ticketing System

Players can open tickets with buttons (e.g. "Account Questions", "Event Information").

Staff can claim or close tickets.

Closing generates a transcript file and optionally archives/logs it.

### 🔹 Other

Persistent state storage in JSON (riddles, scores, config, game state).

Slash commands synced automatically.

Customizable riddle + ticket channels.

# 🛠️ Installation
**1. Clone Repo**

```git clone https://github.com/chicmeg/riddlebot.git cd riddlebot``` 

**2. Install Dependencies**

*Python 3.10+ is recommended.*

```pip install -r requirements.txt```
