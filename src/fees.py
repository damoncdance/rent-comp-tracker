"""Fee schedules by property name.

Keyed by property name from the DB. Data sourced from HelloData Comp Report
#53 (May 2026, page 30) and individual property websites.

Properties without an entry will show "No fee schedule configured" on the
dashboard Fees tab.
"""

FEES: dict[str, dict] = {
    "Inspire West Town": {
        "application": [
            {"item": "Application fee", "cost": "$60", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$500", "note": "Due at lease signing"},
        ],
        "parking": [
            {"type": "Garage", "cost": "$250–$350/mo"},
        ],
        "pets": [
            {"item": "Monthly pet rent", "cost": "$35/pet"},
        ],
    },
    "Nevele22": {
        "application": [
            {"item": "Application fee", "cost": "$50", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$500", "note": ""},
        ],
        "parking": [
            {"type": "Garage", "cost": "$335/mo"},
        ],
        "pets": [
            {"item": "Monthly pet rent", "cost": "$35/pet"},
            {"item": "Pet fee", "cost": "$500", "note": "One-time"},
        ],
    },
    "Seven 10 West": {
        "application": [
            {"item": "Application fee", "cost": "$75", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$400", "note": ""},
        ],
        "pets": [
            {"item": "Pet deposit", "cost": "$250 cat / $400 dog"},
        ],
    },
    "Westerly": {
        "application": [
            {"item": "Application fee", "cost": "$65", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$500", "note": ""},
        ],
        "parking": [
            {"type": "Garage", "cost": "$350/mo"},
        ],
        "pets": [
            {"item": "Monthly pet rent", "cost": "$35/pet"},
            {"item": "Pet fee", "cost": "$500", "note": "One-time"},
        ],
    },
    "Hugo River North": {
        "application": [
            {"item": "Application fee", "cost": "$75", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$500", "note": ""},
        ],
        "parking": [
            {"type": "Garage", "cost": "$300/mo"},
        ],
        "pets": [
            {"item": "Monthly pet rent", "cost": "$25/pet"},
        ],
    },
    "812 West Adams": {
        "application": [
            {"item": "Application fee", "cost": "$50", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$500", "note": ""},
        ],
    },
    "The Jax": {
        "application": [
            {"item": "Application fee", "cost": "$75", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$500", "note": ""},
        ],
        "pets": [
            {"item": "Monthly pet rent", "cost": "$25/pet"},
            {"item": "Pet fee", "cost": "$350", "note": "One-time"},
        ],
    },
    "The Ardus": {
        "application": [
            {"item": "Application fee", "cost": "$50", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$500", "note": ""},
        ],
        "pets": [
            {"item": "Monthly pet rent", "cost": "$25/pet"},
            {"item": "Pet fee", "cost": "$250", "note": "One-time"},
        ],
        "parking": [
            {"type": "Garage", "cost": "$350/mo"},
        ],
    },
    "Evo Union Park Apartments": {
        "application": [
            {"item": "Application fee", "cost": "$50", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$500", "note": ""},
        ],
        "parking": [
            {"type": "Garage", "cost": "$300/mo"},
        ],
        "pets": [
            {"item": "Monthly pet rent", "cost": "$30/pet"},
            {"item": "Pet fee", "cost": "$350", "note": "One-time"},
        ],
    },
    "Arthurs of Old Town": {
        "application": [
            {"item": "Application fee", "cost": "$75", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$600", "note": ""},
        ],
    },
    "The Van Buren": {
        "application": [
            {"item": "Application fee", "cost": "$60", "note": "Per applicant"},
            {"item": "Administration fee", "cost": "$500", "note": ""},
        ],
        "parking": [
            {"type": "Garage", "cost": "$350/mo"},
        ],
        "pets": [
            {"item": "Monthly pet rent", "cost": "$30/pet"},
            {"item": "Pet fee", "cost": "$300", "note": "One-time"},
        ],
    },
    "1100 W Grand Ave": {
        "application": [
            {"item": "Application fee", "cost": "$75", "note": "Non-refundable"},
            {"item": "Administration fee", "cost": "$500", "note": "Due upon lease signing"},
            {"item": "Bike storage", "cost": "Complimentary", "note": ""},
        ],
        "parking": [
            {"type": "Standard (attached garage)", "cost": "$350/mo"},
            {"type": "Semi-private (attached garage)", "cost": "$450/mo"},
            {"type": "EV (attached garage)", "cost": "$500/mo"},
        ],
        "bundled": [
            {"type": "Studio", "cost": "$120/mo"},
            {"type": "Convertible", "cost": "$130/mo"},
            {"type": "One bedroom", "cost": "$140/mo"},
            {"type": "Two bedrooms", "cost": "$160/mo"},
            {"type": "Three bedrooms", "cost": "$195/mo"},
        ],
        "bundled_note": "Includes internet, gas, water, sewer, trash, and recycling.",
        "pets": [
            {"item": "One-time fee (1 pet)", "cost": "$300"},
            {"item": "One-time fee (2 pets)", "cost": "$450"},
            {"item": "Monthly pet rent", "cost": "$35/pet"},
        ],
        "pet_policy": "Max 2 pets per unit. Contact leasing office for breed restrictions.",
        "disclaimer": (
            "Pricing, fees, and incentives are subject to change without notice. "
            "Net effective rents may reflect concessions or limited-time offers. "
            "Contact the leasing office for the most current information."
        ),
    },
}
