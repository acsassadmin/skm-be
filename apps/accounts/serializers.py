from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from .models import Role, OTPVerification

User = get_user_model()


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "code", "description", "requires_approval", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


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
