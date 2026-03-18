#!/usr/bin/env python3
"""
Infer chronic illnesses from extracted medication names.
Takes medication name from label recognition output and uses an LLM to infer
the most likely chronic conditions it treats.
"""

import json
import argparse
import os
import requests
from typing import Optional, Dict, List
from pathlib import Path

# Path to persistent medication database
DB_PATH = Path(__file__).parent.parent / "data" / "medications_db.json"

def load_medication_db() -> Dict:
    """Load medications from persistent database."""
    if DB_PATH.exists():
        try:
            with open(DB_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_medication_db(db: Dict) -> None:
    """Save medications to persistent database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2)


def add_to_medication_db(medication_name: str, conditions: List) -> None:
    """Add a medication to the persistent database."""
    db = load_medication_db()
    med_lower = medication_name.lower().strip()
    if med_lower not in db:
        db[med_lower] = {"conditions": conditions}
        save_medication_db(db)
        print(f"💾 Saved '{medication_name}' to medications database")


# Medical knowledge base for fallback (no API calls)
MEDICATION_ILLNESS_MAP = {
    "metformin": {
        "conditions": [
            {
                "name": "Type 2 Diabetes Mellitus",
                "probability": 85,
                "reasoning": "Metformin is the first-line medication for type 2 diabetes, improving insulin sensitivity and reducing glucose production.",
                "management": "Monitor blood glucose regularly, maintain healthy diet low in refined carbohydrates, exercise 150+ min/week, maintain healthy weight."
            },
            {
                "name": "Prediabetes",
                "probability": 10,
                "reasoning": "Metformin is prescribed to prevent progression to type 2 diabetes in people with impaired glucose tolerance.",
                "management": "Lifestyle modifications are primary: diet changes, regular exercise, weight loss if overweight. Monitor glucose levels regularly."
            },
            {
                "name": "Polycystic Ovary Syndrome (PCOS)",
                "probability": 5,
                "reasoning": "Metformin is used off-label in PCOS to improve insulin resistance and regulate menstrual cycles.",
                "management": "Regular exercise, balanced diet, weight management, monitor reproductive health with gynecologist."
            }
        ]
    },
    "lisinopril": {
        "conditions": [
            {
                "name": "Hypertension (High Blood Pressure)",
                "probability": 80,
                "reasoning": "Lisinopril is an ACE inhibitor commonly prescribed as first-line therapy for hypertension.",
                "management": "Monitor blood pressure regularly, reduce sodium intake, exercise regularly, manage stress, limit alcohol."
            },
            {
                "name": "Heart Failure",
                "probability": 15,
                "reasoning": "ACE inhibitors improve survival and reduce symptoms in heart failure patients.",
                "management": "Follow DASH diet, limit fluid intake, monitor weight daily, take medications as prescribed, avoid strenuous exercise."
            },
            {
                "name": "Chronic Kidney Disease",
                "probability": 5,
                "reasoning": "ACE inhibitors provide renal protection in patients with diabetes and hypertension.",
                "management": "Monitor kidney function regularly, control blood pressure and blood glucose, limit protein and sodium intake."
            }
        ]
    },
    "atorvastatin": {
        "conditions": [
            {
                "name": "Hyperlipidemia (High Cholesterol)",
                "probability": 85,
                "reasoning": "Atorvastatin is a statin that reduces LDL cholesterol and is widely prescribed for cholesterol management.",
                "management": "Maintain low-saturated-fat diet, exercise regularly, maintain healthy weight, avoid smoking, monitor lipid levels."
            },
            {
                "name": "Coronary Artery Disease",
                "probability": 10,
                "reasoning": "Statins are prescribed to reduce cardiovascular events in patients with established CAD.",
                "management": "Follow heart-healthy diet, exercise as tolerated, manage stress, take all cardiac medications, attend cardiac rehabilitation."
            },
            {
                "name": "Type 2 Diabetes with Dyslipidemia",
                "probability": 5,
                "reasoning": "Diabetic patients often have elevated cholesterol and are prescribed statins for cardiovascular protection.",
                "management": "Manage both blood glucose and cholesterol, maintain healthy diet and exercise routine, regular monitoring."
            }
        ]
    },
    "amoxicillin": {
        "conditions": [
            {
                "name": "Acute Bacterial Infection (Respiratory/Ear/Skin)",
                "probability": 90,
                "reasoning": "Amoxicillin is a broad-spectrum antibiotic used to treat various acute bacterial infections.",
                "management": "Complete the full course of antibiotics as prescribed, rest, stay hydrated, manage fever with acetaminophen if needed."
            },
            {
                "name": "Recurrent Bacterial Infections",
                "probability": 8,
                "reasoning": "Patients with recurrent infections may need prophylactic or repeated antibiotic courses.",
                "management": "Identify underlying causes, boost immune system with good nutrition and sleep, practice infection prevention measures."
            },
            {
                "name": "Helicobacter pylori Infection",
                "probability": 2,
                "reasoning": "Amoxicillin is part of triple therapy for H. pylori-related gastric ulcers.",
                "management": "Complete the full antibiotic regimen, avoid NSAIDs, manage stress, eat smaller meals, avoid trigger foods."
            }
        ]
    },
    "omeprazole": {
        "conditions": [
            {
                "name": "Gastroesophageal Reflux Disease (GERD)",
                "probability": 70,
                "reasoning": "Omeprazole is a proton pump inhibitor commonly prescribed to reduce stomach acid and treat GERD symptoms.",
                "management": "Avoid trigger foods (spicy, acidic, fatty), eat smaller meals, don't eat 2-3 hours before bed, manage weight, reduce stress."
            },
            {
                "name": "Peptic Ulcer Disease",
                "probability": 20,
                "reasoning": "Omeprazole promotes ulcer healing and prevents recurrence by reducing acid secretion.",
                "management": "Avoid NSAIDs and aspirin if possible, manage stress, avoid smoking and alcohol, follow prescribed medication regimen."
            },
            {
                "name": "Zollinger-Ellison Syndrome",
                "probability": 10,
                "reasoning": "PPIs are essential for managing severe acid hypersecretion in this rare condition.",
                "management": "Strict medication adherence, monitor symptoms, work closely with gastroenterologist, manage any underlying complications."
            }
        ]
    },
    "levothyroxine": {
        "conditions": [
            {
                "name": "Hypothyroidism",
                "probability": 95,
                "reasoning": "Levothyroxine is the standard replacement therapy for hypothyroidism.",
                "management": "Take consistently on empty stomach, monitor TSH levels regularly, maintain stable iodine intake, manage weight and energy levels."
            },
            {
                "name": "Thyroid Cancer (Post-treatment)",
                "probability": 4,
                "reasoning": "High-dose levothyroxine is used post-thyroidectomy for cancer patients to suppress TSH.",
                "management": "Regular TSH and thyroglobulin monitoring, follow oncologist's directions closely, manage hypothyroid symptoms."
            },
            {
                "name": "Goiter",
                "probability": 1,
                "reasoning": "Levothyroxine may be used to suppress TSH and reduce goiter size in certain cases.",
                "management": "Ensure adequate iodine intake, regular monitoring of goiter size and thyroid function, medication compliance."
            }
        ]
    },
    "amoxici": {
        "conditions": [
            {
                "name": "Acute Bacterial Infection",
                "probability": 90,
                "reasoning": "Amoxicillin is a broad-spectrum antibiotic used for various bacterial infections.",
                "management": "Complete full antibiotic course, rest, stay hydrated, manage fever if needed."
            }
        ]
    },
    "nifedipine": {
        "conditions": [
            {
                "name": "Hypertension (High Blood Pressure)",
                "probability": 75,
                "reasoning": "Nifedipine is a calcium channel blocker commonly used to treat high blood pressure.",
                "management": "Monitor blood pressure regularly, reduce sodium intake, exercise, manage stress, limit alcohol."
            },
            {
                "name": "Angina Pectoris",
                "probability": 20,
                "reasoning": "Nifedipine reduces myocardial oxygen demand and improves coronary blood flow.",
                "management": "Take medication as prescribed, avoid strenuous activity, manage stress, follow heart-healthy diet, seek emergency help if severe chest pain."
            },
            {
                "name": "Raynaud's Phenomenon",
                "probability": 5,
                "reasoning": "Extended-release nifedipine may be used off-label to improve blood flow to extremities.",
                "management": "Keep hands and feet warm, avoid cold exposure, manage underlying conditions, regular monitoring by rheumatologist."
            }
        ]
    },
    "tacrolimus": {
        "conditions": [
            {
                "name": "Organ Transplant Rejection Prevention",
                "probability": 95,
                "reasoning": "Tacrolimus is a primary immunosuppressant used post-transplant to prevent organ rejection.",
                "management": "Strict medication adherence, regular monitoring of drug levels and kidney function, infection prevention, avoid certain drug interactions."
            },
            {
                "name": "Atopic Dermatitis (Eczema)",
                "probability": 4,
                "reasoning": "Topical tacrolimus is used for moderate to severe atopic dermatitis.",
                "management": "Regular skincare with emollients, avoid triggers, use sun protection, monitor for skin infections."
            },
            {
                "name": "Autoimmune Disease",
                "probability": 1,
                "reasoning": "Systemic tacrolimus may be used in severe autoimmune conditions.",
                "management": "Close monitoring by rheumatologist, manage underlying autoimmune condition, monitor for infections and organ toxicity."
            }
        ]
    },
    "zopatine": {
        "conditions": [
            {
                "name": "Schizophrenia/Psychotic Disorder",
                "probability": 80,
                "reasoning": "Paliperidone (similar antipsychotic) is used to treat schizophrenia and schizoaffective disorder.",
                "management": "Regular medication adherence, regular psychiatric monitoring, avoid alcohol, maintain social support, manage side effects."
            },
            {
                "name": "Bipolar Disorder",
                "probability": 15,
                "reasoning": "May be used as adjunctive therapy in bipolar disorder for mood stabilization.",
                "management": "Monitor mood changes, maintain consistent sleep schedule, avoid triggers, attend therapy, regular medication adherence."
            },
            {
                "name": "Major Depressive Disorder with Psychotic Features",
                "probability": 5,
                "reasoning": "Antipsychotics may be added to antidepressants for severe depression with psychosis.",
                "management": "Continue antidepressants, psychotherapy, regular psychiatric follow-up, lifestyle modifications."
            }
        ]
    },
    "sertraline": {
        "conditions": [
            {
                "name": "Major Depressive Disorder",
                "probability": 75,
                "reasoning": "Sertraline is an SSRI commonly prescribed as first-line treatment for depression.",
                "management": "Therapy alongside medication, maintain regular sleep schedule, exercise, avoid alcohol, monitor mood changes."
            },
            {
                "name": "Generalized Anxiety Disorder",
                "probability": 15,
                "reasoning": "SSRIs like sertraline are effective for treating anxiety disorders.",
                "management": "Cognitive behavioral therapy, relaxation techniques, regular exercise, limit caffeine, mindfulness practices."
            },
            {
                "name": "Panic Disorder",
                "probability": 7,
                "reasoning": "Sertraline reduces panic attack frequency and severity.",
                "management": "Breathing exercises, avoid triggers, therapy, maintain routine, avoid stimulants."
            },
            {
                "name": "PTSD/OCD",
                "probability": 3,
                "reasoning": "SSRIs are used for obsessive-compulsive disorder and post-traumatic stress disorder.",
                "management": "Exposure therapy, cognitive behavioral therapy, trauma processing, medication adherence."
            }
        ]
    },
    "albuterol": {
        "conditions": [
            {
                "name": "Asthma",
                "probability": 85,
                "reasoning": "Albuterol is a short-acting bronchodilator used to relieve acute asthma symptoms and attacks.",
                "management": "Use inhaler during attacks, avoid triggers, regular peak flow monitoring, maintain asthma action plan."
            },
            {
                "name": "COPD (Chronic Obstructive Pulmonary Disease)",
                "probability": 12,
                "reasoning": "Albuterol helps open airways and improve breathing in COPD patients.",
                "management": "Quit smoking if applicable, pulmonary rehabilitation, oxygen therapy if needed, regular monitoring."
            },
            {
                "name": "Acute Bronchitis",
                "probability": 3,
                "reasoning": "May be used temporarily to relieve airway constriction during acute infection.",
                "management": "Rest, fluids, humidifier, monitor for complications, follow up if symptoms persist."
            }
        ]
    },
    "warfarin": {
        "conditions": [
            {
                "name": "Atrial Fibrillation",
                "probability": 60,
                "reasoning": "Warfarin is an anticoagulant used to prevent blood clots and stroke in patients with AFib.",
                "management": "Regular INR monitoring, consistent diet with vitamin K, avoid NSAIDs, report bleeding, maintain appointments."
            },
            {
                "name": "Deep Vein Thrombosis (DVT)/Pulmonary Embolism",
                "probability": 25,
                "reasoning": "Warfarin prevents clot formation and reduces risk of recurrent thromboembolic events.",
                "management": "Leg elevation, compression stockings, monitor for swelling/pain, regular INR tests, mobility when possible."
            },
            {
                "name": "Mechanical Heart Valve",
                "probability": 10,
                "reasoning": "Warfarin is essential for preventing thrombosis around mechanical prosthetic valves.",
                "management": "Strict INR monitoring, avoid contact sports, alert healthcare providers about procedure needs."
            },
            {
                "name": "Hypercoagulable Disorders",
                "probability": 5,
                "reasoning": "Used for inherited or acquired conditions causing excessive clotting.",
                "management": "Genetic counseling if inherited, avoid risk factors, regular hematology follow-up, family screening."
            }
        ]
    },
    "prednisone": {
        "conditions": [
            {
                "name": "Autoimmune Diseases (Lupus, Rheumatoid Arthritis)",
                "probability": 70,
                "reasoning": "Prednisone is a corticosteroid used to suppress immune system and reduce inflammation.",
                "management": "Take with food, bone density monitoring, calcium/vitamin D supplementation, avoid infections, taper slowly."
            },
            {
                "name": "Asthma/Severe Allergic Reactions",
                "probability": 15,
                "reasoning": "Used for acute asthma exacerbations and severe allergic responses.",
                "management": "Take exactly as prescribed, monitor for side effects, avoid stopping abruptly, follow-up with specialist."
            },
            {
                "name": "Inflammatory Bowel Disease (Crohn's/Ulcerative Colitis)",
                "probability": 10,
                "reasoning": "Reduces intestinal inflammation during acute flare-ups.",
                "management": "Nutritional support, monitor electrolytes, infection prevention, gradual taper, gastroenterologist follow-up."
            },
            {
                "name": "Chronic Obstructive Pulmonary Disease (COPD)",
                "probability": 5,
                "reasoning": "May be used during acute exacerbations to improve airflow.",
                "management": "Smoking cessation, pulmonary rehabilitation, monitor for side effects during long-term use."
            }
        ]
    },
    "amlodipine": {
        "conditions": [
            {
                "name": "Hypertension (High Blood Pressure)",
                "probability": 80,
                "reasoning": "Amlodipine is a calcium channel blocker commonly used as first-line therapy for hypertension.",
                "management": "Monitor blood pressure regularly, reduce sodium intake, exercise regularly, manage stress, limit alcohol."
            },
            {
                "name": "Coronary Artery Disease/Angina",
                "probability": 15,
                "reasoning": "Improves blood flow to the heart and reduces anginal episodes.",
                "management": "Chest pain monitoring, exercise as tolerated, stress management, take medications consistently."
            },
            {
                "name": "Raynaud's Phenomenon",
                "probability": 5,
                "reasoning": "May improve blood flow to extremities in severe cases.",
                "management": "Keep hands and feet warm, avoid cold exposure, avoid vasoconstrictive drugs, regular monitoring."
            }
        ]
    }
}


def infer_from_local_kb(medication_name: str) -> Dict:
    """
    Infer chronic illnesses from local knowledge base (built-in + database).
    
    Args:
        medication_name: Name of the medication
        
    Returns:
        Dictionary with inferred conditions
    """
    med_lower = medication_name.lower().strip()
    
    # Load from persistent database first
    user_db = load_medication_db()
    
    # Try exact match in user database first
    if med_lower in user_db:
        return {
            "medication_name": medication_name,
            "source": "user_database",
            "conditions": user_db[med_lower]["conditions"]
        }
    
    # Try exact match in built-in knowledge base
    if med_lower in MEDICATION_ILLNESS_MAP:
        return {
            "medication_name": medication_name,
            "source": "local_knowledge_base",
            "conditions": MEDICATION_ILLNESS_MAP[med_lower]["conditions"]
        }
    
    # Try partial match in user database
    for med_key, data in user_db.items():
        if med_key in med_lower or med_lower in med_key:
            return {
                "medication_name": medication_name,
                "source": "user_database",
                "conditions": data["conditions"]
            }
    
    # Try partial match in built-in knowledge base
    for med_key, data in MEDICATION_ILLNESS_MAP.items():
        if med_key in med_lower or med_lower in med_key:
            return {
                "medication_name": medication_name,
                "source": "local_knowledge_base",
                "conditions": data["conditions"]
            }
    
    # Default fallback
    return {
        "medication_name": medication_name,
        "source": "local_knowledge_base",
        "conditions": [
            {
                "name": "Unknown - Consult Healthcare Provider",
                "probability": 100,
                "reasoning": "Medication not in knowledge base. Please consult with a healthcare provider for accurate information.",
                "management": "Consult with your doctor or pharmacist for specific information about this medication."
            }
        ]
    }


def infer_with_llm(medication_name: str, api_key: str, api_url: str = "https://api.sea-lion.ai/v1/chat/completions") -> Optional[Dict]:
    """
    Infer chronic illnesses using LLM API.
    
    Args:
        medication_name: Name of the medication
        api_key: API key for LLM service
        api_url: URL of the LLM API endpoint
        
    Returns:
        Dictionary with inferred conditions or None if API call fails
    """
    prompt = f"""You are a medical knowledge assistant. Given a medication name, infer the top 3-5 most likely chronic illnesses it is commonly prescribed to treat.

For each condition, provide:
1. Condition name
2. Estimated probability (as a percentage)
3. Reasoning (why this medication is used for this condition)
4. General management advice (lifestyle/treatment tips)

Format your response as a JSON object with the following structure:
{{
  "conditions": [
    {{
      "name": "Condition Name",
      "probability": 80,
      "reasoning": "Why this medication treats this condition",
      "management": "Advice for managing this condition"
    }}
  ]
}}

Medication: {medication_name}

IMPORTANT: Return ONLY valid JSON, no additional text."""

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        payload = {
            "model": "aisingapore/Gemma-SEA-LION-v4-27B-IT",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_completion_tokens": 1000,
            "temperature": 0.7
        }
        
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0]["message"]["content"]
            
            # Parse JSON from response
            try:
                conditions_data = json.loads(content)
                return {
                    "medication_name": medication_name,
                    "source": "llm_api",
                    "conditions": conditions_data.get("conditions", [])
                }
            except json.JSONDecodeError:
                # Try to extract JSON from text
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    try:
                        conditions_data = json.loads(json_match.group())
                        return {
                            "medication_name": medication_name,
                            "source": "llm_api",
                            "conditions": conditions_data.get("conditions", [])
                        }
                    except json.JSONDecodeError:
                        pass
        
        return None
        
    except Exception as e:
        print(f"Error calling LLM API: {e}")
        return None


def infer_chronic_illness(medication_name: str, use_llm: bool = True, api_key: Optional[str] = None, auto_save: bool = True) -> Dict:
    """
    Infer chronic illnesses from medication name.
    
    Args:
        medication_name: Name of the medication
        use_llm: Whether to use LLM API for unknown medications (default: True, auto-enables if api_key provided)
        api_key: API key for LLM service
        auto_save: Whether to automatically save new medications to database
        
    Returns:
        Dictionary with inferred conditions
    """
    med_lower = medication_name.lower().strip()
    user_db = load_medication_db()
    
    # Check if medication already exists in database or knowledge base
    if med_lower in user_db or med_lower in MEDICATION_ILLNESS_MAP:
        # Return existing data
        return infer_from_local_kb(medication_name)
    
    # Medication is unseen - try LLM if available
    if api_key:  # Auto-enable LLM if API key is provided
        print(f"🔄 Generating inference for '{medication_name}'...")
        llm_result = infer_with_llm(medication_name, api_key)
        if llm_result:
            if auto_save:
                # Save the LLM result to database for future use
                add_to_medication_db(medication_name, llm_result["conditions"])
                print(f"✅ Learned new medication: {medication_name}")
            return llm_result
    
    # Fall back to local knowledge base (returns "Unknown" placeholder)
    result = infer_from_local_kb(medication_name)
    return result


def format_output(result: Dict, output_format: str = "json") -> str:
    """
    Format the inference result.
    
    Args:
        result: Dictionary with inferred conditions
        output_format: Output format ("json", "text", or "markdown")
        
    Returns:
        Formatted string
    """
    if output_format == "json":
        return json.dumps(result, indent=2)
    
    elif output_format == "text":
        lines = [f"\n=== Possible Chronic Conditions for {result['medication_name']} ===\n"]
        for i, condition in enumerate(result.get("conditions", []), 1):
            lines.append(f"{i}. {condition['name']}")
            lines.append(f"   Estimated Probability: {condition['probability']}%")
            lines.append(f"   Reasoning: {condition['reasoning']}")
            lines.append(f"   General Management Advice: {condition['management']}")
            lines.append("")
        lines.append("Important Note: Medication use does not guarantee the patient has the listed condition.")
        lines.append("Results are probabilistic inference based on typical medical usage.\n")
        return "\n".join(lines)
    
    elif output_format == "markdown":
        lines = [f"# Possible Chronic Conditions for {result['medication_name']}\n"]
        for i, condition in enumerate(result.get("conditions", []), 1):
            lines.append(f"## {i}. {condition['name']}")
            lines.append(f"**Estimated Probability:** {condition['probability']}%\n")
            lines.append(f"**Reasoning:** {condition['reasoning']}\n")
            lines.append(f"**General Management Advice:** {condition['management']}\n")
        lines.append("---")
        lines.append("**Important Note:** Medication use does not guarantee the patient has the listed condition.")
        lines.append("Results are probabilistic inference based on typical medical usage.\n")
        return "\n".join(lines)
    
    return json.dumps(result, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Infer chronic illnesses from medication names"
    )
    parser.add_argument(
        "--medication", "-m",
        required=True,
        help="Medication name to infer illnesses for"
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("SEA_LION_API_KEY"),
        help="API key for LLM service (or set SEA_LION_API_KEY env var). If provided, unknown medications will be generated on-the-fly."
    )
    parser.add_argument(
        "--output-format", "-f",
        choices=["json", "text", "markdown"],
        default="json",
        help="Output format"
    )
    parser.add_argument(
        "--save-json", "-s",
        help="Save output to JSON file"
    )
    parser.add_argument(
        "--no-auto-save",
        action="store_true",
        help="Don't automatically save new medications to database"
    )
    
    args = parser.parse_args()
    
    # Infer chronic illnesses (auto-uses LLM if API key is available)
    result = infer_chronic_illness(
        args.medication,
        use_llm=True,  # Always enabled; auto-detects via api_key
        api_key=args.api_key,
        auto_save=not args.no_auto_save
    )
    
    # Format and print output
    formatted = format_output(result, args.output_format)
    print(formatted)
    
    # Save JSON if requested
    if args.save_json:
        with open(args.save_json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\n✅ Saved to {args.save_json}")
    
    return result


if __name__ == "__main__":
    main()
