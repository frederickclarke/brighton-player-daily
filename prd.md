# Brighton Player Daily - Game PRD Context

## Project Overview
**Game Name:** Brighton Player Daily

**Description:** A daily web-based guessing game for fans of Brighton and Hove Albion football club. Players guess which player from Brighton's recent history is featured each day by receiving progressive clues. Similar to Wordle but focused on Brighton FC players.

**Target Platform:** Web app, optimized for mobile browsers

---

## Core Game Mechanics

### Game Flow
- **One game per day** - strictly "today only" like Wordle (MVP scope)
- **No backlog gameplay** - users cannot play previous days' puzzles
- **Player selection** - randomly chosen from ~185 historical Brighton players
- **No repeats** - system avoids repeating the same player for at least 4 months

### Clue & Scoring System

#### Difficulty Tiers (Progressive Revelation)
Players see clues in order of progressive difficulty (hardest to easiest):

| Tier | Stars | Clue Type | Examples |
|------|-------|-----------|----------|
| **Tier 1** | 5 stars | Birth date only | "Born on January 15, 1985" |
| **Tier 2** | 4 stars | Birth place only | "Born in Liverpool, England" |
| **Tier 3** | 3 stars | League appearances count | "Made 156 appearances for Brighton" |
| **Tier 4** | 2 stars | Position-based clues | "This player was a defender" |
| **Tier 5** | 1 star | Combination clues | "Born in Liverpool, England on January 15, 1985" or "Joined Brighton from Manchester United and scored 12 goals" |

#### Additional Single-Data Clues
- Number of league goals scored for Brighton
- Number of spells at Brighton (career returns)
- Previous team (if not youth academy)
- Next team (if not retirement)

#### Clue Template Constraints
- **Excluded templates** - Do not use previous/next team clues if player joined from youth academy or retired at the club
- **Flexible clues** - Can combine any data points for more complex clues at lower difficulties (Tier 5)
- **Predefined templates** - Use predetermined clue patterns rather than intelligent selection (MVP simplicity)

### Guessing Mechanism
- **Free text input** with two fields: First Name and Last Name
- **Letter count visibility** - Users see how many letters are in each name (like Wordle)
- **Spelling precision** - No spell-check or autocomplete; users must match exact spelling
- **Crossword-like experience** - Users work out first and last names based on letter counts and clue context

### Star Tracking
- **Cumulative score** - Tracks total stars earned across all played days
- **Current streak** - Number of consecutive days player correctly guessed
- **Longest streak** - Records best consecutive streak

### Sharing
- **Format:** "Brighton Player Daily - 4 out of 5 ⭐⭐⭐⭐" or similar
- **Scope (MVP):** Star count sharing only (no leaderboards or friend comparisons for MVP)

---

## Player Data Source

### CSV Dataset
- **Total players:** ~185 historical Brighton FC players
- **Data points per player:**
  - Name (first and last)
  - Date of birth
  - Place of birth
  - Position
  - League appearances for Brighton
  - League goals scored for Brighton
  - Number of spells at club
  - Previous team (first spell)
  - Next team (after first spell)
  - Years playing for Brighton

### Data Handling
- **Backend storage** - CSV data stored server-side (not embedded in app)
- **Daily selection** - Backend selects random player daily, prevents repeats
- **API delivery** - Frontend queries backend for clues and player validation

---

## Technical Architecture

### Technology Stack
- **Backend:** Python
- **Frontend:** JavaScript
- **Data source:** CSV file queried via Python backend
- **Data exposure:** CSV never exposed to frontend; only processed data returned via API

### Key Technical Features
- Daily player randomization with 4-month no-repeat window
- Clue tier management system
- Input validation for player name guesses
- Star calculation logic based on clues revealed
- Streak tracking logic

---

## User Interface
- **Design inspiration:** Similar to Wordle
- **Letter visibility:** Show letter count for first name and last name separately
- **Minimal design** - Not overly complex
- **Mobile-first** - Optimized for mobile browsers

---

## MVP Scope & Future Enhancements

### MVP Includes
- Daily game with progressive clue system
- Star tracking (cumulative and streaks)
- Free text name guessing
- Basic sharing (star counts)
- Python backend + JavaScript frontend

### NOT in MVP (Future Enhancements)
- Playing previous days' puzzles
- Leaderboards
- Friend comparisons
- Advanced clue selection algorithms
- More complex UI features

---

## Key Product Decisions (From Clarifications)

1. **Clue difficulty tiers** - Strictly ordered from hardest (Tier 1) to easiest (Tier 5) rather than randomized
2. **No intelligent clue selection** - Use predefined templates to keep MVP simple
3. **Combination clues** - Allow mixing data points for Tier 5 (easiest) level
4. **Position clues repositioned** - Moved to Tier 4 as they're moderately revealing
5. **Birth date as hardest clue** - Single birth date in Tier 1 is most challenging
6. **Strict daily model** - No backlog or historical gameplay for MVP
7. **No repeat players** - 4-month window to avoid repetition with ~160-player pool
8. **Backend-driven data** - Python backend manages CSV; no client-side exposure

---

## Game Examples

### Example Gameplay Scenario
**Player:** John Smith (born 1985, Liverpool, Defender, 156 apps, 5 goals, 2 spells at Brighton)

**Clue Progression:**
1. (5 stars) - "Born on January 15, 1985"
2. (4 stars) - "Born in Liverpool, England"
3. (3 stars) - "Made 156 appearances for Brighton"
4. (2 stars) - "This player was a defender"
5. (1 star) - "Born in Liverpool, England on January 15, 1985; scored 5 goals for Brighton"

User guesses after clue 2 -> Gets 4 stars -> Shares: "Brighton Player Daily - 4/5"

---

## Success Metrics (Baseline)
- Daily active users (DAU)
- Win rate (percentage of games won per day)
- Average stars earned per game
- Streak retention (users maintaining 7+ day streaks)
- Share rate (social sharing adoption)

---

## Implementation Notes
- Backend should manage a predictable random seed for fair daily player selection
- Consider timezone handling for daily reset
- Input validation must handle various name formats (spaces, hyphens, etc.)
- Responsive design essential for mobile-first audience