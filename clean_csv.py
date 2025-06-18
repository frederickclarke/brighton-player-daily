import re

input_file = 'brighton_players.csv'
output_file = 'brighton_players_cleaned.csv'

with open(input_file, 'r', encoding='utf-8') as infile, open(output_file, 'w', encoding='utf-8') as outfile:
    for i, line in enumerate(infile):
        line = line.strip()
        if i == 0:
            # Write header as-is
            outfile.write(line + '\n')
        else:
            # Find all fields wrapped in double quotes, even if they contain commas
            # Handles: ""Field, with, commas"" or ""Field""
            fields = re.findall(r'""(.*?)""', line)
            # If not found, fallback to single quoted fields
            if not fields:
                fields = re.findall(r'"(.*?)"', line)
            # Write as comma-separated
            outfile.write(','.join(fields) + '\n')

print(f"Cleaned CSV written to {output_file}")