from django.apps import AppConfig as BaseAppConfig, apps
from django.conf import settings
from django.utils import timezone
from urllib.parse import quote


class AppConfig(BaseAppConfig):
    name = 'racetime'
    verbose_name = 'racetime'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        from . import signals  # noqa


def context_processor(request):
    Bulletin = apps.get_model('racetime', 'Bulletin')
    return {
        'bulletins': Bulletin.objects.filter(
            visible_from__lte=timezone.now(),
            visible_to__gte=timezone.now(),
        ),
        'emotes': {},
        'login_next': request.GET.get('next', request.get_full_path),
        'discord_auth_enabled': settings.RT_DISCORD_AUTH_ENABLED,
        'patreon_enabled': settings.RT_PATREON_ENABLED,
        'public_category_requests': settings.RT_PUBLIC_CATEGORY_REQUESTS,
        'public_password_auth': settings.RT_PUBLIC_PASSWORD_AUTH,
        'site_info': settings.RT_SITE_INFO,
    }
