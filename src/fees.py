"""Fee schedules by property name.

Keyed by PROPERTY_NAME from config.py. When adding a new property, add an
entry here. Properties without an entry will show "No fee schedule configured"
on the dashboard Fees tab.
"""

FEES: dict[str, dict] = {
    "Aberdeen Crossing": {
        "application": [
            {"item": "Application fee",    "cost": "$75.00 per applicant", "note": "Non-refundable"},
            {"item": "Administration fee",  "cost": "$500.00",             "note": "Due upon lease signing"},
            {"item": "Bike storage",        "cost": "Complimentary",       "note": ""},
        ],
        "parking": [
            {"type": "Standard (attached garage)",     "cost": "$350/mo"},
            {"type": "Semi-private (attached garage)",  "cost": "$450/mo"},
            {"type": "EV (attached garage)",            "cost": "$500/mo"},
        ],
        "bundled": [
            {"type": "Studio",        "cost": "$120/mo"},
            {"type": "Convertible",   "cost": "$130/mo"},
            {"type": "One bedroom",   "cost": "$140/mo"},
            {"type": "Two bedrooms",  "cost": "$160/mo"},
            {"type": "Three bedrooms","cost": "$195/mo"},
        ],
        "bundled_note": "Includes internet, gas, water, sewer, trash, and recycling.",
        "pets": [
            {"item": "One-time fee (1 pet)",  "cost": "$300"},
            {"item": "One-time fee (2 pets)", "cost": "$450"},
            {"item": "Monthly pet rent",      "cost": "$35/pet"},
        ],
        "pet_policy": "Max 2 pets per unit. Contact leasing office for breed restrictions.",
        "disclaimer": (
            "Pricing, fees, and incentives are subject to change without notice. "
            "Net effective rents may reflect concessions or limited-time offers. "
            "Contact the leasing office for the most current information."
        ),
    },
}
