"""Curated clinical spans for OpenMed disease-model eval gold.

Entity types match TinyMed 65M disease detection (disease_detection_tinymed_65m):
  DISEASE, CONDITION, PATHOLOGY

Spans are patient-specific diagnoses/conditions in clinical sections (not family history).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# doc basename (without .txt) -> list of (phrase, entity_id suffix without openmed::)
ClinicalPhrase = Tuple[str, str]

OPENMED_CLINICAL_BY_DOC: Dict[str, List[ClinicalPhrase]] = {
    "comprehensive_medical_report": [
        ("Hypertension", "DISEASE"),
        ("Hyperlipidemia", "DISEASE"),
        ("Gastroesophageal Reflux Disease (GERD)", "DISEASE"),
        ("Seasonal Allergies", "CONDITION"),
        ("Heart Failure with Reduced Ejection Fraction (HFrEF)", "CONDITION"),
        ("non-ischemic cardiomyopathy", "DISEASE"),
        ("heart failure", "CONDITION"),
        ("Left bundle branch block (LBBB)", "PATHOLOGY"),
        ("Moderate mitral regurgitation", "PATHOLOGY"),
    ],
    "patient_discharge_summary": [
        ("acute inferior ST-elevation myocardial infarction (STEMI)", "DISEASE"),
        ("acute myocardial infarction", "DISEASE"),
        ("Hypertension", "DISEASE"),
        ("Hyperlipidemia", "DISEASE"),
        ("Obesity", "CONDITION"),
        ("Migraine headaches", "CONDITION"),
        ("acute coronary syndrome", "DISEASE"),
        ("Inferior wall hypokinesis", "PATHOLOGY"),
        ("Mild mitral regurgitation", "PATHOLOGY"),
    ],
    "phi_restricted_clinical_notes": [
        ("Type 2 Diabetes", "DISEASE"),
        ("diabetic retinopathy", "PATHOLOGY"),
    ],
    "pii_restricted_medical_report": [
        ("headaches", "CONDITION"),
        ("hypertension", "DISEASE"),
    ],
    "behavioral_phi_confidential": [
        ("Major Depressive Disorder, Recurrent, Moderate", "CONDITION"),
        ("depressed", "CONDITION"),
        ("Depression", "CONDITION"),
    ],
    "genetic_restricted_research": [
        ("breast cancer", "DISEASE"),
        ("ovarian cancer", "DISEASE"),
        ("Alzheimer's", "DISEASE"),
        ("prostate cancer", "DISEASE"),
    ],
    "research_study_phi": [
        ("Resistant Hypertension", "DISEASE"),
        ("Hypertension", "DISEASE"),
        ("Type 2 Diabetes Mellitus", "DISEASE"),
        ("Chronic Kidney Disease, Stage 2", "DISEASE"),
        ("Obstructive Sleep Apnea", "CONDITION"),
    ],
}
