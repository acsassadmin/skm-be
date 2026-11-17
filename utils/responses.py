from rest_framework.response import Response
from rest_framework import status

def success_response(data=None, message="Success", status_code=status.HTTP_200_OK):
    """
    Returns a unified success response for your React frontend.
    """
    return Response({
        "success": True,
        "message": message,
        "data": data if data is not None else {},
        "errors": None
    }, status=status_code)

def error_response(errors=None, message="An error occurred", status_code=status.HTTP_400_BAD_REQUEST):
    """
    Returns a unified error response for handling validation errors or failures.
    """
    return Response({
        "success": False,
        "message": message,
        # "data": {},
        "errors": errors if errors is not None else {}
    }, status=status_code)
