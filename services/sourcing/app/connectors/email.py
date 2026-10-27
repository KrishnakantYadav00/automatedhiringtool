"""
AHP Sourcing Engine — Email / IMAP connector.

Polls an IMAP mailbox for emails containing candidate resumes/applications
and extracts structured candidate data.
"""

from __future__ import annotations

import asyncio
import email
from email.message import Message
import re
from typing import Any, AsyncIterator

from app.config import ImapConfig
from app.connectors.base import BaseConnector
from app.models.schemas import RawCandidateData


EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_REGEX = re.compile(r"(\+?\d{1,3}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}")


class EmailConnector(BaseConnector):
    """Connector that polls an IMAP mailbox for candidate resumes and profiles."""

    def __init__(self, config: ImapConfig) -> None:
        super().__init__(name="email", config=config.model_dump())
        self._imap_config = config

    async def fetch_candidates(self) -> AsyncIterator[RawCandidateData]:
        """Fetch unread candidate emails from IMAP and yield RawCandidateData."""
        start_time = self._start_timer()
        loop = asyncio.get_running_loop()

        try:
            candidates: list[RawCandidateData] = await loop.run_in_executor(
                None, self._fetch_sync
            )
            for candidate in candidates:
                self.metrics.fetched += 1
                yield candidate
        except Exception as exc:
            self.metrics.errors += 1
            self.logger.error("Failed to fetch candidates from IMAP: %s", exc)
        finally:
            self._stop_timer(start_time)

    def _fetch_sync(self) -> list[RawCandidateData]:
        """Synchronous IMAP fetch executed in a thread pool."""
        import imaplib

        results: list[RawCandidateData] = []
        conn = None

        try:
            if self._imap_config.use_ssl:
                conn = imaplib.IMAP4_SSL(self._imap_config.host, self._imap_config.port)
            else:
                conn = imaplib.IMAP4(self._imap_config.host, self._imap_config.port)

            password = self._imap_config.password.get_secret_value()
            if not self._imap_config.username or not password:
                self.logger.warning("IMAP credentials not configured. Skipping mailbox scan.")
                return results

            conn.login(self._imap_config.username, password)
            conn.select(self._imap_config.folder)

            _, message_ids = conn.search(None, "UNSEEN")
            if not message_ids or not message_ids[0]:
                conn.logout()
                return results

            id_list = message_ids[0].split()[:50]  # Batch cap per poll
            for msg_id in id_list:
                try:
                    _, msg_data = conn.fetch(msg_id, "(RFC822)")
                    if msg_data and msg_data[0] and isinstance(msg_data[0], tuple):
                        raw_email = msg_data[0][1]
                        parsed_msg = email.message_from_bytes(raw_email)
                        candidate_data = self._parse_email(msg_id.decode(), parsed_msg)
                        if candidate_data:
                            results.append(candidate_data)
                except Exception as parse_err:
                    self.logger.warning("Error parsing email ID %s: %s", msg_id, parse_err)

            conn.logout()
        except Exception as exc:
            self.logger.error("IMAP connection error during fetch: %s", exc)
            if conn:
                try:
                    conn.logout()
                except Exception:
                    pass
            raise

        return results

    def _parse_email(self, msg_id: str, msg: Message) -> RawCandidateData | None:
        """Extract candidate information from an email message and its attachments."""
        subject = msg.get("Subject", "")
        from_hdr = msg.get("From", "")
        body_text = self._extract_body(msg)

        # Extract email: check body first, fallback to sender
        emails_found = EMAIL_REGEX.findall(body_text)
        candidate_email = emails_found[0] if emails_found else None
        if not candidate_email:
            sender_emails = EMAIL_REGEX.findall(from_hdr)
            candidate_email = sender_emails[0] if sender_emails else None

        # Extract phone
        phones_found = PHONE_REGEX.findall(body_text)
        candidate_phone = "".join(phones_found[0]) if phones_found else None

        # Infer name: often in Subject like "Resume: John Doe" or From header
        name = self._extract_name(subject, from_hdr)

        return RawCandidateData(
            source_name="email",
            source_candidate_id=f"email_{msg_id}",
            full_name=name,
            email=candidate_email,
            phone=candidate_phone,
            resume_text=body_text[:10000] if body_text else None,
            raw_payload={
                "subject": subject,
                "from": from_hdr,
                "msg_id": msg_id,
            },
        )

    def _extract_name(self, subject: str, from_hdr: str) -> str:
        """Heuristic name extraction from subject line or From header."""
        for prefix in ["Resume -", "Resume:", "Application for", "Candidate -", "CV -"]:
            if prefix.lower() in subject.lower():
                parts = subject.split(prefix, 1)
                if len(parts) > 1 and parts[1].strip():
                    return parts[1].strip()

        # Fallback to sender display name (e.g. "John Doe <john@example.com>")
        if "<" in from_hdr:
            display_name = from_hdr.split("<")[0].strip().strip('"\'')
            if display_name:
                return display_name

        return from_hdr.strip()

    def _extract_body(self, msg: Message) -> str:
        """Extract text content from email body parts."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode("utf-8", errors="replace") + "\n"
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace")
        return body.strip()

    async def health_check(self) -> dict[str, Any]:
        """Test IMAP connection."""
        import imaplib

        if not self._imap_config.username or not self._imap_config.password.get_secret_value():
            return {
                "source": self.name,
                "status": "unconfigured",
                "detail": "IMAP credentials not configured.",
            }

        loop = asyncio.get_running_loop()

        def _check() -> dict[str, Any]:
            try:
                if self._imap_config.use_ssl:
                    conn = imaplib.IMAP4_SSL(self._imap_config.host, self._imap_config.port)
                else:
                    conn = imaplib.IMAP4(self._imap_config.host, self._imap_config.port)
                conn.login(self._imap_config.username, self._imap_config.password.get_secret_value())
                conn.logout()
                return {"source": self.name, "status": "ok", "detail": "IMAP connection successful"}
            except Exception as exc:
                return {"source": self.name, "status": "error", "detail": str(exc)}

        return await loop.run_in_executor(None, _check)
