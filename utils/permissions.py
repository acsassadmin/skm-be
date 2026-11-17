# utils/permissions.py
from functools import wraps
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from .responses import error_response
from rest_framework import status
def check_permission(employee, permission_codename) -> bool:
    """
    Standard utility function to check an employee's permission explicitly.
    Safe execution check anywhere in your business services.
    """
    if not employee or not employee.is_authenticated:
        return False
    return employee.has_pos_perm(permission_codename)

def check_module_access(employee, module_codename) -> bool:
    """
    Standard utility function to verify if an employee has higher level module access.
    """
    if not employee or not employee.is_authenticated:
        return False
    return employee.has_module_access(module_codename)

def require_pos_permission(permission_codename):
    """
    Reusable View decorator. Gracefully blocks access and responds 
    with JSON structured responses for POS system endpoints.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not check_permission(request.user, permission_codename):
                return error_response(
                    message=f"Action unauthorized. Missing permission: {permission_codename}.",
                    errors={"permission": "Access Denied"},
                    status_code=status.HTTP_403_FORBIDDEN
                )
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
