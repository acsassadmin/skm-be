# core/cache_hooks.py
import functools
import hashlib
import json
import logging
from typing import Any, Callable, Optional
from django.core.cache import cache
from rest_framework.response import Response

logger = logging.getLogger(__name__)


class CacheHook:
    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        try:
            value = cache.get(key, default)
            if value is default:
                logger.debug("Cache MISS: %s", key)
            else:
                logger.debug("Cache HIT: %s", key)
            return value
        except Exception as exc:
            logger.error("Cache GET failed for '%s': %s", key, exc)
            return default

    @staticmethod
    def set(key: str, value: Any, timeout: Optional[int] = None) -> None:
        try:
            cache.set(key, value, timeout=timeout)
            logger.debug("Cache SET: %s (TTL: %s)", key, timeout or "default")
        except Exception as exc:
            logger.error("Cache SET failed for '%s': %s", key, exc)

    @staticmethod
    def delete(*keys: str) -> None:
        if not keys:
            return
        try:
            cache.delete_many(keys)
            logger.info("Cache DELETE: %s", ", ".join(keys))
        except Exception as exc:
            logger.error("Cache DELETE failed for %s: %s", keys, exc)

    @staticmethod
    def get_version(namespace: str) -> int:
        version_key = f"{namespace}:version"
        try:
            version = cache.get(version_key)
            if version is None:
                cache.set(version_key, 1, timeout=None)
                return 1
            return int(version)
        except Exception as exc:
            logger.error("Cache GET_VERSION failed for '%s': %s", version_key, exc)
            return 1

    @staticmethod
    def bump_version(namespace: str) -> None:
        version_key = f"{namespace}:version"
        try:
            cache.incr(version_key)
            logger.info("Cache BUMP VERSION: %s", version_key)
        except ValueError:
            cache.set(version_key, 2, timeout=None)
        except Exception as exc:
            logger.error("Cache BUMP_VERSION failed for '%s': %s", version_key, exc)

    @staticmethod
    def cache_api_response(namespace: str, timeout: Optional[int] = None,vary_on_user: bool = False,scope_func: Optional[Callable] = None,):
        """
        Decorator for DRF GET methods.
        Generates a fixed-length ~35-char cache key regardless of query param length.
        """
        def decorator(view_func: Callable):
            @functools.wraps(view_func)
            def wrapper(self, request, *args, **kwargs):
                version = CacheHook.get_version(namespace)
                if scope_func:
                    scope = scope_func(request)
                elif vary_on_user:
                    user_id = getattr(request.user, "id", None) or "anon"
                    scope = f"user:{user_id}"
                else:
                    scope = "admin" if getattr(request.user, "is_staff", False) else "public"
                # Isolate by exact user ID when vary_on_user=True, otherwise by role
                if vary_on_user:
                    user_id = getattr(request.user, "id", None) or "anon"
                    scope = f"user:{user_id}"
                else:
                    scope = "admin" if getattr(request.user, "is_staff", False) else "public"

                params = json.dumps(sorted(request.query_params.items()))
                param_hash = hashlib.md5(params.encode("utf-8")).hexdigest()[:12]
                cache_key = f"{namespace}:v{version}:{scope}:{param_hash}"

                cached_data = CacheHook.get(cache_key)
                if cached_data is not None:
                    return Response(cached_data, status=200)

                response = view_func(self, request, *args, **kwargs)

                if getattr(response, "status_code", None) == 200 and hasattr(response, "data"):
                    CacheHook.set(cache_key, response.data, timeout=timeout)

                return response
            return wrapper
        return decorator
