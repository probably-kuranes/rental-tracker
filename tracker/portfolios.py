"""The owner entities, and how to tell which one a statement belongs to.

The name printed on a statement is only Mid South's contact name (Torgo's
statements say "Walter Mascari - T" or "David Mascari"), so a statement is
assigned to a portfolio by the properties on it.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

PORTFOLIOS = [
    {'key': 'david', 'name': 'David Mascari', 'short': 'David', 'color': '#2563A8'},
    {'key': 'dunwich', 'name': 'Dunwich Properties LLC', 'short': 'Dunwich', 'color': '#D97A1E'},
    {'key': 'torgo', 'name': 'Torgo Properties LLC', 'short': 'Torgo', 'color': '#1F8A70'},
    {'key': 'miskatonic', 'name': 'Miskatonic Properties LLC', 'short': 'Miskatonic', 'color': '#8B5CC4'},
    {'key': 'walter', 'name': 'Walter Mascari', 'short': 'Walter', 'color': '#C2417A'},
]
PORTFOLIO_BY_KEY = {p['key']: p for p in PORTFOLIOS}

# Properties that have only ever been in one portfolio. Any one of them on a
# statement identifies the portfolio.
ANCHORS = {
    'david': {'1743-warner', '2615-wellons', '3404-ladue', '3934-argonne', '501-sullivan'},
    'dunwich': {'2478-durham', '3227-lyndale', '3178-manhattan', '1452-robinhood'},
    'torgo': {'3642-windermere'},
    'miskatonic': {'1166-barksdale'},
}
# Statements with none of the anchors: the properties' earlier owners.
FALLBACK = {
    '3403-ladue': 'walter',
    '4333-melwood': 'walter',
    '2549-durham': 'miskatonic',
}
# Contact names that identify a portfolio when the properties cannot.
RECIPIENT_HINTS = {
    'walter mascari - t': 'torgo',
    'torgo': 'torgo',
    'patrizia coletti': 'miskatonic',
    'miskatonic': 'miskatonic',
    'dunwich': 'dunwich',
}

_STREET_NOISE = {'st', 'street', 'rd', 'road', 'ave', 'avenue', 'dr', 'drive', 'ln', 'cv', 'cove',
                 's', 'n', 'e', 'w', 'apt', 'unit'}


def property_key(address: str) -> str:
    """'3403 Ladue St', 'Ladue3403', '3403LADUEST', '1166 S.Barksdale' -> '3403-ladue'."""
    text = address.replace('_1', ' ').replace('.', ' ')
    num = re.search(r'\d{3,5}', text)
    words = [w.lower() for w in re.findall(r'[A-Za-z]+', text)]
    words = [w for w in words if w not in _STREET_NOISE]
    if not num or not words:
        return re.sub(r'[^a-z0-9]+', '-', address.lower()).strip('-')
    word = words[0]
    # Ledger prefixes glue the suffix on ("3403LADUEST", "3642WINDERME").
    for suffix in ('st', 'rd', 'ave'):
        if word.endswith(suffix) and len(word) > len(suffix) + 3 and word[:-len(suffix)] in _KNOWN_STREETS:
            word = word[:-len(suffix)]
    for known in _KNOWN_STREETS:
        if known.startswith(word) and len(word) >= 5:
            word = known
    return f"{num.group(0)}-{word}"


_KNOWN_STREETS = {'ladue', 'windermere', 'melwood', 'warner', 'wellons', 'argonne', 'sullivan',
                  'durham', 'barksdale', 'lyndale', 'manhattan', 'robinhood'}


def portfolio_for(property_keys: Iterable[str], recipient: str = '') -> Optional[str]:
    keys = set(property_keys)
    for pf, anchors in ANCHORS.items():
        if keys & anchors:
            return pf
    for k in keys:
        if k in FALLBACK:
            return FALLBACK[k]
    r = recipient.lower()
    for hint, pf in RECIPIENT_HINTS.items():
        if hint in r:
            return pf
    return None
