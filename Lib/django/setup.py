from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='django',
    overlay_entries=['Lib/django'],
    verification_steps=[
        inline_verification_step(
            "django-smoke",
            """
import django
from django.conf import settings
from django.utils import timezone
from django.urls import path, resolve
from django.http import HttpResponse

if not settings.configured:
    settings.configure(SECRET_KEY="staticpython", INSTALLED_APPS=[], ROOT_URLCONF=__name__, USE_TZ=True, TIME_ZONE="UTC")
django.setup()

def index(request):
    return HttpResponse("ok")

urlpatterns = [path("demo/", index, name="demo")]
match = resolve("/demo/")
assert match.func is index
assert timezone.is_aware(timezone.now())
""",
        )
    ],
)
