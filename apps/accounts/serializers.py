from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from .models import *

User = get_user_model()


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "code", "description", "requires_approval", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]
class ModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ["id", "name", "navigate_route", "is_active"]
        read_only_fields = ["id"]


class RoleModulePermissionSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True)
    role_code = serializers.CharField(source="role.code", read_only=True)
    module_name = serializers.CharField(source="module.name", read_only=True)
    navigate_route = serializers.CharField(source="module.navigate_route", read_only=True)

    class Meta:
        model = RoleModulePermission
        fields = [
            "id",
            "role",
            "role_name",
            "role_code",
            "module",
            "module_name",
            "navigate_route",
            "is_view",
            "is_upload",
            "is_update",
            "is_delete",
            "is_download",
        ]
        read_only_fields = ["id", "role_name", "role_code", "module_name", "navigate_route"]

class UserSerializer(serializers.ModelSerializer):
    role_details = RoleSerializer(source="roles", many=True, read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "full_name",
            "phone",
            "roles",
            "role_details",
            "is_email_verified",
            "is_phone_verified",
            "is_approved",
            "is_active",
            "is_superuser",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined", "is_email_verified", "is_phone_verified"]



class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    role_code = serializers.CharField(write_only=True, required=False, default="CUSTOMER")

    class Meta:
        model = User
        fields = ["email", "username", "full_name", "phone", "password", "role_code"]

    def validate_role_code(self, value):
        code = value.upper()
        if code == "ADMIN":
            raise serializers.ValidationError("Cannot self-register as ADMIN.")
        try:
            return Role.objects.get(code=code, is_active=True)
        except Role.DoesNotExist:
            raise serializers.ValidationError(f"Role '{code}' does not exist or is inactive.")

    def create(self, validated_data):
        role_obj = validated_data.pop("role_code")
        password = validated_data.pop("password")

        user = User(**validated_data)
        user.is_approved = not role_obj.requires_approval
        user.set_password(password)
        user.save()
        user.roles.add(role_obj)
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        user = authenticate(username=email, password=password)
        if not user:
            raise serializers.ValidationError({"detail": "Invalid email or password."})
        if not user.is_active:
            raise serializers.ValidationError({"detail": "This account has been deactivated."})
        if not user.is_approved:
            raise serializers.ValidationError({"detail": "Account pending admin approval."})

        self.user = user
        return attrs

    def get_tokens(self):
        refresh = RefreshToken.for_user(self.user)
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(self.user).data,
        }


class SendOTPSerializer(serializers.Serializer):
    target = serializers.CharField(max_length=255)
    channel = serializers.ChoiceField(choices=OTPVerification.Channel.choices, default="EMAIL")
    purpose = serializers.ChoiceField(choices=OTPVerification.Purpose.choices, default="REGISTER")


class VerifyOTPSerializer(serializers.Serializer):
    target = models.CharField(max_length=255) if False else serializers.CharField(max_length=255)
    otp_code = serializers.CharField(max_length=6)
    purpose = serializers.ChoiceField(choices=OTPVerification.Purpose.choices, default="REGISTER")


class UserAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAddress
        fields = [
            "id",
            "address_type",
            "full_name",
            "phone",
            "company_name",
            "gstin",
            "address_line",
            "city",
            "state",
            "pincode",
            "is_default",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_pincode(self, value):
        cleaned = value.strip()
        if not cleaned.isdigit() or len(cleaned) != 6:
            raise serializers.ValidationError("Enter a valid 6-digit Indian PIN code.")
        return cleaned

    def validate_gstin(self, value):
        cleaned = value.strip().upper()
        if cleaned and len(cleaned) != 15:
            raise serializers.ValidationError("GSTIN must be exactly 15 characters.")
        return cleaned
    
    
    