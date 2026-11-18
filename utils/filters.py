from django.db.models import Q


def apply_search_and_filters(queryset, request, search_fields=None, filter_fields=None):
    """
    Reusable helper for APIView to apply:
    - Keyword search across multiple fields (?search=keyword)
    - Exact field filters (?how_did_you_hear_about_us=google)
    - Date range filters (?start_date=2026-01-01&end_date=2026-12-31)
    """
    query_params = request.query_params

    # 1. Keyword Search (?search=...)
    search_query = query_params.get('search', '').strip()
    if search_query and search_fields:
        q_objects = Q()
        for field in search_fields:
            q_objects |= Q(**{f"{field}__icontains": search_query})
        queryset = queryset.filter(q_objects)

    # 2. Exact Match Filters (e.g., ?how_did_you_hear_about_us=google)
    if filter_fields:
        for param_name, model_field in filter_fields.items():
            value = query_params.get(param_name)
            if value:
                queryset = queryset.filter(**{model_field: value})

    # 3. Date Range Filters on created_at (?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD)
    start_date = query_params.get('start_date')
    end_date = query_params.get('end_date')
    if start_date:
        queryset = queryset.filter(created_at__date__gte=start_date)
    if end_date:
        queryset = queryset.filter(created_at__date__lte=end_date)

    return queryset
