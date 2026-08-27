# Jobs.ge Scraper

A Python script that scrapes IT job listings from [jobs.ge](https://jobs.ge/), filters them by keywords, and sends notifications via Telegram when new jobs are posted.

## Installation

### Prerequisites
- Python 3.14+
- uv

### Setup with uv
```bash
# Clone the repo
git clone https://github.com/nikol1313/jobs.ge-scraper
cd jobsscraper

# Install dependencies
uv sync
```

## Configuration

Create a `.env` file in the project root with the following variables:

```env
# Telegram Configuration
TELEGRAM_BOT_TOKEN="your_bot_token_here"
TELEGRAM_CHAT_ID="your_chat_id_here"

# Scraping Configuration
IT_CATEGORY_ID=6          # IT jobs category ID
MAX_PAGES=3              # Number of pages to scrape
JOB_LIMIT=10            # Maximum jobs to process
REQUEST_TIMEOUT=10
TIMESTAMP_FORMAT="%d/%m/%Y"

# Filtering
EXCLUDE_KEYWORDS="senior,.net,Java,UX/UI,PHP"

```

## Usage

Run the script:

```bash
uv run python jobsge.py
```

## Output Files

- `seen_jobs.json` - Tracks IDs of seen jobs (for duplicate detection)
- `seen_jobs.csv` - CSV history of all discovered jobs with columns: job_id, title, url, timestamp

These files are automatically created and updated. They are excluded from git via `.gitignore`.

## Automation

To run the script automatically, set up a cron job:

```bash
# Edit crontab
crontab -e

# runs every 15 minutes
*/15 * * * * cd /home/nikol/jobsscraper && uv run python jobsge.py >> /home/nikol/jobsscraper/cron.log 2>&1
```

Or use systemd timer, GitHub Actions, or any other scheduler.
