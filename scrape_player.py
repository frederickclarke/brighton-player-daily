import pandas as pd
import requests
from bs4 import BeautifulSoup
import sys
import re

def get_player_url(name, csv_file='brighton_player_urls.csv'):
    """Get the Wikipedia URL for a player from the CSV file."""
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            next(f) # Skip header
            for line in f:
                try:
                    parts = line.strip().rsplit(',', 1)
                    player_name, player_url = parts
                    if player_name == name:
                        return player_url
                except ValueError:
                    continue
        print(f"Error: Player '{name}' not found in the database.")
        return None
    except Exception as e:
        print(f"Error reading or searching CSV file: {e}")
        return None

def get_soup(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def parse_infobox_club_career(infobox):
    """Parse the club career rows from the infobox (for players like Lewis Dunk)."""
    senior_header = infobox.find('th', string=re.compile('Senior career'))
    if not senior_header:
        return []
    club_rows = []
    tr = senior_header.find_parent('tr').find_next_sibling('tr')
    while tr:
        # Stop if we hit "National team" or another section
        if tr.find('th') and ('National team' in tr.get_text() or 'Medal record' in tr.get_text()):
            break
        cells = tr.find_all(['th', 'td'])
        if len(cells) >= 4:
            years = cells[0].get_text(strip=True)
            club = cells[1].get_text(strip=True)
            # Appearances and goals may be in the same cell or separate
            apps = cells[2].get_text(strip=True)
            goals = cells[3].get_text(strip=True)
            # Sometimes apps is like '436 (26)'
            apps_match = re.match(r'^(\d+)(?:\s*\((\d+)\))?$', apps)
            if apps_match:
                apps_val = int(apps_match.group(1))
                if apps_match.group(2):
                    goals_val = int(apps_match.group(2))
                else:
                    goals_val = int(goals) if goals.isdigit() else 0
            else:
                apps_val = int(re.sub(r'[^0-9]', '', apps)) if re.sub(r'[^0-9]', '', apps) else 0
                goals_val = int(re.sub(r'[^0-9]', '', goals)) if re.sub(r'[^0-9]', '', goals) else 0
            club_rows.append({'years': years, 'club': club, 'apps': apps_val, 'goals': goals_val})
        tr = tr.find_next_sibling('tr')
    return club_rows

def scrape_player_info(url):
    """Scrape the 11 required columns for a Brighton player from their Wikipedia page."""
    soup = get_soup(url)
    if not soup:
        return None

    data = {}
    
    # --- Attempt to get data from infobox ---
    infobox = soup.find('table', class_=re.compile(r'\binfobox\b'))
    if not infobox:
        # Try a more robust selector: any table whose class contains 'infobox'
        infobox = soup.find('table', {'class': lambda x: x and 'infobox' in x})
    if infobox:
        name_element = infobox.find(class_=re.compile(r'\bfn\b')) or infobox.find('caption')
        if name_element:
            data['name'] = re.sub(r'\s*\((footballer|soccer|goalkeeper)[^)]*\)', '', name_element.get_text(strip=True)).strip()
        # Robust date of birth extraction
        dob_th = infobox.find('th', string=re.compile('Date of birth', re.I))
        if dob_th:
            dob_td = dob_th.find_next_sibling('td')
            if dob_td:
                dob_text = dob_td.get_text(" ", strip=True)
                # Try to extract date in format '21 November 1991' or similar
                dob_match = re.search(r'(\d{1,2} \w+ \d{4})', dob_text)
                if dob_match:
                    # Format as DD-MMM-YY
                    from datetime import datetime
                    dt = datetime.strptime(dob_match.group(1), '%d %B %Y')
                    data['date of birth'] = dt.strftime('%d-%b-%y')
                else:
                    data['date of birth'] = dob_text
            else:
                data['date of birth'] = ''
        else:
            data['date of birth'] = ''
        pob_th = infobox.find('th', string=re.compile('Place of birth', re.I))
        if pob_th:
            pob_text = pob_th.find_next_sibling('td').get_text(strip=True)
            pob_parts = [p.strip() for p in pob_text.split(',')]
            data['place of birth'] = pob_parts[0]
            data['country of birth'] = pob_parts[-1] if len(pob_parts) > 1 else ""
        else:
            data['place of birth'], data['country of birth'] = "", ""
        pos_th = infobox.find('th', string=re.compile('Position', re.I))
        data['position'] = re.sub(r'\[\d+\]', '', pos_th.find_next_sibling('td').get_text(strip=True)).strip() if pos_th else ""
    else:
        # Debug: print all table classes on the page
        print(f"  -> Warning: Could not find infobox for {url}. Parsing other data.")
        print("  -> Table classes found on page:")
        for t in soup.find_all('table'):
            print("   ", t.get('class'))
        data['name'] = re.sub(r'\s*\((footballer|soccer|goalkeeper)[^)]*\)', '', soup.find('h1', {'id': 'firstHeading'}).get_text(strip=True)).strip()

    # --- **REWRITTEN LOGIC**: Find career stats table and parse it intelligently ---
    career_header = soup.find('span', id=re.compile(r'Career_statistics|Club_career'))
    career_table = career_header.find_next('table', class_=re.compile(r'wikitable')) if career_header else None

    if not career_table:
        # Fallback: Try to parse infobox club career table
        if infobox:
            club_rows = parse_infobox_club_career(infobox)
            # Find all Brighton spells
            brighton_rows = [row for row in club_rows if 'Brighton' in row['club']]
            data['Brighton and Hove Albion league appearances'] = sum(row['apps'] for row in brighton_rows)
            # Always use the parsed goals value for Brighton (from appearances cell if present)
            data['Brighton and Hove Albion league goals'] = sum(row['goals'] for row in brighton_rows)
            data['number of spells at Brighton and Hove Albion'] = len(brighton_rows)
            data['seasons played at Brighton'] = brighton_rows[0]['years'] if brighton_rows else ''
            data['seasons at brighton during second spell'] = brighton_rows[1]['years'] if len(brighton_rows) > 1 else ''
            # Find before/after clubs
            first_brighton_idx = next((i for i, row in enumerate(club_rows) if 'Brighton' in row['club']), None)
            if first_brighton_idx is not None and first_brighton_idx == 0:
                data['Team played for before Brighton and Hove Albion (first spell)'] = 'N/A (First Club)'
            elif first_brighton_idx is not None and first_brighton_idx > 0:
                data['Team played for before Brighton and Hove Albion (first spell)'] = club_rows[first_brighton_idx - 1]['club']
            else:
                data['Team played for before Brighton and Hove Albion (first spell)'] = 'N/A (First Club)'
            # After Brighton (first spell)
            if first_brighton_idx is not None and first_brighton_idx + 1 < len(club_rows):
                # Only set if the next club is not Brighton (shouldn't happen for Dunk)
                next_club = club_rows[first_brighton_idx + 1]['club']
                if 'Brighton' not in next_club:
                    data['Team played for after Brighton and Hove Albion (first spell)'] = next_club
                else:
                    data['Team played for after Brighton and Hove Albion (first spell)'] = 'Still at club'
            else:
                data['Team played for after Brighton and Hove Albion (first spell)'] = 'Still at club'
            return data
        print(f"  -> Warning: Could not find career stats table for {url}")
        return data

    all_rows = career_table.find_all('tr')
    total_apps, total_goals = 0, 0
    spell_seasons = []
    in_brighton_section = False

    for row in all_rows:
        header_cell = row.find('th')
        if header_cell and 'colspan' in header_cell.attrs:
            in_brighton_section = "Brighton & Hove Albion" in header_cell.get_text()
            continue

        cols = row.find_all(['th', 'td'])
        if len(cols) > 3 and "Brighton & Hove Albion" in row.get_text():
             in_brighton_section = True # Handle multi-club tables
        
        # If we are in a Brighton section, or the row itself mentions Brighton
        if in_brighton_section:
            if len(cols) > 3:
                try:
                    # Determine column indices based on table type
                    if in_brighton_section and not "Brighton & Hove Albion" in cols[0].get_text():
                        # Dunk-style table
                        season_index, apps_index, goals_index = 0, 2, 3
                    else:
                        # Zamora-style table
                        season_index, apps_index, goals_index = 0, -2, -1
                    
                    year_col_text = cols[season_index].get_text(strip=True)
                    if re.search(r'\d{4}', year_col_text):
                        seasons = re.sub(r'\[\d+\]', '', year_col_text).strip().replace('→', '').strip()
                        if seasons not in spell_seasons:
                            spell_seasons.append(seasons)
                        
                        apps_text = cols[apps_index].get_text(strip=True)
                        goals_text = cols[goals_index].get_text(strip=True).replace('(', '').replace(')', '')
                        
                        total_apps += int(apps_text) if apps_text.isdigit() else 0
                        total_goals += int(goals_text) if goals_text.isdigit() else 0
                except (ValueError, IndexError):
                    continue
        # Reset if we hit another club header
        if header_cell and 'colspan' in header_cell.attrs and "Brighton & Hove Albion" not in header_cell.get_text():
            in_brighton_section = False
            
    data['Brighton and Hove Albion league appearances'] = total_apps
    data['Brighton and Hove Albion league goals'] = total_goals
    data['number of spells at Brighton and Hove Albion'] = len(set(spell_seasons)) if spell_seasons else 1
    data['seasons played at Brighton'] = spell_seasons[0] if spell_seasons else ""
    data['seasons at brighton during second spell'] = spell_seasons[1] if len(spell_seasons) > 1 else ""

    # Find "before" and "after" clubs robustly
    first_spell_index = -1
    for i, row in enumerate(all_rows):
        if any("Brighton & Hove Albion" in col.get_text(strip=True) for col in row.find_all(['th', 'td'])):
            if first_spell_index == -1:
                first_spell_index = i
            
    if first_spell_index > 1:
        before_row = all_rows[first_spell_index - 1]
        before_cells = before_row.find_all('td')
        if len(before_cells) > 1:
            data['Team played for before Brighton and Hove Albion (first spell)'] = before_cells[1].get_text(strip=True)
        else:
            data['Team played for before Brighton and Hove Albion (first spell)'] = 'N/A'
    else:
        data['Team played for before Brighton and Hove Albion (first spell)'] = 'N/A (First Club)'

    data['Team played for after Brighton and Hove Albion (first spell)'] = 'Still at club'
    if first_spell_index != -1:
        start_search_index = first_spell_index + len(spell_seasons)
        for i in range(start_search_index, len(all_rows)):
            row = all_rows[i]
            if "Total" in row.get_text() or "Brighton" in row.get_text():
                continue
            
            cells = row.find_all('td')
            if len(cells) > 1 and cells[1].find('a'):
                data['Team played for after Brighton and Hove Albion (first spell)'] = cells[1].get_text(strip=True)
                break

    return data

def main():
    columns = [
        'name',
        'date of birth',
        'place of birth',
        'country of birth',
        'position',
        'Brighton and Hove Albion league appearances',
        'Brighton and Hove Albion league goals',
        'number of spells at Brighton and Hove Albion',
        'Team played for before Brighton and Hove Albion (first spell)',
        'Team played for after Brighton and Hove Albion (first spell)',
        'seasons played at Brighton',
        'seasons at brighton during second spell'
    ]
    if len(sys.argv) == 1:
        test_players = [
            "Lewis Dunk",
            "Bobby Zamora",
        ]
        for player_name in test_players:
            print(f"\n=== Testing: {player_name} ===")
            url = get_player_url(player_name)
            if not url:
                continue
            player_info = scrape_player_info(url)
            if not player_info:
                continue
            print("Player Information:")
            print("-" * 50)
            for col in columns:
                print(f"{col}: {player_info.get(col, '')}")
        return
    if len(sys.argv) != 2:
        print("Usage: python scrape_player.py \"Player Name\"")
        return
    player_name = sys.argv[1]
    url = get_player_url(player_name)
    if not url:
        return
    player_info = scrape_player_info(url)
    if not player_info:
        return
    print("\nPlayer Information:")
    print("-" * 50)
    for col in columns:
        print(f"{col}: {player_info.get(col, '')}")

def test_lewis_dunk():
    """Test function to check scraping for Lewis Dunk."""
    url = "https://en.wikipedia.org/wiki/Lewis_Dunk"
    player_info = scrape_player_info(url)
    assert player_info['name'] == 'Lewis Dunk', f"Name mismatch: {player_info['name']}"
    assert player_info['date of birth'] == '21-Nov-91', f"DOB mismatch: {player_info['date of birth']}"
    assert player_info['place of birth'] == 'Brighton', f"Place of birth mismatch: {player_info['place of birth']}"
    assert player_info['country of birth'] == 'England', f"Country of birth mismatch: {player_info['country of birth']}"
    assert player_info['position'].lower().startswith('centre'), f"Position mismatch: {player_info['position']}"
    assert player_info['Brighton and Hove Albion league appearances'] == 436, f"Apps mismatch: {player_info['Brighton and Hove Albion league appearances']}"
    assert player_info['Brighton and Hove Albion league goals'] == 26, f"Goals mismatch: {player_info['Brighton and Hove Albion league goals']}"
    assert player_info['number of spells at Brighton and Hove Albion'] == 1, f"Spells mismatch: {player_info['number of spells at Brighton and Hove Albion']}"
    assert player_info['seasons played at Brighton'].startswith('2010'), f"Seasons mismatch: {player_info['seasons played at Brighton']}"
    assert player_info['Team played for before Brighton and Hove Albion (first spell)'] == 'N/A (First Club)', f"Before mismatch: {player_info['Team played for before Brighton and Hove Albion (first spell)']}"
    assert player_info['Team played for after Brighton and Hove Albion (first spell)'] == 'Still at club', f"After mismatch: {player_info['Team played for after Brighton and Hove Albion (first spell)']}"
    print("Lewis Dunk test passed.")

if __name__ == "__main__":
    main()
