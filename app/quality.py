"""Unit normalization and basic sanity checks, run before the review agent (app/agent.py)."""
import re

from app.models import Evidence

UNIT_FIELDS = {"Length": "ft", "Width": "in", "Thickness": "mil", "Weight": "lb"}
UNITS = {"ft": "ft", "feet": "ft", "foot": "ft", "in": "in", "inch": "in", "inches": "in",
         "mil": "mil", "mils": "mil", "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb"}


def normalize(value, field, source_type):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)?\.?\s*", value)
    if not match:
        return value
    number, unit = match.groups()
    if unit and unit.lower() in UNITS:
        return f"{number} {UNITS[unit.lower()]}"
    # Bare catalog units are explicitly documented in data/README.md.
    if not unit and source_type == "catalog":
        return f"{number} {UNIT_FIELDS[field]}"
    return value


def check_products(products):
    """Normalize units with explicit evidence; returns trace steps."""
    trace = []
    for product in products:
        for name in UNIT_FIELDS:
            evidence = product.fields.get(name)
            if not evidence:
                continue
            value = normalize(evidence.value, name, evidence.source_type)
            if value != evidence.value:
                product.fields[name] = Evidence(value, evidence.source_type,
                    evidence.source + f"; normalized from {evidence.value!r}; units: data/README.md",
                    evidence.confidence)
                product.notes.append(f"Normalized {name}: {evidence.value!r} -> {value!r}.")
                trace.append({"step": len(trace) + 1, "actor": "rules", "tool": "normalize_units",
                              "arguments": {"product_id": product.product_id, "field": name},
                              "result": f"{evidence.value!r} -> {value!r}"})
            numeric = re.match(r"(-?\d+(?:\.\d+)?)", value)
            if numeric and float(numeric.group()) <= 0:
                product.notes.append(f"Suspicious {name}: {value!r}; verify the source.")
        price = product.fields.get("Price (USD)")
        if price:
            try:
                if float(price.value) < 0:
                    product.notes.append("Suspicious negative price; verify the source.")
            except ValueError:
                product.notes.append("Price is not a plain number; review before quoting.")
    return trace
