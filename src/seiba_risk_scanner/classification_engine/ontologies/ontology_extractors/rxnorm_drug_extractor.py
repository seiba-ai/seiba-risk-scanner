import re
from pathlib import Path

# ---------------- CONFIG ----------------
RXNCONSO_PATH = "classification_engine/ontologies/med_ontology_sources/RXNCONSO.RRF"
OUTPUT_PATH = "classification_engine/ontologies/med_ontology_sources/cleaned/rxnorm_medication_strings.txt"

VALID_TTYS = {
    "IN",   # Ingredient
    "PIN",  # Precise Ingredient
    "BN",   # Brand Name
    "SBD",  # Semantic Branded Drug
    "SCD",  # Semantic Clinical Drug
    "SBDF", # Semantic Branded Drug Form
    "SCDF", # Semantic Clinical Drug Form
}

MIN_LEN = 3
MAX_LEN = 100
# ----------------------------------------


def clean_drug_name(text: str) -> str:
    """
    Extract just the core drug name from a medication string.
    Removes volume, dosage, delivery method, and brand name variations.
    
    Examples:
    - "1.5 ml concizumab-mtci 100 mg/ml pen injector [alhemo]" -> "concizumab-mtci"
    - "10 ml insulin glargine 300 unt/ml pen injector [toujeo]" -> "insulin glargine"
    - "0.05 ml aflibercept 40 mg/ml injection [eylea]" -> "aflibercept"
    - "acitretin 10 mg oral capsule" -> "acitretin"
    - "acetaminophen / diphenhydramine oral tablet" -> "acetaminophen / diphenhydramine"
    - "10-hydroxycapric acid" -> "10-hydroxycapric acid" (unchanged, no volume/dosage pattern)
    """
    original = text
    
    # Remove brand names in brackets
    text = re.sub(r'\s*\[.*?\]', '', text)
    
    # Pattern 1: Remove leading volume measurements (e.g., "1.5 ml", "10 actuat", "0.05 ml")
    # This pattern matches: number(s) + optional decimal + unit + space(s) at the start
    text = re.sub(r'^\d+\.?\d*\s*(ml|actuat)\s+', '', text, flags=re.IGNORECASE)
    
    # Pattern 2: Remove dosage/concentration patterns
    # Matches: space + number(s) + unit/unit (e.g., " 100 mg/ml", " 300 unt/ml", " 40 mg/actuat")
    text = re.sub(r'\s+\d+\.?\d*\s*(mg|g|unt|cells|vector-genomes)/\s*(ml|actuat)', '', text, flags=re.IGNORECASE)
    
    # Pattern 3: Remove standalone dosage measurements (e.g., " 10 mg", " 17.5 mg", " 25 mg")
    # This handles cases like "acitretin 10 mg oral capsule" -> "acitretin oral capsule"
    text = re.sub(r'\s+\d+\.?\d*\s+(mg|g|unt|mcg|iu|units?)\s+', ' ', text, flags=re.IGNORECASE)
    # Also remove at the end if followed by delivery method or at end of string
    text = re.sub(r'\s+\d+\.?\d*\s+(mg|g|unt|mcg|iu|units?)\s*$', '', text, flags=re.IGNORECASE)
    
    # Pattern 4: Remove delivery method keywords (at end or middle)
    delivery_methods = [
        # Injectable methods
        'injection', 'injector', 'prefilled syringe', 'pen injector', 'auto-injector',
        'cartridge', 'prefilled', 'syringe', 'pen',
        # Inhalation methods
        'metered dose inhaler', 'inhalation spray', 'spray', 'inhaler',
        # Oral methods
        'oral capsule', 'oral tablet', 'oral solution', 'oral powder', 'oral suspension',
        'oral liquid', 'oral film', 'oral disintegrating tablet', 'oral lozenge',
        'capsule', 'tablet', 'solution', 'powder', 'suspension', 'liquid', 'film',
        'disintegrating tablet', 'lozenge', 'chewable tablet', 'extended release',
        'delayed release', 'sustained release', 'er', 'sr', 'xr', 'cr',
        # Topical methods
        'topical', 'cream', 'ointment', 'gel', 'lotion', 'patch', 'transdermal',
        # Other methods
        'suppository', 'enema', 'drops', 'eye drops', 'ear drops', 'nasal spray'
    ]
    for method in sorted(delivery_methods, key=len, reverse=True):  # Process longer phrases first
        # Remove at end
        text = re.sub(r'\s+' + re.escape(method) + r'\s*$', '', text, flags=re.IGNORECASE)
        # Remove in middle (with spaces around)
        text = re.sub(r'\s+' + re.escape(method) + r'\s+', ' ', text, flags=re.IGNORECASE)
    
    # Pattern 5: Remove trailing formulation descriptors that aren't core drug names
    # Only remove if they're at the end (not part of compound names)
    text = re.sub(r'\s+(liposomal|human|usp|recombinant)\s*$', '', text, flags=re.IGNORECASE)
    
    # Pattern 6: Remove standalone numbers or units that might be left
    text = re.sub(r'^\d+\.?\d*\s*$', '', text)  # If only numbers remain
    
    # Clean up multiple spaces and trim
    text = re.sub(r'\s+', ' ', text).strip()
    
    # If cleaning resulted in empty or very short string, return original
    # (for cases like pure chemical names that don't match our patterns)
    if not text or len(text) < 2:
        return original.strip()
    
    return text


def extract_medication_strings(rrf_path: str) -> set[str]:
    meds = set()

    with open(rrf_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            cols = line.rstrip("\n").split("|")

            # Safety check: RXNCONSO has many columns
            if len(cols) < 15:
                continue

            tty = cols[12]
            if tty not in VALID_TTYS:
                continue

            s = cols[14].strip().lower()

            if not (MIN_LEN <= len(s) <= MAX_LEN):
                continue

            if s.isnumeric():
                continue

            # Clean the drug name to extract just the core name
            cleaned = clean_drug_name(s)
            
            # Skip if cleaning resulted in empty or too short string
            if not cleaned or len(cleaned) < MIN_LEN:
                continue
            
            # Skip if it's just numbers or common non-drug words
            if cleaned.isnumeric() or cleaned in ['ml', 'mg', 'g', 'unt', 'cells']:
                continue

            meds.add(cleaned)

    return meds


def write_set_to_file(values: set[str], output_path: str):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for v in sorted(values):
            f.write(v + "\n")


if __name__ == "__main__":
    meds = extract_medication_strings(RXNCONSO_PATH)
    write_set_to_file(meds, OUTPUT_PATH)

    print(f"Extracted {len(meds):,} medication strings")
