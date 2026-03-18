from collections import Counter
from typing import List, Dict


# Simple heuristic mapping from medication names (substrings) to illnesses.
MED_TO_ILLNESS = {
    "metformin": "Diabetes",
    "insulin": "Diabetes",
    "glipizide": "Diabetes",
    "gliclazide": "Diabetes",
    "amlodipine": "Hypertension (High BP)",
    "losartan": "Hypertension (High BP)",
    "valsartan": "Hypertension (High BP)",
    "lisinopril": "Hypertension (High BP)",
    "atorvastatin": "High Cholesterol",
    "simvastatin": "High Cholesterol",
    "rosuvastatin": "High Cholesterol",
    "allopurinol": "Gout",
    "colchicine": "Gout",
    "omeprazole": "Acid Reflux (GERD)",
    "pantoprazole": "Acid Reflux (GERD)",
    "esomeprazole": "Acid Reflux (GERD)",
}


class MedicationAI:
    """
    Tiny "learning" component that guesses which illnesses are relevant
    for a person, based on their recent medication history.
    """

    def guess_illnesses(self, events: List[Dict]) -> List[str]:
        counts: Counter = Counter()
        for e in events:
            name = (e.get("medication_name") or "").lower()
            for key, illness in MED_TO_ILLNESS.items():
                if key in name:
                    counts[illness] += 1

        if not counts:
            return []

        # Return the top 3 most likely illnesses
        return [ill for ill, _ in counts.most_common(3)]

