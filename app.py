import os  # Import the os module for interacting with the operating system
import pandas as pd  # Import pandas for data handling
from datetime import datetime, timedelta  # Import datetime for working with dates
import google.generativeai as genai
from flask import Flask, jsonify, request, render_template  # Import Flask and related functions for web server
import random
from dotenv import load_dotenv
import json
import re

load_dotenv()

# --- Gemini Configuration ---
ADMIN_KEY = os.environ.get("ADMIN_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash-lite')
else:
    model = None
    print("WARNING: GEMINI_API_KEY is not set. AI features will be disabled.")

# Initialize Flask App
app = Flask(__name__)  # Create a new Flask web application
app.debug = os.environ.get('FLASK_ENV') == 'development' or os.environ.get('DEBUG') == '1' or app.debug

# Prevent browsers/CDNs from caching API responses.  Stale cached data
# (e.g. an old player_id from /api/daily-challenge) can cause clue
# mismatches if the CSV indices change between deployments.
@app.after_request
def set_cache_headers(response):
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
    return response

# --- Data Loading and Processing ---
try:
    # Load the CSV file containing player data into a pandas DataFrame
    players_df = pd.read_csv('brighton_players.csv', quotechar='"', escapechar='\\', on_bad_lines='skip')
    print("DEBUG: Columns after loading:", players_df.columns.tolist())  # Print the column names for debugging
    print("DEBUG: First 5 rows after loading:\n", players_df.head())  # Print the first 5 rows for debugging

    # Remove any rows where the player's name or date of birth is missing
    players_df = players_df.dropna(subset=['name', 'date of birth']).reset_index(drop=True)

    # Find and print any rows where the name is empty or just spaces (should be none)
    empty_name_rows = players_df[players_df['name'].str.strip() == '']
    print('DEBUG: Rows with empty or whitespace-only names:')
    print(empty_name_rows)

    # Function to split a player's full name into first and last name
    def split_name(name):
        if pd.isna(name):  # If the name is missing, return empty strings
            return "", ""
        name_str = str(name).strip().strip('"')  # Clean up the name
        if ' ' in name_str:  # If there is a space, split into first and last
            parts = name_str.split(' ', 1)
            return parts[0], parts[1]
        else:  # If no space, treat the whole name as first name
            return name_str, ""

    # Apply the split_name function to every player's name
    split_results = list(players_df['name'].map(split_name))
    print("DEBUG: split_name results (first 10):", split_results[:10])  # Show first 10 results
    print("DEBUG: Any non-2-length tuples?", [x for x in split_results if len(x) != 2])  # Check for errors
    players_df['first name'], players_df['last name'] = zip(*split_results)  # Add new columns for first and last name

    # Make sure all name and date fields are strings (not missing)
    players_df['first name'] = players_df['first name'].fillna("").astype(str)
    players_df['last name'] = players_df['last name'].fillna("").astype(str)
    players_df['date of birth'] = players_df['date of birth'].fillna("").astype(str)
    # Ensure new columns are present and fill missing values with empty strings
    for col in ['seasons played at Brighton', 'seasons at brighton during second spell']:
        if col not in players_df.columns:
            players_df[col] = ''
        else:
            players_df[col] = players_df[col].fillna("").astype(str)

    players_df = players_df.fillna("")

    print("--- Successfully loaded and processed CSV ---")
    print(players_df.head())  # Show first few rows after processing

except FileNotFoundError:
    # If the CSV file is missing, print an error and stop the app
    print("FATAL ERROR: 'brighton_players.csv' not found. Make sure it's in the same directory as app.py.")
    exit()
except Exception as e:
    # If any other error occurs, print it and stop the app
    print(f"FATAL ERROR loading or processing the CSV: {e}")
    exit()

current_player_index = None  # Global override for local testing

# File to store recent player selections
# Use persistent volume path on Fly.io, local path otherwise
DATA_DIR = os.environ.get('DATA_DIR', '.')
RECENT_PLAYERS_FILE = os.path.join(DATA_DIR, 'recent_players.json')

# The running order of the current selection cycle (player names) lives on the
# persistent volume so that adding players to the CSV never reshuffles days
# that are already scheduled. The bootstrap file seeds it the first time.
CYCLE_STATE_FILE = os.path.join(DATA_DIR, 'cycle_state.json')
CYCLE_BOOTSTRAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cycle_bootstrap.json')

def _eligible_names():
    """Names of players with at least 1 league appearance, in CSV order."""
    apps = players_df['Brighton and Hove Albion league appearances']
    return players_df.loc[apps > 0, 'name'].tolist()

def _shuffled_names(names, seed_date):
    """Deterministic shuffle of player names, seeded by a cycle's start date."""
    shuffled = sorted(names)
    random.Random(seed_date.isoformat()).shuffle(shuffled)
    return shuffled

def load_cycle_state():
    """Return (cycle_start, order) from the saved state, falling back to the bootstrap."""
    for path in (CYCLE_STATE_FILE, CYCLE_BOOTSTRAP_FILE):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            return datetime.fromisoformat(data['cycle_start']).date(), list(data['order'])
        except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
            continue
    raise RuntimeError("No cycle state or bootstrap file available")

def save_cycle_state(cycle_start, order):
    tmp_path = CYCLE_STATE_FILE + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump({'cycle_start': cycle_start.isoformat(), 'order': order}, f, indent=1, ensure_ascii=False)
    os.replace(tmp_path, CYCLE_STATE_FILE)

def get_cycle_order(today):
    """Return (cycle_start, order) for the cycle containing `today`.

    Every eligible player appears exactly once per cycle. Players who become
    eligible mid-cycle (new signings, first appearances) are appended to the
    end of the current cycle, so days that are already scheduled never change.
    A new cycle's order is fixed and saved on the day it starts.
    """
    cycle_start, order = load_cycle_state()
    eligible = _eligible_names()
    eligible_set = set(eligible)

    scheduled = [name for name in order if name in eligible_set]
    newcomers = _shuffled_names([name for name in eligible if name not in set(scheduled)], cycle_start)
    changed = scheduled != order or bool(newcomers)
    order = scheduled + newcomers

    while (today - cycle_start).days >= len(order):
        cycle_start += timedelta(days=len(order))
        order = _shuffled_names(eligible, cycle_start)
        changed = True

    if changed:
        try:
            save_cycle_state(cycle_start, order)
        except Exception as e:
            print(f"WARNING: Could not save cycle_state.json: {e}")
    return cycle_start, order

def load_recent_players():
    """Load the list of recently selected players from file."""
    try:
        with open(RECENT_PLAYERS_FILE, 'r') as f:
            data = json.load(f)
            # Convert dates back to datetime objects
            recent_players = {}
            for date_str, player_id in data.items():
                recent_players[datetime.fromisoformat(date_str)] = player_id
            return recent_players
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_recent_players(recent_players):
    """Save the list of recently selected players to file."""
    # Convert datetime objects to ISO format strings for JSON serialization
    data = {}
    for date, player_id in recent_players.items():
        data[date.isoformat()] = player_id
    
    with open(RECENT_PLAYERS_FILE, 'w') as f:
        json.dump(data, f)

@app.route('/api/set-player', methods=['POST'])
def set_player():
    global current_player_index
    if not app.debug:
        return jsonify({'error': 'Not allowed in production'}), 403
    data = request.json
    if data.get('random'):
        eligible = set(_eligible_names())
        idx = random.choice([i for i, name in enumerate(players_df['name']) if name in eligible])
    else:
        idx = int(data.get('player_id', 0))
    if 0 <= idx < len(players_df):
        current_player_index = idx
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Invalid player index'}), 400

def get_daily_player():
    """Get today's player from the current selection cycle (see get_cycle_order).

    Selections are also recorded in recent_players.json for the debug endpoint.
    """
    global current_player_index

    if app.debug and current_player_index is not None:
        player = players_df.iloc[current_player_index]
        return player

    today = datetime.now().date()
    cycle_start, order = get_cycle_order(today)
    position_in_cycle = max((today - cycle_start).days, 0)
    selected_name = order[position_in_cycle]
    selected_index = int(players_df.index[players_df['name'] == selected_name][0])

    # Record this selection in recent_players.json (for debug/history)
    try:
        recent_players = load_recent_players()
        cutoff_date = today - timedelta(days=30)
        recent_players = {date: player_id for date, player_id in recent_players.items()
                         if date.date() >= cutoff_date}
        today_key = datetime.combine(today, datetime.min.time())
        recent_players[today_key] = selected_index
        save_recent_players(recent_players)
    except Exception as e:
        print(f"WARNING: Could not save recent_players.json: {e}")

    player = players_df.iloc[selected_index]
    print(f"DEBUG: Cycle from {cycle_start}, position {position_in_cycle}/{len(order)}, selected: {player['name']}")
    return player

def _extract_era(seasons_str):
    """Extract decade(s) from a seasons string like '2010-2015, 2018-2020' → 'the 2010s'."""
    if not seasons_str:
        return ""
    import re
    years = re.findall(r'(\d{4})', str(seasons_str))
    if not years:
        return ""
    decades = sorted(set(int(y) // 10 * 10 for y in years))
    if len(decades) == 1:
        return f"the {decades[0]}s"
    return f"the {decades[0]}s and {decades[-1]}s"

# Must match the frontend, which moves to give-up mode after the 5th clue
MAX_VISIBLE_CLUES = 5


def _format_dob(dob_str):
    """'16-Jan-81' → '16 January 1981'. Returns '' if unparseable."""
    try:
        dob = datetime.strptime(str(dob_str).strip(), '%d-%b-%y')
    except ValueError:
        return ""
    # %y pivots at 1969, but no player in the dataset is born after the current year
    if dob.year > datetime.now().year:
        dob = dob.replace(year=dob.year - 100)
    return f"{dob.day} {dob.strftime('%B %Y')}"


def _joined_from_clue(value):
    """Turn the raw 'Team played for before Brighton' value into readable clue text."""
    value = str(value).strip() if value else ""
    if not value:
        return ""
    if value.lower() == 'youth':
        return "This player came through Brighton's academy."
    if value.lower().startswith('unattached'):
        return "This player joined Brighton as a free agent."
    m = re.match(r'^(.*?)\s*\((.*)\)$', value)
    if m:
        club, note = m.group(1).strip(), m.group(2).strip().lower()
        if note == 'youth':
            return f"This player came through the youth ranks at {club} before joining Brighton."
        if note == 'loan':
            return f"This player first arrived at Brighton on loan from {club}."
        if note == 'loan from brighton':
            return f"While on Brighton's books, this player was loaned out to {club}."
        value = club
    return f"This player joined Brighton from {value}."


# --- Derived-clue lookups ---------------------------------------------------
# Seasons are identified by their starting year (2010 = 2010-11). The CSV's
# "2007-2010" means the player arrived in 2007 and left in summer 2010.

def _current_season():
    today = datetime.now()
    return today.year if today.month >= 7 else today.year - 1


def _league_tier(season):
    """Brighton's division for a season (1 = top flight)."""
    if season <= 2000:
        return 4
    if season in (2001, 2003) or 2006 <= season <= 2010:
        return 3
    if season in (2002, 2004, 2005) or 2011 <= season <= 2016:
        return 2
    return 1  # Premier League since 2017-18 — update if that ever changes


TIER_NAMES = {1: "the Premier League", 2: "the second tier", 3: "the third tier", 4: "the fourth tier"}

STADIUMS = ["the Goldstone Ground", "Gillingham's Priestfield", "Withdean", "the Amex"]


def _stadium(season):
    if season <= 1996:
        return STADIUMS[0]
    if season <= 1998:
        return STADIUMS[1]
    if season <= 2010:
        return STADIUMS[2]
    return STADIUMS[3]


LANDMARK_SEASONS = {
    2000: "won the Division Three title in 2001",
    2001: "won the Division Two title in 2002",
    2003: "won promotion via the play-offs in 2004",
    2010: "won the League One title in 2011",
    2016: "won promotion to the Premier League in 2017",
    2022: "qualified for Europe for the first time in 2023",
}

SUSSEX_TOWNS = {'Brighton', 'Hove', 'Worthing', 'Eastbourne', 'Lewes', 'Crawley', 'Hastings',
                'Haywards Heath', 'Chichester', 'Bognor Regis', 'Shoreham-by-Sea', 'Horsham'}

# How interesting each clue type is to a fan. Clue 1 is the most interesting
# clue that doesn't give the answer away; position is deliberately last.
CLUE_INTEREST = {
    'landmark': 5, 'stadium': 5, 'drought': 5,
    'teammate': 4, 'apps_rank': 4, 'goals_rank': 4, 'rate': 4, 'nationality': 4,
    'divisions': 3, 'age_in': 3, 'age_out': 3, 'longevity': 3, 'local': 3,
    'left_for': 3, 'joined_from': 3, 'spells': 3, 'seasons2': 3,
    'goals': 2, 'appearances': 2, 'seasons': 2, 'birthplace': 2,
    'era': 1, 'dob': 1, 'position': 0,
}
# Clues that place the player in time — clue 1 or 2 should always be one
ERA_CLUES = {'era', 'seasons', 'stadium', 'landmark', 'divisions'}
# Clues that state the same underlying fact; only one per group is used
FACT_GROUPS = {
    'birthplace': 'birth', 'local': 'birth', 'nationality': 'birth',
    'seasons': 'duration', 'longevity': 'duration',
    'drought': 'goals', 'goals': 'goals',
    'seasons2': 'spells', 'spells': 'spells',
}
FIRST_CLUE_FITS = (3, 25)   # clue 1 should fit a handful of players, not one or fifty
DECISIVE_FITS = 2           # clue 5 should fit at most this many players


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _season_years(seasons_str):
    """'2007-2010' → [2007, 2008, 2009]; '2024-' → 2024..current; '2021' → [2021]."""
    years = []
    for part in str(seasons_str or '').split(','):
        part = part.strip()
        m = re.match(r'^(\d{4})-(\d{4})?$', part)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else _current_season() + 1
            years += range(start, max(end, start + 1))
        elif re.match(r'^\d{4}$', part):
            years.append(int(part))
    return years


def _player_years(player):
    return sorted(set(_season_years(player['seasons played at Brighton']) +
                      _season_years(player['seasons at brighton during second spell'])))


def _is_current(player):
    return any(str(player[c]).strip().endswith('-')
               for c in ('seasons played at Brighton', 'seasons at brighton during second spell'))


def _birth_year(player):
    try:
        dob = datetime.strptime(str(player['date of birth']).strip(), '%d-%b-%y')
    except ValueError:
        return None
    return dob.year - 100 if dob.year > datetime.now().year else dob.year


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


class _PlayerFacts:
    """Per-player values that clue signatures are computed from (cached per player id)."""
    def __init__(self, player):
        self.id = player.name
        self.years = _player_years(player)
        self.year_set = set(self.years)
        self.birth_year = _birth_year(player)
        self.apps = _int(player['Brighton and Hove Albion league appearances'])
        self.goals = _int(player['Brighton and Hove Albion league goals'])
        self.current = _is_current(player)


_facts_cache = {}
_clue_cache = {}
_candidate_cache = {}


def _all_facts():
    key = (id(players_df), len(players_df))
    if _facts_cache.get('key') != key:
        _facts_cache.clear()
        _clue_cache.clear()
        _candidate_cache.clear()
        _facts_cache['key'] = key
        _facts_cache['all'] = [_PlayerFacts(players_df.iloc[i]) for i in range(len(players_df))]
    return _facts_cache['all']


def _rank(value, values):
    """Competition rank (1 = highest) and whether it's shared."""
    higher = sum(1 for v in values if v > value)
    tied = sum(1 for v in values if v == value) > 1
    return higher + 1, tied


def _candidate_clues(player):
    """
    Every possible clue for a player as dicts: {key, text, fits}.
    `fits` is how many players in the dataset the same clue would describe
    (including this one) — lower means more decisive.
    """
    everyone = _all_facts()
    if player.name in _candidate_cache:
        return [dict(c) for c in _candidate_cache[player.name]]
    me = _PlayerFacts(player)
    rows = [players_df.iloc[i] for i in range(len(players_df))]
    candidates = []

    def add(key, text, signature):
        """signature(row, facts) returns a value; players with an equal value also fit the clue."""
        if not text:
            return
        mine = signature(player, me)
        if mine is None:
            return
        fits = sum(1 for r, f in zip(rows, everyone) if signature(r, f) == mine)
        candidates.append({'key': key, 'text': text, 'fits': max(fits, 1)})

    col = lambda name: (lambda r, f: str(r[name]).strip())

    # --- Basic clues ---
    left_for_value = str(player['Team played for after Brighton and Hove Albion (first spell)']).strip()
    if 'retired' in left_for_value.lower() or not left_for_value:
        left_for_clue = ""
    elif left_for_value == 'Still at club':
        # An open-ended season like "2022-" already implies the player is still at the club
        seasons_str = str(player['seasons played at Brighton']).strip()
        left_for_clue = "" if seasons_str.endswith('-') else "This player is still at the club."
    elif left_for_value == 'Released':
        left_for_clue = "This player was released by Brighton."
    else:
        left_for_clue = f"This player left Brighton to join {left_for_value}."
    add('left_for', left_for_clue, col('Team played for after Brighton and Hove Albion (first spell)'))

    if player['seasons played at Brighton']:
        add('seasons', f"Seasons at Brighton: {player['seasons played at Brighton']}", col('seasons played at Brighton'))
    else:
        era = _extract_era(player['seasons played at Brighton'])
        add('era', f"This player played for Brighton during {era}." if era else "",
            lambda r, f: _extract_era(r['seasons played at Brighton']))
    if player['seasons at brighton during second spell']:
        add('seasons2', f"Seasons at Brighton during second spell: {player['seasons at brighton during second spell']}",
            col('seasons at brighton during second spell'))

    spells = _int(player['number of spells at Brighton and Hove Albion']) or 1
    # Only shown when it adds information beyond the second-spell seasons clue
    if spells > 2 or (spells > 1 and not player['seasons at brighton during second spell']):
        add('spells', f"This player had {spells} separate spells at Brighton.",
            col('number of spells at Brighton and Hove Albion'))

    place, country = str(player['place of birth']).strip(), str(player['country of birth']).strip()
    birthplace = place if place == country or not country else f"{place}, {country}"
    add('birthplace', f"This player was born in {birthplace}." if place else "",
        lambda r, f: (str(r['place of birth']).strip(), str(r['country of birth']).strip()))

    add('appearances', f"This player made {me.apps} league appearances for Brighton.", lambda r, f: f.apps)
    if me.goals or me.apps < 50:  # 50+ apps without a goal gets the more interesting drought clue
        add('goals', f"This player scored {me.goals} league goals for Brighton.", lambda r, f: f.goals)
    add('joined_from', _joined_from_clue(player['Team played for before Brighton and Hove Albion (first spell)']),
        lambda r, f: _joined_from_clue(r['Team played for before Brighton and Hove Albion (first spell)']))
    dob = _format_dob(player['date of birth'])
    add('dob', f"This player was born on {dob}." if dob else "", col('date of birth'))
    add('position', f"This player is a {player['position']}." if player['position'] else "", col('position'))

    # --- Derived clues ---
    if me.years:
        stadiums = lambda f: tuple(s for s in STADIUMS if s in {_stadium(y) for y in f.years})
        st = stadiums(me)
        if st != (STADIUMS[-1],):  # "Amex only" fits most of the dataset
            if len(st) == 1:
                text = f"All of this player's Brighton home games were at {st[0]}."
            elif len(st) == 2:
                text = f"This player played home games for Brighton at both {st[0]} and {st[1]}."
            else:
                text = f"This player played home games for Brighton at {', '.join(st[:-1])} and {st[-1]}."
            add('stadium', text, lambda r, f: stadiums(f))

        tiers = lambda f: tuple(sorted({_league_tier(y) for y in f.years}))
        ts = tiers(me)
        if len(ts) >= 3:
            add('divisions', f"This player played for Brighton in {len(ts)} different divisions.",
                lambda r, f: len(tiers(f)) if len(tiers(f)) >= 3 else None)
        elif len(ts) == 2:
            add('divisions', f"This player played for Brighton in both {TIER_NAMES[ts[0]]} and {TIER_NAMES[ts[1]]}.",
                lambda r, f: tiers(f))
        elif ts != (1,):
            add('divisions', f"This player never played top-flight football for Brighton, only in {TIER_NAMES[ts[0]]}.",
                lambda r, f: tiers(f))

        landmark = next((y for y in me.years if y in LANDMARK_SEASONS), None)
        if landmark is not None:
            add('landmark', f"This player was on Brighton's books when the club {LANDMARK_SEASONS[landmark]}.",
                lambda r, f: landmark in f.year_set or None)

        if me.birth_year:
            age_in = lambda f: f.years[0] - f.birth_year if f.years and f.birth_year else None
            age_out = lambda f: (f.years[-1] + 1 - f.birth_year
                                 if f.years and f.birth_year and not f.current else None)
            if age_in(me) <= 17:
                add('age_in', f"This player was just {age_in(me)} when he joined Brighton.", lambda r, f: age_in(f))
            elif age_in(me) >= 30:
                add('age_in', f"This player was already {age_in(me)} when he arrived at Brighton.", lambda r, f: age_in(f))
            if age_out(me) is not None and age_out(me) >= 32:
                add('age_out', f"This player was {age_out(me)} when his Brighton career ended.", lambda r, f: age_out(f))

        if len(me.years) >= 6:
            add('longevity', f"This player spent {len(me.years)} seasons at Brighton.", lambda r, f: len(f.years))

        # Pair of well-known teammates (100+ apps, 2+ shared seasons) that narrows the field most
        def overlap(a, b):
            return a.id != b.id and len(a.year_set & b.year_set) >= 2
        mates = [f for f in everyone if f.apps >= 100 and overlap(me, f)]
        best = None
        for i, m1 in enumerate(mates):
            for m2 in mates[i + 1:]:
                fits = sum(1 for f in everyone
                           if f.id not in (m1.id, m2.id) and overlap(f, m1) and overlap(f, m2))
                if fits >= FIRST_CLUE_FITS[0] and (best is None or fits < best[0]):
                    best = (fits, m1, m2)
        if best:
            _, m1, m2 = best
            names = players_df.loc[m1.id, 'name'], players_df.loc[m2.id, 'name']
            add('teammate', f"This player was a Brighton teammate of both {names[0]} and {names[1]}.",
                lambda r, f: (f.id not in (m1.id, m2.id) and overlap(f, m1) and overlap(f, m2)) or None)

    all_apps = [f.apps for f in everyone]
    all_goals = [f.goals for f in everyone]
    rank, tied = _rank(me.apps, all_apps)
    if rank <= 15 and me.apps:
        what = "more league appearances than any other player since 2002" if rank == 1 and not tied else \
               f"the {'joint ' if tied else ''}{_ordinal(rank)}-most league appearances of any player since 2002"
        add('apps_rank', f"This player has {what}.", lambda r, f: _rank(f.apps, all_apps)[0])
    rank, tied = _rank(me.goals, all_goals)
    if rank <= 15 and me.goals:
        what = "the top league scorer of any player since 2002" if rank == 1 and not tied else \
               f"the {'joint ' if tied else ''}{_ordinal(rank)}-highest league scorer of any player since 2002"
        add('goals_rank', f"This player is {what}.", lambda r, f: _rank(f.goals, all_goals)[0])

    if me.goals >= 10 and me.apps / me.goals <= 4:
        add('rate', f"This player averaged a league goal every {me.apps / me.goals:.1f} games for Brighton.",
            lambda r, f: round(f.apps / f.goals, 1) if f.goals else None)
    if me.goals == 0 and me.apps >= 50:
        add('drought', f"This player made {me.apps} league appearances without scoring a single league goal.",
            lambda r, f: f.apps if f.goals == 0 else None)

    country_counts = players_df['country of birth'].value_counts()
    if country and country != 'England' and country_counts.get(country, 0) <= 3:
        n = country_counts[country]
        add('nationality', f"This player is the only {country}-born player since 2002." if n == 1 else
            f"This player is one of only {n} {country}-born players since 2002.", col('country of birth'))
    if place in SUSSEX_TOWNS:
        add('local', "This player was born in Sussex.", lambda r, f: str(r['place of birth']).strip() in SUSSEX_TOWNS or None)

    _candidate_cache[player.name] = candidates
    return [dict(c) for c in candidates]


def build_clues(player, seed=None):
    """
    Pick MAX_VISIBLE_CLUES clues for a player (one per star):
      - Clue 1: the most interesting clue that fits a handful of players, so a
        fan can get 5 stars without it being a giveaway.
      - Clues 2-4: interesting clues ordered broad → narrow. At least one of
        clues 1-2 places the player in time.
      - Clue 5: the most interesting decisive clue (fits at most DECISIVE_FITS players).
    Only one clue per underlying fact is used.
    """
    # Seed must NOT include the current date/time — that would reshuffle
    # clues at midnight UTC, causing reordered/duplicate clues for users
    # playing across the day boundary.  Use the player's DataFrame index
    # instead, which is stable for the lifetime of the game session.
    if seed is None:
        seed = str(player.name)
    _all_facts()  # refresh caches if the dataset changed
    cache_key = (player.name, str(seed))
    if cache_key in _clue_cache:
        return list(_clue_cache[cache_key])

    candidates = _candidate_clues(player)
    rng = random.Random(seed)
    rng.shuffle(candidates)  # random tie-break between equally interesting clues
    candidates.sort(key=lambda c: CLUE_INTEREST.get(c['key'], 0), reverse=True)

    chosen = []
    used_facts = set()

    def take(pool):
        c = pool[0]
        chosen.append(c)
        used_facts.add(FACT_GROUPS.get(c['key'], c['key']))

    def available(pred=lambda c: True):
        return [c for c in candidates if c not in chosen
                and FACT_GROUPS.get(c['key'], c['key']) not in used_facts and pred(c)]

    lo, hi = FIRST_CLUE_FITS
    interest = lambda c: CLUE_INTEREST.get(c['key'], 0)
    first = (available(lambda c: lo <= c['fits'] <= hi and c['key'] != 'position')
             # Broad but interesting (e.g. "all home games at Withdean")
             or available(lambda c: c['fits'] > hi and interest(c) >= 3)
             # Sparse-data players: a near-decisive interesting clue beats "scored 0 goals" (fits 77)
             or available(lambda c: c['fits'] == DECISIVE_FITS and interest(c) >= 2)
             or available(lambda c: interest(c) >= 3)
             or available(lambda c: c['key'] != 'position')
             or available())
    if first:
        take(first)

    # Hold back the decisive clue for the final slot
    decisive = available(lambda c: c['fits'] <= DECISIVE_FITS)
    final = decisive[0] if decisive else None
    if final:
        used_facts.add(FACT_GROUPS.get(final['key'], final['key']))

    middle_slots = MAX_VISIBLE_CLUES - len(chosen) - (1 if final else 0)
    # Pin a clue that places the player in time to slot 2, unless the only
    # such clue is decisive (e.g. exact seasons) — then let it sort naturally.
    if chosen and chosen[0]['key'] not in ERA_CLUES and middle_slots > 0:
        era = available(lambda c: c['key'] in ERA_CLUES and c['fits'] > DECISIVE_FITS)
        if era:
            take(era)
            middle_slots -= 1
    n_before_middle = len(chosen)
    not_position = lambda c: c['key'] != 'position'
    for _ in range(middle_slots):
        # Prefer clues that don't give it away; position only as a last resort
        pool = (available(lambda c: c['fits'] > DECISIVE_FITS and not_position(c))
                or available(not_position) or available())
        if not pool:
            break
        take(pool)
    # Broad → narrow within the middle clues
    chosen[n_before_middle:] = sorted(chosen[n_before_middle:], key=lambda c: c['fits'], reverse=True)
    if final:
        chosen.append(final)

    clues = [c['text'] for c in chosen]
    _clue_cache[cache_key] = clues
    return list(clues)


# --- API Routes ---
@app.route('/api/daily-challenge', methods=['GET'])  # Define a web API endpoint for the daily challenge
def get_challenge():
    try:
        player = get_daily_player()  # Get today's player
        clues = build_clues(player)
        return jsonify({
            'firstNameLength': len(player['first name']),
            'lastNameLength': len(player['last name']),
            'firstClue': clues[0],
            'player_id': int(player.name),
            'firstName': player['first name'],
            'lastName': player['last name']
        })
    except KeyError as e:
        # If a column is missing, return an error
        return jsonify({'error': f"A column is missing in the CSV file: {e}"}), 500
    except Exception as e:
        # If any other error occurs, return an error
        return jsonify({'error': f"An unexpected error occurred: {e}"}), 500

@app.route('/api/clues', methods=['POST'])  # Define a web API endpoint for getting more clues
def get_clue():
    try:
        data = request.json  # Get the data sent by the frontend
        player_id = data.get('player_id')  # Get the player's index
        player = players_df.iloc[int(player_id)]  # Get the player's data
        clues = build_clues(player, seed=str(player_id))
        return jsonify({'clue': clues[data.get('clue_index', 0)]})  # Return the requested clue
    except KeyError as e:
        # If a column is missing, return an error
        return jsonify({'error': f"A column is missing in the CSV file for clues: {e}"}), 500
    except Exception as e:
        # If any other error occurs, return an error
        return jsonify({'error': f"An unexpected error occurred getting clues: {e}"}), 500

@app.route('/api/guess', methods=['POST'])  # Define a web API endpoint for checking a guess
def check_guess():
    try:
        data = request.json  # Get the data sent by the frontend
        player_id = data.get('player_id')  # Get the player's index
        guess_first = data.get('guess_first', '').lower()  # Get the guessed first name (lowercase)
        guess_last = data.get('guess_last', '').lower()  # Get the guessed last name (lowercase)
        player = players_df.iloc[int(player_id)]  # Get the player's data
        # Normalize smart quotes/curly apostrophes to straight ones for comparison
        def normalize(s):
            return s.replace('\u2019', "'").replace('\u2018', "'").replace('\u201c', '"').replace('\u201d', '"')
        # Check if the guess matches the player's name
        is_correct = (normalize(guess_first) == normalize(player['first name'].lower()) and
                      normalize(guess_last) == normalize(player['last name'].lower()))
        response = {'correct': is_correct}  # Prepare the response
        if is_correct:
            # If correct, include the full name
            response['fullName'] = f"{player['first name']} {player['last name']}".strip()
        return jsonify(response)  # Return whether the guess was correct
    except KeyError as e:
        # If a column is missing, return an error
        return jsonify({'error': f"A column is missing in the CSV file for guessing: {e}"}), 500
    except Exception as e:
        # If any other error occurs, return an error
        return jsonify({'error': f"An unexpected error occurred while guessing: {e}"}), 500

# --- Gemini API Routes ---
@app.route('/api/cryptic-clue', methods=['POST'])
def get_cryptic_clue():
    if not model:
        return jsonify({'error': 'AI features are not configured.'}), 503
        
    try:
        data = request.json
        player = players_df.iloc[int(data['player_id'])]
        prompt = f"""You are a witty cryptic clue setter for a football guessing game. Create ONE short cryptic clue based on wordplay of the footballer's name: "{player['name']}".

Rules:
- The clue MUST be based on the sound, spelling, or meaning of the name (first, last, or both).
- Do NOT use biographical information (position, nationality, clubs). The clue is about the name itself.
- Keep it to ONE sentence, maximum 20 words.
- Do not reveal the answer or the player's name.
- Reply with ONLY the clue text, no preamble or explanation.

Examples:
- "Gross": "Sounds like an unpleasant amount of goals."
- "Dunk": "To submerge a biscuit, or a type of slam in basketball."
- "March": "The third month, or to walk in military fashion."
- "Welbeck": "A summoning gesture from a water source."
"""

        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=60,
                temperature=0.9,
            )
        )
        return jsonify({'clue': response.text})
    except Exception as e:
        print(f"Gemini API error for cryptic clue: {e}")
        return jsonify({'error': 'Could not generate cryptic clue.'}), 500

@app.route('/api/player-bio', methods=['POST'])
def get_player_bio():
    if not model:
        return jsonify({'error': 'AI features are not configured.'}), 503

    try:
        data = request.json
        player = players_df.iloc[int(data['player_id'])]
        # Add new fields to the prompt if available
        prompt = f"""You are a knowledgeable football commentator. Write a short, engaging biography (2-3 sentences) for this Brighton & Hove Albion footballer based ONLY on the data below.

Player Data:
- Name: {player['name']}
- Position: {player['position']}
- Seasons at Brighton: {player['seasons played at Brighton']}
- Second spell seasons: {player['seasons at brighton during second spell']}
- League Appearances: {player['Brighton and Hove Albion league appearances']}
- League Goals: {player['Brighton and Hove Albion league goals']}
- Joined From: {player['Team played for before Brighton and Hove Albion (first spell)']}
- Left For: {player['Team played for after Brighton and Hove Albion (first spell)']}

Instructions:
1. ALWAYS mention the seasons they played at Brighton.
2. Do not invent facts, nicknames, or events not in the data. Do not overestimate their importance to the club.
3. Write in a confident, informative tone. Do not say information is limited or further research is needed.
4. Reply with ONLY the bio text, no preamble.
"""
        print(f"DEBUG: Player bio prompt:\n{prompt}")
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=200,
                temperature=0.7,
            )
        )
        return jsonify({'bio': response.text})
    except Exception as e:
        print(f"Gemini API error for player bio: {e}")
        return jsonify({'error': 'Could not generate player bio.'}), 500

# --- Frontend Serving Route ---
@app.route('/')  # Define the route for the main web page
def serve_index():
    """Serves the main index.html file from the 'templates' folder."""
    return render_template('index.html')  # Show the main game page

@app.route('/api/config')
def get_config():
    print(f"DEBUG: /api/config called, app.debug={app.debug}")
    return jsonify({'isLocal': app.debug, 'playerCount': len(players_df)})

@app.route('/api/debug/recent-players')
def debug_recent_players():
    """Debug endpoint to see recent player selections. Accessible in production with admin key."""
    if not app.debug:
        provided_key = request.args.get('key')
        if not ADMIN_KEY or provided_key != ADMIN_KEY:
            return jsonify({'error': 'Not allowed in production'}), 403
    
    recent_players = load_recent_players()
    today = datetime.now().date()
    
    # Format the data for display
    recent_data = []
    for date, player_id in recent_players.items():
        if date.date() >= today - timedelta(days=30):
            player = players_df.iloc[player_id]
            recent_data.append({
                'date': date.date().isoformat(),
                'player_id': player_id,
                'player_name': player['name']
            })
    
    return jsonify({
        'recent_players': recent_data,
        'total_players': len(players_df),
        'recent_count': len(recent_data)
    })

@app.route('/api/debug/reset-recent')
def debug_reset_recent():
    """Debug endpoint to reset recent players (for testing)."""
    if not app.debug:
        return jsonify({'error': 'Not allowed in production'}), 403
    
    # Clear the recent players file
    try:
        os.remove(RECENT_PLAYERS_FILE)
        return jsonify({'success': True, 'message': 'Recent players reset'})
    except FileNotFoundError:
        return jsonify({'success': True, 'message': 'No recent players file to reset'})

if __name__ == '__main__':  # If this file is run directly (not imported)
    app.run(host='0.0.0.0', port=5002, debug=True)  # Start the Flask web server