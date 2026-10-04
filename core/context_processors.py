from django.conf import settings


def site(request):
    return {"environment_label": settings.OSEA_ENVIRONMENT_LABEL}
