"""Net Effective Rent (NER) calculation from concession text.

Parses common concession patterns from apartment listing sites and computes:
  - NER: what the tenant actually pays per month over the lease term
  - Concession %: discount as a percentage of gross rent

Formulas:
  Free months:   NER = rent * (lease_term - free_months) / lease_term
  Dollar off:    NER = rent - (total_discount / lease_term)
  Months free equivalent: concession_pct = free_months / lease_term
"""
from __future__ import annotations

import re
from dataclasses import dataclass


DEFAULT_LEASE_TERM = 12  # months


@dataclass
class NERResult:
    gross_rent: float
    ner: float
    concession_pct: float      # 0.0 to 1.0
    free_months: float         # equivalent free months
    dollar_off: float          # total dollar amount off over lease
    lease_term: int
    concession_text: str       # original text


def calculate_ner(
    rent: float,
    concession_text: str,
    lease_term: int = DEFAULT_LEASE_TERM,
) -> NERResult:
    """Calculate NER from rent and concession text.

    Returns NERResult with all fields populated. If no concession is detected,
    NER equals gross rent and concession_pct is 0.
    """
    if not concession_text or not concession_text.strip():
        return NERResult(
            gross_rent=rent, ner=rent, concession_pct=0.0,
            free_months=0.0, dollar_off=0.0,
            lease_term=lease_term, concession_text="",
        )

    text = concession_text.strip()
    free_months = _parse_free_months(text)
    dollar_off = _parse_dollar_off(text)

    # If both are found, use whichever gives a bigger discount
    if free_months > 0 and dollar_off > 0:
        fm_discount = rent * free_months
        if fm_discount >= dollar_off:
            dollar_off = 0.0
        else:
            free_months = 0.0

    if free_months > 0:
        ner = rent * (lease_term - free_months) / lease_term
        total_discount = rent * free_months
    elif dollar_off > 0:
        ner = rent - (dollar_off / lease_term)
        free_months = dollar_off / rent if rent > 0 else 0.0
        total_discount = dollar_off
    else:
        ner = rent
        total_discount = 0.0

    concession_pct = total_discount / (rent * lease_term) if rent > 0 else 0.0

    return NERResult(
        gross_rent=rent,
        ner=round(ner, 2),
        concession_pct=round(concession_pct, 4),
        free_months=round(free_months, 2),
        dollar_off=round(total_discount, 2),
        lease_term=lease_term,
        concession_text=text,
    )


def _parse_free_months(text: str) -> float:
    """Extract free months from concession text.

    Patterns matched:
      "1 month free", "2 months free", "1.5 months free"
      "one month free", "two months free"
      "first month free", "last month free"
      "6 weeks free" (converted to months)
    """
    t = text.lower()

    # Numeric: "1 month free", "2 months free", "1.5 month free"
    m = re.search(r"(\d+\.?\d*)\s*months?\s*(?:free|off|rent\s*free)", t)
    if m:
        return float(m.group(1))

    # Word numbers
    word_map = {
        "one": 1, "two": 2, "three": 3, "four": 4,
        "half": 0.5, "a": 1,
    }
    m = re.search(r"(one|two|three|four|half|a)\s+months?\s*(?:free|off|rent\s*free)", t)
    if m:
        return word_map.get(m.group(1), 0)

    # "first month free" / "last month free"
    if re.search(r"(?:first|last)\s+months?\s*(?:free|off|rent\s*free)", t):
        return 1.0

    # Weeks free (convert to months)
    m = re.search(r"(\d+)\s*weeks?\s*(?:free|off|rent\s*free)", t)
    if m:
        return round(int(m.group(1)) / 4.33, 2)

    return 0.0


def _parse_dollar_off(text: str) -> float:
    """Extract total dollar discount from concession text.

    Patterns matched:
      "$750 off", "$1,500 off", "$2,000 off"
      "$750 discount", "$1,500 credit"
      "save $750", "saving $1,500"
    """
    t = text.lower()

    # "$X off" / "$X discount" / "$X credit"
    m = re.search(r"\$([\d,]+)\s*(?:off|discount|credit|savings?|concession)", t)
    if m:
        return float(m.group(1).replace(",", ""))

    # "save $X" / "saving $X"
    m = re.search(r"sav(?:e|ing|ings)\s*(?:of\s*)?\$([\d,]+)", t)
    if m:
        return float(m.group(1).replace(",", ""))

    # "$X on [bed type]" — e.g. "$750 OFF 1 Bed" (812 W Adams pattern)
    m = re.search(r"\$([\d,]+)\s+off\s+\d+\s*bed", t)
    if m:
        return float(m.group(1).replace(",", ""))

    return 0.0
