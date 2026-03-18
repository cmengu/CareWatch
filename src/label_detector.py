"""
label_detector.py
=================
Medication label scanner for CareWatch.

Ported and hardened from PillReminder's medication.py MedicationLabelDetector.

Production path: swap extract_from_image() body to call a real vision API
(Gemini Vision, GPT-4o, or an on-device OCR model). The rest of the pipeline
is unchanged.

Demo / eval path: returns realistic mock prescriptions with simulated latency.

USAGE (called by scan_node in graph.py):
    from src.label_detector import MedicationLabelDetector
    detector = MedicationLabelDetector()
    result = detector.extract_from_image(file_bytes)
    # {"medication_name": "Metformin", "dose": "500mg", "meal_relation": "after", "confidence": 0.94}
"""

import logging
import random
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.75


class MedicationLabelDetector:
    """
    Vision module that extracts structured medication info from a pill bottle image.

    Returns a dict with keys:
        medication_name  str   — e.g. "Metformin"
        dose             str   — e.g. "500mg"
        meal_relation    str   — "before" | "after" | "fixed"
        confidence       float — 0.0–1.0

    meal_relation reflects real-world clinical usage:
        "before" — must be taken before food (e.g. Omeprazole, 30 min pre-meal)
        "after"  — must be taken with/after food (e.g. Metformin, reduces GI upset)
        "fixed"  — time-fixed, food-independent (e.g. Amlodipine)
    """

    _MOCK_RESPONSES = [
        {"medication_name": "Metformin",    "dose": "500mg",  "meal_relation": "after",  "confidence": 0.94},
        {"medication_name": "Amlodipine",   "dose": "5mg",    "meal_relation": "fixed",  "confidence": 0.91},
        {"medication_name": "Lisinopril",   "dose": "10mg",   "meal_relation": "fixed",  "confidence": 0.88},
        {"medication_name": "Atorvastatin", "dose": "20mg",   "meal_relation": "after",  "confidence": 0.93},
        {"medication_name": "Omeprazole",   "dose": "20mg",   "meal_relation": "before", "confidence": 0.96},
        {"medication_name": "Warfarin",     "dose": "5mg",    "meal_relation": "fixed",  "confidence": 0.89},
        {"medication_name": "Sertraline",   "dose": "50mg",   "meal_relation": "after",  "confidence": 0.87},
        {"medication_name": "Levothyroxine","dose": "50mcg",  "meal_relation": "before", "confidence": 0.92},
    ]

    def extract_from_image(self, file_bytes: bytes) -> Dict[str, Any]:
        """
        Extract structured medication info from raw image bytes.

        Production replacement (swap this body):
        -----------------------------------------
            import google.generativeai as genai
            model = genai.GenerativeModel("gemini-1.5-flash")
            image_blob = {"mime_type": "image/jpeg", "data": file_bytes}
            prompt = (
                "Extract the medication name, dose, and whether it should be taken "
                "before or after food from this pill bottle label. "
                "Return ONLY valid JSON: "
                "{\"medication_name\": str, \"dose\": str, \"meal_relation\": "
                "\"before\"|\"after\"|\"fixed\", \"confidence\": float 0-1}"
            )
            response = model.generate_content([image_blob, prompt])
            import json
            return json.loads(response.text)
        """
        if not file_bytes:
            raise ValueError("extract_from_image: received empty image bytes")
        time.sleep(random.uniform(1.0, 2.0))
        result = random.choice(self._MOCK_RESPONSES).copy()
        logger.info(
            "label_detector: scan result — %s %s (confidence=%.2f, meal_relation=%s)",
            result["medication_name"], result["dose"],
            result["confidence"], result["meal_relation"],
        )
        return result

    def is_confident(self, scan_result: Dict[str, Any]) -> bool:
        return float(scan_result.get("confidence", 0.0)) >= CONFIDENCE_THRESHOLD
