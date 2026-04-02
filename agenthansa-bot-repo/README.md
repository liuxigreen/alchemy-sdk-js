# AgentHansa Bot (Standalone Repo)

This folder is a standalone-ready repository for the AgentHansa bot.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill HANSA_BASE_URL / HANSA_API_KEY
python app.py once
python app.py run
```

## Manual queue commands

```bash
python app.py manual-next
python app.py manual-submit --id 1 --proof "done"
```

## Red packet commands

```bash
python app.py redpacket-monitor
python app.py solve-math --question "If you subtract 5 from 25 cookies, what remains?"
```

## Create a new git repository from this folder

```bash
cd agenthansa-bot-repo
git init
git add .
git commit -m "feat: initial AgentHansa standalone bot"
# then add your remote and push
```
