# utils.py
"""Static SEO description template and title formatter for YouTube beat uploads."""

import os
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
    lines.append(f'"{title}" — Prod. {producer}')
    lines.append("")

    # ── Beat info block ──
    lines.append("── Beat Info ──")
    lines.append(f"Title : {title}")
    lines.append(f"Prod. : {producer}")
    lines.append(f"BPM   : {bpm}")
    lines.append(f"Key   : {key}")
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
    hashtags = ["#typebeat", "#beats", "#instrumental", "#freebeat"]
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


def format_youtube_title(title: str, producer: str, bpm: str) -> str:
    """Format a standard type-beat YouTube title.

    Example:  [FREE] TimeTraveller, prod pk (148 bpm)
    """
    bpm_num = bpm.lower().replace("bpm", "").strip()
    return f"[FREE] {title}, prod {producer} ({bpm_num} bpm)"