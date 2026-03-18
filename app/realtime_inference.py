"""
realtime_inference.py
======================
The LIVE DEMO script. Opens webcam (or video file), runs the full CareWatch pipeline:
  YOLO pose → angle extraction → LSTM classification → live overlay

USAGE:
  # Webcam
  python3 app/realtime_inference.py

  # Video file (for testing without webcam)
  python3 app/realtime_inference.py --source path/to/video.mp4

CONTROLS:
  Q — quit
  S — save current frame as screenshot
"""

import sys, os, argparse, time, collections, threading
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logging
import cv2
import numpy as np
import torch
from ultralytics import YOLO

from src.classification_keypoint import AngleFeatureExtractor, AngleLSTMNet, SEQUENCE_LENGTH, NUM_ANGLE_FEATURES
from src.logger import ActivityLogger
from src.deviation_detector import DeviationDetector
from src.suppression import AlertSuppressionLayer
from src.tts import speak as _tts_speak
from src.medication import MedicationRepo

# ── CONFIG ────────────────────────────────────────────────────────────────────
POSE_MODEL_PATH  = "yolo11x-pose.pt"
LSTM_MODEL_PATH  = "model/trained_carewatch.pt"
LABEL_CLASS_PATH = "model/label_classes.txt"
CONFIDENCE_THRESHOLD = 0.60   # minimum LSTM confidence to display prediction
MIN_KEYPOINT_CONF    = 0.40

# Activity colours (BGR)
ACTIVITY_COLOURS = {
    "sitting":    (180, 180, 180),
    "eating":     (0,   200, 100),
    "walking":    (0,   160, 255),
    "pill_taking":(0,   255, 255),
    "lying_down": (200, 100, 200),
    "no_person":  (80,   80,  80),
    "fallen":     (0,    0,  255),  # red for urgent
    "unknown":    (100, 100, 100),
}

# ── LOAD MODELS ───────────────────────────────────────────────────────────────

def load_models():
    device = torch.device("mps" if torch.backends.mps.is_available() else
                          "cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    pose_model = YOLO(POSE_MODEL_PATH)

    # Load label classes
    if not os.path.exists(LABEL_CLASS_PATH):
        print(f"⚠️  {LABEL_CLASS_PATH} not found. Run training first.")
        label_classes = ["sitting","eating","walking","pill_taking","lying_down","no_person","fallen"]
    else:
        with open(LABEL_CLASS_PATH) as f:
            label_classes = [l.strip() for l in f.readlines()]

    num_classes = len(label_classes)

    # Load LSTM
    lstm_model = AngleLSTMNet(
        input_size=NUM_ANGLE_FEATURES,
        hidden_size=128,
        num_layers=3,
        num_classes=num_classes,
    ).to(device)

    if os.path.exists(LSTM_MODEL_PATH):
        lstm_model.load_state_dict(torch.load(LSTM_MODEL_PATH, map_location=device))
        lstm_model.eval()
        print(f"✅ LSTM model loaded from {LSTM_MODEL_PATH}")
    else:
        print(f"⚠️  No trained model found at {LSTM_MODEL_PATH}. Running pose-only mode.")
        lstm_model = None

    return pose_model, lstm_model, label_classes, device


# ── KEYPOINT EXTRACTION ───────────────────────────────────────────────────────

def extract_keypoints(results) -> np.ndarray | None:
    """Extract flat [x0,y0,...,x16,y16] for most confident person."""
    if results.keypoints is None or len(results.keypoints.data) == 0:
        return None

    kp_data = results.keypoints.data.cpu().numpy()
    best, best_conf = None, -1
    for person in kp_data:
        conf = person[:, 2].mean()
        if conf > best_conf:
            best_conf, best = conf, person
    if best_conf < MIN_KEYPOINT_CONF:
        return None

    return best[:, :2].flatten()   # (34,)


# ── DRAWING HELPERS ───────────────────────────────────────────────────────────

SKELETON_CONNECTIONS = [
    (5, 7), (7, 9),    # left arm
    (6, 8), (8, 10),   # right arm
    (5, 6),            # shoulders
    (5, 11), (6, 12),  # torso sides
    (11, 12),          # hips
    (11, 13), (13, 15),# left leg
    (12, 14), (14, 16),# right leg
    (0, 5), (0, 6),    # neck to shoulders
]

def draw_skeleton(frame, keypoints_flat, colour=(0, 255, 255)):
    if keypoints_flat is None:
        return
    pts = keypoints_flat.reshape(17, 2).astype(int)
    for (a, b) in SKELETON_CONNECTIONS:
        pa, pb = tuple(pts[a]), tuple(pts[b])
        if pa != (0,0) and pb != (0,0):
            cv2.line(frame, pa, pb, colour, 2)
    for pt in pts:
        if tuple(pt) != (0,0):
            cv2.circle(frame, tuple(pt), 4, (255, 255, 255), -1)


def draw_overlay(frame, activity, confidence, fps):
    h, w = frame.shape[:2]
    colour = ACTIVITY_COLOURS.get(activity, ACTIVITY_COLOURS["unknown"])

    # Activity pill (top-left)
    label_text = f"{activity.upper().replace('_', ' ')}  {confidence*100:.0f}%"
    (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_DUPLEX, 0.9, 2)
    cv2.rectangle(frame, (10, 10), (tw + 30, th + 30), colour, -1)
    cv2.putText(frame, label_text, (20, th + 18),
                cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 0, 0), 2)

    # FPS (top-right)
    cv2.putText(frame, f"FPS: {fps:.0f}", (w - 120, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

    # CareWatch watermark (bottom-left)
    cv2.putText(frame, "CareWatch v1.0", (10, h - 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)


# ── DEVIATION CHECK (runs every 15 min, sends Telegram on YELLOW/RED) ──────────
def deviation_check_loop():
    """Background thread: compare today vs baseline, send alerts if needed."""
    while True:
        result = DeviationDetector().check("resident")
        AlertSuppressionLayer().send(result, person_name="Mrs Tan", resident_id="default")
        time.sleep(900)  # 15 minutes


# ── MEAL REMINDER LOOP (runs every 60 s) ────────────────────────────────────
_meal_logger = logging.getLogger(__name__)


def meal_reminder_loop(person_id: str = "resident") -> None:
    """Background thread: check pill/meal schedules and fire TTS reminders."""
    med_repo = MedicationRepo()
    while True:
        try:
            med_repo.check_and_trigger_meal_reminders(
                person_id, speaker=_tts_speak, logger=_meal_logger
            )
        except Exception as exc:
            _meal_logger.warning("meal reminder check failed (non-fatal): %s", exc)

        try:
            med_repo.check_meal_relative_reminders(person_id, speaker=_tts_speak)
        except Exception as exc:
            _meal_logger.warning("meal-relative reminder check failed (non-fatal): %s", exc)

        time.sleep(60)

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def run(source=0):
    pose_model, lstm_model, label_classes, device = load_models()
    extractor = AngleFeatureExtractor()
    logger = ActivityLogger()

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"❌ Cannot open source: {source}")
        return

    threading.Thread(target=deviation_check_loop, daemon=True).start()
    threading.Thread(target=meal_reminder_loop, daemon=True).start()

    # Rolling buffer of angle frames for LSTM
    frame_buffer = collections.deque(maxlen=SEQUENCE_LENGTH)

    current_activity   = "unknown"
    current_confidence = 0.0
    prev_time          = time.time()

    print("▶  CareWatch running. Press Q to quit, S to screenshot.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # ── Pose detection ──
        results = pose_model.predict(frame, conf=0.25, verbose=False)[0]
        keypoints_flat = extract_keypoints(results)

        if keypoints_flat is not None:
            draw_skeleton(frame, keypoints_flat,
                          colour=ACTIVITY_COLOURS.get(current_activity, (0,255,255)))
            angles = extractor.calculate_angles(keypoints_flat)
            frame_buffer.append(angles)
        else:
            frame_buffer.append(np.zeros(NUM_ANGLE_FEATURES, dtype=np.float32))

        # ── LSTM classification (once buffer is full) ──
        if lstm_model is not None and len(frame_buffer) == SEQUENCE_LENGTH:
            seq = torch.tensor(
                np.array(frame_buffer)[np.newaxis, :, :],  # (1, seq, features)
                dtype=torch.float32, device=device
            )
            with torch.no_grad():
                logits = lstm_model(seq)
                probs  = torch.softmax(logits, dim=1)[0]
                top_idx  = probs.argmax().item()
                top_conf = probs[top_idx].item()

            if top_conf >= CONFIDENCE_THRESHOLD:
                current_activity   = label_classes[top_idx]
                current_confidence = top_conf
                if current_confidence >= 0.85:
                    logger.log(current_activity, current_confidence)
            else:
                current_activity   = "unknown"
                current_confidence = top_conf

        # ── FPS ──
        now = time.time()
        fps = 1.0 / max(now - prev_time, 1e-9)
        prev_time = now

        # ── Draw overlay ──
        draw_overlay(frame, current_activity, current_confidence, fps)

        cv2.imshow("CareWatch", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("s"):
            fname = f"screenshot_{int(time.time())}.jpg"
            cv2.imwrite(fname, frame)
            print(f"📸 Saved {fname}")

    cap.release()
    cv2.destroyAllWindows()
    print("👋 CareWatch stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=0,
                        help="Camera index (0) or path to video file")
    args = parser.parse_args()

    source = int(args.source) if str(args.source).isdigit() else args.source
    run(source)