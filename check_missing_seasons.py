import pandas as pd

# Load the CSV file
csv_file = 'brighton_players.csv'
df = pd.read_csv(csv_file)

# Check for missing or empty 'seasons played at Brighton'
missing_seasons = df[df['seasons played at Brighton'].isna() | (df['seasons played at Brighton'].astype(str).str.strip() == '')]

if missing_seasons.empty:
    print('All players have a value for "seasons played at Brighton".')
else:
    print('Players missing "seasons played at Brighton":')
    for idx, row in missing_seasons.iterrows():
        print(f"- {row['name']}") 