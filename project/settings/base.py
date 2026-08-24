"""
Quick-start development settings - unsuitable for production
See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/
"""
from datetime import datetime
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SECRET_KEY = '00aqmqedb05688z06d_%m%a==yu10am82ff)rcxk4il6@6%2=$'
DEBUG = True
ALLOWED_HOSTS = ['*']
APPEND_SLASH = False

# Application definition

INSTALLED_APPS = [
    'daphne',
    'racetime',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.humanize',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_extensions',
    'debug_toolbar',
    'django_recaptcha',
    'channels',
    'corsheaders',
    'django.forms',
    'django_admin_listfilter_dropdown',
    'oauth2_provider',
]

MIDDLEWARE = [
    'debug_toolbar.middleware.DebugToolbarMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'oauth2_provider.middleware.OAuth2TokenMiddleware',
]

ROOT_URLCONF = 'project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'racetime.apps.context_processor',
            ],
        },
    },
]

ASGI_APPLICATION = 'project.asgi.application'
WSGI_APPLICATION = 'project.wsgi.application'

FORM_RENDERER = 'django.forms.renderers.TemplatesSetting'

SILENCED_SYSTEM_CHECKS = ['django_recaptcha.recaptcha_test_key_error']

SITE_ID = 1

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'racetime.utils.RedisChannelLayer',
        'CONFIG': {
            "hosts": [('racetime.redis', 6379)],
        },
    },
}

CORS_ORIGIN_ALLOW_ALL = True
REAL_IP_HEADER = None

INTERNAL_IPS = ['127.0.0.1']
DEBUG_TOOLBAR_CONFIG = {
    'DISABLE_PANELS': {'debug_toolbar.panels.redirects.RedirectsPanel'},
    'SHOW_TOOLBAR_CALLBACK': 'project.debug.show_toolbar',
}

# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'racetime',
        'USER': 'racetime',
        'PASSWORD': 'racetime',
        'HOST': 'racetime.db',
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    },
}

# Authentication

AUTHENTICATION_BACKENDS = (
    'oauth2_provider.backends.OAuth2Backend',
    'django.contrib.auth.backends.ModelBackend',
)
AUTH_USER_MODEL = 'racetime.User'
LOGIN_URL = '/account/auth'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = 'en-gb'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.2/howto/static-files/

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'node_modules', 'jquery', 'dist'),
    os.path.join(BASE_DIR, 'node_modules', 'jquery-form', 'dist'),
    os.path.join(BASE_DIR, 'node_modules', 'jquery-ui-dist'),
    os.path.join(BASE_DIR, 'node_modules', 'js-cookie', 'dist'),
]
STATIC_ROOT = os.path.join(BASE_DIR, 'static')
STATIC_URL = '/static/'

# Media files

MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
MEDIA_URL = '/media/'

# Logging

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'django.server': {
            '()': 'django.utils.log.ServerFormatter',
            'format': '[{server_time}] {message}',
            'style': '{',
        }
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
        },
        'django.server': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'django.server',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'django.server': {
            'handlers': ['django.server'],
            'level': 'WARNING',
            'propagate': False,
        },
        'racebot': {
            'handlers': ['django.server'],
            'level': 'INFO',
            'propagate': False,
        },
    }
}

# OAuth2 settings

OAUTH2_PROVIDER = {
    'AUTHORIZATION_CODE_EXPIRE_SECONDS': 600,
    'PKCE_REQUIRED': False,
    'SCOPES': {
        'read': 'See your name, Twitch username and basic user information.',
        'chat_message': 'Send chat messages to race rooms on your behalf.',
        'race_action': 'Join and interact with races on your behalf.',
        'create_race': 'Create race rooms on your behalf.',
    },
}

# Preserve the stock-client compatibility shim only for upstream development.
# Z1RR test/CI/production profiles disable it and require S256 PKCE.
RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS = True
RT_Z1RR_LIVESPLIT_APPLICATION_NAME = "LiveSplit.Racetime.Z1RR"
RT_Z1RR_LIVESPLIT_REDIRECT_URI = "http://127.0.0.1:4888/"

# Site details

EMAIL_FROM = 'hello@racetime.dev'
# Upstream-compatible defaults. Z1RR production/test profiles explicitly
# disable these legacy public account and category surfaces.
RT_PUBLIC_PASSWORD_AUTH = True
RT_PUBLIC_CATEGORY_REQUESTS = True
RT_PATREON_ENABLED = True

# Distributed public-endpoint throttling is opt-in for upstream development.
# Service-backed and production profiles enable it with a dedicated secret.
RT_THROTTLING_ENABLED = False
RT_THROTTLING_REQUIRE_REDIS = False
RACETIME_THROTTLE_HMAC_KEY = None
RACETIME_TRUSTED_PROXY_CIDR = None


RT_SITE_URI = 'http://localhost:8000'
# Discord OAuth is fail-closed in base/development settings. Deployments that
# enable it must supply credentials through their environment-backed profile.
RT_DISCORD_AUTH_ENABLED = False
DISCORD_AUTHORIZE_URL = 'https://discord.com/oauth2/authorize'
DISCORD_TOKEN_URL = 'https://discord.com/api/oauth2/token'
DISCORD_USER_URL = 'https://discord.com/api/users/@me'
DISCORD_REDIRECT_URI = RT_SITE_URI + '/account/discord/callback'
DISCORD_HTTP_TIMEOUT = (3.05, 10.0)
DISCORD_CLIENT_ID = None
DISCORD_CLIENT_SECRET = None

RT_SITE_INFO = {
    'title': 'racetime.dev',
    'header_text': 'racetime<span class="dot">.</span>dev',
    'meta_site_name': 'racetime.dev',
    'meta_description': 'racetime development environment',
    'footer_text': ['Development environment. Last restart: ' + datetime.now().isoformat()],
    'footer_links': (
        (
            {'text': 'Discord', 'link': 'https://discord.racetime.gg', 'img': 'racetime/image/social/discord.svg'},
            {'text': 'GitHub', 'link': 'https://github.com/racetimeGG/racetime-app', 'img': 'racetime/image/social/github.svg'},
        ),
    ),
    'extra_scripts': [],
}

RT_CACHE_TIMEOUT = {
    'RaceListData': 30,
    'CategoryData': 60,
    'CategoryListData': 60,
    'RaceData': 5,
    'RaceRenders': 15,
}
