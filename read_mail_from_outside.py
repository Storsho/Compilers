
import imaplib
import email
import time
from email.header import decode_header

EMAIL = "storshoforger@gmail.com"
APP_PASSWORD = "zhaw mdel smun ajqw"
TARGET_SENDER = "storshoforger@gmail.com"

def get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                if part.get_content_disposition() == "attachment":
                    continue
                data = part.get_payload(decode=True)
                if data:
                    return data.decode(
                        part.get_content_charset() or "utf-8",
                        errors="replace"
                    )
    else:
        data = msg.get_payload(decode=True)
        if data:
            return data.decode(
                msg.get_content_charset() or "utf-8",
                errors="replace"
            )
    return "(No plain-text message body)"

mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
mail.login(EMAIL, APP_PASSWORD)
mail.select("INBOX")

# Ignore every message currently in the inbox.
status, data = mail.search(None, "ALL")
last_seen = max(
    (int(x) for x in data[0].split()),
    default=0
)

print("Listening for new emails from:", TARGET_SENDER)
print("Press Ctrl+C to stop.")

try:
    while True:
        mail.noop()

        status, data = mail.search(
            None,
            "FROM", f'"{TARGET_SENDER}"'
        )

        if status == "OK":
            for item in data[0].split():
                message_id = int(item)

                if message_id <= last_seen:
                    continue

                status, result = mail.fetch(
                    item, "(RFC822)"
                )

                if status != "OK":
                    continue

                msg = email.message_from_bytes(
                    result[0][1]
                )

                print("\n" + "=" * 40)
                print("From:", msg.get("From"))
                print("Subject:", msg.get("Subject", ""))
                print("Message:")
                print(get_body(msg))
                print("=" * 40)

                last_seen = max(last_seen, message_id)

        time.sleep(5)

except KeyboardInterrupt:
    print("\nStopped listening.")

finally:
    mail.logout()
