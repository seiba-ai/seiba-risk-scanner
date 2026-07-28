import csv
import json
from pathlib import Path

# ---------------- CONFIG ----------------
BIOMARKERS_CSV_PATH = "classification_engine/ontologies/med_ontology_sources/biomarkers.csv"
OUTPUT_JSON_PATH = "classification_engine/ontologies/med_ontology_sources/cleaned/biomarkers_map.json"
# ----------------------------------------

# Read CSV and create dictionary
biomarkers_map = {}
with open(BIOMARKERS_CSV_PATH, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        name = row['name'].strip()
        unit = row['measurement_units'].strip() if row['measurement_units'] else ''
        # Convert null/None strings to empty string
        if unit.lower() in ['null', 'none']:
            unit = ''
        if name:
            biomarkers_map[name] = unit

# Write to JSON
Path(OUTPUT_JSON_PATH).parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT_JSON_PATH, 'w', encoding='utf-8') as f:
    json.dump(biomarkers_map, f, indent=2, ensure_ascii=False)

print(f"Extracted {len(biomarkers_map):,} biomarker entries")
print(f"Output written to: {OUTPUT_JSON_PATH}")
