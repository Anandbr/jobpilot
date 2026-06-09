# JobPilot 🚀

An autonomous AI job application agent that finds, scores, tailors, and helps you apply to jobs — while you focus on interviews.

## What It Does

- 🔍 Monitors LinkedIn for new job postings matching your criteria
- 🧠 Scores each job against your profile using Claude AI
- 📄 Tailors your resume for each high-match role
- 📱 Sends Telegram notifications with Apply/Skip buttons
- 🤖 Handles the application process with browser automation (coming soon)

## Architecture

Built on thin harness fat skills principles —
skills/          — AI intelligence (markdown skill files)
harness/         — thin orchestration layer
tools/           — deterministic functions
data/            — candidate context and resume
config/          — job search preferences

## Tech Stack

- Python 3.11
- Claude API (Haiku for scoring, Sonnet for tailoring)
- SQLite via tools/database.py
- Telegram Bot API for notifications
- LinkedIn job scraping
- Node.js resume generator (tools/generate_resume.js)
- LibreOffice for PDF conversion

## Setup

```bash
git clone https://github.com/Anandbr/jobpilot
cd jobpilot
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm install
```

Create `.env` file —
ANTHROPIC_API_KEY=your_key
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

Add your resume to `data/base_resume.pdf`

Fill in `data/candidate-context.md` with your background.

## Usage

```bash
# Run one scan
python3 jobpilot.py scan

# Run continuously (every 30 mins)
python3 jobpilot.py start

# Check status
python3 jobpilot.py status
```

## Project Status

Active development. Currently in personal use phase.

## Author

Anand Buruganahalli Rajanna
[LinkedIn](https://linkedin.com/in/anandbrajanna) | [GitHub](https://github.com/Anandbr)