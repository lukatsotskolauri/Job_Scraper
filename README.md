# jobs.ge IT Job Scraper

A small Python script that scrapes the latest IT vacancies from [jobs.ge](https://jobs.ge), filters out the ones you don't want, and sends the new ones to a Telegram channel. It runs automatically once a day with GitHub Actions, so you don't need a server.

## Features

- Scrapes the IT category of jobs.ge (configurable number of pages)
- Filters out listings by keyword (for example `senior`, `.net`, `Java`)
- Remembers what it has already sent, so you never get the same job twice
- Sends new listings to a Telegram channel, group, or private chat
- Saves the seen-job state only after Telegram succeeds, so a failed send is retried on the next run
- Runs daily on GitHub Actions for free

## How it works

1. A health check confirms jobs.ge is reachable and the page layout is still parseable.
2. The scraper reads the first `MAX_PAGES` pages of the IT category.
3. Listings containing an excluded keyword are dropped, and the result is capped at `JOB_LIMIT`.
4. Listings whose IDs are not in `seen_jobs.json` are treated as new.
5. New listings are sent to Telegram.
6. Only after a successful send, the new IDs are saved to `seen_jobs.json` (and appended to `seen_jobs.csv`).

## Project structure

```
.
├── jobsge.py              # Entry point
├── jobs_scraper/
│   ├── config.py          # Settings, read from environment variables
│   ├── scraper.py         # Health check and page scraping
│   ├── filter.py          # Keyword exclusion
│   ├── state.py           # Loads the seen job IDs from seen_jobs.json
│   ├── notification.py    # Telegram sending and CSV logging
│   └── models.py          # JobListing data model
├── seen_jobs.json         # IDs of jobs already sent (committed by the workflow)
└── .github/workflows/
    └── scrape.yml         # Daily schedule
```

## Requirements

- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/) for dependency management
- A Telegram bot token and a chat ID

## Setup

### 1. Clone and install

```bash
git clone https://github.com/lukatsotskolauri/Job_Scraper.git
cd Job_Scraper
uv sync
```

### 2. Create a Telegram bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram and send `/newbot`.
2. Follow the prompts and copy the **bot token**.

### 3. Get the chat ID

- **Public channel:** use the username with the `@`, for example `@my_channel`. This is the real username from the `t.me/...` link, not the display name.
- **Private channel or group:** use the numeric ID, which starts with `-100` for channels (for example `-1001234567890`).
  1. Add the bot to the channel as an **administrator** with the **Post Messages** permission.
  2. Post any message in the channel.
  3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the number from `"chat":{"id": ...}`.

To verify the value works:

```bash
curl "https://api.telegram.org/bot<TOKEN>/getChat?chat_id=<CHAT_ID>"
```

### 4. Configure

Create a `.env` file in the project root:

```env
TELEGRAM_BOT_TOKEN=123456:your-bot-token
TELEGRAM_CHAT_ID=@your_channel_or_-100xxxxxxxxxx

# Optional (defaults shown in the table below)
IT_CATEGORY_ID=6
MAX_PAGES=3
JOB_LIMIT=10
REQUEST_TIMEOUT=10
TIMESTAMP_FORMAT=%d/%m/%Y
EXCLUDE_KEYWORDS=senior,.net,Java,UX/UI,PHP
```

Never commit `.env`. It is already listed in `.gitignore`.

### 5. Run

```bash
uv run python jobsge.py
```

New listings are printed in the terminal and sent to Telegram. Run it a second time and it should report `0 new listing(s)`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | none | Bot token from @BotFather (required) |
| `TELEGRAM_CHAT_ID` | none | Channel, group, or user ID to send to (required) |
| `IT_CATEGORY_ID` | `6` | jobs.ge category ID |
| `MAX_PAGES` | `3` | Number of listing pages to scrape |
| `JOB_LIMIT` | `15` | Maximum number of listings per run |
| `REQUEST_TIMEOUT` | `15` | HTTP timeout in seconds |
| `TIMESTAMP_FORMAT` | `%d/%m/%Y` | Date format shown in messages |
| `EXCLUDE_KEYWORDS` | `senior,.net,Java,UX/UI,PHP` | Comma-separated words; listings with these in the title are skipped |

## Automation with GitHub Actions

The workflow in `.github/workflows/scrape.yml` runs the scraper every day at 05:00 UTC (09:00 in Tbilisi) and commits the updated `seen_jobs.json` back to the repo so state persists between runs.

### Setup

1. Push the project to your own GitHub repository (private is recommended).
2. Go to **Settings → Secrets and variables → Actions** and add two repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. Go to **Settings → Actions → General → Workflow permissions** and select **Read and write permissions**.
4. Open the **Actions** tab, choose **Jobs scraper**, and click **Run workflow** to test.

### Workflow file

```yaml
name: Jobs scraper

on:
  schedule:
    - cron: "0 5 * * *"   # 05:00 UTC = 09:00 Tbilisi
  workflow_dispatch:       # manual run button

permissions:
  contents: write

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5

      - name: Run scraper
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          IT_CATEGORY_ID: "6"
          MAX_PAGES: "3"
          JOB_LIMIT: "10"
          REQUEST_TIMEOUT: "10"
          TIMESTAMP_FORMAT: "%d/%m/%Y"
          EXCLUDE_KEYWORDS: "senior,.net,Java,UX/UI,PHP"
        run: uv run python jobsge.py

      - name: Save seen jobs
        run: |
          git config user.name "github-actions"
          git config user.email "github-actions@users.noreply.github.com"
          git add -f seen_jobs.json
          git diff --cached --quiet || git commit -m "Update seen jobs"
          git push
```

Notes:

- GitHub cron times are always in **UTC**. Tbilisi is UTC+4, so subtract 4 hours from your local time.
- Scheduled runs can start a few minutes late.
- The workflow commits to the repo daily, so run `git pull` before pushing from your own machine.
- Keep the bot token and chat ID in **Secrets**. Plain settings like `MAX_PAGES` can stay in the workflow file.

### Alternative: run locally on a schedule

**Linux or macOS (cron):**

```bash
crontab -e
# every day at 09:00
0 9 * * * cd /path/to/Job_Scraper && uv run python jobsge.py >> cron.log 2>&1
```

**Windows (Task Scheduler):**

```powershell
$dir = "C:\path\to\Job_Scraper"
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
  -Argument "/c uv run python jobsge.py >> cron.log 2>&1" `
  -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At 9am
Register-ScheduledTask -TaskName "JobsGeScraper" -Action $action -Trigger $trigger
```

A local schedule only runs while the computer is on.

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| `Telegram API returned HTTP 400: chat not found` | Wrong `TELEGRAM_CHAT_ID`, or the bot is not an admin of the channel. Use the real `@username` or the `-100...` ID. |
| `HTTP 401 Unauthorized` | Wrong or missing bot token. |
| `0 new listing(s)` every time | Everything scraped is already in `seen_jobs.json`. Delete or edit the file to resend. |
| `Health check failed` | jobs.ge is unreachable, blocked the request, or changed its layout. |
| Workflow fails on "Save seen jobs" | Enable **Read and write permissions** for workflows in the repo settings. |
| `git push` is rejected | The workflow committed in the meantime. Run `git pull --rebase`, then push again. |
| `JSONDecodeError` on `seen_jobs.json` | The file is empty or corrupt. Replace its contents with `[]`. |

## Security

- Never commit `.env` or paste your bot token anywhere public. If a token leaks, revoke it with `/revoke` in @BotFather.
- Keep the repository private if it contains personal settings.

## Disclaimer

This project scrapes a public website for personal use. Respect jobs.ge's terms of use and keep the request rate low.
