from django.contrib.auth.models import AbstractUser
from django.db import models
import secrets
from datetime import timedelta
from django.utils import timezone

class Role(models.Model):
    """
    Dynamic Role table.
    Initial seeded codes: ADMIN, CUSTOMER, DEALER, STUDENT, FACULTY
    Future phase codes: FREELANCER, CONTENT_MANAGER, etc.
    """
    name = models.CharField(max_length=50, unique=True)         
    code = models.SlugField(max_length=50, unique=True)         
    description = models.TextField(blank=True)
    requires_approval = models.BooleanField(default=False)      
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.code = self.code.upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15, blank=True, db_index=True)
    full_name = models.CharField(max_length=150)

    # Dynamic Role Link (supports multiple roles per user)
    roles = models.ManyToManyField(Role, related_name="users", blank=True)

    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "full_name"]

    def has_role(self, role_code: str) -> bool:
        if self.is_superuser:
            return True
        return self.roles.filter(code=role_code.upper(), is_active=True).exists()

    @property
    def role_codes(self) -> list[str]:
        return list(self.roles.filter(is_active=True).values_list("code", flat=True))

    def __str__(self):
        return self.email
    
class OTPVerification(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        PHONE = "PHONE", "Phone"

    class Purpose(models.TextChoices):
        REGISTER = "REGISTER", "Registration"
        LOGIN = "LOGIN", "Login"
        RESET_PASSWORD = "RESET_PASSWORD", "Reset Password"

    target = models.CharField(max_length=255, db_index=True)  # Email or Phone
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.REGISTER)
    otp_code = models.CharField(max_length=6)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def create_otp(cls, target: str, channel: str = "EMAIL", purpose: str = "REGISTER"):
        # Invalidate older unused OTPs for the same target & purpose
        cls.objects.filter(target=target, purpose=purpose, is_used=False).update(is_used=True)
        code = f"{secrets.randbelow(1000000):06d}"
        return cls.objects.create(
            target=target,
            channel=channel,
            purpose=purpose,
            otp_code=code,
            expires_at=timezone.now() + timedelta(minutes=10),
        )

    def is_valid(self) -> bool:
        return not self.is_used and timezone.now() <= self.expires_at

    def __str__(self):
        return f"{self.target} - {self.purpose} ({self.otp_code})"