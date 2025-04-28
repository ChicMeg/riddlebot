# 🤖 Riddle Discord Bot

A Discord bot that lets server admins add riddles, allows users to guess answers, and tracks scores with a leaderboard. Built with Python and hosted on [Render.com](https://render.com).

---

## ✨ Features

- 🧠 Admin-only command to add riddles
- Admin answer input deleted after 5 seconds to allow participation among administrators without cheating!
- 🧩 Random riddles posted with `!riddle`
- ✅ Reaction on correct answers, ❌ on incorrect ones
- ⏱ 30 second cooldown between guesses per user
- Solved riddles are deleted from the active riddle list!
- 🏆 `!leaderboard` command shows top scores
- 💾 Persistent storage for riddles and scores

---

## 🚀 Deployment (wispbyte.com)

### 1. Fork or clone the repo
```bash
git clone https://github.com/yourusername/riddlebot.git
cd riddlebot
