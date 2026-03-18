"""
chronic_detector.py
====================
Infers chronic illness conditions from a resident's medication history.

Two lookup layers:
  1. Local knowledge base — fast, offline, covers ~15 common medications
  2. LLM fallback — Groq (already used in CareWatch) or SEA-LION for unknowns

Primary entry point for ChronicAgent:
    ChronicDetector().detect(events) -> ChronicResult

Secondary entry point for MedScanAgent enrichment:
    ChronicDetector().infer_from_name(medication_name) -> Dict
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "medications_db.json"

MED_TO_ILLNESS: Dict[str, str] = {
    "metformin":     "Type 2 Diabetes",
    "insulin":       "Type 2 Diabetes",
    "glipizide":     "Type 2 Diabetes",
    "gliclazide":    "Type 2 Diabetes",
    "amlodipine":    "Hypertension",
    "losartan":      "Hypertension",
    "valsartan":     "Hypertension",
    "lisinopril":    "Hypertension",
    "nifedipine":    "Hypertension",
    "atorvastatin":  "Hyperlipidemia",
    "simvastatin":   "Hyperlipidemia",
    "rosuvastatin":  "Hyperlipidemia",
    "allopurinol":   "Gout",
    "colchicine":    "Gout",
    "omeprazole":    "Acid Reflux (GERD)",
    "pantoprazole":  "Acid Reflux (GERD)",
    "esomeprazole":  "Acid Reflux (GERD)",
    "warfarin":      "Atrial Fibrillation / Thrombosis",
    "sertraline":    "Depression / Anxiety",
    "levothyroxine": "Hypothyroidism",
    "prednisone":    "Autoimmune / Inflammatory Disease",
    "albuterol":     "Asthma / COPD",
    "amoxicillin":   "Bacterial Infection",
}

_DETAILED_MAP: Dict[str, List[Dict]] = {
    "metformin": [
        {"name": "Type 2 Diabetes Mellitus", "probability": 85,
         "reasoning": "First-line medication for T2DM — improves insulin sensitivity.",
         "management": "Monitor blood glucose regularly, low-carb diet, 150+ min exercise/week."},
        {"name": "Prediabetes", "probability": 10,
         "reasoning": "Prevents progression to T2DM in high-risk individuals.",
         "management": "Lifestyle modifications primary — diet, exercise, weight loss."},
    ],
    "lisinopril": [
        {"name": "Hypertension", "probability": 80,
         "reasoning": "ACE inhibitor, first-line for high blood pressure.",
         "management": "Monitor BP, reduce sodium, regular exercise, limit alcohol."},
        {"name": "Heart Failure", "probability": 15,
         "reasoning": "ACE inhibitors improve survival in heart failure.",
         "management": "Limit fluids, monitor weight daily, avoid strenuous exercise."},
    ],
    "atorvastatin": [
        {"name": "Hyperlipidemia (High Cholesterol)", "probability": 85,
         "reasoning": "Statin reducing LDL cholesterol, first-line therapy.",
         "management": "Low saturated fat diet, exercise regularly, monitor lipid panel."},
        {"name": "Coronary Artery Disease", "probability": 10,
         "reasoning": "Statins prescribed to reduce cardiovascular events in established CAD.",
         "management": "Heart-healthy diet, exercise as tolerated, stress management."},
    ],
    "omeprazole": [
        {"name": "Gastroesophageal Reflux Disease (GERD)", "probability": 70,
         "reasoning": "PPI reduces stomach acid and treats GERD symptoms.",
         "management": "Avoid trigger foods, eat smaller meals, no eating 2-3h before bed."},
        {"name": "Peptic Ulcer Disease", "probability": 20,
         "reasoning": "Promotes ulcer healing by reducing acid secretion.",
         "management": "Avoid NSAIDs, manage stress, no smoking or alcohol."},
    ],
    "warfarin": [
        {"name": "Atrial Fibrillation", "probability": 60,
         "reasoning": "Anticoagulant preventing stroke in AFib patients.",
         "management": "Regular INR monitoring, consistent vitamin K diet, avoid NSAIDs."},
        {"name": "Deep Vein Thrombosis", "probability": 25,
         "reasoning": "Prevents recurrent thromboembolic events.",
         "management": "Leg elevation, compression stockings, regular INR tests."},
        {"name": "Mechanical Heart Valve", "probability": 10,
         "reasoning": "Essential for preventing thrombosis around prosthetic valves.",
         "management": "Strict INR monitoring, alert all healthcare providers before procedures."},
    ],
    "sertraline": [
        {"name": "Major Depressive Disorder", "probability": 75,
         "reasoning": "SSRI, first-line antidepressant.",
         "management": "Therapy alongside medication, regular sleep, exercise, avoid alcohol."},
        {"name": "Generalised Anxiety Disorder", "probability": 15,
         "reasoning": "SSRIs effective for anxiety disorders.",
         "management": "CBT, relaxation techniques, limit caffeine, mindfulness."},
    ],
    "levothyroxine": [
        {"name": "Hypothyroidism", "probability": 95,
         "reasoning": "Standard thyroid hormone replacement therapy.",
         "management": "Take on empty stomach consistently, monitor TSH levels."},
    ],
    "amlodipine": [
        {"name": "Hypertension", "probability": 80,
         "reasoning": "Calcium channel blocker for hypertension.",
         "management": "Monitor BP, reduce sodium, exercise, manage stress."},
        {"name": "Coronary Artery Disease / Angina", "probability": 15,
         "reasoning": "Improves coronary blood flow and reduces anginal episodes.",
         "management": "Monitor chest pain, exercise as tolerated, stress management."},
    ],
    "prednisone": [
        {"name": "Autoimmune Disease (Lupus / Rheumatoid Arthritis)", "probability": 70,
         "reasoning": "Corticosteroid suppressing immune system to reduce inflammation.",
         "management": "Take with food, bone density monitoring, calcium/vitamin D, avoid infections."},
        {"name": "Asthma / Severe Allergic Reactions", "probability": 15,
         "reasoning": "Used for acute asthma exacerbations and severe allergic responses.",
         "management": "Do not stop abruptly, monitor for side effects, follow specialist."},
    ],
    "albuterol": [
        {"name": "Asthma", "probability": 85,
         "reasoning": "Short-acting bronchodilator for acute asthma symptom relief.",
         "management": "Keep inhaler accessible, avoid triggers, regular peak flow monitoring."},
        {"name": "COPD", "probability": 12,
         "reasoning": "Helps open airways in COPD patients.",
         "management": "Smoking cessation if applicable, pulmonary rehabilitation."},
    ],
}

_HIGH_CONCERN_CONDITIONS = {
    "Type 2 Diabetes Mellitus", "Type 2 Diabetes", "Heart Failure",
    "Atrial Fibrillation", "Coronary Artery Disease", "COPD",
    "Autoimmune Disease (Lupus / Rheumatoid Arthritis)",
}


def _load_db() -> Dict:
    if _DB_PATH.exists():
        try:
            with open(_DB_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_db(db: Dict) -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_DB_PATH, "w") as f:
        json.dump(db, f, indent=2)


def _add_to_db(medication_name: str, conditions: List[Dict]) -> None:
    db = _load_db()
    key = medication_name.lower().strip()
    if key not in db:
        db[key] = {"conditions": conditions}
        _save_db(db)
        logger.info("chronic_detector: saved '%s' to medications_db.json", medication_name)


@dataclass
class ChronicResult:
    inferred_conditions: List[Dict] = field(default_factory=list)
    top_illnesses:       List[str]  = field(default_factory=list)
    medication_count:    int        = 0
    source:              str        = "local_knowledge_base"
    concern_level:       str        = "normal"
    summary:             str        = ""

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)


class ChronicDetector:
    MIN_EVENTS_FOR_INFERENCE = 2

    def detect(self, events: List[Dict]) -> ChronicResult:
        if len(events) < self.MIN_EVENTS_FOR_INFERENCE:
            return ChronicResult(
                summary="Insufficient medication history for chronic condition inference.",
                medication_count=len(events),
            )

        counts: Counter = Counter()
        all_conditions: List[Dict] = []
        seen_names: set = set()

        for event in events:
            name = (event.get("medication_name") or "").lower().strip()
            for key, illness in MED_TO_ILLNESS.items():
                if key in name:
                    counts[illness] += 1
            for key, conditions in _DETAILED_MAP.items():
                if key in name:
                    for c in conditions:
                        if c["name"] not in seen_names:
                            all_conditions.append(c)
                            seen_names.add(c["name"])

        if not counts:
            return ChronicResult(
                summary="No known chronic medications detected in recent medication history.",
                medication_count=len(events),
            )

        top_illnesses = [ill for ill, _ in counts.most_common(3)]
        all_conditions.sort(key=lambda c: c.get("probability", 0), reverse=True)

        concern = "normal"
        if len(top_illnesses) >= 3:
            concern = "watch"
        if any(c["name"] in _HIGH_CONCERN_CONDITIONS for c in all_conditions):
            concern = "watch"

        illness_str = ", ".join(top_illnesses)
        summary = (
            f"Medication history suggests ongoing management of: {illness_str}. "
            f"Based on {len(events)} medication events over the past 30 days. "
            "Caregivers should ensure medications are taken consistently."
        )

        return ChronicResult(
            inferred_conditions=all_conditions[:5],
            top_illnesses=top_illnesses,
            medication_count=len(events),
            source="local_knowledge_base",
            concern_level=concern,
            summary=summary,
        )

    def infer_from_name(
        self,
        medication_name: str,
        api_key: Optional[str] = None,
        auto_save: bool = True,
    ) -> Dict:
        key = medication_name.lower().strip()
        user_db = _load_db()

        if key in user_db:
            return {"medication_name": medication_name, "source": "user_database",
                    "conditions": user_db[key]["conditions"]}

        for med_key, conditions in _DETAILED_MAP.items():
            if med_key in key or key in med_key:
                return {"medication_name": medication_name, "source": "local_knowledge_base",
                        "conditions": conditions}

        effective_key = api_key or os.environ.get("GROQ_API_KEY") or os.environ.get("SEA_LION_API_KEY")
        if effective_key:
            result = self._query_llm(medication_name, effective_key)
            if result:
                if auto_save:
                    _add_to_db(medication_name, result["conditions"])
                return result

        return {
            "medication_name": medication_name,
            "source": "unknown",
            "conditions": [{"name": "Unknown — consult healthcare provider", "probability": 100,
                            "reasoning": "Medication not in knowledge base.",
                            "management": "Consult your doctor or pharmacist for specific guidance."}],
        }

    def _query_llm(self, medication_name: str, api_key: str) -> Optional[Dict]:
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            result = self._query_groq(medication_name, groq_key)
            if result:
                return result
        return self._query_sea_lion(medication_name, api_key)

    def _query_groq(self, medication_name: str, api_key: str) -> Optional[Dict]:
        _PROMPT = (
            f"Given the medication '{medication_name}', list the top 3 chronic conditions it treats. "
            "Return ONLY valid JSON with no preamble: "
            "{\"conditions\": [{\"name\": str, \"probability\": int, "
            "\"reasoning\": str, \"management\": str}]}"
        )
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": _PROMPT}],
                max_tokens=500, temperature=0.1,
            )
            data = json.loads(resp.choices[0].message.content)
            return {"medication_name": medication_name, "source": "llm_groq",
                    "conditions": data.get("conditions", [])}
        except Exception as e:
            logger.warning("chronic_detector: Groq query failed: %s", e)
            return None

    def _query_sea_lion(self, medication_name: str, api_key: str) -> Optional[Dict]:
        _PROMPT = (
            f"Given the medication '{medication_name}', list the top 3 chronic conditions it treats. "
            "Return ONLY valid JSON with no preamble: "
            "{\"conditions\": [{\"name\": str, \"probability\": int, "
            "\"reasoning\": str, \"management\": str}]}"
        )
        try:
            import requests
            resp = requests.post(
                "https://api.sea-lion.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "aisingapore/Gemma-SEA-LION-v4-27B-IT",
                      "messages": [{"role": "user", "content": _PROMPT}],
                      "max_completion_tokens": 500, "temperature": 0.1},
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return {"medication_name": medication_name, "source": "llm_sea_lion",
                    "conditions": data.get("conditions", [])}
        except Exception as e:
            logger.warning("chronic_detector: SEA-LION query failed: %s", e)
            return None
