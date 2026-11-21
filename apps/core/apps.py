from django.apps import AppConfig
import sys 
import logging
from django.core.cache import cache

logger=logging.getLogger(__name__)

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    
    def ready(self):
        if 'runserver' not in sys.argv:
            return
        try:
            cache.get("__health_check__")
            logger.info("✅ Redis cache is connected and ready.")
        except Exception as exc:
            logger.warning(
                "⚠️  WARNING: Redis is not running (%s). "
                "App will run using database fallback. "
                "Start Redis with: wsl -u root service redis-server start",
                exc,
            )
