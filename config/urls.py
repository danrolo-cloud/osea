from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import include, path, reverse


def back_office_login(request):
    """The back office uses the main sign-in page, so two-step sign-in applies there too."""
    if request.user.is_authenticated:
        # Signed in but not allowed into the back office: say so (redirecting would loop).
        raise PermissionDenied
    query = request.GET.urlencode()
    return redirect(reverse("accounts:login") + (f"?{query}" if query else ""))


admin.site.site_header = "OSEA back office"
admin.site.site_title = "OSEA back office"
admin.site.index_title = "Records"

urlpatterns = [
    path("", include("core.urls")),
    path("", include("schools.urls")),
    path("", include("audit.urls")),
    path("", include("competitions.urls")),
    path("", include("matches.urls")),
    path("account/", include("accounts.urls")),
    # Django's built-in back office. A fallback for a few trusted people,
    # not the main admin interface. Kept at a non-obvious address.
    path("back-office/login/", back_office_login),
    path("back-office/", admin.site.urls),
]
