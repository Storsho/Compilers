# ##########################################################################
# ##   EDIT THESE SETTINGS, THEN RUN: python3 read.py   (Ctrl+C to stop)     ##
# ##########################################################################
GMAIL_ADDRESS = "storshoforger@gmail.com"      # the shared inbox to listen to
GMAIL_APP_PASSWORD = "zhaw mdel smun ajqw"  # Gmail App Password (spaces allowed)
ONLY_FROM = "storshoforger@gmail.com"          # only show NEW mail from this address
CHECK_EVERY_SECONDS = 5                        # how often to look for new mail (minimum 3)
SEPARATOR = "______________"                   # printed after every message
# ##########################################################################
#
# Group-chat listener. Many people can run this at the same time on the same
# inbox and each one sees every new message.
#   - The inbox is opened READ-ONLY and nothing is marked as read, so one
#     listener never "steals" a message from another.
#   - On start it remembers the newest mail already in the inbox and only
#     prints mail that arrives AFTER that point (old mail is never shown).
#   - Output:   Name: message
#               ______________
#     (email subject = Name, email body = message)

import imaplib
import re
import ssl
import sys
import time
from email import message_from_bytes, policy
from email.utils import getaddresses
from html import unescape

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
TIMEOUT = 30
MIN_CHECK_SECONDS = 3
MAX_RETRY_SECONDS = 60


def body_of(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return "(No content)"
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
        text = unescape(re.sub(r"<[^>]*>", " ", text))
    return text.replace("\r\n", "\n").strip() or "(No content)"


def sender_of(msg):
    headers = [str(v) for v in msg.get_all("from", [])]
    return [a.strip().lower() for _, a in getaddresses(headers) if a]


def connect(address, password):
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT,
                             ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
    try:
        conn.login(address, password)
        status, _ = conn.select("INBOX", readonly=True)  # read-only: never changes flags
        if status != "OK":
            raise imaplib.IMAP4.error("could not open INBOX")
    except Exception:
        try:
            conn.logout()
        except Exception:
            pass
        raise
    return conn


def uids_matching(conn, *criteria):
    status, data = conn.uid("search", None, *criteria)
    if status != "OK":
        raise imaplib.IMAP4.abort("search failed")
    return sorted(int(u) for u in (data[0] or b"").split())


def check_inbox(conn, wanted, state):
    conn.noop()  # makes Gmail report newly arrived mail
    if state["last"] is None:  # first run: start from "now", skip old mail
        all_uids = uids_matching(conn, "ALL")
        state["last"] = all_uids[-1] if all_uids else 0
        return
    last = state["last"]
    # "UID n:*" always includes the newest message, so filter again with > last
    for uid in [u for u in uids_matching(conn, "UID", f"{last + 1}:*") if u > last]:
        status, data = conn.uid("fetch", str(uid), "(BODY.PEEK[])")
        raw = next((i[1] for i in data or [] if isinstance(i, tuple)), None)
        if status != "OK" or raw is None:
            return  # try again next round, don't skip it
        msg = message_from_bytes(raw, policy=policy.default)
        if wanted in sender_of(msg):
            name = " ".join(str(msg["subject"] or "").split()) or "(No subject)"
            print(f"{name}: {body_of(msg)}\n{SEPARATOR}", flush=True)
        state["last"] = uid


def main():
    address = GMAIL_ADDRESS.strip()
    password = GMAIL_APP_PASSWORD.replace(" ", "").strip()
    wanted = ONLY_FROM.strip().lower()
    poll = max(MIN_CHECK_SECONDS, float(CHECK_EVERY_SECONDS))
    if not address or not password or password == "PASTE-NEW-APP-PASSWORD" or not wanted:
        print("Edit GMAIL_ADDRESS, GMAIL_APP_PASSWORD and ONLY_FROM at the top of read.py.",
              file=sys.stderr)
        return 2

    print(f"Listening for new mail from {wanted} (every {poll:g}s). Ctrl+C to stop.", file=sys.stderr)
    state = {"last": None}
    conn, failures = None, 0
    try:
        while True:
            wait = poll
            try:
                if conn is None:
                    conn = connect(address, password)
                check_inbox(conn, wanted, state)
                failures = 0
            except imaplib.IMAP4.error as exc:
                if "AUTHENTICATIONFAILED" in str(exc).upper() or "invalid credentials" in str(exc).lower():
                    print("Login failed. Check the App Password and that IMAP is enabled.", file=sys.stderr)
                    return 1
                conn = None
                failures += 1
                wait = min(MAX_RETRY_SECONDS, poll * 2 ** (failures - 1))
                print(f"IMAP problem ({exc}). Retrying in {wait:.0f}s.", file=sys.stderr)
            except OSError as exc:
                conn = None
                failures += 1
                wait = min(MAX_RETRY_SECONDS, poll * 2 ** (failures - 1))
                print(f"Network problem ({exc}). Retrying in {wait:.0f}s.", file=sys.stderr)
            time.sleep(wait)
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 0
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
