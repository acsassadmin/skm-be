from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

class StandardPagination(PageNumberPagination):
    page_size = 6
    page_size_query_param = 'size'  
    max_page_size = 1000
    
    def get_page_size(self, request):
        """
        Custom lookup interceptor allowing clients to pass either '?size=25' 
        or '?page_size=25' parameter structures.
        """
        # 1. First check your configured primary key
        if self.page_size_query_param in request.query_params:
            return super().get_page_size(request)
            
        # 2. Seamless fallback option to handle '?page_size=X' formatting requests
        if 'page_size' in request.query_params:
            try:
                requested_size = int(request.query_params.get('page_size'))
                # Enforce max pagination safety guards
                return min(requested_size, self.max_page_size)
            except (ValueError, TypeError):
                pass
                
        return self.page_size

    def get_paginated_response(self, data,message=None):
        return Response({
            "success": True,
            "message": message if message is not None else "Data retrieved successfully",
            "pagination": {
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "page_size": self.get_page_size(self.request),
            },
            "data": data if data is not None else [],
            "errors": None  # Match your standard success_response structure
        })
        
