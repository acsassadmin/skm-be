from utils.email_service import send_otp_email


def send_otp_notification(target: str, otp_code: str, channel: str = "EMAIL", purpose: str = "Verification"):
    if channel == "EMAIL":
        send_otp_email(recipient=target, otp_code=otp_code, purpose=purpose)
    elif channel == "PHONE":
        # TODO: Integrate MSG91 / Fast2SMS / WhatsApp API after SKM approval (Contract Sec 12.6)
        print(f"[DEV SMS OTP] To: {target} | Code: {otp_code}")
