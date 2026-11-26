# core/cache_constants.py

class CacheTTL:
    SHORT = 60              # 1 minute
    MEDIUM = 60 * 15        # 15 minutes
    LONG = 60 * 60 * 2      # 2 hours


class CacheKeys:
    # Version namespaces (used by @CacheHook.cache_api_response & signals)
    PRODUCTS = "products"
    CATEGORIES = "categories"
    PERMISSIONS = "permissions"
    ROLES = "roles"
    COUPONS = "coupons"
    LOW_STOCK_ALERTS = "low_stock_alerts"
    SALES_REPORTS = "sales_reports"
    PAYMENT_SETTINGS = "payment_settings"
