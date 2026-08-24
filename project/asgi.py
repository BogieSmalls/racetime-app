import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'project.settings')
django_application = get_asgi_application()

from racetime.routing import MiddlewareStack, urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_application,
    'websocket': MiddlewareStack(URLRouter(urlpatterns)),
})
