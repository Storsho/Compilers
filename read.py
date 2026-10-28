# ##########################################################################
# ##   EDIT THESE SETTINGS, THEN RUN: python3 read.py   (Ctrl+C to stop)     ##
# ##########################################################################
GMAIL_ADDRESS = "storshoforger@gmail.com"               # the inbox to listen to
GMAIL_APP_PASSWORD = "zhaw mdel smun ajqw"  # Gmail App Password (spaces allowed)
ONLY_FROM = "storshoforger@gmail.com"                       # only show NEW mail from this address
CHECK_EVERY_SECONDS = 10                               # how often to look for new mail (minimum 5)
SEPARATOR = "______________"                           # printed after every mail
# ##########################################################################
#
# Keeps running and prints each new (unread) Gmail message from ONLY_FROM as it
# arrives. Example output:
#
#     Name: Hairy
#     message: I am hairy karadi
#     ______________
#
# (The email subject is shown as "Name" and the email content as "message".)
# It checks the inbox every CHECK_EVERY_SECONDS seconds, so a new mail shows up
# within about that time. If the connection drops it reconnects by itself.
# Mail from other senders is ignored and left unread. A message is marked as read
# only after it has been printed, so it is never shown twice. Nothing is deleted.
# Uses IMAP over SSL/TLS (port 993, verified certificate).
# Use a Gmail App Password, NOT your normal Google password.
# Do not share this file or upload it anywhere once your password is in it.

import email
import imaplib
import re
import socket
import ssl
import sys
import time
from email import policy
from email.utils import getaddresses
from html import unescape
from html.parser import HTMLParser

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
TIMEOUT = 30  # seconds
MIN_CHECK_SECONDS = 5  # checking more often than this risks Gmail throttling
MAX_RETRY_SECONDS = 60  # longest wait between reconnection attempts
NO_SUBJECT = "(No subject)"
NO_CONTENT = "(No content)"
ADDRESS_PATTERN = re.compile(r"^[^@\s<>,;:\"()\[\]\\]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PLACEHOLDER_ADDRESS = "your.address@gmail.com"
PLACEHOLDER_PASSWORD = "your-16-character-app-password"
PLACEHOLDER_SENDER = "sender@example.com"


class ConfigError(Exception):
    """Settings at the top of the file are missing or still placeholders."""


class LoginFailed(Exception):
    """Gmail rejected the credentials."""


class MailboxError(Exception):
    """INBOX could not be opened."""


class MessageUnavailable(Exception):
    """A message could not be fetched."""


def get_settings(address, password, only_from):
    address = (address or "").strip()
    password = (password or "").replace(" ", "").strip()  # Google shows it in groups of 4
    only_from = (only_from or "").strip()
    if not address or address == PLACEHOLDER_ADDRESS or not password or password == PLACEHOLDER_PASSWORD:
        raise ConfigError("edit GMAIL_ADDRESS and GMAIL_APP_PASSWORD at the top of read.py")
    if not only_from or only_from == PLACEHOLDER_SENDER:
        raise ConfigError("edit ONLY_FROM at the top of read.py (the sender whose mail you want to read)")
    for name, value in (("GMAIL_ADDRESS", address), ("ONLY_FROM", only_from)):
        if not ADDRESS_PATTERN.match(value):
            raise ConfigError(f"{name} is not a valid email address")
    return address, password, only_from


# ---------------------------------------------------------------- message parsing

class _HTMLText(HTMLParser):
    """Collect visible text from HTML, ignoring tags, scripts and styles."""

    BLOCK = {"p", "div", "br", "tr", "li", "ul", "ol", "table", "blockquote", "section",
             "article", "header", "footer", "pre", "hr", "h1", "h2", "h3", "h4", "h5", "h6"}
    PARAGRAPH = {"p", "blockquote", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.skip = 0  # recover from a <head> that was never closed
        elif tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.PARAGRAPH:
            self.parts.append("\n\n")  # paragraphs are separated by one blank line
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup):
    try:
        parser = _HTMLText()
        parser.feed(markup)
        parser.close()
        text = "".join(parser.parts)
    except Exception:  # malformed HTML: fall back to crude tag stripping
        text = unescape(re.sub(r"<[^>]*>", " ", markup))
    lines = [" ".join(line.split()) for line in text.replace("\r", "").split("\n")]
    cleaned = []
    for line in lines:
        if line or (cleaned and cleaned[-1]):  # keep at most one blank line in a row
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def decode_part(part):
    payload = part.get_payload(decode=True)  # undoes base64 / quoted-printable
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset)
    except (UnicodeDecodeError, LookupError):
        return payload.decode("utf-8", errors="replace")


def _text_parts(part):
    """Yield text/* parts that are not attachments, in document order."""
    maintype = part.get_content_maintype()
    if maintype == "multipart":
        for sub in part.iter_parts():
            yield from _text_parts(sub)
    elif maintype == "text" and part.get_content_disposition() != "attachment":
        yield part


def extract_body(msg):
    """Prefer a non-empty text/plain part; otherwise readable text from text/html."""
    plain = html = None
    try:
        for part in _text_parts(msg):
            try:
                text = decode_part(part)
            except Exception:  # skip a malformed part, keep looking
                continue
            if not text.strip():
                continue
            kind = part.get_content_type()
            if kind == "text/plain" and plain is None:
                plain = text
                break
            if kind == "text/html" and html is None:
                html = text
    except Exception:  # malformed structure: use whatever was found so far
        pass
    if plain is not None:
        return plain.replace("\r\n", "\n").replace("\r", "\n").strip()
    if html is not None:
        return html_to_text(html)
    return ""


def parse_message(raw):
    return email.message_from_bytes(raw, policy=policy.default)


def from_addresses(msg):
    """Lower-cased address(es) in the From header, e.g. ['sender@example.com']."""
    try:
        headers = [str(value) for value in msg.get_all("from", [])]
        return [address.strip().lower() for _, address in getaddresses(headers) if address]
    except Exception:
        return []


def render_parsed(msg):
    try:
        subject = " ".join(str(msg["subject"] or "").split())  # decodes MIME encoded-words
    except Exception:
        subject = ""
    return subject or NO_SUBJECT, extract_body(msg) or NO_CONTENT


def render_message(raw):
    """Turn raw RFC 822 bytes into (subject, body) with fallbacks for empty values."""
    return render_parsed(parse_message(raw))


# ---------------------------------------------------------------- IMAP

class _State:
    """What the listener remembers between checks (kept across reconnections)."""

    def __init__(self):
        self.shown = set()    # message UIDs already printed: never printed twice
        self.skipped = set()  # UIDs whose From is not exactly ONLY_FROM
        self.warned = set()   # UIDs we have already complained about


def _warn(text):
    print(f"Warning: {text}", file=sys.stderr)


def _close(conn):
    if conn is None:
        return
    try:
        conn.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


def connect(address, password):
    """Open a verified IMAP-over-SSL connection, log in and select INBOX."""
    context = ssl.create_default_context()  # verifies certificate and hostname
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=context, timeout=TIMEOUT)
    try:
        try:
            conn.login(address, password)
        except imaplib.IMAP4.error:
            raise LoginFailed() from None
        status, _ = conn.select("INBOX")  # read-write, so messages can be marked read
        if status != "OK":
            raise MailboxError("could not open INBOX")
    except BaseException:
        _close(conn)
        raise
    return conn


def fetch_raw(conn, uid):
    # BODY.PEEK[] fetches the message WITHOUT marking it as read.
    status, data = conn.uid("fetch", uid, "(BODY.PEEK[])")
    if status != "OK":
        raise MessageUnavailable()
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    raise MessageUnavailable()


def _mark_read(conn, uid, state):
    try:
        status, _ = conn.uid("store", uid, "+FLAGS", "(\\Seen)")
        ok = status == "OK"
    except imaplib.IMAP4.abort:
        raise  # connection problem: handled by the caller
    except imaplib.IMAP4.error:
        ok = False
    if not ok and uid not in state.warned:
        state.warned.add(uid)
        _warn("could not mark a message as read; it will not be printed again.")


def check_inbox(conn, wanted, out, state):
    """Look at the inbox once and print any new mail from `wanted`."""
    conn.noop()  # lets Gmail report mail that arrived since the last look
    # Gmail narrows the search to unread mail whose From contains the address.
    status, data = conn.uid("search", None, "UNSEEN", "FROM", f'"{wanted}"')
    if status != "OK":
        raise imaplib.IMAP4.abort("search failed")

    this_round = set()
    for uid in (data[0] or b"").split():  # UIDs are bytes, e.g. b"42"
        if uid in this_round or uid in state.skipped:
            continue
        this_round.add(uid)

        if uid not in state.shown:
            try:
                msg = parse_message(fetch_raw(conn, uid))
                if wanted not in from_addresses(msg):
                    state.skipped.add(uid)  # Gmail matches substrings; require the exact address
                    continue
                subject, body = render_parsed(msg)
            except (imaplib.IMAP4.abort, OSError):
                raise  # connection problem: handled by the caller
            except Exception:  # one bad message must not stop the others; it stays unread
                if uid not in state.warned:
                    state.warned.add(uid)
                    _warn("a message could not be read; it was left unread.")
                continue

            print(f"Name: {subject}\nmessage: {body}\n{SEPARATOR}", file=out)
            out.flush()
            state.shown.add(uid)

        # Mark as read only now that the message has been retrieved and shown.
        _mark_read(conn, uid, state)


def listen(address, password, only_from, out=None, poll=CHECK_EVERY_SECONDS,
           sleep=time.sleep, should_stop=lambda: False):
    """Check the inbox again and again until interrupted. Reconnects if the connection drops."""
    out = out or sys.stdout
    wanted = only_from.strip().lower()
    state = _State()
    conn = None
    failures = 0
    try:
        while not should_stop():
            wait = poll
            try:
                if conn is None:
                    conn = connect(address, password)
                check_inbox(conn, wanted, out, state)
                failures = 0
            except (LoginFailed, MailboxError):
                raise  # wrong password or no access: retrying will not help
            except (imaplib.IMAP4.error, OSError) as exc:
                _close(conn)
                conn = None
                failures += 1
                wait = min(MAX_RETRY_SECONDS, max(poll, MIN_CHECK_SECONDS) * 2 ** (failures - 1))
                print(f"{describe_error(exc)} Retrying in {wait:.0f}s (Ctrl+C to stop).", file=sys.stderr)
            sleep(wait)
    finally:
        _close(conn)


def describe_error(exc):
    if isinstance(exc, LoginFailed):
        return ("Login failed. Use a Gmail App Password (not your normal password; 2-Step Verification "
                "must be on), check GMAIL_ADDRESS, and make sure IMAP is enabled for the account.")
    if isinstance(exc, MailboxError):
        return f"{exc}. Check that IMAP is enabled for this Gmail account."
    if isinstance(exc, socket.gaierror):
        return f"Could not resolve {IMAP_HOST}. Check your internet connection and DNS."
    if isinstance(exc, ssl.SSLError):
        return "Secure (TLS) connection failed. Check the system clock and installed CA certificates."
    if isinstance(exc, TimeoutError):
        return f"Timed out talking to {IMAP_HOST}:{IMAP_PORT}. The port may be blocked on this network."
    if isinstance(exc, ConnectionRefusedError):
        return f"Connection to {IMAP_HOST}:{IMAP_PORT} was refused. The port may be blocked on this network."
    if isinstance(exc, imaplib.IMAP4.error):
        return "The IMAP connection was lost or the server reported an error."
    if isinstance(exc, OSError):
        return "Network error. Check your internet connection."
    return f"Unexpected error ({type(exc).__name__})."


def main(address=None, password=None, only_from=None, poll=None):
    address = GMAIL_ADDRESS if address is None else address
    password = GMAIL_APP_PASSWORD if password is None else password
    only_from = ONLY_FROM if only_from is None else only_from
    poll = CHECK_EVERY_SECONDS if poll is None else poll
    try:
        address, password, only_from = get_settings(address, password, only_from)
        poll = max(MIN_CHECK_SECONDS, float(poll))
    except (ConfigError, ValueError, TypeError) as exc:
        reason = exc if isinstance(exc, ConfigError) else "CHECK_EVERY_SECONDS must be a number"
        print(f"Configuration error: {reason}.", file=sys.stderr)
        return 2

    print(f"Listening for new mail from {only_from} (checking every {poll:g}s). Press Ctrl+C to stop.",
          file=sys.stderr)
    try:
        listen(address, password, only_from, poll=poll)
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 0
    except Exception as exc:  # command-line tool: report every failure type clearly
        print(f"Error: {describe_error(exc)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # never crash on an unprintable character
    sys.exit(main())
