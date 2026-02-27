import os  # Import the os module for interacting with the operating system
import pandas as pd  # Import pandas for data handling
from datetime import datetime, timedelta  # Import datetime for working with dates
import google.generativeai as genai
from flask import Flask, jsonify, request, render_template  # Import Flask and related functions for web server
import random
from dotenv import load_dotenv
import json

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
RECENT_PLAYERS_FILE = 'recent_players.json'

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
    idx = int(data.get('player_id', 0))
    if 0 <= idx < len(players_df):
        current_player_index = idx
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Invalid player index'}), 400

def get_daily_player():
    """Get today's player using a randomized but deterministic selection."""
    global current_player_index

    if app.debug and current_player_index is not None:
        player = players_df.iloc[current_player_index]
        return player

    today = datetime.now().date()
    recent_players = load_recent_players()

    # Clean up old entries (older than 30 days)
    cutoff_date = today - timedelta(days=30)
    recent_players = {date: player_id for date, player_id in recent_players.items()
                     if date.date() >= cutoff_date}

    # Check if today's player has already been selected — return it immediately
    today_key = datetime.combine(today, datetime.min.time())
    if today_key in recent_players:
        selected_index = recent_players[today_key]
        player = players_df.iloc[selected_index]
        print(f"DEBUG: Returning cached player for today: {player.to_dict()}")
        return player

    # Get recently used player IDs (last 30 days)
    recently_used = set(recent_players.values())

    # Create a seeded random number generator for today
    # Use a combination of year and day of year for the seed
    seed = today.year * 1000 + today.timetuple().tm_yday
    rng = random.Random(seed)

    # Get all player indices that have at least 1 league appearance
    all_indices = [idx for idx in range(len(players_df))
                   if players_df.iloc[idx]['Brighton and Hove Albion league appearances'] > 0]

    # Remove recently used players from the pool
    available_indices = [idx for idx in all_indices if idx not in recently_used]

    # If we've used all players recently, reset the pool
    if not available_indices:
        available_indices = all_indices
        recently_used.clear()

    # Select a random player from available ones
    selected_index = rng.choice(available_indices)

    # Record this selection
    recent_players[today_key] = selected_index
    save_recent_players(recent_players)

    player = players_df.iloc[selected_index]
    print(f"DEBUG: Selected new player for today: {player.to_dict()}")
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

def build_clues(player, seed=None):
    """
    Build a list of clues for a player, avoiding clues that repeat the same facts.
    Each clue is tagged with the facts it uses. Only one clue per fact is included.
    Clues are organised into difficulty tiers (hard → easy) for a consistent challenge curve.
    """
    facts_used = set()
    clues = []
    # Custom logic for the 'left_for' clue
    left_for_value = player['Team played for after Brighton and Hove Albion (first spell)']
    if isinstance(left_for_value, str):
        if 'Retired' in left_for_value:
            left_for_clue = ""
        elif left_for_value.strip() == 'Still at club':
            left_for_clue = "This player is still at the club."
        else:
            left_for_clue = f"This player left Brighton to join {left_for_value}"
    else:
        left_for_clue = ""

    # Era clue derived from seasons
    era = _extract_era(player['seasons played at Brighton'])
    era_clue = f"This player played for Brighton during {era}." if era else ""

    # Goals clue
    goals = player['Brighton and Hove Albion league goals']
    goals_clue = f"This player scored {goals} league goals for Brighton." if pd.notna(goals) else ""

    # Define clues in difficulty tiers (hard → medium → easy)
    # Tier 1 (Hard/vague): broad facts that apply to many players
    # Only include the era clue if there's no specific seasons data (era is redundant when seasons is shown)
    tier_1 = [
        (era_clue if not player['seasons played at Brighton'] else "", {'era'}),
        (f"This player was born in {player['place of birth']}, {player['country of birth']} and has {player['number of spells at Brighton and Hove Albion']} spell(s) at Brighton.", {'birth', 'spells'}),
        (f"Seasons at Brighton: {player['seasons played at Brighton']}" if player['seasons played at Brighton'] else "", {'seasons'}),
        (f"Seasons at Brighton during second spell: {player['seasons at brighton during second spell']}" if player['seasons at brighton during second spell'] else "", {'seasons2'}),
    ]
    # Tier 2 (Medium): narrows the field considerably
    tier_2 = [
        (f"This player made {player['Brighton and Hove Albion league appearances']} league appearances for Brighton.", {'appearances'}),
        (goals_clue, {'goals'}),
        (f"This player joined Brighton from {player['Team played for before Brighton and Hove Albion (first spell)']}", {'joined_from'}),
        (left_for_clue, {'left_for'}),
    ]
    # Tier 3 (Easy/most revealing): strongly identifies the player
    tier_3 = [
        (f"This player is a {player['position']}.", {'position'}),
        (f"This player was born on {player['date of birth']}, in {player['place of birth']}, {player['country of birth']}.", {'birth'}),
    ]

    # Remove empty clues from each tier
    tier_1 = [(c, t) for c, t in tier_1 if c.strip()]
    tier_2 = [(c, t) for c, t in tier_2 if c.strip()]
    tier_3 = [(c, t) for c, t in tier_3 if c.strip()]

    # Shuffle within each tier deterministically
    if seed is None:
        seed = str(datetime.now().date()) + str(player.name)
    rng = random.Random(seed)
    rng.shuffle(tier_1)
    rng.shuffle(tier_2)
    rng.shuffle(tier_3)

    # Present tiers in order: hard first, easy last
    clue_defs = tier_1 + tier_2 + tier_3

    for clue, tags in clue_defs:
        if not tags & facts_used:  # Only add if none of the tags have been used
            clues.append(clue)
            facts_used.update(tags)
    return clues

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
        clues = build_clues(player, seed=str(datetime.now().date()) + str(player_id))
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
        prompt = f"""
        You are a witty and intelligent cryptic clue setter for a football guessing game.
        Your task is to create a single, short, clever, cryptic clue based on wordplay of the footballer's name: "{player['name']}".

        **Instructions:**
        1.  The clue MUST be based on the sound, spelling, or meaning of the player's name (first, last, or both).
        2.  Do NOT use biographical information like their position, nationality, or former clubs. The clue must be about the name itself.
        3.  Keep it short and punchy.
        4.  Do not reveal the answer or the player's name in your response.

        **Examples of good clues:**
        - For a player named "Gross": "Sounds like an unpleasant amount of goals."
        - For a player named "Dunk": "To submerge a biscuit, or a type of slam in basketball."
        - For a player named "Lallana": "This player's name sounds like a gentle song."
        - For a player named "March": "The third month of the year, or to walk in a military manner."

        Now, generate a cryptic clue for: "{player['name']}"
        """

        response = model.generate_content(prompt)
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
        prompt = f"""
You are a knowledgeable and enthusiastic football commentator. Write a short, engaging biography (2-3 sentences) for the following Brighton & Hove Albion footballer based ONLY on the data provided below.

**IMPORTANT: The seasons the player played for Brighton are listed below. YOU MUST include this information in the bio if it is present and the player is not still at the club.**

**Player Data:**
- Seasons played at Brighton: {player['seasons played at Brighton']}
- Name: {player['name']}
- Position: {player['position']}
- League Appearances for Brighton: {player['Brighton and Hove Albion league appearances']}
- League Goals for Brighton: {player['Brighton and Hove Albion league goals']}
- Joined From: {player['Team played for before Brighton and Hove Albion (first spell)']}
- Left For: {player['Team played for after Brighton and Hove Albion (first spell)']}
- Seasons at Brighton during second spell: {player['seasons at brighton during second spell']}

**Instructions:**
1. Focus on their contribution and time at Brighton, and SPECIFICALLY mention the seasons they played for the club (see above).
2. Do not invent facts, nicknames, or events not present in the data. Do not overestimate thier importance to the club.
3. Write in a confident and informative tone. Do not say that information is limited or that further research is needed.

"""
        print(f"DEBUG: Player bio prompt:\n{prompt}")
        response = model.generate_content(prompt)
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