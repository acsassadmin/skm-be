from .models import *
from .serializers import *
from accounts.services.otp_service import send_otp_notification
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny,IsAuthenticated
from utils.responses import success_response,error_response
from rest_framework.exceptions import ValidationError
from rest_framework import status
from utils.otp import generate_otp_code, get_otp_expiry
from django.utils import timezone

class SendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Invalid OTP request.")

        target = serializer.validated_data["target"]
        channel = serializer.validated_data["channel"]
        purpose = serializer.validated_data["purpose"]

        # Purge expired OTPs across the table + any previous OTPs for this target & purpose
        OTPVerification.objects.filter(expires_at__lt=timezone.now()).delete()
        OTPVerification.objects.filter(target=target, purpose=purpose).delete()

        otp_code = generate_otp_code()
        OTPVerification.objects.create(
            target=target,
            channel=channel,
            purpose=purpose,
            otp_code=otp_code,
            expires_at=get_otp_expiry(minutes=10),
        )

        send_otp_notification(target=target, otp_code=otp_code, channel=channel)

        return success_response(
            data={"target": target, "channel": channel},
            message=f"OTP sent successfully via {channel.lower()}.",
            status_code=status.HTTP_200_OK,
        )


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Validation failed.")

        target = serializer.validated_data["target"]
        otp_code = serializer.validated_data["otp_code"]
        purpose = serializer.validated_data["purpose"]

        otp_obj = (
            OTPVerification.objects.filter(
                target=target, otp_code=otp_code, purpose=purpose, is_used=False
            )
            .order_by("-created_at")
            .first()
        )

        if not otp_obj or not otp_obj.is_valid():
            return error_response(
                errors={"otp_code": "Invalid or expired OTP."},
                message="OTP verification failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        channel = otp_obj.channel
        # Delete the verified OTP immediately so the table stays clean
        OTPVerification.objects.filter(target=target, purpose=purpose).delete()

        user = User.objects.filter(email=target).first() or User.objects.filter(phone=target).first()
        if user:
            if channel == "EMAIL":
                user.is_email_verified = True
            else:
                user.is_phone_verified = True
            user.save(update_fields=["is_email_verified", "is_phone_verified"])

            if user.is_approved:
                refresh = RefreshToken.for_user(user)
                return success_response(
                    data={
                        "access": str(refresh.access_token),
                        "refresh": str(refresh),
                        "user": UserSerializer(user).data,
                    },
                    message="OTP verified successfully.",
                    status_code=status.HTTP_200_OK,
                )

        return success_response(message="OTP verified successfully.", status_code=status.HTTP_200_OK)

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Registration failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.save()
        return success_response(
            data=UserSerializer(user).data,
            message="Account created successfully!",
            status_code=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Authentication failed.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        tokens = serializer.get_tokens()
        return success_response(
            data=tokens,
            message="Login successful. Authorization granted.",
            status_code=status.HTTP_200_OK,
        )


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return success_response(
            data=serializer.data,
            message="Profile retrieved successfully.",
            status_code=status.HTTP_200_OK,
        )


class RoleView(APIView):
    permission_classes = [IsAuthenticated]

    # READ (List all or retrieve single via ?id=)
    def get(self, request):
        role_id = request.query_params.get("id")

        if role_id:
            try:
                obj = Role.objects.get(id=role_id)
                serializer = RoleSerializer(obj)
                return success_response(
                    data=serializer.data,
                    message="Role retrieved successfully.",
                    status_code=status.HTTP_200_OK,
                )
            except Role.DoesNotExist:
                return error_response(
                    message="Role not found.",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

        queryset = Role.objects.all().order_by("-created_at")
        serializer = RoleSerializer(queryset, many=True)
        return success_response(
            data=serializer.data,
            message="Roles retrieved successfully.",
            status_code=status.HTTP_200_OK,
        )

    # CREATE
    def post(self, request):
        serializer = RoleSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Validation failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save()
        return success_response(
            data=serializer.data,
            message="Role created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    # UPDATE (via ?id=)
    def put(self, request):
        role_id = request.query_params.get("id")
        if not role_id:
            return error_response(
                message="ID parameter is required for update.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            obj = Role.objects.get(id=role_id)
        except Role.DoesNotExist:
            return error_response(
                message="Role not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = RoleSerializer(obj, data=request.data, partial=True)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Validation failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save()
        return success_response(
            data=serializer.data,
            message="Role updated successfully.",
            status_code=status.HTTP_200_OK,
        )

    # DELETE (via ?id=)
    def delete(self, request):
        role_id = request.query_params.get("id")
        if not role_id:
            return error_response(
                message="ID parameter is required for deletion.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            obj = Role.objects.get(id=role_id)
            obj.delete()
            return success_response(
                message="Role deleted successfully.",
                status_code=status.HTTP_200_OK,
            )
        except Role.DoesNotExist:
            return error_response(
                message="Role not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        except ProtectedError:
            return error_response(
                errors={"detail": "Cannot delete role because it is assigned to active users."},
                message="Role is currently in use.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )


class UserPermissionsAPIView(APIView):
    """
    GET /api/auth/permissions/
    Returns the logged-in user's allowed screens (modules) and CRUD/download flags.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if not user.is_approved and not user.is_superuser:
            return error_response(
                errors={"detail": "Account pending administrator approval."},
                message="Account not approved",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        if user.is_superuser:
            modules = [
                {
                    "id": m.id,
                    "name": m.name,
                    "navigate_route": m.navigate_route,
                    "is_view": True,
                    "is_upload": True,
                    "is_update": True,
                    "is_delete": True,
                    "is_download": True,
                }
                for m in Module.objects.filter(is_active=True)
            ]
            return success_response(
                data={"roles": ["SUPERUSER"], "modules": modules},
                message="Permissions fetched successfully.",
            )

        active_roles = list(user.roles.filter(is_active=True).values_list("id", "code"))
        role_ids = [r[0] for r in active_roles]
        role_codes = [r[1] for r in active_roles]

        perms = RoleModulePermission.objects.filter(
            role_id__in=role_ids,
            module__is_active=True,
        ).select_related("module")

        merged = {}
        for p in perms:
            m = p.module
            if m.id not in merged:
                merged[m.id] = {
                    "id": m.id,
                    "name": m.name,
                    "navigate_route": m.navigate_route,
                    "is_view": False,
                    "is_upload": False,
                    "is_update": False,
                    "is_delete": False,
                    "is_download": False,
                }
            merged[m.id]["is_view"] |= p.is_view
            merged[m.id]["is_upload"] |= p.is_upload
            merged[m.id]["is_update"] |= p.is_update
            merged[m.id]["is_delete"] |= p.is_delete
            merged[m.id]["is_download"] |= p.is_download

        visible_modules = [item for item in merged.values() if item["is_view"]]

        return success_response(
            data={"roles": role_codes, "modules": visible_modules},
            message="Permissions fetched successfully.",
        )
class ModuleAPIView(APIView):
    """
    GET    /api/auth/modules/         -> List all active modules
    GET    /api/auth/modules/?id=1    -> Single module
    POST   /api/auth/modules/         -> Create module
    PUT    /api/auth/modules/?id=1    -> Update module
    DELETE /api/auth/modules/?id=1    -> Delete module
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mod_id = request.query_params.get("id")
        if mod_id:
            try:
                obj = Module.objects.get(id=mod_id)
                return success_response(data=ModuleSerializer(obj).data)
            except Module.DoesNotExist:
                return error_response(errors={"detail": "Module not found."}, status_code=404)

        qs = Module.objects.all().order_by("id")
        return success_response(data=ModuleSerializer(qs, many=True).data)

    def post(self, request):
        try:
            serializer = ModuleSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return success_response(
                data=serializer.data,
                message="Module created successfully.",
                status_code=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            return error_response(errors=e.detail, message="Validation failed.")

    def put(self, request):
        mod_id = request.query_params.get("id")
        if not mod_id:
            return error_response(errors={"detail": "Query parameter ?id= is required."})
        try:
            obj = Module.objects.get(id=mod_id)
            serializer = ModuleSerializer(obj, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return success_response(data=serializer.data, message="Module updated successfully.")
        except Module.DoesNotExist:
            return error_response(errors={"detail": "Module not found."}, status_code=404)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Validation failed.")

    def delete(self, request):
        mod_id = request.query_params.get("id")
        if not mod_id:
            return error_response(errors={"detail": "Query parameter ?id= is required."})
        deleted, _ = Module.objects.filter(id=mod_id).delete()
        if not deleted:
            return error_response(errors={"detail": "Module not found."}, status_code=404)
        return success_response(message="Module deleted successfully.")
class RoleModulePermissionAPIView(APIView):
    """
    Admin API to manage Role -> Module permissions.
    GET    /api/auth/role-permissions/           -> List all (or filter by ?role_id=)
    GET    /api/auth/role-permissions/?id=1      -> Single record
    POST   /api/auth/role-permissions/           -> Create mapping
    PUT    /api/auth/role-permissions/?id=1      -> Update flags
    DELETE /api/auth/role-permissions/?id=1      -> Delete mapping
    """
    permission_classes = [IsAuthenticated]  # Restrict to ADMIN via HasModulePermission below

    def get(self, request):
        perm_id = request.query_params.get("id")
        role_id = request.query_params.get("role_id")

        if perm_id:
            try:
                obj = RoleModulePermission.objects.select_related("role", "module").get(id=perm_id)
                return success_response(data=RoleModulePermissionSerializer(obj).data)
            except RoleModulePermission.DoesNotExist:
                return error_response(errors={"detail": "Permission record not found."}, status_code=404)

        qs = RoleModulePermission.objects.select_related("role", "module").all()
        if role_id:
            qs = qs.filter(role_id=role_id)

        return success_response(data=RoleModulePermissionSerializer(qs, many=True).data)

    def post(self, request):
        try:
            serializer = RoleModulePermissionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return success_response(
                data=serializer.data,
                message="Role module permission created.",
                status_code=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            return error_response(errors=e.detail, message="Validation failed.")

    def put(self, request):
        perm_id = request.query_params.get("id")
        if not perm_id:
            return error_response(errors={"detail": "Query parameter ?id= is required."})

        try:
            obj = RoleModulePermission.objects.get(id=perm_id)
            serializer = RoleModulePermissionSerializer(obj, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return success_response(data=serializer.data, message="Permissions updated.")
        except RoleModulePermission.DoesNotExist:
            return error_response(errors={"detail": "Permission record not found."}, status_code=404)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Validation failed.")

    def delete(self, request):
        perm_id = request.query_params.get("id")
        if not perm_id:
            return error_response(errors={"detail": "Query parameter ?id= is required."})

        deleted, _ = RoleModulePermission.objects.filter(id=perm_id).delete()
        if not deleted:
            return error_response(errors={"detail": "Permission record not found."}, status_code=404)
        return success_response(message="Permission record deleted.")

class UserView(APIView):
    permission_classes = [IsAuthenticated]

    # READ (List all or retrieve single via ?id=)
    def get(self, request):
        user_id = request.query_params.get("id")

        if user_id:
            try:
                obj = User.objects.select_related("role").get(id=user_id)
                serializer = UserSerializer(obj)
                return success_response(
                    data=serializer.data,
                    message="User retrieved successfully.",
                    status_code=status.HTTP_200_OK,
                )
            except User.DoesNotExist:
                return error_response(
                    message="User not found.",
                    status_code=status.HTTP_404_NOT_FOUND,
                )

        queryset = User.objects.select_related("role").all().order_by("-date_joined")
        serializer = UserSerializer(queryset, many=True)
        return success_response(
            data=serializer.data,
            message="Users retrieved successfully.",
            status_code=status.HTTP_200_OK,
        )

    # CREATE
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Validation failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.save()
        return success_response(
            data=UserSerializer(user).data,
            message="User created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    # UPDATE (via ?id=)
    def put(self, request):
        user_id = request.query_params.get("id")
        if not user_id:
            return error_response(
                message="ID parameter is required for update.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            obj = User.objects.select_related("role").get(id=user_id)
        except User.DoesNotExist:
            return error_response(
                message="User not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = UserSerializer(obj, data=request.data, partial=True)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Validation failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save()
        return success_response(
            data=serializer.data,
            message="User updated successfully.",
            status_code=status.HTTP_200_OK,
        )

    # DELETE (via ?id=)
    def delete(self, request):
        user_id = request.query_params.get("id")
        if not user_id:
            return error_response(
                message="ID parameter is required for deletion.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            obj = User.objects.get(id=user_id)
            obj.is_active = False
            obj.save(update_fields=["is_active"])
            return success_response(
                message="User deactivated successfully.",
                status_code=status.HTTP_200_OK,
            )
        except User.DoesNotExist:
            return error_response(
                message="User not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )