import logging
import threading
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _deliver_email_async(subject: str, html_body: str, plain_body: str, recipient: str):
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
    except Exception as exc:
        logger.exception("Failed to send email to %s (%s): %s", recipient, subject, exc)


def send_template_email(
    recipient: str,
    subject: str,
    template_name: str,
    context: dict,
    async_send: bool = True,
):
    if not recipient:
        return

    html_body = render_to_string(template_name, context)
    plain_body = strip_tags(html_body).strip()

    if async_send:
        thread = threading.Thread(
            target=_deliver_email_async,
            args=(subject, html_body, plain_body, recipient),
            daemon=True,
        )
        thread.start()
    else:
        _deliver_email_async(subject, html_body, plain_body, recipient)


def send_otp_email(recipient: str, otp_code: str, purpose: str = "Verification"):
    send_template_email(
        recipient=recipient,
        subject=f"SKM Electronics - Your {purpose} OTP",
        template_name="emails/otp.html",
        context={"otp_code": otp_code, "purpose": purpose},
    )
    


def send_account_approval_email(
    recipient: str,
    full_name: str,
    is_approved: bool,
    role_name: str = "Dealer",
    login_url: str = "",
):
    url = login_url or getattr(settings, "FRONTEND_URL", "http://localhost:5173/login")
    subject = (
        f"SKM Electronics - Your {role_name} Account is Approved!"
        if is_approved
        else f"SKM Electronics - {role_name} Account Approval Revoked"
    )
    send_template_email(
        recipient=recipient,
        subject=subject,
        template_name="emails/account_approval.html",
        context={
            "full_name": full_name,
            "is_approved": is_approved,
            "role_name": role_name,
            "login_url": url,
        },
    )


def send_account_activation_email(
    recipient: str,
    full_name: str,
    is_active: bool,
    login_url: str = "",
):
    url = login_url or getattr(settings, "FRONTEND_URL", "http://localhost:5173/login")
    subject = (
        "SKM Electronics - Your Account Has Been Activated"
        if is_active
        else "SKM Electronics - Your Account Has Been Deactivated"
    )
    send_template_email(
        recipient=recipient,
        subject=subject,
        template_name="emails/account_activation.html",
        context={
            "full_name": full_name,
            "is_active": is_active,
            "login_url": url,
        },
    )
