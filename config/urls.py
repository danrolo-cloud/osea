from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "OSEA back office"
admin.site.site_title = "OSEA back office"
admin.site.index_title = "Records"

urlpatterns = [
    path("", include("core.urls")),
    path("", include("schools.urls")),
    path("", include("audit.urls")),
    path("", include("competitions.urls")),
    path("account/", include("accounts.urls")),
    # Django's built-in back office. A fallback for a few trusted people,
    # not the main admin interface. Kept at a non-obvious address.
    path("back-office/", admin.site.urls),
]
