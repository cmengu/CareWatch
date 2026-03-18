#!/usr/bin/env python3
"""
Complete pipeline: Extract medication from image label → Infer chronic illnesses.
Combines label recognition with medical knowledge inference.
"""

import json
import argparse
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from label_recognition.preprocess import analyze_prescription_label
from scripts.infer_chronic_illness import infer_chronic_illness, format_output


def run_pipeline(image_path: str, 
                 api_key: str = None,
                 output_dir: str = None,
                 auto_save: bool = True) -> dict:
    """
    Run the complete pipeline: extract medication → infer illnesses.
    
    Args:
        image_path: Path to prescription label image
        api_key: API key for LLM service (if provided, unknown meds are generated on-the-fly)
        output_dir: Directory to save output JSON files
        auto_save: Whether to automatically save new medications to database
        
    Returns:
        Complete pipeline result
    """
    print(f"📋 Processing image: {image_path}")
    print("=" * 60)
    
    # Step 1: Extract medication info from label
    print("\n[Step 1] Extracting medication information from prescription label...")
    label_data = analyze_prescription_label(image_path)
    
    medication_name = label_data.get("medication_name")
    if not medication_name:
        print("❌ Could not extract medication name from prescription label")
        return {
            "success": False,
            "error": "No medication name found in prescription label"
        }
    
    print(f"✅ Extracted medication: {medication_name}")
    
    # Step 2: Infer chronic illnesses (auto-generates if API key available)
    print(f"\n[Step 2] Inferring chronic illnesses for {medication_name}...")
    illness_data = infer_chronic_illness(
        medication_name,
        use_llm=True,
        api_key=api_key,
        auto_save=auto_save
    )
    
    print(f"✅ Identified {len(illness_data.get('conditions', []))} possible conditions")
    
    # Step 3: Combine results
    result = {
        "success": True,
        "image_path": image_path,
        "prescription_label": {
            "patient_name": label_data.get("patient_name"),
            "medication_name": label_data.get("medication_name"),
            "dosage": label_data.get("dosage"),
            "instructions": label_data.get("instructions"),
            "quantity": label_data.get("quantity"),
            "refills": label_data.get("refills")
        },
        "inferred_illnesses": illness_data.get("conditions", []),
        "inference_source": illness_data.get("source")
    }
    
    # Step 4: Display results
    print("\n" + "=" * 60)
    print("📊 RESULTS")
    print("=" * 60)
    
    print(f"\n👤 Patient Information:")
    print(f"   Name: {label_data.get('patient_name') or 'Not found'}")
    print(f"   Medication: {label_data.get('medication_name')}")
    print(f"   Dosage: {label_data.get('dosage') or 'Not found'}")
    print(f"   Instructions: {label_data.get('instructions') or 'Not found'}")
    
    print(f"\n🏥 Inferred Chronic Conditions (Top {len(illness_data.get('conditions', []))}):")
    for i, condition in enumerate(illness_data.get("conditions", []), 1):
        print(f"\n   {i}. {condition['name']}")
        print(f"      Probability: {condition['probability']}%")
        print(f"      Reasoning: {condition['reasoning']}")
        print(f"      Management: {condition['management']}")
    
    # Step 5: Save results if output directory specified
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
        # Create output filename based on image filename
        image_stem = Path(image_path).stem
        json_output = Path(output_dir) / f"{image_stem}_inference.json"
        
        with open(json_output, "w") as f:
            json.dump(result, f, indent=2)
        
        print(f"\n✅ Results saved to: {json_output}")
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Extract medication from prescription label and infer chronic illnesses"
    )
    parser.add_argument(
        "--image", "-i",
        required=True,
        help="Path to prescription label image"
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("SEA_LION_API_KEY"),
        help="API key for LLM service (or set SEA_LION_API_KEY env var). If provided, unknown medications are generated on-the-fly."
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="./output",
        help="Directory to save output JSON files (default: ./output)"
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Only output JSON to stdout, suppress console output"
    )
    parser.add_argument(
        "--no-auto-save",
        action="store_true",
        help="Don't automatically save new medications to database"
    )
    
    args = parser.parse_args()
    
    # Run pipeline (auto-generates unknown medications if API key available)
    result = run_pipeline(
        args.image,
        api_key=args.api_key,
        output_dir=args.output_dir,
        auto_save=not args.no_auto_save
    )
    
    # Output JSON if requested
    if args.json_only:
        print(json.dumps(result, indent=2))
    
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
