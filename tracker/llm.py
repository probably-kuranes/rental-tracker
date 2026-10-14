"""The two places Claude is used: reading Mid South's update emails, and
writing the monthly summary. Both are optional; without ANTHROPIC_API_KEY
the tracker still works and the summary falls back to a plain list."""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

MODEL = os.getenv('LLM_MODEL', 'claude-opus-5-5')
FALLBACK_BETA = 'server-side-fallback-2026-07-01'


def available() -> bool:
    return bool(os.getenv('ANTHROPIC_API_KEY') or os.getenv('ANTHROPIC_AUTH_TOKEN'))


def _client():
    import anthropic
    return anthropic.Anthropic()


def _create(**kwargs):
    """messages.create with refusal fallbacks enabled; returns the text, or
    None if the request was refused."""
    response = _client().beta.messages.create(
        model=MODEL, betas=[FALLBACK_BETA], fallbacks='default', **kwargs)
    if response.stop_reason == 'refusal':
        log.warning("Claude declined the request: %s", response.stop_details)
        return None
    return ''.join(b.text for b in response.content if b.type == 'text')


EMAIL_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['relevant', 'summary', 'events'],
    'properties': {
        'relevant': {'type': 'boolean', 'description': 'True if the email is about one of the owner\'s properties.'},
        'summary': {'type': 'string', 'description': 'One sentence, plain English.'},
        'events': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['property', 'date', 'type', 'title', 'amount'],
                'properties': {
                    'property': {'type': 'string', 'description': 'Street address as written, e.g. "4333 Melwood".'},
                    'date': {'type': 'string', 'description': 'YYYY-MM-DD the thing happened (the email date if not stated).'},
                    'type': {'type': 'string', 'enum': [
                        'lease', 'renewal', 'move_out', 'make_ready', 'repair', 'repair_request', 'theft',
                        'vandalism', 'eviction', 'inspection', 'late', 'insurance', 'code_violation', 'update']},
                    'title': {'type': 'string', 'description': 'Under 12 words.'},
                    'amount': {'type': ['number', 'null'], 'description': 'Dollar amount if one is given.'},
                },
            },
        },
    },
}

EMAIL_SYSTEM = (
    "You read emails from a property manager (Mid South Best Rentals, Memphis) to the owner of a small "
    "portfolio of rental houses, and record what happened at each house. Record facts the email states: "
    "new leases, move-outs, make-ready or repair work and its cost, repair requests, theft, vandalism, "
    "evictions, inspections, code violations. Marketing emails and routine notices about statements or "
    "deposits are not relevant. Do not guess an amount or a date the email does not give; use the email's "
    "date when the event date is not stated."
)


def extract_email_events(subject: str, sender: str, date: str, body: str) -> Optional[dict]:
    text = _create(
        max_tokens=4000,
        output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': EMAIL_SCHEMA}},
        system=EMAIL_SYSTEM,
        messages=[{'role': 'user', 'content': f"From: {sender}\nDate: {date}\nSubject: {subject}\n\n{body[:20000]}"}],
    )
    return json.loads(text) if text else None


SUMMARY_SYSTEM = {
    'owner': (
        "You write a brief monthly update about a family's rental houses in Memphis, for the owner. "
        "You are given the facts for one month as JSON, taken from the property manager's statements and "
        "emails. Format: one line saying how the month went overall; then, for each portfolio, its name on "
        "its own line followed by short bullet points (\"- \"), one per house where something happened and "
        "one for the money (rent collected, costs, paid out, balance with the manager). Keep each bullet to "
        "one line where possible. Use exact figures from the facts. Say plainly when a statement is missing "
        "or a house is empty. Never invent anything that is not in the facts. No other headings, no "
        "closing pleasantries. Plain text only: no Markdown, no bold, no asterisks."
    ),
    'family': (
        "You write a brief monthly email to the owner's parents about the Torgo Properties houses in "
        "Memphis. You are given the facts for one month as JSON. Write warmly and simply, as their son "
        "would. Format: 'Hi both,' on its own line; one short line on how the month went; then short "
        "bullet points (\"- \"), one per house (whether it is let, whether rent came in, any work and its "
        "cost) and one for the money (rent collected, costs, what was paid out, and the balance with the "
        "manager if it is below zero); then 'Love, David'. Keep each bullet to one line where possible. "
        "Never invent anything that is not in the facts. Plain text only: no Markdown, no bold, no asterisks."
    ),
    'manager': (
        "You draft a short email from the owner to the property manager (Mid South Best Rentals) following "
        "up on anything odd in one month's statements and emails. You are given the month's facts as JSON, "
        "including 'checks': things the owner's tracker flagged. Format: 'Hi,' on its own line; one line "
        "saying which month this is about; then numbered questions or requests, one per item, each specific "
        "(house, date, amount) and each asking for what the owner needs (an explanation, a missing statement, "
        "an invoice, a plan, a date). Group items for the same house. Skip anything routine. Polite and "
        "direct, no small talk. End with 'Thanks,' and 'David'. If nothing needs following up, write a "
        "single line saying so instead of an email. Never invent anything that is not in the facts. "
        "Do not ask for a statement the facts show is already covered by a longer statement. "
        "Plain text only: no Markdown, no bold, no asterisks."
    ),
}


def write_summary(facts: dict, audience: str = 'owner') -> Optional[str]:
    return _create(
        max_tokens=4000,
        output_config={'effort': 'medium'},
        system=SUMMARY_SYSTEM[audience],
        messages=[{'role': 'user', 'content': json.dumps(facts, default=str, indent=1)}],
    )
