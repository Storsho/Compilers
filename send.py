import smtplib
from email.mime.text import MIMEText

sender = "storshoforger@gmail.com"
receiver = "storshoforger@gmail.com"
app_password = "zhaw mdel smun ajqw"

message = MIMEText(
    "Hello world"
)

message["Subject"] = "Rest in peace"
message["From"] = sender
message["To"] = receiver

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, app_password)
        server.send_message(message)

    print("Email sent successfully!")

except Exception as e:
    print("Error:", e)