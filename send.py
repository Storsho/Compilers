# ##########################################################################
# ##   EDIT THESE TWO LINES TO CHANGE THE EMAIL, THEN RUN: python3 send.py   ##
# ##########################################################################
NAME = "Mr.Validation 2"                    # <-- becomes the email SUBJECT
MESSAGE = "I Validate mithuna"     # <-- becomes the email CONTENT (the body)
# ##########################################################################

# ---------------- Account settings (edit once, then leave alone) ----------------
GMAIL_ADDRESS = "storshoforger@gmail.com"               # the account that sends
GMAIL_APP_PASSWORD = "zhaw mdel smun ajqw"  # Gmail App Password (spaces allowed)
RECEIVER_ADDRESS = "storshoforger@gmail.com"              # who receives the email
# --------------------------------------------------------------------------------
#
# Sends one email through Gmail: SMTP, port 587, STARTTLS, verified certificate.
# Use a Gmail App Password, NOT your normal Google password.
# Do not share this file or upload it anywhere once your password is in it.
# For a longer message, use triple quotes:   MESSAGE = """line one
# line two"""

import re
import smtplib
import socket
import ssl
import sys
from email.message import EmailMessage

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
TIMEOUT = 30  # seconds, for connecting and for every server reply
ADDRESS_PATTERN = re.compile(r"^[^@\s<>,;:\"()\[\]\\]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PLACEHOLDER_ADDRESS = "your.address@gmail.com"
PLACEHOLDER_PASSWORD = "your-16-character-app-password"
PLACEHOLDER_RECEIVER = "receiver@example.com"


class ConfigError(Exception):
    """A setting at the top of the file is missing, invalid or still a placeholder."""


def get_settings(address, password, receiver, name, message):
    """Validate and clean all settings. Raises ConfigError with a plain-language reason."""
    address = (address or "").strip()
    password = (password or "").replace(" ", "").strip()  # Google shows it in groups of 4
    receiver = (receiver or "").strip()
    name = (name or "").strip()
    message = (message or "").strip()

    if not address or address == PLACEHOLDER_ADDRESS or not password or password == PLACEHOLDER_PASSWORD:
        raise ConfigError("edit GMAIL_ADDRESS and GMAIL_APP_PASSWORD at the top of send.py")
    if not receiver or receiver == PLACEHOLDER_RECEIVER:
        raise ConfigError("edit RECEIVER_ADDRESS at the top of send.py")
    if not ADDRESS_PATTERN.match(address):
        raise ConfigError("GMAIL_ADDRESS is not a valid email address")
    if not (receiver.isascii() and ADDRESS_PATTERN.match(receiver)):
        raise ConfigError("RECEIVER_ADDRESS is not a valid email address")
    if not name:
        raise ConfigError("NAME is empty (it becomes the email subject)")
    if "\n" in name or "\r" in name:
        raise ConfigError("NAME must be a single line (it becomes the email subject)")
    if not message:
        raise ConfigError("MESSAGE is empty (it becomes the email content)")
    return address, password, receiver, name, message


def build_message(sender, receiver, name, message):
    email_message = EmailMessage()
    email_message["From"] = sender
    email_message["To"] = receiver
    email_message["Subject"] = name  # NAME -> subject (non-ASCII is encoded automatically)
    email_message.set_content(message, charset="utf-8")  # MESSAGE -> content, UTF-8
    return email_message


def _close(server):
    try:
        server.quit()
    except (smtplib.SMTPException, OSError):
        server.close()


def send_email(sender, password, email_message):
    """Connect, upgrade to TLS, log in and send. Raises on any failure."""
    context = ssl.create_default_context()  # verifies certificate and hostname
    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT)
    try:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()  # EHLO must be repeated once the connection is encrypted
        server.login(sender, password)
        server.send_message(email_message)
    finally:
        _close(server)


def describe_error(exc, password=""):
    """Return a short, safe, human-readable explanation of a failure."""
    # SMTPException is a subclass of OSError, so SMTP errors are checked first.
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return ("Authentication failed. Use a Gmail App Password (not your normal password; "
                "2-Step Verification must be on) and check GMAIL_ADDRESS.")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "Gmail rejected RECEIVER_ADDRESS."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "Gmail rejected the sender address."
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return "The server closed the connection unexpectedly. Check your network, firewall or VPN and try again."
    if isinstance(exc, smtplib.SMTPException):
        detail = str(exc).replace(password, "[hidden]") if password else str(exc)
        return f"SMTP error: {detail}"
    if isinstance(exc, socket.gaierror):
        return f"Could not resolve {SMTP_HOST}. Check your internet connection and DNS."
    if isinstance(exc, ssl.SSLError):
        return "Secure (TLS) connection failed. Check the system clock and installed CA certificates."
    if isinstance(exc, TimeoutError):
        return f"Timed out connecting to {SMTP_HOST}:{SMTP_PORT}. Port {SMTP_PORT} may be blocked on this network."
    if isinstance(exc, ConnectionRefusedError):
        return f"Connection to {SMTP_HOST}:{SMTP_PORT} was refused. The port may be blocked on this network."
    if isinstance(exc, OSError):
        return "Network error. Check your internet connection."
    return f"Unexpected error ({type(exc).__name__})."


def main(address=None, password=None, receiver=None, name=None, message=None):
    # Values default to the settings at the top of the file (tests pass their own).
    address = GMAIL_ADDRESS if address is None else address
    password = GMAIL_APP_PASSWORD if password is None else password
    receiver = RECEIVER_ADDRESS if receiver is None else receiver
    name = NAME if name is None else name
    message = MESSAGE if message is None else message

    try:
        sender, password, receiver, name, message = get_settings(address, password, receiver, name, message)
        email_message = build_message(sender, receiver, name, message)
    except (ConfigError, ValueError) as exc:  # ValueError covers undecodable characters
        print(f"Configuration error: {exc}.", file=sys.stderr)
        return 2

    try:
        send_email(sender, password, email_message)
    except Exception as exc:  # command-line tool: report every failure type clearly
        print(f"Error: {describe_error(exc, password)}", file=sys.stderr)
        return 1

    print("Email sent successfully.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)
