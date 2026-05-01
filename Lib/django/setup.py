from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="django",
    overlay_entries=["Lib/django"],
    verification_steps=[
        inline_verification_step(
            "django-smoke",
            """
import django
from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse, QueryDict
from django.template import Context, Engine
from django.urls import path, resolve, reverse
from django.utils import timezone

if not settings.configured:
    settings.configure(
        SECRET_KEY="staticpython",
        INSTALLED_APPS=[],
        ROOT_URLCONF=__name__,
        USE_TZ=True,
        TIME_ZONE="UTC",
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": False, "OPTIONS": {}}],
    )
django.setup()

def index(request):
    return HttpResponse("ok")

urlpatterns = [path("demo/", index, name="demo")]
match = resolve("/demo/")
assert match.func is index
assert reverse("demo") == "/demo/"
request = HttpRequest()
request.method = "GET"
request.path = "/demo/"
request.GET = QueryDict("x=1")
assert index(request).content == b"ok"
with connection.cursor() as cursor:
    cursor.execute("select 1")
    assert cursor.fetchone() == (1,)
assert Engine().from_string("Hello {{ name }}").render(Context({"name": "Codex"})) == "Hello Codex"
assert timezone.is_aware(timezone.now())
""",
        )
    ],
)
