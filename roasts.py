"""
Roast generation: combines real tracked activity (message count, posting
hours, habits) with a bank of running-gag lines for specific known
members, plus generic fallback lines for anyone else. Content stays
scoped to what someone actually posts in the server -- never appearance,
personal life, or anything outside Discord activity.
"""
import random

# Matched against a member's display name/username, lowercase substring.
# Add more entries any time -- key is the fragment to match, value is a
# list of lines (one gets picked at random each roast so it doesn't feel
# repetitive back-to-back).
KNOWN_GAGS = {
    "jjmac": [
        "still hasn't admitted he's wrong about a single thing this calendar year",
        "will die on a hill nobody else is even standing on",
        "stubborn to the point it should be a diagnosable condition",
    ],
    "rsguy": [
        "currently thinking about a torta instead of literally anything happening in this chat",
        "has a torta-shaped hole in his heart and it's showing",
        "would trade the whole parlay slip for one good torta",
    ],
    "derb": [
        "rolled out of bed at 4pm again, professional sleeper",
        "certified bum sleep schedule, wakes up when the west coast games are already in the 6th",
        "hasn't seen a sunrise since the Clinton administration",
    ],
    "wash wombat": [
        "down so bad on his bets the unit tracker should just start crying preemptively",
        "still betting like the parlay gods owe him something",
        "0-fer energy every single week and yet he keeps firing",
    ],
    "wombat": [
        "down so bad on his bets the unit tracker should just start crying preemptively",
        "still betting like the parlay gods owe him something",
    ],
    "mas": [
        "only shows up in the DMs asking for the unethical",
        "allergic to paying for anything, but never misses a chance to ask",
    ],
}


GENERIC_LINES = [
    "sent {count} messages this week and somehow said nothing of substance",
    "{count} messages deep and still hasn't had an original thought",
    "posting at a {count}-messages-a-week pace like anyone asked",
]

LATE_NIGHT_LINES = [
    "posts like a raccoon, wide awake at the exact hours normal people are asleep",
    "clearly has no relationship with a normal sleep schedule",
]

LOL_LINES = [
    "said 'lol' {lol_count} times this week without once actually laughing",
]

CAPS_LINES = [
    "went full caps lock {caps_count} times, main character syndrome in full effect",
]

QUESTION_LINES = [
    "asked {question_count} questions this week and still doesn't know anything",
]

NO_DATA_LINES = [
    "hasn't said a word all week -- witness protection or just scared?",
    "so quiet lately we forgot he was even in this server",
]


def _match_gag(display_name: str) -> str | None:
    name_lower = display_name.lower()
    for fragment, lines in KNOWN_GAGS.items():
        if fragment in name_lower:
            return random.choice(lines)
    return None


def build_roast(display_name: str, stats: dict) -> str:
    """stats: output of storage.get_user_stats. Returns a full roast line."""
    if stats.get("count", 0) == 0:
        return f"**{display_name}** — {random.choice(NO_DATA_LINES)}"

    parts = []

    known = _match_gag(display_name)
    if known:
        parts.append(known)
    else:
        parts.append(random.choice(GENERIC_LINES).format(count=stats["count"]))

    extras = []
    if stats.get("late_night_ratio", 0) >= 0.3:
        extras.append(random.choice(LATE_NIGHT_LINES))
    if stats.get("lol_count", 0) >= 5:
        extras.append(random.choice(LOL_LINES).format(lol_count=stats["lol_count"]))
    if stats.get("caps_count", 0) >= 3:
        extras.append(random.choice(CAPS_LINES).format(caps_count=stats["caps_count"]))
    if stats.get("question_count", 0) >= 8:
        extras.append(random.choice(QUESTION_LINES).format(question_count=stats["question_count"]))

    if extras:
        parts.append(random.choice(extras))

    body = " — " + ". Also, ".join(parts) if len(parts) > 1 else f" — {parts[0]}"
    return f"**{display_name}**{body}."
