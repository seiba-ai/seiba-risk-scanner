import csv
import json
from pathlib import Path

# ---------------- CONFIG ----------------
ICD_PCS_CSV_PATH = "classification_engine/ontologies/med_ontology_sources/icd_pcs.csv"
OUTPUT_PATH = "classification_engine/ontologies/med_ontology_sources/cleaned/icd_pcs_codes.json"
# ----------------------------------------


def extract_procedure_codes(csv_path: str) -> dict[str, str]:
    """
    Extract ICD-10-PCS codes and their descriptions from CSV.
    Returns a dictionary with procedure code as key and description as value.
    
    Column structure:
    - Column 0: Procedure Code Category
    - Column 1: ICD-10-PCS Codes
    - Column 2: Procedure Code Descriptions
    - Column 3: Code Status
    """
    procedure_codes = {}
    
    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
        # Use csv.reader to properly handle quoted fields with commas
        reader = csv.reader(f)
        
        # Skip header row
        next(reader, None)
        
        for row in reader:
            # Safety check: ensure we have enough columns
            if len(row) < 3:
                continue
            
            # Column 1 (index 1): ICD-10-PCS Codes
            code = row[1].strip() if len(row) > 1 else ""
            
            # Column 2 (index 2): Procedure Code Descriptions
            description = row[2].strip() if len(row) > 2 else ""
            
            # Skip rows with empty code or description
            if not code or not description:
                continue
            
            # Remove quotes if present
            code = code.strip('"')
            description = description.strip('"')
            
            # Store in dictionary (if duplicates exist, last one wins)
            procedure_codes[code] = description
    
    return procedure_codes


def write_dict_to_json(data: dict[str, str], output_path: str):
    """Write dictionary to JSON file with proper formatting."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    procedure_codes = extract_procedure_codes(ICD_PCS_CSV_PATH)
    print(f"Length of procedure_codes dictionary: {len(procedure_codes):,}")
    
    write_dict_to_json(procedure_codes, OUTPUT_PATH)
    
    print(f"Extracted {len(procedure_codes):,} unique procedure codes")
    print(f"Output written to: {OUTPUT_PATH}")
