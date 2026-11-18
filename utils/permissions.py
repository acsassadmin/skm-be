from rest_framework.permissions import BasePermission
from accounts.models import RoleModulePermission


class HasModulePermission(BasePermission):
    """
    Usage:
        permission_classes = [IsAuthenticated, HasModulePermission.for_module("Catalogue", "is_upload")]
    """
    module_name = ""
    action = "is_view"
    message = "You do not have permission to perform this action."

    @classmethod
    def for_module(cls, module_name: str, action: str = "is_view"):
        return type(
            f"HasModulePerm_{module_name}_{action}",
            (cls,),
            {"module_name": module_name, "action": action},
        )

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if not user.is_approved:
            return False

        return RoleModulePermission.objects.filter(
            role__users=user,
            role__is_active=True,
            module__name__iexact=self.module_name,
            module__is_active=True,
            **{self.action: True},
        ).exists()
