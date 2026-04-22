from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Canonical values stored in DB
POSITIONS: list[str] = [
    "designer",
    "art_director",
    "copywriter",
    "creative_director",
    "junior_art_director",
    "junior_copywriter",
    "senior_art_director",
    "senior_copywriter",
    "traffic_manager",
]

POSITION_LABELS: dict[str, str] = {
    "designer": "Designer",
    "art_director": "Art Director",
    "copywriter": "Copywriter",
    "creative_director": "Creative Director",
    "junior_art_director": "Junior Art Director",
    "junior_copywriter": "Junior Copywriter",
    "senior_art_director": "Senior Art Director",
    "senior_copywriter": "Senior Copywriter",
    "traffic_manager": "Traffic Manager",
}


def position_label(pos: str | None) -> str:
    if not pos:
        return "—"
    return POSITION_LABELS.get(pos, pos)


def positions_kb(prefix: str) -> InlineKeyboardMarkup:
    # 2 columns layout as requested
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("Designer", callback_data=f"{prefix}:designer"),
            InlineKeyboardButton("Art Director", callback_data=f"{prefix}:art_director"),
        ],
        [
            InlineKeyboardButton("Copywriter", callback_data=f"{prefix}:copywriter"),
            InlineKeyboardButton("Creative Director", callback_data=f"{prefix}:creative_director"),
        ],
        [
            InlineKeyboardButton("Junior Art Director", callback_data=f"{prefix}:junior_art_director"),
            InlineKeyboardButton("Junior Copywriter", callback_data=f"{prefix}:junior_copywriter"),
        ],
        [
            InlineKeyboardButton("Senior Art Director", callback_data=f"{prefix}:senior_art_director"),
            InlineKeyboardButton("Senior Copywriter", callback_data=f"{prefix}:senior_copywriter"),
        ],
    ]
    return InlineKeyboardMarkup(rows)

