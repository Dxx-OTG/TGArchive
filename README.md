# 🗄️ TGArchive — Telegram Group OSINT Toolkit

> 🇮🇹 Versione italiana: [README.it.md](README.it.md)

> Telegram bot + scraping toolkit to archive and search the members, message senders and shared links of Telegram groups.
> Published for research and educational purposes: it wires a [Telethon](https://docs.telethon.dev/) scraper, an [aiogram](https://docs.aiogram.dev/) bot and [PostgreSQL](https://www.postgresql.org/) into a single `CSV → database` pipeline.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)
![License](https://img.shields.io/badge/license-PolyForm--Noncommercial--1.0.0-blue)

---

## ⚠️ Notes (read first)

- **Private bot.** It replies only to the Telegram IDs/usernames listed in `ADMIN_USER_IDS`; every other sender is rejected automatically, including on `/start`.
- **Scraping involves real personal data** (usernames, user IDs, sometimes messages). Complying with [Telegram's Terms of Service](https://telegram.org/tos) and the applicable privacy law (e.g. the GDPR in the EU) is the responsibility of whoever runs it.
- **Secrets stay local.** `.env` (token, credentials) and `*.session` files (authenticated Telegram login) are excluded by [.gitignore](.gitignore) and are not part of the repository. The tracked template is [`.env.example`](.env.example).
- `Blacklist.py` hides specific people/groups/channels **everywhere** — every list, search, count (including Stats and the per-group counts), link and favorite, in both the bot and the CLI, as if they didn't exist.

---

## 📑 Table of contents

**Install & run**
1. [Prerequisites](#-prerequisites)
2. [Dependencies](#-dependencies)
3. [Setup](#-setup)
4. [`.env` configuration](#-env-configuration)
5. [Menu](#-menu)
6. [Transfer to another PC](#-transfer-to-another-pc)

**How it works**

7. [What it does and how to use it](#-what-it-does-and-how-to-use-it)
8. [Project structure](#-project-structure)

**Reference**

9. [Recommendations](#-recommendations)
10. [Telegram rate limits (FloodWait)](#-telegram-rate-limits-floodwait)
11. [Troubleshooting](#-troubleshooting)
12. [License](#-license)

---

## 🔧 Prerequisites

| Requirement | Notes |
|---|---|
| **Windows 10 / 11** | Automation scripts are `.bat` + PowerShell. |
| **Python 3.10+** | Must be in `PATH`. Check with `python --version`. [Download](https://www.python.org/downloads/) (tick *"Add Python to PATH"*). `TGArchive.bat` checks this automatically and tells you if it's missing or too old. |
| **Git** | To clone the repo. [Download](https://git-scm.com/download/win). |
| **winget** | Used to auto-install PostgreSQL. Already present on up-to-date Windows 10/11 (it's "App Installer"). |
| **A Telegram account** | To create the bot and to authenticate scraping. |
| **Bot token** | From [@BotFather](https://t.me/BotFather): `/newbot`. |
| **API ID + API Hash** | From [my.telegram.org](https://my.telegram.org) → *API development tools* (step-by-step under [`.env` configuration](#-env-configuration)). |

> PostgreSQL is installed automatically by **Setup Database** (via winget) — no manual install needed.

---

## 📦 Dependencies

Python packages (in [`requirements.txt`](requirements.txt), installed automatically into a virtual environment on first run):

```
Telethon>=1.43      # scraping (user account)
aiogram>=3.13       # Telegram bot
asyncpg>=0.30       # async PostgreSQL driver
python-dotenv>=1.0  # reads the .env file
watchfiles>=0.21    # instant CSV-folder change detection for the bot's import watcher
```

Plus **PostgreSQL 17** (installed by **Setup Database**).

---

## 🚀 Setup

Everything runs through **`TGArchive.bat`**, the single entry point. It detects what is missing and guides through each step — creating `.env`, filling it in, installing the database — then shows the full menu once everything is ready.

### 1. Clone

```bash
git clone https://github.com/Dxx-OTG/TGArchive.git
cd TGArchive
TGArchive.bat
```

### 2. Run `TGArchive.bat`

Double-click **`TGArchive.bat`** (or run it from the terminal as shown above) and follow the on-screen menu:

1. On first run it creates `.env` from the template and opens it in a text editor (Notepad, or a fallback if Notepad isn't available). Fill in `BOT_TOKEN`, `TG_API_ID`, `TG_API_HASH` and `ADMIN_USER_IDS` (see [`.env` configuration](#-env-configuration)).
2. It then offers **Setup Database**, which installs PostgreSQL 17, creates the `scraper` database, applies the schema from `db\migrations\`, and writes the `DATABASE_URL_*` lines into `.env`. It reopens itself as administrator when needed. It always states plainly what it found (PostgreSQL not installed / already installed and working / installed but unreachable) instead of guessing silently. It only ever creates an **empty** schema — your scraped data lives in the `output\` CSVs and is (re-)imported into the database the first time you start the bot or the CLI, so a reset never loses anything.
3. Once the database is ready, the menu flags it if the Telegram scraping account isn't authenticated yet. Choose **🔑 Telegram Login** to sign in right from the menu (phone number + OTP, plus 2FA password if enabled) — no need to open the CLI — so scraping works from the bot's hub/card too. (The CLI also logs you in the first time you run a scrape.)
4. With `.env`, the database, and the Telethon login all ready, the full menu appears — choose **Start The Bot**.

No script in `scripts\` needs to be launched by hand: `TGArchive.bat` runs them all with the right checks. The menu runs on the system Python (standard library only), so it never holds `.venv` open, and before showing the full menu it probes the database (not just "is the port open") so it can tell apart "not set up", "unreachable", "wrong credentials" and "schema missing/broken", each with its own explanation.

---

## 🔐 `.env` configuration

| Variable | Value |
|---|---|
| `BOT_TOKEN` | The token [@BotFather](https://t.me/BotFather) returns after `/newbot`. |
| `TG_API_ID` | The numeric `api_id` from [my.telegram.org](https://my.telegram.org). |
| `TG_API_HASH` | The `api_hash` from [my.telegram.org](https://my.telegram.org). |
| `TG_SESSION_NAME` | Telethon session file name. Leave as-is (e.g. `telegram_session`). |
| `ADMIN_USER_IDS` | **Who can use the bot.** Accepts usernames (with or without `@`) **or** numeric IDs, mixable, comma-separated. E.g. `@johndoe` or `123456789` or `@johndoe,987654321`. |
| `DATABASE_URL_BOT` | Written by **Setup Database** — do not edit by hand. |
| `DATABASE_URL_COLLECTOR` | Written by **Setup Database** — do not edit by hand. |

> **Getting `TG_API_ID` and `TG_API_HASH`:** sign in at [my.telegram.org](https://my.telegram.org) with your phone number, open **API development tools**, and fill in the *Create new application* form — **App title** and **Short name** are required (any value), platform/URL/description don't matter. Click **Create application**: the page reloads and shows your **App api_id** (a number) and **App api_hash** (a long hex string) — copy them into `.env`. You do this once; the same values keep working, and revisiting the page shows the existing app. Keep the `api_hash` private (it's a secret, like a password).

> To find a Telegram user ID: leave `ADMIN_USER_IDS` empty, start the bot, and send it `/start`. The request is rejected, but the bot console prints the sender's `tg_user_id`. Add it to `ADMIN_USER_IDS` and restart the bot.

---

## 📋 Menu

**`TGArchive.bat`** is the single entry point. Its menu:

- 🤖 **Start The Bot** — runs the bot in a separate window; it stays open while in use.
- 🛠️ **CLI** — a terminal mirror of the bot: the same commands (search, browse, stats, export, delete, favorites, scrape) on the same database.
- 🔑 **Telegram Login / Switch Account** — authenticate the scraping account (phone + OTP, plus 2FA) straight from the menu, without opening the CLI. If an account is already logged in, the same option offers to **switch account**: it logs the old one out, deletes its `.session` file, and logs the new one in. The label changes to reflect the state (Login when logged out, Switch when logged in).
- 🗄️ **Setup Database** — install or repair the database (shown until it is ready).
- 📦 **Prepare Transfer To New PC** — package the folder for another machine.
- 🧹 **Clean Logs/History** — wipe the local `log\` files and, separately (each after its own y/n), the two caches: the reachability-check results and the 24h resolved-link identities (reopened cards). No scraped data is touched. Pagination/card tokens stay in memory and reset on a bot restart.
- ⚙️ **Open `.env` in a text editor** — edit the configuration directly (Notepad, with automatic fallbacks if it isn't available).

---

## 🔄 Transfer to another PC

To move a working install while keeping the archive:

**On the old PC:**
1. *TGArchive.bat* → **Prepare Transfer To New PC**. This clears the `DATABASE_URL_*` lines in `.env` and removes `.venv`, the `__pycache__` folders and the local `log\*.log` files. Your scraped data travels as the `output\` CSVs — there's no DB dump. (Close the bot/scraping windows first if open, so `.venv` is not locked.)
2. Copy the whole folder to the new PC. It carries `.env` and `.session`, which are secrets — move it over a trusted channel.

**On the new PC:**
3. Run **`TGArchive.bat`**. It rebuilds `.venv` for this machine (a virtualenv cannot be moved between PCs), then runs Setup Database, which creates an empty `scraper` database. Start the bot: it imports your `output\` CSVs into the fresh database on first launch, rebuilding the full archive.

---

## 📖 What it does and how to use it

TGArchive archives and searches the **members, message senders and shared links** of Telegram groups and channels. You drive it from a command-free **Telegram bot** (the main way) or an equivalent **terminal CLI** — both work on the same archive.

### Get going

1. **Log in once** (if you haven't): the menu's **🔑 Telegram Login** signs the scraping account in (phone + OTP, plus 2FA if enabled), saved in the `.session` file — or just run any CLI scrape and it asks you then. The bot itself never asks for a phone number.
2. **Collect.** From the bot: `/start` → 🤖 Scrape, or paste a group/channel and use its card. From the CLI: `scrapemembers` / `scrapemessages` / `scrapelinks <group|channel> [limit]`. The target is a public `@username`/`t.me` link or a private `t.me/+…` invite the account has already joined.
3. **Explore.** Browse, search, favorite, check and export — from the bot's hub or the CLI's commands. Both read the same database, so they always agree.

### The bot (command-free)

**`/start` is the only command** — everything else happens in the menu it opens, or by pasting a reference. Two ways in:

- **`/start` → menu hub.** Six sections, all navigated **in place** (the same message is edited, no new messages):
  - **🤖 Scrape** — a group's members, message senders, or shared links (pick how many messages to read; re-scraping merges, keeping old data).
  - **🔎 Search** — **users**, **bots**, **groups**, **channels** or **links** (type any part of a name, `@username`, id or t.me link).
  - **🗂 Browse** — everything you've collected, by category (groups, channels, users, bots, links), with member/link counts.
  - **📊 Data** — **Stats**; **Check** (reachability: Check All + Check Links); **Export All** (zip); **Delete All**.
  - **⭐ Favorites** — your saved entities.
  - **ℹ️ Help** — an in-app guide, in **English or Italian** (one tap toggles the language), with a link to this full guide.
- **Paste a `@username` / `t.me` link** (or forward a channel post) → an **action card** for that entity: scrape, check, favorite, view members/links, export, delete, or **add it to the archive without scraping**. A private group's invite link opens its card too (favorite/check/add work even before the scraping account joins; only Scrape needs it to be a member).

**Everything is a card.** Tapping any name or link in any list (search results, members, a group's links, favorites, stats) opens that entity's card in the same message — only a card's own title links out to Telegram. Lists paginate (◀ / ▶) and sort alphabetically (users without a username last).

### The CLI (terminal mirror)

A plain-text mirror of the bot on the **same database and logic** — a terminal has no buttons, so it uses typed commands: `searchusers`/`searchbots`/`searchgroups`/`searchchannels`/`searchlinks`, `users`, `bots`, `groups`, `channels`, `members`, `links`, `stats`, `export`, `delete`, `favorites`, `check [all|links|prune]`, `scrape*`, `card`. Pasting a reference opens its card here too.

### Good to know

- **Scraping is additive** — re-scraping a group only adds new members/links, it never removes what's already there. Only links to a real user/channel/group are kept, and a link source can be a channel, not just a group.
- **Add without scraping** puts a group/channel/user/bot into the archive as a placeholder you can favorite and check.
- **Bots** are told apart from users automatically (a bot's `@username` ends in *bot*).
- **Reachability check** flags entities ✅ reachable / ❌ gone-or-banned / ⚠️ unverified and can drop the dead ones. It's paced and cached 24h to stay gentle with Telegram — see [FloodWait](#-telegram-rate-limits-floodwait).
- **Your data is the `output\` folder** (CSV files). The database is just a fast index rebuilt from it on every start — disposable — so `output\` is the real archive: **back it up yourself**. The bot and the CLI can't run at the same time (they share one Telegram account), so close one before opening the other.

---

## 📁 Project structure

```
.
├── TGArchive.bat          # single entry point (the menu)
├── .env.example           # config template (copy to .env)
├── Blacklist.py           # people/groups/channels to hide everywhere
├── requirements.txt
├── bot/                   # Telegram bot (aiogram), private (admin-only gate)
│   ├── main.py            # startup, middlewares, polling
│   ├── card.py, card_view.py     # the entity "action card": logic + rendering
│   ├── csv_watcher.py     # imports the CSVs into the DB, live (watchfiles)
│   ├── telethon_client.py # the shared scraping client, bot side
│   ├── i18n.py            # all user-facing strings (incl. the EN/IT in-app help)
│   ├── middlewares/       # admin-only gate, rate limit
│   └── modules/           # routers (start hub, card, check, admin) + helpers (search, groups, stats, scrape)
├── CLI/                   # terminal mirror of the bot (same DB, same logic)
│   ├── Menu.py            # REPL: connects DB + Telethon, syncs CSVs, dispatches commands
│   ├── commands.py        # command handlers (reuse db.queries; plain-text rendering)
│   └── Scrape.py, Messages.py, ExtractLinks.py   # the three scrapers
├── collectors/            # shared backend: Telethon client + lock, login, entity resolve,
│                          #   reachability check, CSV -> DB import, pacing/throttle
├── db/                    # PostgreSQL: pool, queries, blacklist, cleanup
│   └── migrations/        # 0001_init.sql (the full schema)
└── scripts/               # .bat + PowerShell: setup DB, transfer, login, clean logs, menu
    └── _bootstrap_venv.bat # shared venv/dependency bootstrap, called by every script that needs it
```

---

## 💡 Recommendations

- **Protect the scraping account.** Everything live (resolving a link, checking, scraping) is done by the one account in `telegram.session`. Heavy or bursty use can get it **rate-limited or restricted by Telegram** — see [FloodWait](#-telegram-rate-limits-floodwait) below. If you scrape/check a lot, use a **dedicated (spare) account**, not your personal one.
- **Don't spam.** Avoid pasting dozens of brand-new links back-to-back, and don't force a full re-check of a big archive at once — **check in batches** (Check, then ⏭ Skip recent later). The bot already paces itself and caps each run, but restraint keeps you well clear of limits.
- **If Telegram rate-limits you (a FloodWait):** just wait the time the bot shows and retry — it's a temporary cooldown, nothing is lost. A spare account sidesteps it immediately (its cooldown is separate); to make the bot gentler still, raise the pacing in `collectors/throttle.py`.
- **Search/Browse/Stats are free.** They read the database only — zero Telegram calls, so use them freely even while the account is cooling down from a FloodWait.
- **One job at a time.** The bot and the CLI share the same account/session and a lock stops them running together — close one before using the other.
- **Re-scraping is additive** — it only adds new members/links, never drops what you already have. Scrape the same group again later to top it up.
- **Hide people/groups with `Blacklist.py`** — listed entries vanish from every list, search, count, link and favorite (read at startup, so restart after editing).
- **`output\` is your archive — back it up yourself.** The database is disposable (rebuilt from `output\` on every start), so there's no DB backup: the CSVs in `output\` (plus `.env`/`.session`) are the only thing that can't be regenerated. Copy that folder somewhere safe periodically if the data matters, and use **Prepare Transfer** before moving to another PC.

---

## ⏳ Telegram rate limits (FloodWait)

**What it is.** The one account in `telegram.session` does every live action (resolving a pasted link, checking reachability, scraping). When it makes too many calls too fast — above all **entity resolves** (`ResolveUsername` / `CheckChatInvite`, which Telegram limits hardest) — Telegram replies "wait N seconds": a *FloodWait*. It's a temporary, per-account cooldown to make you slow down — **not a ban, and nothing is lost.**

**What triggers it here.** Mostly **Check** on a big archive (each target is one resolve, and hundreds of never-seen entities in a row is exactly what Telegram throttles) and rapidly pasting many brand-new links. A single scrape is fine — it's mostly paced reads of one chat.

**What you'll see.** The bot tells you, with the wait time, e.g. *"⏳ Telegram is rate-limiting this account (FloodWait) — try again in about 1h 15m."* A check that hits it stops early and **saves the partial results**. Just wait it out, then retry — see [Recommendations](#-recommendations) above for how to avoid it.

---

## 🩹 Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `BOT_TOKEN missing in .env` | `.env` is not created or not filled in. See [configuration](#-env-configuration). |
| Bot does not reply to `/start` | The sender's ID/username is not in `ADMIN_USER_IDS`. The console prints the sender's ID. |
| `Conflict: terminated by other getUpdates request` | The same bot (same `BOT_TOKEN`) is already running elsewhere. Close the other instance. |
| Database broken / lost credentials | Run **Setup Database** from the menu. It repairs/resets the `scraper` database **without reinstalling PostgreSQL**: it reuses the working credentials if `.env` still has them, otherwise recovers access in place. This is also the typical fallout of running Setup Database from more than one copy of this folder - PostgreSQL is one shared service, so only the most recent copy's `.env` stays valid. |
| Menu or bot console says database "reachable, but credentials don't work" | Same fix as above (Setup Database). The menu checks real credentials before you even try to start the bot; if you bypass it and launch `start_bot.bat` directly, the bot's own startup check catches the same problem with the same message. |
| Menu or bot console says database "schema missing or broken" | The connection and credentials are fine but the expected tables aren't - run **Setup Database** to reapply the schema (it re-creates it empty; your `output\` CSVs re-import on the next start, so no data is lost). Same check exists on both the menu and the bot's own startup. |
| Setup Database says "found a different installation" and stops | A PostgreSQL version other than 17 is already on this PC (different Windows service name) - this project only manages PostgreSQL 17. Uninstall the other version manually (Settings > Apps), then run Setup Database again. |
| `winget not available` during setup | Install "App Installer" from the Microsoft Store, then run Setup Database again. |
| Changed `Blacklist.py` / `.env` but nothing changed | Both are read only at startup: restart the bot (or the CLI). |
| Scraping replies "Scraping unavailable" | The Telethon session isn't authenticated yet: run **🔑 Telegram Login** from the menu (phone + OTP) — or open the **CLI** and run any scrape command once — then restart the bot. |
| "another TGArchive process is already connected" | Expected, not a bug: the CLI and the bot share one `.session` file and an automatic lock stops them from running at the same time. Close one before using the other. |
| CLI says "DATABASE_URL_BOT is missing" / "schema missing or broken" | The CLI uses the same database as the bot. Run **Setup Database** first, then reopen the CLI. |

---

## 📜 License

[PolyForm Noncommercial 1.0.0](LICENSE). Personal, educational and research use only - **not licensed for commercial use or resale**. Provided "as is", with no warranty of any kind; lawful use, compliant with all applicable laws and terms of service, is the responsibility of the user.
