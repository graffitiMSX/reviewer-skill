"""Offline token estimator. Absolute counts are approximate; ratios are stable
because both sides of every comparison use this same function."""
import json, os, re

RUN = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*|\d+|\n|[ \t\r\f\v]+|[^\sA-Za-z0-9_$]+")
DEFAULT_CALIBRATION = os.path.join(os.path.dirname(__file__), "calibration.json")

def _r(x):
    """Half-up rounding. Python's round() is banker's rounding, which makes goldens ambiguous."""
    return int(x + 0.5)

def _run_tokens(run):
    if run == "\n":
        return 1
    c = run[0]
    n = len(run)
    if c.isalpha() or c in "_$":
        return max(1, _r(n / 4.2))
    if c.isdigit():
        return max(1, _r(n / 3))
    if c.isspace():
        return max(1, _r(n / 6))
    return max(1, _r(n / 1.6))

def estimate(text, k=1.0):
    """Estimated token count for a piece of source."""
    if not text:
        return 0
    return _r(k * sum(_run_tokens(m.group(0)) for m in RUN.finditer(text)))

def chars(text):
    """UTF-8 byte length. Needs no estimator and is not arguable."""
    return len(text.encode("utf-8"))

def load_k(path=None):
    """Return (k, calibrated). Missing or malformed calibration means (1.0, False)."""
    path = path or DEFAULT_CALIBRATION
    try:
        with open(path) as fh:
            d = json.load(fh)
        return float(d.get("k", 1.0)), bool(d.get("calibrated", False))
    except (OSError, ValueError):
        return 1.0, False
