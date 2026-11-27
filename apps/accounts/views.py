from .models import *
from .serializers import *
from accounts.services.otp_service import send_otp_notification
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny,IsAuthenticated
from utils.responses import success_response,error_response
from rest_framework.exceptions import ValidationError
from django.db.models import ProtectedError
from rest_framework import status
from utils.otp import generate_otp_code, get_otp_expiry
from django.utils import timezone
from core.cache_constants import *
from core.cache_hooks import *
from core.schema import auto_schema
from utils.email_service import (
    send_account_activation_email,
    send_account_approval_email,
    send_password_reset_email
)
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
class SendOTPView(APIView):
    permission_classes = [AllowAny]
    @auto_schema(summary="Send OTP",request=SendOTPSerializer,response=SendOTPSerializer)
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
    @auto_schema(summary="verify OTP",request=VerifyOTPSerializer,response=VerifyOTPSerializer)
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
    @auto_schema(summary="Register User",request=RegisterSerializer,response=RegisterSerializer)
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
    @auto_schema(summary="Login User",request=LoginSerializer,response=LoginSerializer)
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

    @auto_schema(
        summary="Get all roles or a single role by ID",
        params={"id": int},
        response=RoleSerializer,
        many=True,
    )
    @CacheHook.cache_api_response(namespace=CacheKeys.ROLES, timeout=CacheTTL.SHORT)
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
    @auto_schema(
        summary="Create a new role",
        request=RoleSerializer,
        response=RoleSerializer,
    )
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
        CacheHook.bump_version(CacheKeys.ROLES)
        return success_response(
            data=serializer.data,
            message="Role created successfully.",
            status_code=status.HTTP_201_CREATED,
        )

    @auto_schema(
        summary="Update an existing role",
        params={"id*": int},
        request=RoleSerializer,
        response=RoleSerializer,
    )
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
        CacheHook.bump_version(CacheKeys.ROLES)
        return success_response(
            data=serializer.data,
            message="Role updated successfully.",
            status_code=status.HTTP_200_OK,
        )

    @auto_schema(
        summary="Delete a role",
        params={"id*": int},
    )
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
            CacheHook.bump_version(CacheKeys.ROLES)
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
    @auto_schema(summary="Get logged-in user's module permissions")
    @CacheHook.cache_api_response(
        namespace=CacheKeys.PERMISSIONS,
        timeout=CacheTTL.MEDIUM,
        vary_on_user=True,  
    )
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

    @auto_schema(
        summary="Get all modules or a single module by ID",
        params={"id": int},
        response=ModuleSerializer,
        many=True,
    )
    @CacheHook.cache_api_response(namespace=CacheKeys.PERMISSIONS, timeout=CacheTTL.LONG)
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

    @auto_schema(
        summary="Create a new module",
        request=ModuleSerializer,
        response=ModuleSerializer,
    )
    def post(self, request):
        try:
            serializer = ModuleSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            CacheHook.bump_version(CacheKeys.PERMISSIONS)
            return success_response(
                data=serializer.data,
                message="Module created successfully.",
                status_code=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            return error_response(errors=e.detail, message="Validation failed.")

    @auto_schema(
        summary="Update an existing module",
        params={"id*": int},
        request=ModuleSerializer,
        response=ModuleSerializer,
    )
    def put(self, request):
        mod_id = request.query_params.get("id")
        if not mod_id:
            return error_response(errors={"detail": "Query parameter ?id= is required."})
        try:
            obj = Module.objects.get(id=mod_id)
            serializer = ModuleSerializer(obj, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            CacheHook.bump_version(CacheKeys.PERMISSIONS)
            return success_response(data=serializer.data, message="Module updated successfully.")
        except Module.DoesNotExist:
            return error_response(errors={"detail": "Module not found."}, status_code=404)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Validation failed.")

    @auto_schema(
        summary="Delete a module",
        params={"id*": int},
    )
    def delete(self, request):
        mod_id = request.query_params.get("id")
        if not mod_id:
            return error_response(errors={"detail": "Query parameter ?id= is required."})
        deleted, _ = Module.objects.filter(id=mod_id).delete()
        CacheHook.bump_version(CacheKeys.PERMISSIONS)
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
    @auto_schema(
        summary="Get role-module permissions (all, by role_id, or single by id)",
        params={"id": int, "role_id": int},
        response=RoleModulePermissionSerializer,
        many=True,
    )
    @CacheHook.cache_api_response(namespace=CacheKeys.PERMISSIONS, timeout=CacheTTL.LONG)
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
    @auto_schema(
        summary="Create role-module permission mapping",
        request=RoleModulePermissionSerializer,
        response=RoleModulePermissionSerializer,
    )
    # def post(self, request):
    #     try:
    #         serializer = RoleModulePermissionSerializer(data=request.data)
    #         serializer.is_valid(raise_exception=True)
    #         serializer.save()
    #         CacheHook.bump_version(CacheKeys.PERMISSIONS)
    #         return success_response(
    #             data=serializer.data,
    #             message="Role module permission created.",
    #             status_code=status.HTTP_201_CREATED,
    #         )
    #     except ValidationError as e:
    #         return error_response(errors=e.detail, message="Validation failed.")
    def post(self, request):
        role_id = request.data.get("role")
        module_id = request.data.get("module")
        if not role_id or not module_id:
            return error_response(
                errors={"detail": "Both 'role' and 'module' are required."},
                message="Validation failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        instance = RoleModulePermission.objects.filter(
            role_id=role_id, module_id=module_id
        ).first()

        serializer = RoleModulePermissionSerializer(
            instance, data=request.data, partial=bool(instance)
        )
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Validation failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save()
        CacheHook.bump_version(CacheKeys.PERMISSIONS)
        return success_response(
            data=serializer.data,
            message="Role permissions saved successfully.",
            status_code=status.HTTP_200_OK if instance else status.HTTP_201_CREATED,
        )
    @auto_schema(
        summary="Update role-module permission flags",
        params={"id*": int},
        request=RoleModulePermissionSerializer,
        response=RoleModulePermissionSerializer,
    )
    def put(self, request):
        perm_id = request.query_params.get("id")
        if not perm_id:
            return error_response(errors={"detail": "Query parameter ?id= is required."})

        try:
            obj = RoleModulePermission.objects.get(id=perm_id)
            serializer = RoleModulePermissionSerializer(obj, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            CacheHook.bump_version(CacheKeys.PERMISSIONS)
            return success_response(data=serializer.data, message="Permissions updated.")
        except RoleModulePermission.DoesNotExist:
            return error_response(errors={"detail": "Permission record not found."}, status_code=404)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Validation failed.")

    @auto_schema(
        summary="Delete role-module permission mapping",
        params={"id*": int},
    )
    def delete(self, request):
        perm_id = request.query_params.get("id")
        if not perm_id:
            return error_response(errors={"detail": "Query parameter ?id= is required."})

        deleted, _ = RoleModulePermission.objects.filter(id=perm_id).delete()
        CacheHook.bump_version(CacheKeys.PERMISSIONS)
        if not deleted:
            return error_response(errors={"detail": "Permission record not found."}, status_code=404)
        return success_response(message="Permission record deleted.")

class UserView(APIView):
    permission_classes = [IsAuthenticated]

    # READ (List all or retrieve single via ?id=)
    @auto_schema(
        summary="Get all users or a single user by ID",
        params={"id": int},
        response=UserSerializer,
        many=True,
    )
    def get(self, request):
        user_id = request.query_params.get("id")
        base_qs = User.objects.prefetch_related("roles", "addresses").order_by("-date_joined")

        if user_id:
            try:
                obj = base_qs.get(id=user_id)
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

        role_code = request.query_params.get("role")
        is_approved = request.query_params.get("is_approved")

        queryset = base_qs
        if role_code:
            queryset = queryset.filter(roles__code=role_code.upper())
        if is_approved is not None and is_approved != "":
            queryset = queryset.filter(is_approved=is_approved.lower() == "true")

        serializer = UserSerializer(queryset.distinct(), many=True)
        return success_response(
            data=serializer.data,
            message="Users retrieved successfully.",
            status_code=status.HTTP_200_OK,
        )

    # CREATE
    @auto_schema(
        summary="Create a new user",
        request=RegisterSerializer,
        response=UserSerializer,
    )
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
    @auto_schema(
        summary="Update user details, role, or approval status",
        params={"id*": int},
        request=UserSerializer,
        response=UserSerializer,
    )
    def put(self, request):
        user_id = request.query_params.get("id")
        if not user_id:
            return error_response(
                errors={"id": "Query parameter ?id= is required."},
                message="User ID is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            obj = User.objects.prefetch_related("roles", "addresses").get(id=user_id)
        except User.DoesNotExist:
            return error_response(
                message="User not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        old_approved = obj.is_approved
        old_active = obj.is_active

        serializer = UserSerializer(obj, data=request.data, partial=True)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(
                errors=e.detail,
                message="Validation failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        updated_user = serializer.save()

        if updated_user.is_approved != old_approved:
            primary_role = updated_user.roles.first()
            role_label = primary_role.name.title() if primary_role else "Account"
            send_account_approval_email(
                recipient=updated_user.email,
                full_name=updated_user.full_name,
                is_approved=updated_user.is_approved,
                role_name=role_label,
            )

        if updated_user.is_active != old_active:
            send_account_activation_email(
                recipient=updated_user.email,
                full_name=updated_user.full_name,
                is_active=updated_user.is_active,
            )
        return success_response(
            data=serializer.data,
            message="User updated successfully.",
            status_code=status.HTTP_200_OK,
        )

    @auto_schema(
        summary="Deactivate a user account",
        params={"id*": int},
    )
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

class UserAddressView(APIView):
    """
    GET    /api/auth/addresses/         -> List user's saved addresses (or ?id= for single)
    POST   /api/auth/addresses/         -> Add a new shipping/billing address
    PUT    /api/auth/addresses/?id=1    -> Update an address
    DELETE /api/auth/addresses/?id=1    -> Delete an address
    """

    permission_classes = [IsAuthenticated]
    @auto_schema(
        summary="Get user's saved addresses or a single address by ID",
        params={"id": int},
        response=UserAddressSerializer,
        many=True,
    )
    def get(self, request):
        addr_id = request.query_params.get("id")
        if addr_id:
            address = UserAddress.objects.filter(id=addr_id, user=request.user).first()
            if not address:
                return error_response(
                    message="Address not found.", status_code=status.HTTP_404_NOT_FOUND
                )
            return success_response(data=UserAddressSerializer(address).data)

        addresses = UserAddress.objects.filter(user=request.user)
        return success_response(
            data=UserAddressSerializer(addresses, many=True).data,
            message="Addresses retrieved successfully.",
        )

    @auto_schema(
        summary="Add a new shipping/billing address",
        request=UserAddressSerializer,
        response=UserAddressSerializer,
    )
    def post(self, request):
        serializer = UserAddressSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Invalid address data.")

        # Auto-mark first address as default
        is_first = not UserAddress.objects.filter(user=request.user).exists()
        is_default = serializer.validated_data.get("is_default", False) or is_first

        address = serializer.save(user=request.user, is_default=is_default)
        return success_response(
            data=UserAddressSerializer(address).data,
            message="Address saved successfully.",
            status_code=status.HTTP_201_CREATED,
        )
    @auto_schema(
        summary="Update an existing address",
        params={"id*": int},
        request=UserAddressSerializer,
        response=UserAddressSerializer,
    )
    def put(self, request):
        addr_id = request.query_params.get("id")
        if not addr_id:
            return error_response(
                errors={"id": "Query parameter ?id= is required."},
                message="Address ID missing.",
            )

        address = UserAddress.objects.filter(id=addr_id, user=request.user).first()
        if not address:
            return error_response(
                message="Address not found.", status_code=status.HTTP_404_NOT_FOUND
            )

        serializer = UserAddressSerializer(address, data=request.data, partial=True)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as e:
            return error_response(errors=e.detail, message="Invalid address update.")

        serializer.save()
        return success_response(data=serializer.data, message="Address updated successfully.")
    @auto_schema(
        summary="Delete a saved address",
        params={"id*": int},
    )
    def delete(self, request):
        addr_id = request.query_params.get("id")
        if not addr_id:
            return error_response(
                errors={"id": "Query parameter ?id= is required."},
                message="Address ID missing.",
            )

        address = UserAddress.objects.filter(id=addr_id, user=request.user).first()
        if not address:
            return error_response(
                message="Address not found.", status_code=status.HTTP_404_NOT_FOUND
            )

        was_default = address.is_default
        address.delete()

        # Promote most recent remaining address to default if the default was deleted
        if was_default:
            next_addr = UserAddress.objects.filter(user=request.user).first()
            if next_addr:
                next_addr.is_default = True
                next_addr.save(update_fields=["is_default"])

        return success_response(message="Address deleted successfully.")


class ForgotPasswordAPIView(APIView):
    """
    Endpoint: POST /api/auth/forgot-password/
    Generates a secure cryptographic reset link and sends it to the user's email.
    """
    permission_classes = [AllowAny]

    @auto_schema(
        summary="Request password reset link",
        request=ForgotPasswordSerializer,
    )
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors, message="Validation Failed")

        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user:
            send_password_reset_email(user)

        return success_response(
            data=None,
            message="If the email matches an active account, a secure reset link has been dispatched.",
        )


class ResetPasswordAPIView(APIView):
    """
    Endpoint: POST /api/auth/reset-password/
    Validates uid + token and updates the user's password.
    """
    permission_classes = [AllowAny]

    @auto_schema(
        summary="Confirm password reset with uid and token",
        request=ResetPasswordSerializer,
    )
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(errors=serializer.errors, message="Validation Failed")

        data = serializer.validated_data

        try:
            user_id = force_str(urlsafe_base64_decode(data["uid"]))
            user = User.objects.get(pk=user_id, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return error_response(
                errors="The reset link contains invalid or corrupted parameters.",
                message="Invalid Link Parameters",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(user, data["token"]):
            return error_response(
                errors="This link is invalid or has expired. Please request a new link.",
                message="Token Validation Error",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(data["new_password"])
        user.save(update_fields=["password"])

        return success_response(
            data=None,
            message="Your account password has been changed successfully. You may now log in.",
        )