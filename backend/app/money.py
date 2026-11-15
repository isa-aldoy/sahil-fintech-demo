"""Exact money handling. No floats anywhere: amounts are parsed to integer fils."""
import re

_AMOUNT = re.compile(r"^[0-9]{1,7}(\.[0-9]{1,3})?$")  # ASCII digits only


def parse_bhd(text: str) -> int:
    """'12.5' -> 12500 fils. Raises ValueError for anything that is not a plain positive amount."""
    text = text.strip()
    if not _AMOUNT.match(text):
        raise ValueError("Enter an amount like 12.500")
    whole, _, frac = text.partition(".")
    fils = int(whole) * 1000 + int((frac + "000")[:3])
    if fils <= 0:
        raise ValueError("Amount must be more than zero")
    return fils


def format_bhd(fils: int) -> str:
    sign = "-" if fils < 0 else ""
    fils = abs(fils)
    return f"{sign}{fils // 1000:,}.{fils % 1000:03d}"
