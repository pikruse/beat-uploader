# utils.py
"""Static SEO description template and title formatter for YouTube beat uploads."""

import os
import re
from dotenv import load_dotenv

load_dotenv()

CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")
TIKTOK = os.getenv("TIKTOK", "")
INSTAGRAM = os.getenv("INSTAGRAM", "")


def generate_description(
    title: str,
    producer: str,
    bpm: str,
    key: str,
    beatstars_url: str = "",
    tags: list[str] | None = None,
) -> str:
    """Build a keyword-rich YouTube description for a type beat.

    Args:
        title:          Beat name (e.g. "TimeTraveller").
        producer:       Producer credit (e.g. "pk").
        bpm:            BPM string (e.g. "148 BPM").
        key:            Key string (e.g. "Cm").
        beatstars_url:  Purchase link (shown at top if provided).
        tags:           Extra genre / mood keywords.

    Returns:
        Formatted description string.
    """
    lines: list[str] = []

    # ── Purchase link (most important — above the fold) ──
    if beatstars_url:
        lines.append(f"🔥 Purchase / Lease this beat: {beatstars_url}")
        lines.append("")

    # ── Title + credit ──
    lines.append(f'"{title}" — prod {producer}')
    lines.append("")

    # ── Beat info block ──
    lines.append("── Beat Info ──")
    lines.append(f"Title: {title}")
    lines.append(f"Prod: {producer}")
    lines.append(f"BPM: {bpm}")
    lines.append(f"Key: {key}")
    lines.append("")

    # ── Tag line ──
    tag_list = tags or []
    if tag_list:
        lines.append("Genre / Mood: " + ", ".join(tag_list))
        lines.append("")

    # ── Contact ──
    if CONTACT_EMAIL:
        lines.append(f"📧 Business Inquiries: {CONTACT_EMAIL}")
        lines.append("")

    # ── Socials ──
    if TIKTOK or INSTAGRAM:
        lines.append("── Socials ──")
        if INSTAGRAM:
            lines.append(f"Instagram: https://instagram.com/{INSTAGRAM}")
        if TIKTOK:
            lines.append(f"TikTok: https://tiktok.com/@{TIKTOK}")
        lines.append("")

    # ── Hashtags (YouTube indexes these for search) ──
    hashtags = ["#typebeat", 
                "#beats", 
                "#instrumental", 
                "#freebeat", 
                "#prod_pk", 
                "#pk", 
                "#glo", 
                "#digicore", 
                "#underground",
                "#hiphop",
                "#rap",
                "#trap",
                "#lofi",
                "#chill",
                "#dark",
                "#emotional",
                "#melodic"]
    for p in producer.replace(",", " ").split():
        p = p.strip()
        if p:
            hashtags.append(f"#{p.lower()}")
    for t in tag_list[:5]:
        clean = t.strip().replace(" ", "").lower()
        if clean:
            hashtags.append(f"#{clean}")

    lines.append(" ".join(hashtags))

    return "\n".join(lines)


def clean_producer(producer: str) -> str:
    """Strip a leading "prod"/"prod." credit from each producer name.

    Beat filenames often already carry the credit ("NightDrive 140 prod pk"),
    and the title/description templates add their own "prod" — without this
    the output reads "prod prod pk". Names merely starting with the letters
    (e.g. "Prodigy") are untouched: only a standalone leading word counts.
    """
    parts = [re.sub(r"^prod\.?\s+", "", p.strip(), flags=re.IGNORECASE).strip()
             for p in producer.split(",")]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else producer.strip()


def format_youtube_title(title: str, producer: str, bpm: str,
                         tags: list[str] | None = None) -> str:
    """Format a standard type-beat YouTube title.

    Example:  [Free] trap x dark type beat - "TimeTraveller" 148 bpm, prod pk

    YouTube rejects titles over 100 characters or containing < / > with
    "invalidTitle", so this strips those characters and, if the full form is
    too long, drops the tags, then the producer credit, before hard-trimming.
    """
    def clean(s: str) -> str:
        return s.replace("<", "").replace(">", "").strip()

    title = clean(title)
    bpm_num = clean(bpm.lower().replace("bpm", "").strip())

    tag_part = " x ".join(clean(t) for t in (tags or []) if clean(t))
    tag_part = f"{tag_part} " if tag_part else ""

    producers = [clean(p) for p in clean_producer(producer).split(",") if clean(p)]
    if not producers:
        prod_part = ""
    elif len(producers) == 1:
        prod_part = producers[0]
    else:
        prod_part = ", ".join(producers[:-1]) + " and " + producers[-1]

    candidates = [
        f'[Free] {tag_part}type beat - "{title}" {bpm_num} bpm, prod {prod_part}',
        f'[Free] type beat - "{title}" {bpm_num} bpm, prod {prod_part}',
        f'[Free] type beat - "{title}" {bpm_num} bpm',
    ]
    for cand in candidates:
        if len(cand) <= 100:
            return cand
    return candidates[-1][:100]