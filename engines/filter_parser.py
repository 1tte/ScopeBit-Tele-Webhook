"""
Filter parser for scanner commands.
Supports: /rcm cm > 100jt, /rsm sm > 500jt, etc.
"""
import re

# Alias mapping: user-friendly names → dict keys
_ALIASES = {
    "cm": "cm", "cleanmoney": "cm", "clean_money": "cm", "clean": "cm",
    "sm": "sm", "smartmoney": "sm", "smart_money": "sm", "smart": "sm",
    "bm": "bm", "badmoney": "bm", "bad_money": "bm", "bad": "bm",
    "tx": "tx", "freq": "tx", "count": "tx",
}

# Value suffix multipliers
_SUFFIXES = {
    "jt": 1_000_000,
    "m": 1_000_000_000,
    "rb": 1_000,
    "k": 1_000,
    "t": 1_000_000_000_000,
}

_OPS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "=": lambda a, b: a == b,
    "==": lambda a, b: a == b,
}


def parse_filter(filter_str: str):
    """Parse filter string like 'cm > 100jt' → callable(row) -> bool.
    
    Returns None if filter_str is empty or unparseable.
    """
    if not filter_str or not filter_str.strip():
        return None

    # Pattern: variable operator value[suffix]
    pattern = r"(\w+)\s*(>=|<=|==|>|<|=)\s*(-?[\d.]+)\s*(\w*)"
    match = re.match(pattern, filter_str.strip())
    if not match:
        return None

    var_name, op_str, val_str, suffix = match.groups()

    # Resolve variable
    key = _ALIASES.get(var_name.lower())
    if not key:
        return None

    # Resolve operator
    op_fn = _OPS.get(op_str)
    if not op_fn:
        return None

    # Resolve value
    try:
        value = float(val_str)
    except ValueError:
        return None

    if suffix:
        mult = _SUFFIXES.get(suffix.lower())
        if mult:
            value *= mult

    value = int(value)

    def _filter(row: dict) -> bool:
        return op_fn(row.get(key, 0), value)

    return _filter
