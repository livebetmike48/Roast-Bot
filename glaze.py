"""
Glaze generation: the opposite of roasts.py. Combines a bank of
over-the-top praise lines with real compliments pulled from OTHER
people's messages (including backfilled history) that mention the
target -- so a glaze can surface an actual "derb is the goat" someone
said months ago, not just a canned line.
"""
import random

# Positive-language cues used to filter storage.get_compliment_candidates
# down to messages that actually read as praise, not just any message
# that happens to mention the person's name.
POSITIVE_KEYWORDS = [
    "goat", "the guy", "legend", "unreal", "elite", "insane", "clutch",
    "king", "mvp", "love this guy", "genius", "cooking", "cooked",
    "nasty", "real one", "goated", "w derb", "best bettor", "carried",
    "carries", "no cap", "actually good", "underrated", "respect",
]

# Known GOAT-tier praise pools, same shape as roasts.KNOWN_GAGS -- add
# more people any time.
KNOWN_GLAZE = {
    "derb": [
        "the GOAT, undisputed, no notes",
        "the reason this server even has a pulse",
        "quietly the most important person in this chat and nobody says it enough",
        "built different, and everyone knows it",
        "the blueprint. Everyone else is just cosplaying.",
        "Mr. Moneyline himself, and honestly? Earned.",
        "the only one in here actually cooking",
        "a legend walking among mortals",
    ],
}

GENERIC_GLAZE_LINES = [
    "an absolute rock in this server, respect",
    "carrying this chat and not getting nearly enough credit for it",
    "one of the good ones, genuinely",
    "underrated in every possible way",
    "the kind of person that makes a group chat actually worth being in",
    "doing more for this server than people realize",
]

COMPLIMENT_LINES = [
    "and it's not just us -- {author} said it best: \"{quote}\"",
    "don't just take it from us, {author} put it perfectly: \"{quote}\"",
    "the people agree -- {author} said \"{quote}\" and honestly, correct",
    "receipts don't lie: {author} once said \"{quote}\"",
]

NO_DATA_GLAZE_LINES = [
    "hasn't said much lately, but greatness doesn't need to announce itself",
    "quiet, but that's what legends do",
]


def _match_known_glaze(display_name: str, exclude: list[str] | None = None) -> str | None:
    exclude = exclude or []
    name_lower = display_name.lower()
    for fragment, lines in KNOWN_GLAZE.items():
        if fragment not in name_lower:
            continue
        pool = [l for l in lines if l not in exclude] or lines
        return random.choice(pool)
    return None


def find_compliment(candidates: list[dict]) -> tuple[str, str] | None:
    """candidates: storage.get_compliment_candidates() output. Returns
    (quote, author_username) for the first message containing real
    positive language, or None if nothing qualifies."""
    for row in candidates:
        content = row.get("content") or ""
        content_lower = content.lower()
        if any(kw in content_lower for kw in POSITIVE_KEYWORDS):
            return content[:150], row.get("username", "someone")
    return None


def build_glaze(display_name: str, message_count: int, recent_lines: list[str] | None = None,
                 compliment: tuple[str, str] | None = None) -> str:
    """message_count: how much activity this person has (from
    storage.get_user_stats -- just needs the count). recent_lines: this
    person's last few delivered GLAZE lines (kind='glaze'), excluded so
    it doesn't loop back too soon. compliment: (quote, author) from
    find_compliment, when real praise material exists in the server's
    history."""
    if message_count == 0:
        return f"**{display_name}** — {random.choice(NO_DATA_GLAZE_LINES)}"

    parts = []
    known = _match_known_glaze(display_name, exclude=recent_lines)
    parts.append(known if known else random.choice(GENERIC_GLAZE_LINES))

    if compliment:
        quote, author = compliment
        parts.append(random.choice(COMPLIMENT_LINES).format(quote=quote, author=author))

    body = " — " + ". ".join(parts) if len(parts) > 1 else f" — {parts[0]}"
    return f"**{display_name}**{body}."
