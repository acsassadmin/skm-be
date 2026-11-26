from django.contrib.auth.models import AbstractUser
from django.db import models
import secrets
from datetime import timedelta
from django.utils import timezone
from django.utils.text import slugify
class Role(models.Model):
    """
    Dynamic Role table.
    Initial seeded codes: ADMIN, CUSTOMER, DEALER, STUDENT, FACULTY
    Future phase codes: FREELANCER, CONTENT_MANAGER, etc.
    """
    name = models.CharField(max_length=50, unique=True)         
    code = models.SlugField(max_length=50, unique=True,blank=True)         
    description = models.TextField(blank=True)
    requires_approval = models.BooleanField(default=False)      
    is_self_registerable = models.BooleanField(default=True) 
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.code and self.name:
            self.code = slugify(self.name).replace("-", "_").upper()[:50]
        else:
            self.code = self.code.strip().replace("-", "_").upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"

class Module(models.Model):
    name=models.CharField(max_length=100)
    navigate_route=models.CharField(max_length=150,null=True,blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.name}-{self.navigate_route}"
    
class RoleModulePermission(models.Model):
    
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="module_permissions")
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="role_permissions")

    is_view = models.BooleanField(default=True)
    is_upload = models.BooleanField(default=False)    
    is_update = models.BooleanField(default=False)    
    is_delete = models.BooleanField(default=False)
    is_download = models.BooleanField(default=False)  

    class Meta:
        unique_together = ("role", "module")

    def __str__(self):
        return f"{self.role.code} -> {self.module.name}"
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

    

    def is_valid(self) -> bool:
        return not self.is_used and timezone.now() <= self.expires_at

    def __str__(self):
        return f"{self.target} - {self.purpose} ({self.otp_code})"
    
class UserAddress(models.Model):
    """Saved shipping/billing addresses & optional GSTIN for Customers & Dealers."""

    class AddressType(models.TextChoices):
        HOME = "HOME", "Home"
        OFFICE = "OFFICE", "Office / Warehouse"
        OTHER = "OTHER", "Other"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    address_type = models.CharField(
        max_length=15, choices=AddressType.choices, default=AddressType.HOME
    )
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=15)
    company_name = models.CharField(max_length=150, blank=True)
    gstin = models.CharField(max_length=20, blank=True)
    address_line = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=15)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "-updated_at"]

    def save(self, *args, **kwargs):
        if self.gstin:
            self.gstin = self.gstin.upper().strip()
        if self.is_default:
            UserAddress.objects.filter(user=self.user, is_default=True).exclude(pk=self.pk).update(
                is_default=False
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} - {self.city} ({self.user.email})"