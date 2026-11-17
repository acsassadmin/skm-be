import secrets
from datetime import timedelta
from django.utils import timezone


def generate_otp_code(length: int = 6) -> str:
    """Generate a cryptographically secure numeric OTP."""
    upper_bound = 10 ** length
    return f"{secrets.randbelow(upper_bound):0{length}d}"


def get_otp_expiry(minutes: int = 10):
    """Return timezone-aware expiry timestamp."""
    return timezone.now() + timedelta(minutes=minutes)


def is_otp_expired(expires_at) -> bool:
    """Check whether the given expiry timestamp has passed."""
    return timezone.now() > expires_at
