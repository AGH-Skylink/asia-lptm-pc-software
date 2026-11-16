"""Readable ASCII conversion for chat and text transmission."""
import unicodedata


def ascii_text(text: str) -> str:
    replacements = str.maketrans({
        "ł": "l", "Ł": "L", "ß": "ss", "ẞ": "SS", "æ": "ae", "Æ": "AE",
        "ø": "o", "Ø": "O", "œ": "oe", "Œ": "OE", "đ": "d", "Đ": "D",
        "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "–": "-", "—": "-",
        "−": "-", "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"', "…": "...",
    })
    normalized = unicodedata.normalize("NFKD", text.translate(replacements))
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.encode("ascii", errors="replace").decode("ascii")


def convert_ascii_field(widget) -> bool:
    original = widget.get("1.0", "end-1c")
    converted = ascii_text(original)
    if original == converted:
        return False
    widget.delete("1.0", "end")
    widget.insert("1.0", converted)
    return True
