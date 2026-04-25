from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User, CountryOffice, Role, ModulePermission, UserCountryAccess


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginForm(forms.Form):
    """Email + password login. Authentication happens in clean()."""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Email address',
            'autofocus': True,
            'autocomplete': 'email',
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password',
            'autocomplete': 'current-password',
        }),
    )

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get('email')
        password = cleaned.get('password')
        if email and password:
            self.user = authenticate(self.request, username=email, password=password)
            if self.user is None:
                raise ValidationError('Invalid email or password.')
            if not self.user.is_active:
                raise ValidationError('This account is disabled.')
        return cleaned


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UserForm(forms.ModelForm):
    """Create or edit a user. Password is only used at creation."""
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
        help_text='Leave blank to use the default initial password.',
    )

    class Meta:
        model = User
        fields = [
            'email', 'first_name', 'last_name',
            'phone', 'position', 'profile_photo',
            'primary_country_office', 'is_global_admin', 'is_active',
        ]
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'position': forms.TextInput(attrs={'class': 'form-control'}),
            'profile_photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'primary_country_office': forms.Select(attrs={'class': 'form-select'}),
            'is_global_admin': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['primary_country_office'].queryset = CountryOffice.objects.filter(is_active=True)
        self.fields['primary_country_office'].empty_label = '— Select primary office —'
        self.fields['primary_country_office'].required = False
        # is_global_admin is the conventional Django pattern for staff toggles
        self.fields['is_global_admin'].help_text = 'Grants access across all country offices.'

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('A user with that email already exists.')
        return email

    def clean_password(self):
        pw = self.cleaned_data.get('password', '')
        if pw:
            validate_password(pw)
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        # On creation, mirror the email into the username field (your USERNAME_FIELD is email,
        # but `username` is still required by AbstractUser — we keep it in sync)
        if not user.username:
            user.username = user.email
        password = self.cleaned_data.get('password') or 'UNDP@2026!'
        if not user.pk or password != self.initial.get('password'):
            user.set_password(password)
        if commit:
            user.save()
        return user


class UserAccessGrantForm(forms.Form):
    """Grant a user access to a country office with a specific role."""
    country_office = forms.ModelChoiceField(
        queryset=CountryOffice.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='— Country office —',
    )
    role = forms.ModelChoiceField(
        queryset=Role.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='— Role —',
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2,
                                     'placeholder': 'Why is this access being granted?'}),
    )


# ---------------------------------------------------------------------------
# Roles & Permissions
# ---------------------------------------------------------------------------

class RoleForm(forms.ModelForm):
    """Create or edit a role within a country office."""

    class Meta:
        model = Role
        fields = ['name', 'country_office', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Programme Manager',
            }),
            'country_office': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3,
                'placeholder': 'What does this role typically do?',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['country_office'].queryset = CountryOffice.objects.filter(is_active=True)
        self.fields['country_office'].empty_label = '— Country office —'

    def clean(self):
        # Re-derive the slug code from the name so it stays unique-per-CO
        cleaned = super().clean()
        return cleaned


class RolePermissionsForm(forms.Form):
    """
    Bulk add/remove permissions on a role using a matrix of checkboxes
    keyed `perm__<module>__<action>`.
    """

    def __init__(self, *args, role=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = role
        existing = set()
        if role is not None:
            existing = set(role.permissions.values_list('module', 'action'))

        for module_code, _ in ModulePermission.MODULE_CHOICES:
            for action_code, _ in ModulePermission.ACTION_CHOICES:
                key = f'perm__{module_code}__{action_code}'
                self.fields[key] = forms.BooleanField(
                    required=False,
                    initial=(module_code, action_code) in existing,
                    widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
                )

    def save(self):
        """Persist the matrix to the role. Returns (added, removed) counts."""
        if self.role is None:
            return 0, 0

        wanted = set()
        for key, value in self.cleaned_data.items():
            if not value or not key.startswith('perm__'):
                continue
            _, module, action = key.split('__', 2)
            wanted.add((module, action))

        existing = set(self.role.permissions.values_list('module', 'action'))
        to_add = wanted - existing
        to_remove = existing - wanted

        for module, action in to_add:
            ModulePermission.objects.get_or_create(role=self.role, module=module, action=action)
        for module, action in to_remove:
            ModulePermission.objects.filter(
                role=self.role, module=module, action=action,
            ).delete()

        return len(to_add), len(to_remove)


# ---------------------------------------------------------------------------
# Profile self-edit
# ---------------------------------------------------------------------------

class ProfileForm(forms.ModelForm):
    """A user editing their own profile — limited to safe fields."""

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'position', 'profile_photo']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'position': forms.TextInput(attrs={'class': 'form-control'}),
            'profile_photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


class PasswordChangeForm(forms.Form):
    """Lightweight password change form for the profile page."""
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'current-password'}),
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        pw = self.cleaned_data['current_password']
        if self.user and not self.user.check_password(pw):
            raise ValidationError('Current password is incorrect.')
        return pw

    def clean(self):
        cleaned = super().clean()
        new = cleaned.get('new_password')
        confirm = cleaned.get('confirm_password')
        if new and confirm and new != confirm:
            self.add_error('confirm_password', 'Passwords do not match.')
        if new:
            try:
                validate_password(new, user=self.user)
            except ValidationError as e:
                self.add_error('new_password', e)
        return cleaned

    def save(self):
        if self.user:
            self.user.set_password(self.cleaned_data['new_password'])
            self.user.save()
            return self.user
        return None