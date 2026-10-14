<h1 align="center">
    AgentVision
    <br>
    <small>An AI agent that reads Link-in-bio web pages the way a person does</small>
</h1>

<p align="center">
    <img alt="Python" src="https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white">
    <img alt="Selenium" src="https://img.shields.io/badge/Selenium-Chrome-43B02A?logo=selenium&logoColor=white">
    <img alt="Gemini" src="https://img.shields.io/badge/Gemini-API-8E75B2?logo=googlegemini&logoColor=white">
    <img alt="pandas" src="https://img.shields.io/badge/pandas-CSV-150458?logo=pandas&logoColor=white">
</p>

<p align="center">
    <a href="#how-it-works"><strong>How it works</strong></a>
    &middot;
    <a href="#key-features"><strong>Key features</strong></a>
    &middot;
    <a href="#installation"><strong>Installation</strong></a>
    &middot;
    <a href="#getting-started"><strong>Getting started</strong></a>
    &middot;
    <a href="#limits"><strong>Limits</strong></a>
</p>

AgentVision takes a list of URLs and works out if each page links to a set of platforms you choose. It opens every page in a headless Chrome browser. Gemini looks at a screenshot and the page text, then tells the script what to click.

I built it for pages where normal scraping falls short. Some hide their links behind age gates or pop-ups. Others send you through a link-in-bio page like Linktree, so the real link is a click or two away.

```python
TARGET_DOMAINS = ["YOUR_TARGET_DOMAIN_1.com"]
TARGET_PLATFORM_NAMES = ["YOUR_PLATFORM_1"]

# Then run it against a CSV of URLs
# python agentvision.py
```

---

## How it works

The script reads your CSV and skips any rows already in the output file. So you can stop it halfway and pick up where you left off.

For each URL it starts a fresh Chrome session through a random proxy from your list. It takes a screenshot and asks Gemini if anything is blocking the page. If there's an age confirmation button, the script clicks it. If there's a date of birth form, it fills it in.

Next it sends the screenshot and the page text to Gemini. Gemini replies in JSON and says if a target link is on the page. If it can't see one directly, it names the button most likely to lead there. The script clicks that button and follows any new tab that opens. If it lands on a link-in-bio page, it scans that page too.

Each result goes into the output CSV straight away. The result is Yes, No or Error.

## Key features

### Vision based page reading
Gemini gets a screenshot as well as the text. That means it can spot buttons that are hard to find in the HTML, like low contrast text or links styled as images.

### Gate handling
Age confirmation screens and date of birth forms get handled before the main scan. The script works out which one it's facing from the screenshot.

### Link-in-bio follow through
When a click lands on Linktree, Beacons, Carrd or similar, the script runs a second scan on that page instead of stopping.

### Crash safe output
Results are written one row at a time. If the script dies, you lose nothing that's already been checked.

### Retry logic
Gemini rate limits trigger a wait that doubles each time, starting at 20 seconds. Pages that time out get pushed to the back of the queue and tried once more at the end.

### Proxy rotation
Every page load picks a proxy at random from your list. That spreads the traffic across addresses.

## Installation

You'll need Python 3, Google Chrome and a Gemini API key.

```bash
pip install pandas pillow google-genai selenium webdriver-manager
```

## Getting started

Open `agentvision.py` and fill in the config block at the top.

```python
API_KEY = "gemini_API_key"
INPUT_FILE = "input_file.csv"
OUTPUT_FILE = "output_file.csv"

PROXIES = [
    "http://HOST:PORT",
]

TARGET_DOMAINS = ["YOUR_TARGET_DOMAIN_1.com"]
TARGET_PLATFORM_NAMES = ["YOUR_PLATFORM_1"]
```

> [!NOTE]
> Proxies are written as `http://HOST:PORT`. Chrome won't take a username and password in this setting, so use proxies that let you whitelist your IP. Leave the list empty to run without proxies.

Your input CSV needs a `url` column and a `username` column. The `followers` and `following` columns are optional and get copied across.

```
username,url,followers,following
example_user,https://example.com/profile,1200,300
```

Then run it.

```bash
python agentvision.py
```

The output looks like this.

```
username,url,followers,following,target_link_found,error_note
example_user,https://example.com/profile,1200,300,Yes,
```

## Limits

Every page uses at least two Gemini calls, so big runs cost money and take time. On link-in-bio pages, any button the model flags counts as a Yes, which means some false positives. The date of birth filler assumes the fields go day, month, year. It won't work on sites that order them differently.

---

<div align="center"><small>Built by Seyna</small></div>
