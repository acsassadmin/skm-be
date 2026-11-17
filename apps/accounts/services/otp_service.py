import threading
from django.conf import settings
from django.core.mail import send_mail


def _send_email_async(subject: str, message: str, recipient: str):
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient],
        fail_silently=False,
    )


def send_otp_notification(target: str, otp_code: str, channel: str = "EMAIL"):
    if channel == "EMAIL":
        subject = "SKM Electronics - Your Verification OTP"
        message = f"Your OTP code is {otp_code}. It is valid for 10 minutes."
        thread = threading.Thread(
            target=_send_email_async,
            args=(subject, message, target),
            daemon=True,
        )
        thread.start()
    elif channel == "PHONE":
            # TODO: Integrate MSG91 / Fast2SMS / WhatsApp API after SKM approval (Contract Sec 12.6)
            print(f"[DEV SMS OTP] To: {target} | Code: {otp_code}")