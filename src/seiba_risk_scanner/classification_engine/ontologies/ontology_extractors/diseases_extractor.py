import csv
from pathlib import Path

# ---------------- CONFIG ----------------
MONDO_CSV_PATH = "classification_engine/ontologies/med_ontology_sources/MONDO.csv"
OUTPUT_PATH = "classification_engine/ontologies/med_ontology_sources/cleaned/mondo_disease_strings.txt"

MIN_LEN = 2
MAX_LEN = 200
# ----------------------------------------


def split_synonyms(synonyms_str: str) -> list[str]:
    """
    Split synonyms string by both comma and pipe separators.
    Handles cases where synonyms are separated by ',' or '|'.
    
    Examples:
    - "term1|term2|term3" -> ["term1", "term2", "term3"]
    - "term1, term2, term3" -> ["term1", "term2", "term3"]
    - "term1|term2, term3" -> ["term1", "term2", "term3"]
    """
    if not synonyms_str or not synonyms_str.strip():
        return []
    
    # First split by pipe
    terms = []
    for pipe_part in synonyms_str.split('|'):
        # Then split each pipe part by comma
        for comma_part in pipe_part.split(','):
            term = comma_part.strip()
            if term:  # Only add non-empty terms
                terms.append(term)
    
    return terms


def extract_disease_names(csv_path: str) -> set[str]:
    """
    Extract all unique disease names from MONDO.csv.
    Includes preferred labels and all synonyms.
    """
    disease_names = set()
    
    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
        # Use csv.reader to properly handle quoted fields with commas
        reader = csv.reader(f)
        
        # Skip header row
        next(reader, None)
        
        for row in reader:
            # Safety check: ensure we have enough columns
            if len(row) < 3:
                continue
            
            # Column 1 (index 1): Preferred Label
            preferred_label = row[1].strip() if len(row) > 1 else ""
            
            # Column 2 (index 2): Synonyms
            synonyms_str = row[2].strip() if len(row) > 2 else ""
            
            # Add preferred label if it exists and meets criteria
            if preferred_label:
                # Remove quotes if present
                preferred_label = preferred_label.strip('"')
                if MIN_LEN <= len(preferred_label) <= MAX_LEN:
                    disease_names.add(preferred_label)
            
            # Process synonyms
            if synonyms_str:
                # Remove quotes if present
                synonyms_str = synonyms_str.strip('"')
                synonyms = split_synonyms(synonyms_str)
                
                for synonym in synonyms:
                    # Clean up the synonym
                    synonym = synonym.strip()
                    if MIN_LEN <= len(synonym) <= MAX_LEN:
                        disease_names.add(synonym)
    
    return disease_names


def write_set_to_file(values: set[str], output_path: str):
    """Write sorted set of values to a text file, one per line."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for v in sorted(values):
            f.write(v + "\n")


if __name__ == "__main__":
    disease_names = extract_disease_names(MONDO_CSV_PATH)
    print(f"Length of disease_names set: {len(disease_names):,}")
    
    write_set_to_file(disease_names, OUTPUT_PATH)
    
    print(f"Extracted {len(disease_names):,} unique disease names")
    print(f"Output written to: {OUTPUT_PATH}")
