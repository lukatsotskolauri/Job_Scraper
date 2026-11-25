# jobs.ge IT Job Scraper

A small Python script that scrapes the latest IT vacancies from [jobs.ge](https://jobs.ge), filters out the ones you don't want, and sends the new ones to a Telegram channel. It runs automatically twice a day (12:00 and 20:00 Tbilisi time) with GitHub Actions, so you don't need a server.

## Features

- Scrapes the IT category of jobs.ge (configurable number of pages)
- Remembers what it has already sent, so you never get the same job twice
- Sends new listings to a Telegram channel, group, or private chat, with a clickable title, the company and the application deadline
- Can send other jobs.ge categories to other chats with the same bot (see [Multiple chats and categories](#multiple-chats-and-categories))
- Saves the seen-job state only after Telegram succeeds, so a failed send is retried on the next run
- Runs twice a day on GitHub Actions for free

## How it works

1. A health check confirms jobs.ge is reachable and the page layout is still parseable.
2. For each configured category, the scraper reads the first `MAX_PAGES` pages.
3. Only listings posted in the last `MAX_AGE_DAYS` days are kept, so old listings never show up as new.
4. Listings whose IDs are not in that category's list in `seen_jobs.json` are treated as new. At most `JOB_LIMIT` of them are sent per run; any extra wait for the next run, so nothing is skipped on busy days.
5. New listings are sent to every chat assigned to that category.
6. Only after a successful send, the new IDs are saved to `seen_jobs.json` (and appended to `seen_jobs.csv`).

## Project structure

```
.
├── jobsge.py              # Entry point
├── jobs_scraper/
│   ├── config.py          # Settings, read from environment variables
│   ├── scraper.py         # Health check and page scraping
│   ├── filter.py          # Keeps only recently posted listings
│   ├── state.py           # Seen job IDs per category, stored in seen_jobs.json
│   ├── notification.py    # Telegram sending and CSV logging
│   └── models.py          # JobListing data model
├── seen_jobs.json         # IDs of jobs already sent, per category (committed by the workflow)
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
TELEGRAM_CHAT_ID=@your_channel_or_-100xxxxxxxxxx   # receives IT jobs

# Optional: other chats with their own category (chat_id:category_id, comma-separated)
CHAT_CATEGORIES=-1001234567890:3

# Optional (defaults shown in the table below)
IT_CATEGORY_ID=6
MAX_PAGES=3
JOB_LIMIT=10
REQUEST_TIMEOUT=10
TIMESTAMP_FORMAT=%d/%m/%Y
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
| `TELEGRAM_CHAT_ID` | none | Channel, group, or user ID that receives IT jobs |
| `CHAT_CATEGORIES` | none | Extra chats, each with its own category: `chat_id:category_id,chat_id:category_id` |
| `IT_CATEGORY_ID` | `6` | jobs.ge category ID used for `TELEGRAM_CHAT_ID` |
| `MAX_PAGES` | `3` | Number of listing pages to scrape |
| `JOB_LIMIT` | `15` | Maximum number of new listings sent per category per run; extra ones go out on the next run |
| `MAX_AGE_DAYS` | `3` | Only listings posted within this many days count as new |
| `REQUEST_TIMEOUT` | `15` | HTTP timeout in seconds |
| `TIMESTAMP_FORMAT` | `%d/%m/%Y` | Date format shown in messages |

At least one of `TELEGRAM_CHAT_ID` or `CHAT_CATEGORIES` must be set.

## Multiple chats and categories

One bot can post different job categories to different chats.

1. Find the category number: open the category on jobs.ge and look at `cid=` in the URL. For example, `https://www.jobs.ge/?page=1&q=&cid=3` is category `3`. (IT is `6`.) Other URL filters such as `lid` and `jid` are ignored.
2. Add the bot to the other chat and get its chat ID (see step 3 of Setup).
3. Set `CHAT_CATEGORIES` to `chat_id:category_id` pairs, separated by commas:

   ```env
   CHAT_CATEGORIES=-1001234567890:3,987654321:12
   ```

`TELEGRAM_CHAT_ID` keeps getting IT jobs. Alternatively, put your own chat in the list too (`<your_chat_id>:6,...`) and remove `TELEGRAM_CHAT_ID`.

Each category is scraped once, even if several chats share it, and keeps its own seen-job list. The first run for a new category sends the newest `JOB_LIMIT` listings and marks the rest of the recent ones as seen, then only new ones are sent. If one category fails, the others are still sent and saved, and the run is marked as failed.

## Automation with GitHub Actions

The workflow in `.github/workflows/scrape.yml` runs the scraper every day at 08:00 and 16:00 UTC (12:00 and 20:00 in Tbilisi) and commits the updated `seen_jobs.json` back to the repo so state persists between runs.

### Setup

1. Push the project to your own GitHub repository (private is recommended).
2. Go to **Settings → Secrets and variables → Actions** and add these repository secrets:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `CHAT_CATEGORIES` (optional, for extra chats)
3. Go to **Settings → Actions → General → Workflow permissions** and select **Read and write permissions**.
4. Open the **Actions** tab, choose **Jobs scraper**, and click **Run workflow** to test.

### Workflow file

```yaml
name: Jobs scraper

on:
  schedule:
    - cron: "0 8,16 * * *"   # 08:00 and 16:00 UTC = 12:00 and 20:00 Tbilisi
  workflow_dispatch:       # manual run button

permissions:
  contents: write

# Never run two scrapes at once, so they can't both push seen_jobs.json.
concurrency:
  group: scrape
  cancel-in-progress: false

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
          CHAT_CATEGORIES: ${{ secrets.CHAT_CATEGORIES }}
          IT_CATEGORY_ID: "6"
          MAX_PAGES: "3"
          JOB_LIMIT: "10"
          REQUEST_TIMEOUT: "10"
          TIMESTAMP_FORMAT: "%d/%m/%Y"
        run: uv run python jobsge.py

      - name: Save seen jobs
        if: success() || failure()   # keep progress from categories that succeeded
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
- The workflow commits to the repo after each run, so run `git pull` before pushing from your own machine.
- Keep the bot token and chat IDs in **Secrets**. Plain settings like `MAX_PAGES` can stay in the workflow file.

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
| `0 new listing(s)` every time | Everything scraped is already in `seen_jobs.json`. Delete that category's list from the file to resend. |
| `Invalid CHAT_CATEGORIES entry` | Each entry must be `chat_id:category_id`, separated by commas, for example `-1001234567890:3`. |
| `Health check failed` | jobs.ge is unreachable, blocked the request, or changed its layout. |
| Workflow fails on "Save seen jobs" | Enable **Read and write permissions** for workflows in the repo settings. |
| `git push` is rejected | The workflow committed in the meantime. Run `git pull --rebase`, then push again. |
| `seen_jobs.json` is empty or corrupt | The script logs a warning and starts fresh. To reset it by hand, replace its contents with `{}`. |

## Security

- Never commit `.env` or paste your bot token anywhere public. If a token leaks, revoke it with `/revoke` in @BotFather.
- Keep the repository private if it contains personal settings.

## Disclaimer

This project scrapes a public website for personal use. Respect jobs.ge's terms of use and keep the request rate low.
