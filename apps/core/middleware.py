import threading
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.tokens import AccessToken

_request_locals = threading.local()
User = get_user_model()  

class JWTMiddleware(MiddlewareMixin):
    """
    Middleware to validate JWT tokens for API requests and attach the Employee instance to the request.
    """
    def process_request(self, request):
        # 1. Only apply to API requests
        if not request.path.startswith('/api/'):
            return None

        # 2. List of paths that do NOT require a token (added missing leading slash to firebase endpoint)
        exempt_paths = [
            
            '/api/auth/refresh/',
            '/api/auth/verify-otp/',
            '/api/auth/send-otp/',
            '/api/auth/token/refresh/',
            '/api/auth/login/',
            '/api/auth/register/',
            '/api/docs/',
            '/api/schema/',
            '/api/redoc/',
            '/api/core/contact/',
            '/api/core/enquiry/',
            '/api/catalogue/products/'
            
            
           
        ]
        
        if request.path in exempt_paths:
            return None

        # 3. Get the Authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header:
            return JsonResponse({'error': 'Authorization header missing'}, status=401)

        try:
            # Expected format: "Bearer <token>"
            parts = auth_header.split()
            if parts[0].lower() != 'bearer' or len(parts) != 2:
                return JsonResponse({'error': 'Invalid Authorization header format. Use "Bearer <token>"'}, status=401)

            token_str = parts[1]

            # 4. Validate the token using SimpleJWT
            validated_token = AccessToken(token_str)
            
            # 5. Attach the authenticated Employee user directly to the request
            user_id = validated_token.get('user_id')
            if user_id:
                try:
                    request.user = User.objects.get(pk=user_id)
                except User.DoesNotExist:
                    return JsonResponse({'error': 'User associated with this token does not exist'}, status=401)
            
        except (TokenError, InvalidToken):
            return JsonResponse({'error': 'Invalid or expired token'}, status=401)

        return None
    
    
class ThreadLocalMiddleware(MiddlewareMixin):
    """
    Middleware that stores the request object in thread local storage.
    """
    def process_request(self, request):
        _request_locals.request = request

    def process_response(self, request, response):
        if hasattr(_request_locals, 'request'):
            del _request_locals.request
        return response

    def process_exception(self, request, exception):
        if hasattr(_request_locals, 'request'):
            del _request_locals.request

def get_current_request():
    return getattr(_request_locals, 'request', None)



