#!/usr/bin/env python3
"""
Medical Knowledge Assistant: Infer chronic illnesses from medication name.
Given a medication, infer the most likely chronic illnesses it's prescribed for.
Results can be returned as JSON and posted via curl.
"""

import json
import argparse
from typing import Dict, List, Optional

# Medication to chronic condition mapping
MEDICATION_CONDITIONS = {
    "metformin": {
        "conditions": [
            {
                "name": "Type 2 Diabetes Mellitus",
                "probability": 85,
                "reasoning": "Metformin is a first-line medication for type 2 diabetes. It works by reducing glucose production in the liver and improving insulin sensitivity.",
                "management": "Maintain regular blood glucose monitoring, follow a balanced diet low in refined carbohydrates, engage in regular physical activity (150 min/week), maintain healthy weight, and attend regular medical checkups."
            },
            {
                "name": "Prediabetes",
                "probability": 60,
                "reasoning": "Metformin is prescribed to prediabetic patients to slow progression to type 2 diabetes and improve glucose tolerance.",
                "management": "Lifestyle modifications are primary: reduce weight by 5-10%, increase physical activity, reduce sugar intake, focus on whole grains and fiber, and monitor blood glucose regularly."
            },
            {
                "name": "Polycystic Ovary Syndrome (PCOS)",
                "probability": 40,
                "reasoning": "Metformin is used in PCOS management to improve insulin resistance, regulate menstrual cycles, and improve fertility outcomes.",
                "management": "Maintain healthy weight through balanced diet and exercise, monitor hormonal levels, manage stress, consider fertility treatments if needed, and regular gynecological checkups."
            },
            {
                "name": "Metabolic Syndrome",
                "probability": 35,
                "reasoning": "Metformin helps manage insulin resistance component of metabolic syndrome, which includes hypertension, dyslipidemia, and central obesity.",
                "management": "Comprehensive lifestyle changes: reduce weight, increase physical activity, adopt Mediterranean or DASH diet, reduce sodium intake, limit alcohol, and manage stress."
            },
            {
                "name": "Gestational Diabetes",
                "probability": 25,
                "reasoning": "Metformin may be used during pregnancy to manage elevated blood glucose levels without the teratogenic risks of some other medications.",
                "management": "Regular glucose monitoring, dietary modifications focusing on complex carbohydrates, moderate physical activity, frequent prenatal checkups, and monitoring for maternal/fetal complications."
            }
        ]
    },
    "lisinopril": {
        "conditions": [
            {
                "name": "Hypertension (High Blood Pressure)",
                "probability": 90,
                "reasoning": "Lisinopril is an ACE inhibitor commonly prescribed as first-line therapy for hypertension to reduce blood pressure and cardiovascular risk.",
                "management": "Monitor blood pressure regularly, reduce sodium intake to <2300mg/day, maintain healthy weight, exercise regularly, limit alcohol, manage stress, and avoid smoking."
            },
            {
                "name": "Heart Failure",
                "probability": 75,
                "reasoning": "Lisinopril improves cardiac function by reducing afterload and promoting vasodilation, and is recommended in most heart failure guidelines.",
                "management": "Fluid restriction, salt restriction, regular monitoring of weight and symptoms, cardiac rehabilitation, avoid NSAIDs, and maintain medication adherence."
            },
            {
                "name": "Chronic Kidney Disease",
                "probability": 60,
                "reasoning": "Lisinopril provides renoprotective effects by reducing proteinuria and slowing kidney function decline, especially in diabetic nephropathy.",
                "management": "Monitor kidney function regularly (creatinine, GFR), control blood pressure, manage diabetes if present, limit protein intake, and avoid nephrotoxic medications."
            },
            {
                "name": "Myocardial Infarction (Post-MI Recovery)",
                "probability": 55,
                "reasoning": "ACE inhibitors like lisinopril reduce mortality post-MI by improving left ventricular remodeling and reducing heart failure development.",
                "management": "Cardiac rehabilitation, stress testing, monitor for signs of heart failure, lifestyle modifications, and adherence to full medication regimen."
            }
        ]
    },
    "atorvastatin": {
        "conditions": [
            {
                "name": "Hyperlipidemia (High Cholesterol)",
                "probability": 90,
                "reasoning": "Atorvastatin is a statin that reduces LDL cholesterol by inhibiting HMG-CoA reductase, commonly prescribed for elevated cholesterol.",
                "management": "Maintain heart-healthy diet low in saturated fats, increase fiber intake, exercise regularly, maintain healthy weight, avoid smoking, and have regular lipid panel checks."
            },
            {
                "name": "Coronary Artery Disease",
                "probability": 80,
                "reasoning": "Statins are standard therapy in CAD to reduce LDL cholesterol, stabilize plaques, and reduce cardiovascular events.",
                "management": "Comprehensive cardiac risk reduction: diet modification, regular exercise, smoking cessation, stress management, control of hypertension and diabetes, and regular cardiac monitoring."
            },
            {
                "name": "Cardiovascular Disease Prevention",
                "probability": 70,
                "reasoning": "Atorvastatin is used for primary and secondary prevention of cardiovascular events in high-risk patients based on calculated risk scores.",
                "management": "Regular cardiovascular risk assessment, maintain healthy lifestyle, control all modifiable risk factors, and adhere to medication regimen."
            },
            {
                "name": "Diabetes with Dyslipidemia",
                "probability": 60,
                "reasoning": "Statins are recommended for most diabetic patients to reduce cardiovascular risk associated with diabetes.",
                "management": "Blood glucose control, lipid management, blood pressure control, regular screening for diabetic complications, and comprehensive cardiovascular risk reduction."
            }
        ]
    },
    "amoxicillin": {
        "conditions": [
            {
                "name": "Acute Bacterial Infection",
                "probability": 95,
                "reasoning": "Amoxicillin is a broad-spectrum beta-lactam antibiotic used to treat acute bacterial infections, not a chronic condition medication.",
                "management": "Complete the full course of antibiotics, rest, hydration, symptom management with over-the-counter medications, and monitor for adverse effects."
            },
            {
                "name": "Chronic Recurrent Infections",
                "probability": 40,
                "reasoning": "Long-term amoxicillin prophylaxis may be used in patients with chronic respiratory infections or immunocompromised states.",
                "management": "Identify underlying cause of recurrent infections, immune system assessment, consider prophylactic antibiotics if indicated, and preventive measures like vaccinations."
            }
        ]
    },
    "omeprazole": {
        "conditions": [
            {
                "name": "Gastroesophageal Reflux Disease (GERD)",
                "probability": 85,
                "reasoning": "Omeprazole is a proton pump inhibitor that reduces gastric acid and is first-line therapy for GERD symptoms.",
                "management": "Dietary modifications (avoid trigger foods, eat smaller meals), elevate head of bed, maintain healthy weight, avoid NSAIDs, reduce alcohol and caffeine."
            },
            {
                "name": "Peptic Ulcer Disease",
                "probability": 75,
                "reasoning": "Omeprazole heals ulcers and prevents recurrence by suppressing gastric acid secretion.",
                "management": "Eradicate H. pylori if present, avoid NSAIDs, reduce stress, avoid alcohol and smoking, dietary modifications, and monitor for complications."
            },
            {
                "name": "Zollinger-Ellison Syndrome",
                "probability": 30,
                "reasoning": "Omeprazole is used in high doses to manage the excessive gastric acid production characteristic of this rare condition.",
                "management": "High-dose PPI therapy, investigate gastrinoma location, consider surgery if appropriate, and monitor acid suppression and symptom control."
            }
        ]
    },
    "levothyroxine": {
        "conditions": [
            {
                "name": "Hypothyroidism",
                "probability": 95,
                "reasoning": "Levothyroxine is the standard replacement therapy for hypothyroidism, restoring adequate thyroid hormone levels.",
                "management": "Regular TSH monitoring, maintain consistent dosing schedule, take on empty stomach, monitor for over/under-replacement, and manage dietary factors affecting absorption."
            },
            {
                "name": "Hashimoto's Thyroiditis",
                "probability": 90,
                "reasoning": "Levothyroxine is prescribed for the hypothyroidism resulting from this autoimmune thyroid condition.",
                "management": "Long-term thyroid hormone replacement, regular TSH and free T4 monitoring, manage autoimmune condition, and monitor for associated autoimmune diseases."
            },
            {
                "name": "Thyroid Cancer (Post-Operative)",
                "probability": 50,
                "reasoning": "High-dose levothyroxine may be used post-thyroidectomy to suppress TSH and reduce recurrence risk.",
                "management": "Regular TSH suppression monitoring, thyroglobulin levels, imaging surveillance, radioactive iodine therapy if indicated, and long-term endocrinology follow-up."
            }
        ]
    }
}

def normalize_medication_name(med_name: str) -> str:
    """Normalize medication name for lookup."""
    return med_name.lower().strip()

def infer_conditions(medication_name: str) -> Optional[Dict]:
    """
    Infer chronic conditions from medication name.
    
    Args:
        medication_name: Name of the medication
        
    Returns:
        Dictionary with conditions and metadata, or None if medication not found
    """
    normalized_name = normalize_medication_name(medication_name)
    
    if normalized_name in MEDICATION_CONDITIONS:
        conditions_data = MEDICATION_CONDITIONS[normalized_name]
        return {
            "medication_name": medication_name,
            "normalized_name": normalized_name,
            "conditions": conditions_data["conditions"],
            "disclaimer": "Medication use does not guarantee the patient has the listed condition. Results are probabilistic inference based on typical medical usage.",
            "note": "This is NOT a medical diagnosis. Always consult healthcare professionals for proper diagnosis and treatment."
        }
    else:
        return None

def format_output(result: Dict) -> str:
    """Format the inference result as a readable string."""
    if not result:
        return "Medication not found in database."
    
    output = f"\n{'='*70}\n"
    output += f"POSSIBLE CHRONIC CONDITIONS FOR: {result['medication_name'].upper()}\n"
    output += f"{'='*70}\n\n"
    
    for i, condition in enumerate(result["conditions"], 1):
        output += f"{i}. {condition['name']}\n"
        output += f"   Estimated Probability: {condition['probability']}%\n"
        output += f"   Reasoning: {condition['reasoning']}\n"
        output += f"   General Management Advice: {condition['management']}\n\n"
    
    output += f"{'='*70}\n"
    output += f"IMPORTANT NOTE:\n"
    output += f"{result['disclaimer']}\n"
    output += f"{result['note']}\n"
    output += f"{'='*70}\n"
    
    return output

def main():
    parser = argparse.ArgumentParser(
        description="Infer chronic illnesses from medication name",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Print results to console
  python infer_image.py --medication "Metformin"
  
  # Save results to JSON file
  python infer_image.py --medication "Lisinopril" --output results.json
  
  # Output JSON for curl POST
  python infer_image.py --medication "Atorvastatin" --json
        """
    )
    
    parser.add_argument(
        "--medication", "-m",
        required=True,
        help="Name of the medication to analyze"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (JSON format)"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON to stdout (for curl POST)"
    )
    
    args = parser.parse_args()
    
    # Infer conditions
    result = infer_conditions(args.medication)
    
    if not result:
        print(f"Error: Medication '{args.medication}' not found in database.")
        print(f"Supported medications: {', '.join(MEDICATION_CONDITIONS.keys())}")
        return
    
    # Output handling
    if args.json:
        # Output JSON to stdout for curl
        print(json.dumps(result, indent=2))
    elif args.output:
        # Save to file
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Results saved to {args.output}")
        print(format_output(result))
    else:
        # Print formatted output
        print(format_output(result))
        
        # Also save to default JSON file
        default_output = f"inference_{normalize_medication_name(args.medication)}.json"
        with open(default_output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\n✓ JSON results also saved to: {default_output}")

if __name__ == "__main__":
    main()
