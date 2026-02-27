# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Brighton Player Daily — a Wordle-style daily guessing game for Brighton & Hove Albion FC players (2002–2025). One player per day, progressive clues, star-based scoring. Built with Flask backend + vanilla JS frontend.

## Commands

```bash
# Run locally (starts on http://localhost:5002 with debug mode)
python app.py

# Install dependencies
pip install -r requirements.txt

# Production server (Fly.io uses this)
gunicorn --bind 0.0.0.0:8080 app:app

# Run tests (run before every deployment)
pytest test_app.py -v

# Deploy to Fly.io (use --depot=false if the default Depot builder hits 401 registry errors)
flyctl deploy --depot=false
```

## Architecture

**Single-file backend:** `app.py` — Flask app that loads `brighton_players.csv` into a pandas DataFrame at startup, serves the SPA, and exposes JSON API routes.

**Single-file frontend:** `templates/index.html` — ~1150 lines of HTML/JS/Tailwind CSS (CDN). All game logic, UI rendering, share modal, and stats (localStorage) live here. No build step.

**Data file:** `brighton_players.csv` — ~184 players with 22 columns (name, DOB, position, appearances, goals, transfer history, seasons, spells). This is the single source of truth for all player data.

### Key Backend Mechanics

- **Daily player selection:** Seeded RNG (`year*1000 + day_of_year`) picks a player deterministically. Selections cached in `recent_players.json` to prevent repeats within 30 days.
- **Clue system:** `build_clues()` generates clues from player data columns, tagged by fact type to avoid duplicates, shuffled deterministically.
- **Reveal Letter:** Frontend-only feature — reveals a random unrevealed letter in the player's name at the cost of 1 star. Uses the same `revealedClues` penalty pattern as the cryptic clue. Revealed letters are visually distinct (amber styling) and persist through incorrect guesses.
- **Gemini AI integration:** Optional — generates cryptic name-wordplay clues and player bios via `gemini-2.5-flash-lite`. Gracefully disabled if `GEMINI_API_KEY` is unset.

### API Routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Serve the game SPA |
| `/api/daily-challenge` | GET | Today's player (name lengths, first clue, player_id) |
| `/api/clues` | POST | Get next clue by index |
| `/api/guess` | POST | Validate a name guess |
| `/api/cryptic-clue` | POST | AI-generated name wordplay clue |
| `/api/player-bio` | POST | AI-generated player biography |
| `/api/config` | GET | Debug mode flag + player count |
| `/api/set-player` | POST | Debug only: override today's player |
| `/api/debug/recent-players` | GET | Debug only: view recent selections |
| `/api/debug/reset-recent` | GET | Debug only: clear selection cache |

### Environment Variables

- `GEMINI_API_KEY` — Required for AI features (cryptic clues, bios). Stored in `.env`.
- `FLASK_ENV=development` or `DEBUG=1` — Enables debug mode (player switcher, debug endpoints).

### Deployment

Fly.io (`fly.toml`): app `brighton-daily`, region `lhr`, port 8080, auto-scales to zero. Docker builds from `python:3.11-slim`.

**GitHub sync rule:** After every successful deploy to Fly.io, commit and push all deployed changes to `main` so the GitHub repo always reflects what is running in production.

### Testing Policy

- **Run tests before every deployment:** `pytest test_app.py -v` must pass with 0 failures.
- **Review test coverage with every change:** After implementing any feature or bug fix, review the existing test suite and add new tests to cover the changed behaviour. This includes backend logic changes (clue generation, player selection, guess validation) and any new API behaviour.
- **Test categories:** Data integrity, split_name, build_clues, recent players, get_daily_player, API routes, debug endpoints, Gemini routes, special character handling, clue logic, player selection filter.
- **What to test:** New backend logic, edge cases for special characters in player names, clue deduplication rules, and player selection filters. Frontend-only changes (CSS, localStorage) don't need backend tests but should be manually verified before deploy.

###  Session Management
- **Naming Rule:** At the start of every new task or significant pivot, proactively rename the current session using the `/rename` command.
- **Format:** Use `[Project-Name]: [Brief-Task-Description]` (e.g., `Brighton: CSV-Audit` or `Brighton: Fly-Deploy-Fix`).
- **Trigger:** Rename as soon as the "Plan" for a task is approved.
