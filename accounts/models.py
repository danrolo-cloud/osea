from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", User.Role.COACH)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have is_staff and is_superuser set.")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        # Email addresses are matched without regard to capital letters.
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})


class User(AbstractBaseUser, PermissionsMixin):
    """
    A person who can sign in.

    `role` decides which part of the platform they use:
      - ADMIN: OSEA staff/volunteers who run competitions.
      - COACH: teacher coaches. A coach can only see a school's data once an
        administrator has approved their link to that school (added in Phase 1).

    `is_staff` is separate and only controls access to Django's built-in
    back-office screen, which is a fallback tool for a few trusted people.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "OSEA administrator"
        COACH = "coach", "Teacher coach"

    email = models.EmailField("email address", unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.COACH)

    is_active = models.BooleanField(
        default=True,
        help_text="Turn off instead of deleting, so this person's history is preserved.",
    )
    is_staff = models.BooleanField(
        default=False,
        help_text="Can open the built-in back-office screen. Keep this to very few people.",
    )
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.get_full_name()} <{self.email}>"

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name

    @property
    def is_osea_admin(self):
        return self.is_active and self.role == self.Role.ADMIN

    @property
    def is_coach(self):
        return self.is_active and self.role == self.Role.COACH
