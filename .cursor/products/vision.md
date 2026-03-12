# CareWatch
### AI-powered early detection of behavioural decline in elderly individuals living alone

---

## The Problem

1 in 3 elderly Singaporeans lives alone. Their families only find out something is wrong **after** a fall, a hospitalisation, a crisis.

But health decline doesn't happen suddenly. It shows up in behaviour days or weeks earlier.  
Grandma stops eating breakfast. She stops walking to the kitchen by 9am. She skips her routine.  
No one notices — until it's too late.

---

## The Insight

> Routine deviation is an early warning signal. No consumer product detects it today.

Existing solutions are **reactive** — fall detectors, pill alarms, emergency buttons.  
They fire after something bad already happened.

CareWatch is **predictive**. It detects the drift before the crisis.

---

## What CareWatch Does

A single camera placed in the home passively observes the resident's daily life.  
No wearables. No manual input. No change to their routine.

**Week 1 — Learn**  
CareWatch silently builds a personal baseline: when they wake up, when they eat,  
when they walk, when they take their medication, when they rest.

**Week 2 onwards — Monitor**  
Every 15 minutes, CareWatch compares today's behaviour against their personal baseline.  
Deviations are scored, weighted by clinical significance, and surfaced to the family.

**When something is wrong — Alert**  
A Telegram message reaches the family immediately:  
*"Mrs Tan has not taken her medication. No movement detected since 9am. Usual activity expected at 8:45am."*

---

## The Technology

| Layer | What it does |
|---|---|
| YOLO11x-pose | Detects 17 body keypoints per frame in real time |
| Angle LSTM | Classifies activity from sequences of joint angles |
| Personal baseline | Statistical profile built from 7 days of observations |
| Deviation detector | Z-score anomaly detection against personal baseline |
| Risk scorer | Weighted urgency score 0–100 per resident |
| Alert engine | Telegram notification to family on YELLOW/RED risk |
| Dashboard | Family-facing web view of timeline, risk score, history |

Activities detected: `sitting` · `eating` · `walking` · `pill taking` · `lying down` · `no person`

---

## The Finished Product

**For the family** — a mobile dashboard showing:
- Is she okay right now?
- Did she take her medication today?
- How does today compare to her normal routine?
- What has her past week looked like?

**For the resident** — nothing changes. No wearable. No button to press.  
The camera watches. The family rests easy.

---

## Why This Wins

- **No existing consumer product** does personalised routine baseline monitoring
- **Camera only** — no wearables, no sensors, no behaviour change required  
- **Predictive not reactive** — flags drift before the crisis, not after  
- **Singapore-relevant** — ageing population, high single-elderly household rate  
- **Extensible** — the same architecture applies to NICU neonatal monitoring (our next step)

---

*Built for the Singapore Innovation Challenge 2026*  
*Team: Brandon Yeo, Ng Chen Meng*