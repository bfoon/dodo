from django.contrib.auth.models import AbstractUser
from django.db import models


class CountryOffice(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=10, unique=True)
    region = models.CharField(max_length=100)
    timezone = models.CharField(max_length=50, default='UTC')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class Role(models.Model):
    """Dynamic roles per country office"""
    PERMISSION_CHOICES = [
        ('view', 'View Only'),
        ('create', 'Create'),
        ('edit', 'Edit'),
        ('delete', 'Delete'),
        ('approve', 'Approve'),
        ('admin', 'Admin'),
    ]
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=100)
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE, related_name='roles')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['code', 'country_office']
        ordering = ['name']

    def __str__(self):
        return f"{self.name} [{self.country_office.code}]"


class ModulePermission(models.Model):
    """Dynamic module-level permissions for roles"""
    MODULE_CHOICES = [
        ('dashboard', 'Dashboard'),
        ('projects', 'Projects'),
        ('monitoring', 'Monitoring & Indicators'),
        ('surveys', 'Surveys & Data Collection'),
        ('reporting', 'Reporting'),
        ('users', 'User Management'),
        ('admin', 'Administration'),
    ]
    ACTION_CHOICES = [
        ('view', 'View'),
        ('create', 'Create'),
        ('edit', 'Edit'),
        ('delete', 'Delete'),
        ('approve', 'Approve'),
        ('export', 'Export'),
    ]
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='permissions')
    module = models.CharField(max_length=50, choices=MODULE_CHOICES)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)

    class Meta:
        unique_together = ['role', 'module', 'action']

    def __str__(self):
        return f"{self.role.name} - {self.module}: {self.action}"


class User(AbstractUser):
    """Extended user with country office and role assignments"""
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True)
    position = models.CharField(max_length=200, blank=True)
    profile_photo = models.ImageField(upload_to='profiles/', blank=True, null=True)
    is_global_admin = models.BooleanField(default=False, help_text='Can access all country offices')
    primary_country_office = models.ForeignKey(
        CountryOffice, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='primary_users'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']

    def __str__(self):
        return f"{self.get_full_name()} ({self.email})"

    def get_country_offices(self):
        if self.is_global_admin:
            return CountryOffice.objects.filter(is_active=True)
        return CountryOffice.objects.filter(
            user_access__user=self, user_access__is_active=True
        ).distinct()

    def has_module_permission(self, module, action, country_office=None):
        if self.is_superuser or self.is_global_admin:
            return True
        qs = self.user_access.filter(is_active=True)
        if country_office:
            qs = qs.filter(country_office=country_office)
        role_ids = qs.values_list('role_id', flat=True)
        return ModulePermission.objects.filter(
            role_id__in=role_ids, module=module, action=action
        ).exists()


class UserCountryAccess(models.Model):
    """Links users to country offices with specific roles"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_access')
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE, related_name='user_access')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_access')
    granted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='granted_access'
    )
    unit = models.ForeignKey(
        'projects.ProgrammeUnit',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='member_access',
        help_text='Leave blank for country-office-level access (e.g. central '
                    'M&E office, CO admin). Set to a unit to restrict this '
                    'user to that unit only.',
    )
    is_active = models.BooleanField(default=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ['user', 'country_office', 'role', 'unit']

    def __str__(self):
        return f"{self.user} → {self.country_office} [{self.role.name}]"


class ActivityLog(models.Model):
    """Audit trail"""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    country_office = models.ForeignKey(CountryOffice, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50)
    module = models.CharField(max_length=50)
    object_id = models.CharField(max_length=50, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user} - {self.action} - {self.timestamp}"


class MERoleConfig(models.Model):
    """
    Admin-editable mapping of "logical M&E roles" (admin, M&E officer,
    tracker editor, etc.) to the module:action permissions that grant them.

    Why: previously is_me_officer() was hardcoded to check
    monitoring:approve. That's fragile — different COs may use different
    role schemes. This table lets the admin pick which permissions count.

    A user is treated as having the logical role if they have ANY of the
    triggering permissions in the relevant country office. Country-office
    scope is applied at query time, not stored here, so a single config row
    applies system-wide.
    """

    LOGICAL_ROLE_CHOICES = [
        ('admin', 'Country-Office Administrator'),
        ('me_officer', 'M&E Officer'),
        ('tracker_editor', 'Tracker Editor'),
        ('comment_author', 'Comment Author'),
    ]

    logical_role = models.CharField(
        max_length=30,
        choices=LOGICAL_ROLE_CHOICES,
        unique=True,
        help_text='Internal role name used by permission checks.',
    )
    label = models.CharField(
        max_length=100,
        help_text='Display label shown in role-management UI.',
    )
    description = models.TextField(
        blank=True,
        help_text='What this logical role can do, in plain language.',
    )
    triggering_permissions = models.JSONField(
        default=list,
        help_text=(
            'List of "module:action" strings. A user with ANY of these '
            'permissions in a country office is considered to hold this '
            'logical role within that CO. Example: '
            '["monitoring:approve", "users:admin"].'
        ),
    )
    co_level_only = models.BooleanField(
        default=False,
        help_text=(
            'If true, the user must have CO-level access (UserCountryAccess '
            'with unit=NULL) to be granted this logical role. Use for roles '
            'that should never be unit-scoped, like the central M&E officer '
            'or the country-office tracker editor.'
        ),
    )
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['logical_role']
        verbose_name = 'M&E role configuration'
        verbose_name_plural = 'M&E role configurations'

    def __str__(self):
        return f'{self.label} ({self.logical_role})'

    @classmethod
    def defaults(cls):
        """Seed values used by the migration if no config exists yet."""
        return [
            {
                'logical_role': 'admin',
                'label': 'Country-Office Administrator',
                'description': (
                    'Full access to all data, projects, users, and settings '
                    'within the country office.'
                ),
                'triggering_permissions': ['users:admin', 'admin:admin'],
                'co_level_only': True,
            },
            {
                'logical_role': 'me_officer',
                'label': 'M&E Officer',
                'description': (
                    'Central M&E function. Can approve indicator data, run '
                    'verifications, and update the tracker for any unit.'
                ),
                'triggering_permissions': ['monitoring:approve'],
                'co_level_only': True,
            },
            {
                'logical_role': 'tracker_editor',
                'label': 'Tracker Editor',
                'description': (
                    'Can update reporting status on the tracker. CO-level '
                    'editors see the whole CO; unit-attached editors see '
                    'only their unit.'
                ),
                'triggering_permissions': ['reporting:edit', 'monitoring:edit'],
                'co_level_only': False,
            },
            {
                'logical_role': 'comment_author',
                'label': 'Comment Author',
                'description': 'Can post comments on indicator data and verifications.',
                'triggering_permissions': ['monitoring:view', 'reporting:view'],
                'co_level_only': False,
            },
        ]
