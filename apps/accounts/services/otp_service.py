from django.conf import settings
from django.core.mail import send_mail


def send_otp_notification(target: str, otp_code: str, channel: str = "EMAIL"):
    if channel == "EMAIL":
        subject = "SKM Electronics - Your Verification Code"
        message = (
            f"Hello,\n\n"
            f"Your one-time verification code for SKM Electronics is: {otp_code}\n"
            f"This code is valid for 10 minutes. Do not share it with anyone.\n\n"
            f"Regards,\nSKM Electronics Team"
        )
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[target],
            fail_silently=False,
        )
    elif channel == "PHONE":
        # TODO: Integrate MSG91 / Fast2SMS / WhatsApp API after SKM approval (Contract Sec 12.6)
        print(f"[DEV SMS OTP] To: {target} | Code: {otp_code}")
