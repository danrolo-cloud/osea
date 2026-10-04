from django.conf import settings
from django.test.runner import DiscoverRunner


class TestRunner(DiscoverRunner):
    """
    Tests run the same everywhere: two-step sign-in is not enforced for
    administrators unless a test turns it on (the two-step tests do).
    Passwords use a fast hash in tests only; the live site keeps the slow, secure one.
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        settings.OSEA_REQUIRE_ADMIN_2FA = False
        settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
