"""
rag_ground_truth.py
===================
25 ground-truth (query, relevant_keywords) pairs for RAG retrieval evaluation.

relevant_keywords: list of strings that must ALL appear in a retrieved document
for it to count as relevant. Case-insensitive match.

Design principle: keywords are specific enough to identify one or two facts,
but not so specific that they match only by exact phrase. This makes the
ground truth robust to minor phrasing changes in the knowledge base.
"""

from dataclasses import dataclass


@dataclass
class RAGGroundTruth:
    query_id: str
    query: str  # sent to ChromaDB as query_texts
    relevant_keywords: list[str]  # ALL must appear in a doc for it to be relevant
    min_relevant_docs: int = 1  # minimum number of docs that should be relevant


GROUND_TRUTH = [
    # Fall response
    RAGGroundTruth(
        "Q01",
        "fall detected elderly resident emergency response",
        ["fall", "emergency", "995"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q02",
        "fall conscious resident what to do",
        ["conscious", "alert", "fall"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q03",
        "hip fracture signs after fall elderly",
        ["hip", "fracture", "bear weight"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q04",
        "head injury after fall symptoms to watch",
        ["head", "confusion", "vomiting"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q05",
        "fall monitoring frequency after event",
        ["30 minutes", "4 hours", "fall"],
        min_relevant_docs=1,
    ),
    # Medication
    RAGGroundTruth(
        "Q06",
        "warfarin missed dose stroke risk",
        ["warfarin", "stroke"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q07",
        "warfarin aspirin interaction bleeding",
        ["warfarin", "aspirin", "bleeding"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q08",
        "missed medication morning window elderly",
        ["morning", "pill", "10am"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q09",
        "anticoagulant timing critical dose late",
        ["anticoagulants", "2 hours", "caregiver"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q10",
        "diuretic fall risk bathroom night",
        ["diuretic", "urination", "fall"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q11",
        "sedative benzodiazepine balance fall risk",
        ["benzodiazepine", "balance", "fall"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q12",
        "metformin diabetic missed dose hyperglycemia",
        ["metformin", "hyperglycemia"],
        min_relevant_docs=1,
    ),
    # Eating and nutrition
    RAGGroundTruth(
        "Q13",
        "missed meal insulin hypoglycemia risk",
        ["hypoglycaemia", "insulin", "emergency"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q14",
        "diabetic resident meal timing insulin",
        ["diabetic", "meal", "blood sugar"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q15",
        "appetite loss elderly depression infection",
        ["appetite", "depression", "infection"],
        min_relevant_docs=1,
    ),
    # Walking and activity
    RAGGroundTruth(
        "Q16",
        "reduced walking activity fall fear pain",
        ["walking", "physiotherapy", "pain"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q17",
        "night walking fall risk elderly",
        ["night", "fall risk", "walking"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q18",
        "prolonged sitting dvt pressure sores",
        ["sitting", "thrombosis", "pressure"],
        min_relevant_docs=1,
    ),
    # Night wandering
    RAGGroundTruth(
        "Q19",
        "night wandering dementia sundowning",
        ["wandering", "dementia", "sundowning"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q20",
        "night wandering safety pathway lights",
        ["wandering", "night lights", "stairways"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q21",
        "night wandering pain analgesic timing",
        ["wandering", "pain", "analgesic"],
        min_relevant_docs=1,
    ),
    # Monitoring and alerting
    RAGGroundTruth(
        "Q22",
        "high severity anomaly notification time",
        ["HIGH severity", "15 minutes"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q23",
        "escalating trend risk score monitoring",
        ["escalating", "3", "consecutive"],
        min_relevant_docs=1,
    ),
    RAGGroundTruth(
        "Q24",
        "dehydration dizziness fall risk elderly",
        ["dehydration", "dizziness", "fall"],
        min_relevant_docs=1,
    ),
    # Emergency contacts
    RAGGroundTruth(
        "Q25",
        "singapore emergency ambulance number",
        ["995", "Singapore"],
        min_relevant_docs=1,
    ),
]
