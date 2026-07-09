"""Delivery: send email via the Resend HTTP API.

Railway (and many hosts) block outbound SMTP, so delivery goes over HTTPS
(443) through Resend rather than an SMTP provider like Gmail. Same pattern as
the morning-digest project.
"""
from __future__ import annotations

from typing import Optional

import requests

RESEND_URL = "https://api.resend.com/emails"


def send(api_key: str, from_addr: str, to_addr: str, subject: str,
         text_body: str, html_body: Optional[str] = None) -> None:
    payload = {
        "from": from_addr,
        "to": [to_addr],
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        payload["html"] = html_body

    resp = requests.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Resend API error {resp.status_code}: {resp.text}")
