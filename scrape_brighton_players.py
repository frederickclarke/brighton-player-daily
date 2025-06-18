import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
import os
from urllib.parse import unquote

# --- Configuration ---
CSV_FILE_NAME = 'brighton_players.csv'

# --- Output Mode ---
# Set to True to create a new timestamped CSV file for checking.
# Set to False to overwrite the existing CSV_FILE_NAME.
CREATE_NEW_FILE_FOR_OUTPUT = True

# --- Season Selection ---
# To run for specific seasons only, add them to this list (e.g., ['2023-24', '2022-23']).
# To run for all seasons, leave this list empty: []
SEASONS_TO_RUN = ['2024-25']

# --- Script Constants ---
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
HEADERS = {'User-Agent': USER_AGENT}

# List of Wikipedia season URLs to scrape for player names
SEASON_URLS = [
    "https://en.wikipedia.org/wiki/2002%E2%80%9303_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2004%E2%80%9305_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2005%E2%80%9306_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2006%E2%80%9307_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2007%E2%80%9308_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2008%E2%80%9309_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2009%E2%80%9310_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2010%E2%80%9311_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2011%E2%80%9312_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2012%E2%80%9313_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2013%E2%80%9314_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2014%E2%80%9315_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2015%E2%80%9316_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2016%E2%80%9317_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2017%E2%80%9318_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2018%E2%80%9319_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2019%E2%80%9320_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2020%E2%80%9321_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2021%E2%80%9322_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2022%E2%80%9323_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2023%E2%80%9324_Brighton_%26_Hove_Albion_F.C._season",
    "https://en.wikipedia.org/wiki/2024%E2%80%9325_Brighton_%26_Hove_Albion_F.C._season"
]

def get_soup(url):
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'lxml')
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def find_player_urls(season_url):
    """Finds all player Wikipedia URLs from the main squad table on a season page."""
    soup = get_soup(season_url)
    if not soup:
        return set()

    player_links = set()
    squad_tables = soup.find_all('table', class_=re.compile(r'wikitable|sortable'))

    for table in squad_tables:
        headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
        # Check if the table seems to be a squad list by looking for a 'Name' or 'Player' header
        if 'name' in headers or 'player' in headers:
            for row in table.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) > 1:
                    # Player name is typically in the second cell
                    link_cell = cells[1]
                    link = link_cell.find('a', href=True)
                    if link:
                        href = link.get('href', '')
                        if href.startswith('/wiki/') and ':' not in href:
                            player_links.add('https://en.wikipedia.org' + href)
    return player_links


def clean_player_name(name):
    """Removes parenthetical disambiguation like (footballer, born 1983)."""
    return re.sub(r'\s*\((footballer|soccer|goalkeeper)[^)]*\)', '', name).strip()

def parse_player_page(player_url):
    """Parses an individual player's page to extract detailed info."""
    soup = get_soup(player_url)
    if not soup:
        return None

    infobox = soup.find('table', class_=re.compile(r'\binfobox\b'))
    if not infobox:
        print(f"  -> Warning: Could not find infobox for {player_url}")
        return None

    data = {}
    
    name_element = infobox.find(class_=re.compile(r'\bfn\b')) or infobox.find('caption')
    if name_element:
        data['name'] = clean_player_name(name_element.get_text(strip=True))
    else:
        data['name'] = clean_player_name(soup.find('h1', {'id': 'firstHeading'}).get_text(strip=True))

    dob_label = infobox.find('th', string=re.compile('Date of birth'))
    pob_label = infobox.find('th', string=re.compile('Place of birth'))
    data['date of birth'] = dob_label.find_next_sibling('td').get_text(strip=True).split('(')[0].strip() if dob_label else ""
    
    if pob_label:
        pob_text = pob_label.find_next_sibling('td').get_text(strip=True)
        pob_parts = [p.strip() for p in pob_text.split(',')]
        data['place of birth'] = pob_parts[0]
        data['country of birth'] = pob_parts[-1] if len(pob_parts) > 1 else ""
    else:
        data['place of birth'] = ""
        data['country of birth'] = ""

    pos_label = infobox.find('th', string=re.compile('Position'))
    data['position'] = pos_label.find_next_sibling('td').get_text(strip=True) if pos_label else ""

    career_tables = soup.find_all('table', class_=re.compile(r'wikitable'))
    brighton_spells = []
    
    for table in career_tables:
        headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
        if 'team' in headers and 'apps' in headers and '(gls)' in headers:
            for row in table.find_all('tr'):
                cols_text = [col.get_text(strip=True) for col in row.find_all(['th', 'td'])]
                if any("Brighton & Hove Albion" in text for text in cols_text):
                     brighton_spells.append(row)

    total_apps, total_goals, spell_seasons = 0, 0, []
    
    for spell in brighton_spells:
        cols = spell.find_all(['th', 'td'])
        try:
            year_col_text = cols[0].get_text(strip=True)
            if re.search(r'\d{4}', year_col_text):
                seasons = re.sub(r'\[\d+\]', '', year_col_text).strip().replace('→', '').strip()
                if seasons not in spell_seasons:
                    spell_seasons.append(seasons)
                
                apps_text, goals_text = cols[-2].get_text(strip=True), cols[-1].get_text(strip=True).replace('(', '').replace(')', '')
                total_apps += int(apps_text) if apps_text.isdigit() else 0
                total_goals += int(goals_text) if goals_text.isdigit() else 0
        except (ValueError, IndexError):
            continue

    data.update({
        'Brighton and Hove Albion league appearances': total_apps,
        'Brighton and Hove Albion league goals': total_goals,
        'number of spells at Brighton and Hove Albion': len(set(spell_seasons)),
        'seasons played at Brighton': spell_seasons[0] if spell_seasons else "",
        'seasons at brighton during second spell': spell_seasons[1] if len(spell_seasons) > 1 else ""
    })

    all_rows = soup.find('table', {'class': 'wikitable'}).find_all('tr') if soup.find('table', {'class': 'wikitable'}) else []
    first_spell_index = -1
    for i, row in enumerate(all_rows):
        if any("Brighton & Hove Albion" in col.get_text(strip=True) for col in row.find_all(['th', 'td'])):
            if first_spell_index == -1:
                first_spell_index = i
            
    if first_spell_index > 1:
        before_row_cells = all_rows[first_spell_index - 1].find_all('td')
        data['Team played for before Brighton and Hove Albion (first spell)'] = before_row_cells[1].get_text(strip=True) if len(before_row_cells) > 1 else ""
    else:
        data['Team played for before Brighton and Hove Albion (first spell)'] = 'N/A (First Club)'
        
    if first_spell_index != -1:
        first_spell_end_index = first_spell_index + sum(1 for r in brighton_spells if r in all_rows[first_spell_index:]) -1
        if first_spell_end_index + 1 < len(all_rows):
            after_row_cells = all_rows[first_spell_end_index + 1].find_all('td')
            data['Team played for after Brighton and Hove Albion (first spell)'] = after_row_cells[1].get_text(strip=True) if len(after_row_cells) > 1 else ""
        else:
             data['Team played for after Brighton and Hove Albion (first spell)'] = 'N/A (Last Club)'
    else:
        data['Team played for after Brighton and Hove Albion (first spell)'] = 'N/A'
        
    return data

def main():
    """Main function to run the scraper."""
    if not os.path.exists(CSV_FILE_NAME):
        headers = [
            'name', 'date of birth', 'place of birth', 'country of birth', 'position',
            'Brighton and Hove Albion league appearances', 'Brighton and Hove Albion league goals',
            'number of spells at Brighton and Hove Albion',
            'Team played for before Brighton and Hove Albion (first spell)',
            'Team played for after Brighton and Hove Albion (first spell)',
            'seasons played at Brighton', 'seasons at brighton during second spell'
        ]
        pd.DataFrame(columns=headers).to_csv(CSV_FILE_NAME, index=False)
        print(f"Created {CSV_FILE_NAME} with necessary headers.")
    
    if SEASONS_TO_RUN:
        print(f"--- Running for a subset of seasons: {SEASONS_TO_RUN} ---")
        urls_to_process = [url for url in SEASON_URLS if any(season.replace('-', '%E2%80%93') in url for season in SEASONS_TO_RUN)]
    else:
        print("--- Running for all seasons ---")
        urls_to_process = SEASON_URLS
        
    if not urls_to_process:
        print("No matching season URLs found for the specified subset. Please check the SEASONS_TO_RUN list.")
        return

    all_player_urls = set()
    print("--- Finding all unique player URLs ---")
    for url in urls_to_process:
        print(f"Fetching season: {unquote(url.split('/')[-1])}")
        urls = find_player_urls(url)
        all_player_urls.update(urls)
        time.sleep(0.5)

    if not all_player_urls:
        print("Could not find any player URLs. Please check the season page links and structure.")
        return

    print(f"\nFound {len(all_player_urls)} unique player URLs to process.")
    
    all_player_data = []
    for i, url in enumerate(sorted(list(all_player_urls))):
        player_name_from_url = unquote(url.split('/')[-1]).replace('_', ' ')
        print(f"Processing player {i+1}/{len(all_player_urls)}: {player_name_from_url}")
        player_data = parse_player_page(url)
        if player_data and player_data.get('name'):
            all_player_data.append(player_data)
        time.sleep(0.5)

    if not all_player_data:
        print("No player data was successfully scraped. Exiting.")
        return

    new_df = pd.DataFrame(all_player_data)
    
    final_columns = [
        'name', 'date of birth', 'place of birth', 'country of birth', 'position',
        'Brighton and Hove Albion league appearances', 'Brighton and Hove Albion league goals',
        'number of spells at Brighton and Hove Albion',
        'Team played for before Brighton and Hove Albion (first spell)',
        'Team played for after Brighton and Hove Albion (first spell)',
        'seasons played at Brighton', 'seasons at brighton during second spell'
    ]
    
    for col in final_columns:
        if col not in new_df.columns:
            new_df[col] = ""
            
    output_df = new_df[final_columns].drop_duplicates(subset=['name']).reset_index(drop=True)
    
    if CREATE_NEW_FILE_FOR_OUTPUT:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_filename = f"brighton_players_test_run_{timestamp}.csv"
        print(f"\n--- Creating new file for checking: {output_filename} ---")
        output_df.to_csv(output_filename, index=False)
    else:
        output_filename = CSV_FILE_NAME
        if SEASONS_TO_RUN:
            print(f"\n--- Updating master file '{output_filename}' with data from specified seasons... ---")
            try:
                original_df = pd.read_csv(output_filename)
                original_df = original_df[~original_df['name'].isin(output_df['name'])]
                combined_df = pd.concat([original_df, output_df], ignore_index=True)
                combined_df.to_csv(output_filename, index=False)
            except FileNotFoundError:
                output_df.to_csv(output_filename, index=False)
        else:
            print(f"\n--- Overwriting master file: {output_filename} ---")
            output_df.to_csv(output_filename, index=False)
    
    print(f"\n--- Scraping complete. Data saved to {output_filename} ---")

if __name__ == "__main__":
    main()
