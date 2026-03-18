"use client";

import { useState, useEffect } from "react";

// ── Constants ─────────────────────────────────────────────────────────────────

const ACTIVITIES = {
  sitting:     { color: "#4a9eff", label: "Sitting",     icon: "SIT" },
  eating:      { color: "#00e676", label: "Eating",      icon: "EAT" },
  walking:     { color: "#ff9800", label: "Walking",     icon: "WLK" },
  pill_taking: { color: "#ffeb3b", label: "Pill Taking", icon: "MED" },
  lying_down:  { color: "#ce93d8", label: "Lying Down",  icon: "LIE" },
  no_person:   { color: "#546e7a", label: "Away",        icon: "---" },
  unknown:     { color: "#8892a4", label: "Unknown",     icon: "???" },
  fallen:      { color: "#ff1744", label: "FALLEN",      icon: "!!!" },
};

const DEMO_NORMAL = {
  current:     "eating",
  confidence:  0.91,
  risk:        18,
  baselineRisk:15,
  apiOk:       false,
  timeline: [
    { hour: 7.0,  activity: "lying_down",  duration: 0.5  },
    { hour: 7.5,  activity: "walking",     duration: 0.5  },
    { hour: 8.0,  activity: "pill_taking", duration: 0.25 },
    { hour: 8.25, activity: "eating",      duration: 0.75 },
    { hour: 9.0,  activity: "sitting",     duration: 2.0  },
    { hour: 11.0, activity: "walking",     duration: 0.5  },
    { hour: 11.5, activity: "eating",      duration: 0.75 },
    { hour: 12.25,activity: "sitting",     duration: 1.75 },
    { hour: 14.0, activity: "lying_down",  duration: 1.0  },
    { hour: 15.0, activity: "sitting",     duration: 1.0  },
    { hour: 16.0, activity: "eating",      duration: 0.5  },
  ],
  alerts: [
    { time: "+0.0s", label: "MORNING PILL",    sub: "Pill taken at 08:05 · on schedule",     color: "#00e676", severity: "ok"   },
    { time: "+0.2s", label: "BREAKFAST",        sub: "Eating detected 08:25 · normal window", color: "#00e676", severity: "ok"   },
    { time: "+0.5s", label: "ACTIVITY NORMAL",  sub: "Walking 11:00 · within baseline",       color: "#4a9eff", severity: "info" },
    { time: "+1.1s", label: "NAP DETECTED",     sub: "Lying down 14:00 · 60m · normal",       color: "#ce93d8", severity: "info" },
  ],
  week: [
    { day: "MON", risk: 14, pill: true  },
    { day: "TUE", risk: 22, pill: true  },
    { day: "WED", risk: 18, pill: true  },
    { day: "THU", risk: 35, pill: false },
    { day: "FRI", risk: 20, pill: true  },
    { day: "SAT", risk: 12, pill: true  },
    { day: "SUN", risk: 18, pill: true  },
  ],
  medication: [
    { label: "Morning dose", time: "08:00", done: true,  actual: "08:05" },
    { label: "Lunch dose",   time: "13:00", done: true,  actual: "13:12" },
    { label: "Night dose",   time: "21:00", done: false, actual: null    },
  ],
  vitals: {
    heartRate: { a: 72,     unit: "bpm"   },
    steps:     { a: 1243,   unit: "steps" },
    inRoom:    { a: "YES",  unit: ""      },
    temp:      { a: "36.8", unit: "°C"   },
  },
};

const DEMO_CRISIS = {
  ...DEMO_NORMAL,
  current:     "lying_down",
  confidence:  0.87,
  risk:        73,
  baselineRisk:15,
  apiOk:       false,
  alerts: [
    { time: "+0.0s", label: "MORNING PILL MISSED", sub: "Expected 08:45 · Now 2h 15m overdue",    color: "#ff1744", severity: "critical" },
    { time: "+0.3s", label: "INACTIVITY DETECTED", sub: "No movement for 3h+ since 09:00",         color: "#ff1744", severity: "critical" },
    { time: "+0.8s", label: "LATE BREAKFAST",       sub: "Eating at 09:40 · 70m late vs baseline", color: "#ffeb3b", severity: "warning"  },
    { time: "+1.2s", label: "TRAVEL SPEED",         sub: "Slow gait vs yesterday · −32%",          color: "#ffeb3b", severity: "warning"  },
    { time: "+1.8s", label: "LONG LIE-DOWN",        sub: "Lying down 12:00 · 2h 10m · unusual",   color: "#ff1744", severity: "critical" },
  ],
  medication: [
    { label: "Morning dose", time: "08:00", done: false, actual: null },
    { label: "Lunch dose",   time: "13:00", done: false, actual: null },
    { label: "Night dose",   time: "21:00", done: false, actual: null },
  ],
  vitals: {
    heartRate: { a: 58,    unit: "bpm"   },
    steps:     { a: 214,   unit: "steps" },
    inRoom:    { a: "YES", unit: ""      },
    temp:      { a: "36.4",unit: "°C"   },
  },
};

// Initial live state — same shape as DEMO_NORMAL, apiOk=false means fallback to demo
const INITIAL_LIVE = {
  current:     "unknown",
  confidence:  0,
  risk:        0,
  baselineRisk:15,
  apiOk:       false,
  timeline:    [],
  alerts:      [],
  week:        [],
  medication:  [],
  vitals: {
    heartRate: { a: 0,     unit: "bpm"   },
    steps:     { a: 0,     unit: "steps" },
    inRoom:    { a: "---", unit: ""      },
    temp:      { a: "---", unit: "°C"   },
  },
};

// ── Pure data helpers ────────────────────────────────────────────────────────

/**
 * Convert activity_log rows to timeline items.
 * logs: Array<{ timestamp?: string, hour?: number, minute?: number, activity: string, confidence: number }>
 */
function logsToTimeline(logs) {
  return (logs || []).map((row) => {
    const ts = row.timestamp || "";
    const t =
      ts.length >= 16
        ? ts.slice(11, 16)
        : `${String(row.hour || 0).padStart(2, "0")}:${String(row.minute || 0).padStart(2, "0")}`;
    return {
      time:     t,
      activity: row.activity || "unknown",
      conf:     row.confidence ?? 0.9,
      note:     "",
    };
  });
}

/**
 * Convert flat timeline to ActivityRing segments.
 * Each log entry → 15-min segment (0.25h). Consecutive same-activity segments merge.
 */
function timelineToRingFormat(timeline) {
  if (!timeline || timeline.length === 0) return DEMO_NORMAL.timeline;
  const segments = [];
  for (const t of timeline) {
    const [h, m] = (t.time || "00:00").split(":").map(Number);
    const hour = h + m / 60;
    const last = segments[segments.length - 1];
    if (last && last.activity === t.activity) {
      last.duration += 0.25;
    } else {
      segments.push({ hour, activity: t.activity, duration: 0.25 });
    }
  }
  return segments;
}

/**
 * Build 7-day week summary.
 * logs: Array<{ date: string, activity: string }> from /api/logs/week
 * riskResult: { risk_score: number }
 */
function buildWeekData(logs, riskResult) {
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const base = new Date();
  const out = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(base);
    d.setDate(d.getDate() - (6 - i));
    const dayStr = d.toISOString().slice(0, 10);
    const dayLogs = (logs || []).filter((r) => r.date === dayStr);
    const events = dayLogs.length;
    const pill = dayLogs.some((r) => r.activity === "pill_taking");
    const risk =
      i === 6
        ? (riskResult?.risk_score ?? 15)
        : Math.min(90, 10 + events + (pill ? 0 : 25));
    out.push({
      day:    DAYS[d.getDay()].toUpperCase(),
      risk,
      pill,
      events,
    });
  }
  return out;
}

/**
 * Build medication schedule from today's logs.
 * todayLogs: Array<{ activity: string, hour: number, minute: number }>
 * mode: "normal" | "crisis"
 */
function getMedSchedule(todayLogs, mode) {
  const schedule = [
    { time: "08:00", label: "Morning dose", done: false, actual: null },
    { time: "13:00", label: "Lunch dose",   done: false, actual: null },
    { time: "21:00", label: "Night dose",   done: false, actual: null },
  ];
  const pillLogs = (todayLogs || []).filter((r) => r.activity === "pill_taking");
  for (let i = 0; i < schedule.length; i++) {
    for (const p of pillLogs) {
      const h = p.hour ?? 0;
      const m = p.minute ?? 0;
      const pt = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
      if (i === 0 && h < 12) {
        schedule[i].done = true;
        schedule[i].actual = pt;
      } else if (i === 1 && h >= 11 && h <= 14) {
        schedule[i].done = true;
        schedule[i].actual = pt;
      } else if (i === 2 && h >= 20) {
        schedule[i].done = true;
        schedule[i].actual = pt;
      }
    }
  }
  // Crisis mode override — always show morning dose as missed for demo clarity
  if (mode === "crisis") {
    schedule[0].done   = false;
    schedule[0].actual = null;
  }
  return schedule;
}

// ── Sub-components ───────────────────────────────────────────────────────────

function Spark({ data, color, height = 36 }) {
  const w = 160, h = height;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pts = data
    .map((v, i) =>
      `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * (h - 4) - 2}`
    )
    .join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ActivityRing({ data, size = 220 }) {
  const cx = size / 2, cy = size / 2;
  const r  = size * 0.38;
  const safeData = data && data.length > 0 ? data : DEMO_NORMAL.timeline;
  const totalHours = safeData.reduce((s, d) => s + d.duration, 0) || 1;
  let angle = -Math.PI / 2;
  const slices = safeData.map((d) => {
    const sweep = (d.duration / totalHours) * 2 * Math.PI;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    angle += sweep;
    const x2 = cx + r * Math.cos(angle);
    const y2 = cy + r * Math.sin(angle);
    const large = sweep > Math.PI ? 1 : 0;
    return {
      d:     `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`,
      color: ACTIVITIES[d.activity]?.color || "#555",
    };
  });
  return (
    <svg width={size} height={size}>
      <circle cx={cx} cy={cy} r={r + 2} fill="none" stroke="#1e2535" strokeWidth="1" />
      {slices.map((s, i) => (
        <path key={i} d={s.d} fill={s.color} opacity={0.85} />
      ))}
      <circle cx={cx} cy={cy} r={r * 0.55} fill="#080b12" />
      <text x={cx} y={cy - 6}  textAnchor="middle" fill="#4a5568" fontSize="8" fontFamily="'IBM Plex Mono',monospace" letterSpacing="2">ACTIVITY</text>
      <text x={cx} y={cy + 8}  textAnchor="middle" fill="#4a5568" fontSize="8" fontFamily="'IBM Plex Mono',monospace" letterSpacing="2">PROFILE</text>
      <text x={cx} y={cy + 22} textAnchor="middle" fill="#4a5568" fontSize="7" fontFamily="'IBM Plex Mono',monospace">(derived)</text>
    </svg>
  );
}

function RiskScore({ score, label }) {
  const color =
    score <= 30 ? "#00e676" :
    score <= 60 ? "#ffeb3b" :
                  "#ff1744";
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: 9, color: "#4a5568", letterSpacing: 3, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 72, fontWeight: 700, color, lineHeight: 1, fontFamily: "'IBM Plex Mono',monospace" }}>{score}</div>
      <div style={{ fontSize: 9, color: "#4a5568", letterSpacing: 2, marginTop: 4 }}>RISK INDEX</div>
    </div>
  );
}

function AlertRow({ alert, revealed }) {
  const dotColor =
    alert.severity === "critical" ? "#ff1744" :
    alert.severity === "warning"  ? "#ffeb3b" :
                                    "#00e676";
  return (
    <div style={{
      opacity:    revealed ? 1 : 0,
      transform:  revealed ? "translateX(0)" : "translateX(10px)",
      transition: "all 0.4s ease",
      borderBottom: "1px solid #1e2535",
      padding: "8px 0",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <div style={{ width: 6, height: 6, borderRadius: "50%", background: dotColor, marginTop: 3, flexShrink: 0 }} />
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: alert.color, letterSpacing: 1 }}>{alert.label}</span>
            <span style={{ fontSize: 8, color: "#2d3550" }}>{alert.time}</span>
          </div>
          <div style={{ fontSize: 8, color: "#4a5568", marginTop: 2, lineHeight: 1.4 }}>{alert.sub}</div>
        </div>
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export default function CareWatchDashboard() {
  const [mode,     setMode]     = useState("normal");
  const [alertAck, setAlertAck] = useState(false);
  const [tick,     setTick]     = useState(0);
  const [revealed, setRevealed] = useState([]);
  const [liveData, setLiveData] = useState(INITIAL_LIVE);
  const [injecting,setInjecting]= useState(false);

  // Consent gate — PDPA compliance (Step 5 merge)
  const [consented, setConsented] = useState(() =>
    typeof window !== "undefined" && localStorage.getItem("carewatch_consent") === "true"
  );

  // Medication label scan (Step 5 merge)
  const [scanResult, setScanResult] = useState(null);
  const [scanning,   setScanning]   = useState(false);

  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  // Use live data when API is reachable; otherwise fall back to demo constants
  const data = liveData.apiOk
    ? { ...liveData, mode }
    : mode === "crisis" ? DEMO_CRISIS : DEMO_NORMAL;

  const act       = ACTIVITIES[data.current] || ACTIVITIES.unknown;
  const riskColor = data.risk <= 30 ? "#00e676" : data.risk <= 60 ? "#ffeb3b" : "#ff1744";
  const mono      = "'IBM Plex Mono', 'Courier New', monospace";
  const panel     = { background: "#0d1117", border: "1px solid #1e2535", borderRadius: 2 };

  // Sparkline data — replace with historical API data when available
  const hrData   = Array.from({ length: 20 }, (_, i) => 65 + Math.sin(i * 0.7) * 8 + (mode === "crisis" ? -10 : 0));
  const stpData  = Array.from({ length: 20 }, (_, i) => 50 + Math.cos(i * 0.5) * 30);
  const riskData = Array.from({ length: 20 }, (_, i) =>
    mode === "crisis" ? 40 + i * 1.8 + Math.sin(i) * 5 : 10 + Math.sin(i * 0.8) * 8
  );

  // ── Fetch live data from API ───────────────────────────────────────────────
  async function loadLiveData() {
    try {
      const [latest, risk, week, today, baseline] = await Promise.all([
        fetch(`${API}/api/logs/latest`).then((r) => r.json()),
        fetch(`${API}/api/risk`).then((r) => r.json()),
        fetch(`${API}/api/logs/week`).then((r) => r.json()),
        fetch(`${API}/api/logs/today`).then((r) => r.json()),
        fetch(`${API}/api/baseline`).then((r) => r.json()),
      ]);

      const timeline   = logsToTimeline(Array.isArray(today) ? today : []);
      const ringFormat = timelineToRingFormat(timeline);
      const weekData   = buildWeekData(Array.isArray(week) ? week : [], risk);
      const medication = getMedSchedule(Array.isArray(today) ? today : [], mode);

      // Map anomalies from detector into alert feed format
      const alertsFromAPI = Array.isArray(risk?.anomalies)
        ? risk.anomalies
            .filter((a) => a && typeof a === "object")
            .map((a) => ({
              time:     "+0s",
              label:    (a.message || "Alert").slice(0, 40),
              sub:      a.message || "",
              color:    a.severity === "HIGH" ? "#ff1744" : "#ffeb3b",
              severity: a.severity === "HIGH" ? "critical" : "warning",
            }))
        : [];

      setLiveData({
        current:     latest?.activity     || "unknown",
        confidence:  latest?.confidence   ?? 0,
        risk:        risk?.risk_score     ?? 0,
        baselineRisk:baseline?.baseline_risk ?? 15,
        apiOk:       true,
        timeline:    ringFormat,
        alerts:      alertsFromAPI.length > 0 ? alertsFromAPI : DEMO_NORMAL.alerts,
        week:        weekData.map((d) => ({
          day:  d.day.slice(0, 3).toUpperCase(),
          risk: d.risk,
          pill: d.pill,
        })),
        medication,
        vitals: DEMO_NORMAL.vitals, // API does not provide vitals; use demo placeholder
      });
    } catch (_e) {
      // API unreachable — keep apiOk: false, component renders demo fallback
      setLiveData((prev) => ({ ...prev, apiOk: false }));
    }
  }

  // ── Demo data injection ────────────────────────────────────────────────────
  async function handleInjectDemo() {
    setInjecting(true);
    try {
      await fetch(`${API}/api/demo/inject`, { method: "POST" });
      await loadLiveData();
    } catch (_e) {
      // silently fail — dashboard stays in demo mode
    } finally {
      setInjecting(false);
    }
  }

  // ── Ticker — drives clock re-render every second ───────────────────────────
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  // ── Auto-fetch on mount and every 30s ─────────────────────────────────────
  useEffect(() => {
    loadLiveData();
    const interval = setInterval(loadLiveData, 30_000);
    return () => clearInterval(interval);
  }, [mode]); // re-fetch when mode changes so medication schedule recalculates

  // ── Staggered alert reveal animation ──────────────────────────────────────
  useEffect(() => {
    setRevealed([]);
    data.alerts.forEach((_, i) => {
      setTimeout(() => setRevealed((r) => [...r, i]), i * 300 + 100);
    });
  }, [mode, liveData.apiOk]);

  // key={tick} ensures React cannot optimize away the clock span
  const timeStr = new Date().toLocaleTimeString("en-SG", {
    hour:   "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  // ── Consent handlers (PDPA compliance) ────────────────────────────────────
  const residentId = "resident_001";
  const handleConsent = async () => {
    try {
      await fetch(`${API}/residents/${residentId}/consent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ consented: true, consented_by: "caregiver" }),
      });
    } catch (_) {}
    localStorage.setItem("carewatch_consent", "true");
    setConsented(true);
  };

  // ── Medication scan handler ────────────────────────────────────────────────
  const handleScan = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setScanning(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(`${API}/residents/${residentId}/scan`, {
        method: "POST", body: formData,
      });
      const data = await res.json();
      setScanResult(data);
    } catch (err) {
      console.error("Scan failed:", err);
    } finally {
      setScanning(false);
    }
  };

  // ── Consent gate — show modal before dashboard ────────────────────────────
  if (!consented) {
    return (
      <div style={{ background: "#080b12", minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "'IBM Plex Mono','Courier New',monospace" }}>
        <div style={{ background: "#0d1117", border: "1px solid #1e2535", borderRadius: 8, padding: 32, maxWidth: 480, color: "#c9d1d9" }}>
          <h2 style={{ color: "#4a9eff", marginTop: 0 }}>CareWatch Data Consent</h2>
          <p style={{ fontSize: 12, lineHeight: 1.6 }}>
            CareWatch collects activity logs and medication events to monitor resident health.
            Data is stored locally and never shared with third parties.
            See <strong>data_privacy_plan.md</strong> for full details.
          </p>
          <button
            onClick={handleConsent}
            style={{ background: "#4a9eff", color: "#fff", border: "none", borderRadius: 4, padding: "10px 24px", cursor: "pointer", fontFamily: "inherit", fontSize: 12 }}
          >
            I Agree
          </button>
        </div>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div style={{ background: "#080b12", minHeight: "100vh", fontFamily: mono, color: "#c9d1d9", display: "flex", flexDirection: "column", fontSize: 11 }}>

      {/* ── TOPBAR ── */}
      <div style={{ borderBottom: "1px solid #1e2535", padding: "0 16px", height: 44, display: "flex", alignItems: "center", justifyContent: "space-between", background: "#080b12" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 28, height: 28, borderRadius: 4, background: "linear-gradient(135deg,#4a9eff,#0057ff)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>👁️</div>
          <div>
            <span style={{ fontWeight: 700, fontSize: 13, color: "#fff", letterSpacing: 1 }}>CARE</span>
            <span style={{ fontWeight: 700, fontSize: 13, color: "#4a9eff", letterSpacing: 1 }}>WATCH</span>
            <span style={{ fontSize: 8, color: "#2d3550", marginLeft: 8 }}>SYS V1.0</span>
          </div>
        </div>

        <div style={{ display: "flex", gap: 32, alignItems: "center" }}>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 8, color: "#4a5568", letterSpacing: 2 }}>RESIDENT</div>
            <div style={{ fontSize: 10, color: "#8892a4" }}>MRS TAN · 74F · LIVING ROOM</div>
          </div>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 8, color: "#4a5568", letterSpacing: 2 }}>BASELINE</div>
            <div style={{ fontSize: 10, color: "#8892a4" }}>SESS_MRS_TAN_BASELINE_7D</div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {["normal", "crisis"].map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); setAlertAck(false); }}
              style={{
                background:   mode === m ? (m === "crisis" ? "#ff1744" : "#00e676") : "transparent",
                color:        mode === m ? "#000" : "#4a5568",
                border:       `1px solid ${m === "crisis" ? "#ff174440" : "#00e67640"}`,
                borderRadius: 2, padding: "3px 8px", fontSize: 8,
                letterSpacing: 2, cursor: "pointer", fontFamily: mono,
              }}
            >
              {m === "normal" ? "NORMAL DAY" : "CRISIS MODE"}
            </button>
          ))}

          {/* Live indicator — green when API connected, grey when in demo fallback */}
          <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "3px 10px", background: "#0d1117", borderRadius: 10, border: "1px solid #1e2535" }}>
            <div style={{ width: 5, height: 5, borderRadius: "50%", background: liveData.apiOk ? "#00e676" : "#546e7a", animation: liveData.apiOk ? "pulse 2s infinite" : "none" }} />
            <span style={{ fontSize: 8, color: liveData.apiOk ? "#00e676" : "#546e7a", letterSpacing: 2 }}>
              {liveData.apiOk ? "LIVE" : "DEMO"}
            </span>
          </div>

          {/* Clock — key={tick} forces re-render every second */}
          <span key={tick} style={{ fontSize: 10, color: "#2d3550" }}>{timeStr}</span>
        </div>
      </div>

      {/* ── CRISIS BANNER ── */}
      {mode === "crisis" && !alertAck && (
        <div style={{ background: "linear-gradient(135deg,#1a0a0a,#2d0f0f)", borderBottom: "1px solid #ff1744", padding: "8px 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 14 }}>🚨</span>
            <div>
              <span style={{ color: "#ff6b6b", fontWeight: 700, fontSize: 10, letterSpacing: 2 }}>CRITICAL ALERT — MRS TAN</span>
              <span style={{ color: "#ff9999", fontSize: 9, marginLeft: 12 }}>Pill taking not detected · Expected 08:45 · Now 2h 15m overdue</span>
            </div>
          </div>
          <button
            onClick={() => setAlertAck(true)}
            style={{ background: "transparent", border: "1px solid #ff174460", color: "#ff6b6b", padding: "3px 10px", fontSize: 8, letterSpacing: 2, cursor: "pointer", fontFamily: mono, borderRadius: 2 }}
          >
            ACKNOWLEDGE
          </button>
        </div>
      )}

      {/* ── "Load demo data" banner — shown when API is unreachable ── */}
      {!liveData.apiOk && (
        <div style={{ background: "#0d1117", borderBottom: "1px solid #1e2535", padding: "6px 16px", display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 8, color: "#4a5568" }}>No live data — API unreachable. Showing demo fallback.</span>
          <button
            onClick={handleInjectDemo}
            disabled={injecting}
            style={{ background: "transparent", border: "1px solid #4a9eff40", color: "#4a9eff", padding: "2px 8px", fontSize: 8, letterSpacing: 2, cursor: injecting ? "not-allowed" : "pointer", fontFamily: mono, borderRadius: 2 }}
          >
            {injecting ? "LOADING..." : "LOAD DEMO DATA"}
          </button>
        </div>
      )}

      {/* ── 3-PANEL LAYOUT ── */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "220px 1fr 240px", overflow: "hidden" }}>

        {/* ── LEFT PANEL ── */}
        <div style={{ borderRight: "1px solid #1e2535", padding: 12, display: "flex", flexDirection: "column", gap: 10, overflowY: "auto" }}>
          <div style={{ fontSize: 8, color: "#2d3550", letterSpacing: 3, marginBottom: 4 }}>SENSOR OVERVIEW</div>

          {[
            { label: "HEART RATE",  unit: "bpm",   data: hrData,   color: "#ff5252" },
            { label: "DAILY STEPS", unit: "steps",  data: stpData,  color: "#4a9eff" },
            { label: "RISK TREND",  unit: "idx",    data: riskData, color: riskColor  },
          ].map((s) => (
            <div key={s.label} style={{ ...panel, padding: "8px 10px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ fontSize: 8, color: "#4a5568", letterSpacing: 2 }}>{s.label}</span>
                <span style={{ fontSize: 8, color: "#2d3550" }}>{s.unit}</span>
              </div>
              <Spark data={s.data} color={s.color} />
              <div style={{ fontSize: 8, color: "#2d3550", marginTop: 3 }}>— TODAY</div>
            </div>
          ))}

          <div style={{ fontSize: 8, color: "#2d3550", letterSpacing: 3, marginTop: 4 }}>CURRENT VALUES</div>
          <div style={{ ...panel, padding: "8px 10px" }}>
            {Object.entries(data.vitals).map(([key, v]) => {
              const labels = { heartRate: "HEART", steps: "STEPS", inRoom: "IN ROOM", temp: "TEMP" };
              return (
                <div key={key} style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "3px 0", borderBottom: "1px solid #1e2535" }}>
                  <span style={{ fontSize: 8, color: "#4a5568", letterSpacing: 1 }}>{labels[key]}</span>
                  <span style={{ fontSize: 12, color: mode === "crisis" && key === "steps" ? "#ff1744" : "#c9d1d9", fontWeight: 600 }}>
                    {v.a}<span style={{ fontSize: 8, color: "#2d3550", marginLeft: 2 }}>{v.unit}</span>
                  </span>
                </div>
              );
            })}
          </div>

          <div style={{ fontSize: 8, color: "#2d3550", letterSpacing: 3, marginTop: 4 }}>MEDICATION</div>

          {/* Scan upload button */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "4px 0" }}>
            <input type="file" accept="image/*" onChange={handleScan} id="scan-upload" style={{ display: "none" }} />
            <label htmlFor="scan-upload" style={{ background: "#1e2535", color: "#4a9eff", border: "1px solid #4a9eff", borderRadius: 3, padding: "3px 10px", cursor: "pointer", fontSize: 9, letterSpacing: 1 }}>
              {scanning ? "SCANNING..." : "SCAN LABEL"}
            </label>
            {scanResult && (
              <span style={{ fontSize: 9, color: "#00e676" }}>
                {scanResult.medication_name} {scanResult.dose} ({Math.round(scanResult.confidence * 100)}%)
              </span>
            )}
          </div>

          <div style={{ ...panel, padding: "8px 10px" }}>
            {data.medication.map((med, i) => {
              const isMissed = !med.done && mode === "crisis";
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 0", borderBottom: i < 2 ? "1px solid #1e2535" : "none" }}>
                  <span style={{ fontSize: 11 }}>{isMissed ? "❌" : med.done ? "✅" : "⏳"}</span>
                  <div>
                    <div style={{ fontSize: 8, color: isMissed ? "#ff6b6b" : "#8892a4" }}>{med.label}</div>
                    <div style={{ fontSize: 7, color: "#2d3550" }}>
                      {med.actual ? `Taken ${med.actual}` : `Scheduled ${med.time}`}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── CENTRE PANEL ── */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "16px 0", gap: 0, overflowY: "auto" }}>

          {/* Dual risk scores */}
          <div style={{ display: "flex", alignItems: "center", gap: 32, marginBottom: 16 }}>
            <RiskScore score={data.risk} label="TODAY'S RISK" />
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: 8, color: "#2d3550", letterSpacing: 2 }}>GAP</div>
              <div style={{ fontSize: 28, color: "#2d3550", fontWeight: 600 }}>{Math.abs(data.risk - (data.baselineRisk ?? 15))}</div>
              <div style={{ fontSize: 7, color: "#2d3550" }}>pts</div>
            </div>
            {/* baselineRisk from API — no longer hardcoded */}
            <RiskScore score={data.baselineRisk ?? 15} label="7D BASELINE" />
          </div>

          {/* Activity ring */}
          <div style={{ width: 320, height: 320, borderRadius: "50%", border: "1px solid #1e2535", display: "flex", alignItems: "center", justifyContent: "center", background: "radial-gradient(circle, #0d111780 0%, #080b12 70%)" }}>
            <ActivityRing data={data.timeline} size={260} />
          </div>

          {/* Current activity badge */}
          <div style={{ marginTop: 12, padding: "6px 20px", background: `${act.color}18`, border: `1px solid ${act.color}40`, borderRadius: 2, textAlign: "center" }}>
            <div style={{ fontSize: 8, color: "#4a5568", letterSpacing: 3, marginBottom: 2 }}>CURRENT ACTIVITY</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: act.color, letterSpacing: 4 }}>{act.label.toUpperCase()}</div>
            <div style={{ fontSize: 8, color: "#4a5568", marginTop: 2 }}>{Math.round(data.confidence * 100)}% CONFIDENCE</div>
          </div>

          {/* Timeline bar */}
          <div style={{ width: "80%", marginTop: 16 }}>
            <div style={{ fontSize: 7, color: "#2d3550", letterSpacing: 3, marginBottom: 4 }}>TODAY'S TIMELINE — 06:00 → 22:00</div>
            <div style={{ height: 16, background: "#0d1117", border: "1px solid #1e2535", borderRadius: 2, overflow: "hidden", position: "relative" }}>
              {data.timeline.map((seg, i) => {
                const left  = ((seg.hour - 6) / 16) * 100;
                const width = (seg.duration / 16) * 100;
                return (
                  <div
                    key={i}
                    style={{ position: "absolute", left: `${left}%`, width: `${Math.max(width, 0.5)}%`, height: 14, background: ACTIVITIES[seg.activity]?.color || "#555", opacity: 0.8 }}
                    title={seg.activity}
                  />
                );
              })}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 2 }}>
              {[6, 9, 12, 15, 18, 21].map((h) => (
                <span key={h} style={{ fontSize: 7, color: "#2d3550" }}>
                  {h < 12 ? `${h}am` : h === 12 ? "12pm" : `${h - 12}pm`}
                </span>
              ))}
            </div>
          </div>

          {/* 7-day week */}
          <div style={{ width: "80%", marginTop: 14 }}>
            <div style={{ fontSize: 7, color: "#2d3550", letterSpacing: 3, marginBottom: 6 }}>7-DAY HISTORY · 💊 = pill taken</div>
            <div style={{ display: "flex", gap: 6 }}>
              {data.week.map((d, i) => {
                const c = d.risk <= 30 ? "#00e676" : d.risk <= 60 ? "#ffeb3b" : "#ff1744";
                return (
                  <div key={i} style={{ flex: 1, textAlign: "center" }}>
                    <div style={{ fontSize: 7, color: "#2d3550", marginBottom: 2 }}>{d.day}</div>
                    <div style={{ height: 32, background: "#0d1117", border: "1px solid #1e2535", borderRadius: 2, position: "relative", overflow: "hidden" }}>
                      <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: `${d.risk}%`, background: c }} />
                    </div>
                    <div style={{ fontSize: 8, color: c, fontWeight: 700, marginTop: 1 }}>{d.risk}</div>
                    <div style={{ fontSize: 9 }}>{d.pill ? "💊" : "❌"}</div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Status bar */}
          <div style={{ width: "80%", marginTop: "auto", paddingTop: 12, borderTop: "1px solid #1e2535", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#00e676" }} />
              <span style={{ fontSize: 8, color: "#00e676", letterSpacing: 2 }}>READY</span>
            </div>
            <span style={{ fontSize: 7, color: "#2d3550" }}>SESS_MRS_TAN_001 · CareWatch v1.0</span>
          </div>
        </div>

        {/* ── RIGHT PANEL ── */}
        <div style={{ borderLeft: "1px solid #1e2535", padding: 12, display: "flex", flexDirection: "column", overflowY: "auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <span style={{ fontSize: 8, color: "#2d3550", letterSpacing: 3 }}>ALERT FEED</span>
            <span style={{ fontSize: 9, color: riskColor, fontWeight: 700 }}>RISK: {data.risk}</span>
          </div>

          {/* Risk breakdown — crisis only */}
          {mode === "crisis" && (
            <div style={{ ...panel, padding: "8px 10px", marginBottom: 10 }}>
              <div style={{ fontSize: 7, color: "#ff1744", letterSpacing: 2, marginBottom: 6 }}>RISK BREAKDOWN</div>
              {[
                { label: "Pill not taken", pts: 40, color: "#ff1744" },
                { label: "Inactivity 3h+", pts: 25, color: "#ff1744" },
                { label: "Late breakfast",  pts: 8,  color: "#ffeb3b" },
              ].map((r, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "2px 0", borderBottom: i < 2 ? "1px solid #1e2535" : "none" }}>
                  <span style={{ fontSize: 8, color: "#8892a4" }}>{r.label}</span>
                  <span style={{ fontSize: 8, color: r.color, fontWeight: 700 }}>+{r.pts}pts</span>
                </div>
              ))}
            </div>
          )}

          {/* Alert feed */}
          <div style={{ flex: 1 }}>
            {data.alerts.map((a, i) => (
              <AlertRow key={`${mode}-${i}`} alert={a} revealed={revealed.includes(i)} />
            ))}
          </div>

          {/* Activity key */}
          <div style={{ marginTop: 12, borderTop: "1px solid #1e2535", paddingTop: 10 }}>
            <div style={{ fontSize: 7, color: "#2d3550", letterSpacing: 3, marginBottom: 6 }}>ACTIVITY KEY</div>
            {Object.entries(ACTIVITIES)
              .filter(([k]) => k !== "unknown")
              .map(([key, v]) => (
                <div key={key} style={{ display: "flex", alignItems: "center", gap: 6, padding: "2px 0" }}>
                  <div style={{ width: 6, height: 6, borderRadius: 1, background: v.color, flexShrink: 0 }} />
                  <span style={{ fontSize: 7, color: "#4a5568" }}>{v.label.toUpperCase()}</span>
                </div>
              ))}
          </div>

          {/* Summary stats */}
          <div style={{ marginTop: 12, borderTop: "1px solid #1e2535", paddingTop: 10 }}>
            <div style={{ fontSize: 7, color: "#2d3550", letterSpacing: 3, marginBottom: 6 }}>SUMMARY</div>
            {[
              { label: "Pill compliance", value: `${Math.round((data.week.filter((d) => d.pill).length / Math.max(data.week.length, 1)) * 100)}%`, color: "#ffeb3b" },
              { label: "Active days",     value: `${data.week.filter((d) => d.risk < 50).length}/${data.week.length}`,                              color: "#00e676" },
              { label: "Avg risk",        value: `${Math.round(data.week.reduce((s, d) => s + d.risk, 0) / Math.max(data.week.length, 1))}`,         color: "#4a9eff" },
            ].map((s, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", borderBottom: "1px solid #1e2535" }}>
                <span style={{ fontSize: 8, color: "#4a5568" }}>{s.label}</span>
                <span style={{ fontSize: 10, color: s.color, fontWeight: 700 }}>{s.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&display=swap');
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 3px; }
        ::-webkit-scrollbar-track { background: #080b12; }
        ::-webkit-scrollbar-thumb { background: #1e2535; }
      `}</style>
    </div>
  );
}
