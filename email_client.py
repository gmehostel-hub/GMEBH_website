import os
import time
import logging
from typing import List, Optional, Dict, Any

import requests
from flask_mail import Message


class EmailClient:
    """
    Unified email client with support for Brevo (Sendinblue) API for bulk sending,
    with batching, pacing, and basic retries. Falls back to Flask-Mail if no API key.
    """

    def __init__(self, flask_app=None, flask_mail=None):
        self.provider = (os.environ.get("SEND_PROVIDER") or "").strip().lower()
        self.brevo_key = os.environ.get("BREVO_API_KEY")
        self.from_email = os.environ.get("FROM_EMAIL") or os.environ.get("MAIL_USERNAME")
        self.from_name = os.environ.get("FROM_NAME") or "Hostel Management"
        self._mail = flask_mail
        self._app = flask_app

        # Auto-select provider if not explicitly set
        if not self.provider:
            if self.brevo_key:
                self.provider = "brevo"
            else:
                self.provider = "flask_mail"

    # ---------- Public API ----------
    def send_single(self, to: str, subject: str, body_text: str, body_html: Optional[str] = None) -> bool:
        if self.provider == "brevo":
            return self._brevo_send_single(to, subject, body_text, body_html)
        return self._flask_mail_send_single(to, subject, body_text, body_html)

    def send_bulk(
        self,
        recipients: List[str],
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        batch_size: int = 50,
        delay_s: float = 30.0,
        max_retries: int = 3,
        jitter_s: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Send to many recipients with batching, pacing, and simple retries.
        Returns a summary dict with counts.
        """
        success = 0
        failed = 0
        errors: List[str] = []

        # Normalize and de-duplicate recipients
        deduped = []
        seen = set()
        for r in recipients:
            if not r:
                continue
            e = r.strip().lower()
            if e and e not in seen:
                seen.add(e)
                deduped.append(e)

        for i in range(0, len(deduped), batch_size):
            batch = deduped[i : i + batch_size]
            # Prefer sending individually for better deliverability
            for rcpt in batch:
                ok = self._send_with_retries(rcpt, subject, body_text, body_html, max_retries)
                if ok:
                    success += 1
                else:
                    failed += 1
            # Pace between batches
            if i + batch_size < len(deduped):
                sleep_time = max(0.0, delay_s + (jitter_s * (0.5 - os.urandom(1)[0] / 255.0)))
                time.sleep(sleep_time)

        return {"sent": success, "failed": failed, "total": len(deduped), "errors": errors}

    # ---------- Internal helpers ----------
    def _send_with_retries(self, to: str, subject: str, body_text: str, body_html: Optional[str], max_retries: int) -> bool:
        attempt = 0
        delay = 2.0
        while attempt <= max_retries:
            ok = self.send_single(to, subject, body_text, body_html)
            if ok:
                return True
            attempt += 1
            time.sleep(delay)
            delay = min(60.0, delay * 2)
        return False

    # ---------- Flask-Mail fallback ----------
    def _flask_mail_send_single(self, to: str, subject: str, body_text: str, body_html: Optional[str]) -> bool:
        if not self._mail or not self._app:
            logging.error("Flask-Mail not available")
            return False
        try:
            with self._app.app_context():
                msg = Message(subject, sender=self.from_email, recipients=[to])
                msg.body = body_text
                if body_html:
                    msg.html = body_html
                self._mail.send(msg)
            return True
        except Exception as e:
            logging.error(f"Flask-Mail send error: {e}")
            return False

    # ---------- Brevo (Sendinblue) ----------
    def _brevo_send_single(self, to: str, subject: str, body_text: str, body_html: Optional[str]) -> bool:
        if not self.brevo_key:
            logging.error("BREVO_API_KEY missing")
            return False
        try:
            payload = {
                "sender": {"email": self.from_email, "name": self.from_name},
                "to": [{"email": to}],
                "subject": subject,
                "textContent": body_text or "",
            }
            if body_html:
                payload["htmlContent"] = body_html

            headers = {
                "api-key": self.brevo_key,
                "accept": "application/json",
                "content-type": "application/json",
            }
            resp = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers, timeout=15)
            if 200 <= resp.status_code < 300:
                return True
            # Consider 429/5xx transient
            if resp.status_code in (429, 500, 502, 503, 504):
                return False
            logging.error(f"Brevo send failed {resp.status_code}: {resp.text}")
            return False
        except Exception as e:
            logging.error(f"Brevo API error: {e}")
            return False
