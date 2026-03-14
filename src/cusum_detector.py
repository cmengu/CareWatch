"""
cusum_detector.py
=================
CUSUM (Cumulative Sum) detector for CareWatch anomaly detection.
One CUSUMDetector per monitored signal — fitted from baseline, accumulates
evidence across observations, fires when cumulative sum exceeds threshold.

USAGE:
    from src.cusum_detector import CUSUMDetector, CUSUMResult
    det = CUSUMDetector(signal_name='pill_taking_timing', baseline_mean=8.0, baseline_std=1.0)
    result = det.update(observation=12.0)  # returns CUSUMResult
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class CUSUMResult:
    """
    Output of a single CUSUMDetector update call.
    Replaces the ungrounded 0-100 score for one monitored signal.
    """
    signal_name:         str
    observation:         float
    baseline_mean:       float
    sigma_distance:      float        # how many std devs from baseline
    statistic_upper:     float        # current upper CUSUM statistic
    statistic_lower:     float        # current lower CUSUM statistic
    threshold:           float        # h — detection threshold
    signal_detected:     bool         # True when statistic exceeds threshold
    direction:           str          # "high", "low", or "none"
    consecutive_count:   int          # observations in current run above threshold
    checked_at:          str          # ISO timestamp


class CUSUMDetector:
    """
    Cumulative Sum Control Chart for one monitored signal.
    Fitted to an individual resident's baseline — not population averages.

    Parameters
    ----------
    signal_name : str
        Human-readable name of the signal being monitored.
    baseline_mean : float
        Expected value for this resident — from baseline JSON.
    baseline_std : float
        Standard deviation for this resident — from baseline JSON.
        Used to compute k = 0.5 * std (standard starting point).
    h : float
        Detection threshold. Default 5.0 — standard industrial starting point.
        Tune against adversarial eval cases in Day 10.
    """

    def __init__(
        self,
        signal_name:   str,
        baseline_mean: float,
        baseline_std:  float,
        h:             float = 5.0,
    ):
        if baseline_std <= 0:
            raise ValueError(
                f"CUSUMDetector({signal_name}): baseline_std must be > 0, "
                f"got {baseline_std}. Cannot fit detector on zero-variance baseline."
            )

        self.signal_name   = signal_name
        self.baseline_mean = baseline_mean
        self.baseline_std  = baseline_std
        self.k             = 0.5 * baseline_std   # allowable slack
        self.h             = h                     # detection threshold

        # Running statistics — in memory, reset on process restart
        self._C_pos       = 0.0   # upper CUSUM statistic
        self._C_neg       = 0.0   # lower CUSUM statistic
        self._consecutive = 0     # observations in current run

    def update(self, observation: float) -> CUSUMResult:
        """
        Ingest one new observation. Update running statistics.
        Returns CUSUMResult describing current state.
        """
        # Update upper and lower CUSUM statistics
        self._C_pos = max(
            0.0,
            self._C_pos + observation - (self.baseline_mean + self.k)
        )
        self._C_neg = max(
            0.0,
            self._C_neg - observation + (self.baseline_mean - self.k)
        )

        signal_detected = self._C_pos > self.h or self._C_neg > self.h

        # Track consecutive observations in current run
        if signal_detected:
            self._consecutive += 1
        else:
            self._consecutive = 0

        # Direction of deviation
        if self._C_pos > self.h:
            direction = "high"
        elif self._C_neg > self.h:
            direction = "low"
        else:
            direction = "none"

        # Sigma distance — how far this single observation is from baseline
        sigma_distance = (
            abs(observation - self.baseline_mean) / self.baseline_std
        )

        return CUSUMResult(
            signal_name=self.signal_name,
            observation=observation,
            baseline_mean=self.baseline_mean,
            sigma_distance=round(sigma_distance, 2),
            statistic_upper=round(self._C_pos, 3),
            statistic_lower=round(self._C_neg, 3),
            threshold=self.h,
            signal_detected=signal_detected,
            direction=direction,
            consecutive_count=self._consecutive,
            checked_at=datetime.now().isoformat(),
        )

    def reset(self) -> None:
        """
        Reset running statistics after a confirmed intervention.
        Call this when a caretaker acknowledges and resolves an alert.
        """
        self._C_pos       = 0.0
        self._C_neg       = 0.0
        self._consecutive = 0
