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
        "argues with the referee, the group chat, and reality itself, and loses to all three",
        "the human embodiment of 'I'm not mad, you're wrong'",
        "could be shown video evidence and still find a way to be right in his own head",
    ],
    "rsguy": [
        "currently thinking about a torta instead of literally anything happening in this chat",
        "has a torta-shaped hole in his heart and it's showing",
        "would trade the whole parlay slip for one good torta",
        "shows up to the group chat with the enthusiasm of a man who just remembered lunch exists",
        "his love language is sandwiches and it's honestly kind of sad",
        "if RSguy had a walk-up song it would just be the sound of a torta being wrapped in foil",
    ],
    "derb": [
        "rolled out of bed at 4pm again, professional sleeper",
        "certified bum sleep schedule, wakes up when the west coast games are already in the 6th",
        "hasn't seen a sunrise since the Clinton administration",
        "operates on a schedule that only exists in international waters",
        "sleep is his one true skill and honestly his only skill",
        "wakes up more refreshed at 4pm than most people feel after a full night's rest, and does absolutely nothing with it",
    ],
    "wash wombat": [
        "down so bad on his bets the unit tracker should just start crying preemptively",
        "still betting like the parlay gods owe him something",
        "0-fer energy every single week and yet he keeps firing",
        "the unit tracker has a restraining order against him at this point",
        "bets with the confidence of a man who has never once cashed",
        "his record is the reason 'regression to the mean' was invented",
    ],
    "wombat": [
        "down so bad on his bets the unit tracker should just start crying preemptively",
        "still betting like the parlay gods owe him something",
        "the unit tracker has a restraining order against him at this point",
    ],
    "mas": [
        "only shows up asking for the unethical, never for anything else",
        "has never once asked about anything that wasn't an unethical",
        "shows up, asks for the unethical, disappears -- every single time",
        "the second something unethical drops, he's suddenly very present",
        "his entire relationship with this server is asking for unethicals",
        "doesn't care about the game, the bet, or the chat -- just the unethical",
    ],
}

# Short reputation summaries fed to the AI generator as a persona hint --
# separate from KNOWN_GAGS (the fixed template lines used as fallback),
# since the AI should riff on the trait freely rather than reuse the exact
# wording of any specific line.
PERSONA_HINTS = {
    "jjmac": "Notoriously stubborn -- never admits he's wrong about anything, will argue a losing point forever.",
    "rsguy": "Obsessed with tortas, always seems to be thinking about food over whatever's actually happening.",
    "derb": "Sleeps way too late, rolls in mid-afternoon, certified bum sleep schedule.",
    "wash wombat": "Historically bad at betting, always fires anyway despite a rough record.",
    "wombat": "Historically bad at betting, always fires anyway despite a rough record.",
    "mas": "Only ever shows up asking for the unethical -- never contributes anything, never talks about anything else.",
}


def match_persona_hint(display_name: str) -> str | None:
    name_lower = display_name.lower()
    for fragment, hint in PERSONA_HINTS.items():
        if fragment in name_lower:
            return hint
    return None


GENERIC_LINES = [
    "sent {count} messages this week and somehow said nothing of substance",
    "{count} messages deep and still hasn't had an original thought",
    "posting at a {count}-messages-a-week pace like anyone asked",
    "talks a lot for someone who never says anything worth remembering",
    "{count} messages and not a single one worth screenshotting",
    "quantity over quality, every single week",
    "clearly has nowhere else to be",
    "each message somehow less interesting than the last",
    "put in real hours this week for zero payoff",
    "deep into a bit nobody asked him to start",
]

LATE_NIGHT_LINES = [
    "posts like a raccoon, wide awake at the exact hours normal people are asleep",
    "clearly has no relationship with a normal sleep schedule",
    "running on a body clock set to a different time zone entirely, and not a good one",
    "posting at hours that should honestly concern someone",
    "up typing when the rest of the group is dead asleep like a normal person",
    "operating on vampire hours and it shows in every message",
]

LOL_LINES = [
    "said 'lol' {lol_count} times this week without once actually laughing",
    "hides behind 'lol' instead of ever having a real reaction",
    "can't finish a thought without typing 'lol' like it means something",
    "'lol' is basically his entire personality at this point",
    "types 'lol' the way other people breathe -- constantly, without thinking",
]

CAPS_LINES = [
    "went full caps lock {caps_count} times, main character syndrome in full effect",
    "screams in text for absolutely no reason",
    "treats the caps lock key like it owes him money",
    "acts like every message is breaking news",
    "types like the group chat can't hear him unless he's yelling",
]

QUESTION_LINES = [
    "asked {question_count} questions this week and still doesn't know anything",
    "questions everything, answers nothing",
    "still hasn't connected a single dot despite asking about all of them",
    "more confused by the end of the week than at the start of it",
    "asks like the answer will finally make sense this time -- it won't",
]

# Rotating connectors between clauses, instead of always defaulting to
# "Also," -- this alone kills a lot of the sameness across different
# people's roasts.
CONNECTORS = [
    "Also,", "And get this —", "Not to mention,", "On top of that,",
    "Oh, and", "As if that's not enough,", "Cherry on top:",
]

# Chance any single qualifying "extra" clause (late-night/lol/caps/
# questions) actually gets included. Crossing the threshold used to
# GUARANTEE the clause would appear -- with deep backfilled history,
# almost everyone clears these bars every time, so nearly every roast
# ended up citing 2-3 stats regardless of wording variety. Gating it
# probabilistically means plenty of roasts skip stats entirely and lean
# on the gag/generic line alone.
EXTRA_INCLUDE_CHANCE = 0.5

FLASHBACK_LINES = [
    "never forget when he said \"{quote}\" — truly a defining moment",
    "pulled from the archives: \"{quote}\" — words to live by, unfortunately",
    "going through the receipts and found this gem: \"{quote}\"",
    "the server remembers: \"{quote}\" — some things you just can't take back",
    "still thinking about the time he said \"{quote}\"",
]

NO_DATA_LINES = [
    "hasn't said a word all week -- witness protection or just scared?",
    "so quiet lately we forgot he was even in this server",
]


def _match_gag(display_name: str, exclude: list[str] | None = None) -> str | None:
    """Picks a gag line for this person, excluding any of their recently
    used lines so it takes longer to cycle back to the same joke."""
    exclude = exclude or []
    name_lower = display_name.lower()
    for fragment, lines in KNOWN_GAGS.items():
        if fragment not in name_lower:
            continue
        pool = [l for l in lines if l not in exclude] or lines  # fall back to full pool if it'd empty out
        return random.choice(pool)
    return None


def build_roast(display_name: str, stats: dict, recent_lines: list[str] | None = None,
                 flashback_quote: str | None = None) -> str:
    """stats: output of storage.get_user_stats. recent_lines: this
    person's last few delivered lines (from storage.get_recent_lines),
    excluded from selection so roasts don't loop back too soon.
    flashback_quote: an optional REAL old message (from
    storage.get_random_message) -- when present, has a chance of being
    woven in as a direct callback instead of (or alongside) the usual
    gag/stat lines. This is the 'remembers everything for months' payoff:
    an actual quote, not a paraphrase. Returns the full roast line --
    caller saves it via storage.record_roast_line() afterward."""
    if stats.get("count", 0) == 0:
        return f"**{display_name}** — {random.choice(NO_DATA_LINES)}"

    parts = []

    # Flashback fires some of the time when material exists, so it reads
    # as a surprise callback rather than a guaranteed structural element
    # every single roast.
    if flashback_quote and random.random() < 0.35:
        parts.append(random.choice(FLASHBACK_LINES).format(quote=flashback_quote[:150]))

    known = _match_gag(display_name, exclude=recent_lines)
    if known:
        parts.append(known)
    else:
        parts.append(random.choice(GENERIC_LINES).format(count=stats["count"]))

    extras = []
    if stats.get("late_night_ratio", 0) >= 0.2 and random.random() < EXTRA_INCLUDE_CHANCE:
        extras.append(random.choice(LATE_NIGHT_LINES))
    if stats.get("lol_count", 0) >= 3 and random.random() < EXTRA_INCLUDE_CHANCE:
        extras.append(random.choice(LOL_LINES).format(lol_count=stats["lol_count"]))
    if stats.get("caps_count", 0) >= 2 and random.random() < EXTRA_INCLUDE_CHANCE:
        extras.append(random.choice(CAPS_LINES).format(caps_count=stats["caps_count"]))
    if stats.get("question_count", 0) >= 5 and random.random() < EXTRA_INCLUDE_CHANCE:
        extras.append(random.choice(QUESTION_LINES).format(question_count=stats["question_count"]))

    if extras:
        random.shuffle(extras)
        # Even among qualifying extras, usually take just one -- taking
        # two is the occasional exception, not the norm, so the roast's
        # length/shape varies too, not just the wording.
        take = 2 if len(extras) >= 2 and random.random() < 0.25 else 1
        parts.extend(extras[:take])
    elif known and random.random() < 0.5:
        # Known-gag people SOMETIMES get a real stat line blended in --
        # not always, or the gag+stat combo becomes its own predictable
        # skeleton. Plenty of roasts are just the gag alone.
        parts.append(random.choice(GENERIC_LINES).format(count=stats["count"]))

    if len(parts) == 1:
        body = f" — {parts[0]}"
    else:
        joined = f". {random.choice(CONNECTORS)} ".join(parts)
        body = f" — {joined}"
    return f"**{display_name}**{body}."
