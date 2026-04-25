from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views import View
from django.contrib import messages
from django.db.models import Q

from .forms import (
    LoginForm, UserForm, UserAccessGrantForm,
    RoleForm, RolePermissionsForm,
    ProfileForm, PasswordChangeForm,
)
from .models import (
    User, CountryOffice, Role, UserCountryAccess, ModulePermission,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _can_manage_users(user):
    """Superusers, global admins, and (per-CO) anyone with users:edit."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_global_admin:
        return True
    return ModulePermission.objects.filter(
        role__user_access__user=user,
        role__user_access__is_active=True,
        module='users', action='edit',
    ).exists()


class UserManagerRequiredMixin(UserPassesTestMixin):
    raise_exception = True

    def test_func(self):
        return _can_manage_users(self.request.user)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class CustomLoginView(View):
    template_name = 'accounts/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard:home')
        return render(request, self.template_name, {'form': LoginForm()})

    def post(self, request):
        form = LoginForm(request.POST, request=request)
        if form.is_valid():
            login(request, form.user)
            return redirect(request.GET.get('next', 'dashboard:home'))
        return render(request, self.template_name, {'form': form})


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class ProfileView(LoginRequiredMixin, View):
    def get(self, request):
        accesses = (
            request.user.user_access.filter(is_active=True)
            .select_related('country_office', 'role')
        )
        return render(request, 'accounts/profile.html', {
            'accesses': accesses,
            'profile_form': ProfileForm(instance=request.user),
            'password_form': PasswordChangeForm(user=request.user),
        })

    def post(self, request):
        action = request.POST.get('action')
        if action == 'update_profile':
            form = ProfileForm(request.POST, request.FILES, instance=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated.')
            else:
                messages.error(request, 'Please fix the errors below.')
                return render(request, 'accounts/profile.html', {
                    'accesses': request.user.user_access.filter(is_active=True)
                        .select_related('country_office', 'role'),
                    'profile_form': form,
                    'password_form': PasswordChangeForm(user=request.user),
                })

        elif action == 'change_password':
            form = PasswordChangeForm(request.POST, user=request.user)
            if form.is_valid():
                form.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, 'Password changed.')
            else:
                messages.error(request, 'Please fix the errors below.')
                return render(request, 'accounts/profile.html', {
                    'accesses': request.user.user_access.filter(is_active=True)
                        .select_related('country_office', 'role'),
                    'profile_form': ProfileForm(instance=request.user),
                    'password_form': form,
                })
        return redirect('accounts:profile')


class SwitchOfficeView(LoginRequiredMixin, View):
    def post(self, request, co_id):
        co = get_object_or_404(CountryOffice, pk=co_id, is_active=True)
        if request.user.is_global_admin or request.user.user_access.filter(
            country_office=co, is_active=True
        ).exists():
            request.session['active_country_office_id'] = co.pk
            messages.success(request, f'Switched to {co.name}')
        else:
            messages.error(request, 'Access denied.')
        return redirect(request.META.get('HTTP_REFERER', 'dashboard:home'))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UserListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        q = (request.GET.get('q') or '').strip()

        if request.user.is_global_admin:
            users = User.objects.all().select_related('primary_country_office')
        elif co:
            users = (
                User.objects.filter(
                    user_access__country_office=co, user_access__is_active=True,
                ).distinct().select_related('primary_country_office')
            )
        else:
            users = User.objects.none()

        if q:
            users = users.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q) |
                Q(email__icontains=q) | Q(position__icontains=q)
            )

        return render(request, 'accounts/user_list.html', {
            'users': users.order_by('first_name', 'last_name'),
            'q': q,
            'can_manage': _can_manage_users(request.user),
        })


class UserCreateView(UserManagerRequiredMixin, LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'accounts/user_form.html', {
            'form': UserForm(),
            'access_form': UserAccessGrantForm(),
            'mode': 'create',
        })

    def post(self, request):
        form = UserForm(request.POST, request.FILES)
        access_form = UserAccessGrantForm(request.POST)

        if form.is_valid():
            user = form.save()
            # Optional: grant initial access if both fields filled
            if access_form.is_valid():
                co = access_form.cleaned_data.get('country_office')
                role = access_form.cleaned_data.get('role')
                if co and role:
                    user.primary_country_office = co
                    user.save()
                    UserCountryAccess.objects.create(
                        user=user, country_office=co, role=role,
                        granted_by=request.user,
                        notes=access_form.cleaned_data.get('notes', ''),
                    )
            messages.success(request, f'User {user.get_full_name()} created.')
            return redirect('accounts:user_list')

        messages.error(request, 'Please fix the errors below.')
        return render(request, 'accounts/user_form.html', {
            'form': form,
            'access_form': access_form,
            'mode': 'create',
        })


class UserEditView(UserManagerRequiredMixin, LoginRequiredMixin, View):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return render(request, 'accounts/user_form.html', {
            'form': UserForm(instance=user),
            'target_user': user,
            'mode': 'edit',
        })

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        form = UserForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, 'User updated.')
            return redirect('accounts:user_list')
        return render(request, 'accounts/user_form.html', {
            'form': form, 'target_user': user, 'mode': 'edit',
        })


class UserAccessView(UserManagerRequiredMixin, LoginRequiredMixin, View):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return render(request, 'accounts/user_access.html', {
            'target_user': user,
            'accesses': user.user_access.filter(is_active=True)
                .select_related('country_office', 'role'),
            'revoked_accesses': user.user_access.filter(is_active=False)
                .select_related('country_office', 'role'),
            'access_form': UserAccessGrantForm(),
        })

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        action = request.POST.get('action')

        if action == 'grant':
            form = UserAccessGrantForm(request.POST)
            if form.is_valid():
                obj, created = UserCountryAccess.objects.get_or_create(
                    user=user,
                    country_office=form.cleaned_data['country_office'],
                    role=form.cleaned_data['role'],
                    defaults={
                        'granted_by': request.user,
                        'is_active': True,
                        'notes': form.cleaned_data.get('notes', ''),
                    },
                )
                if not created:
                    obj.is_active = True
                    if form.cleaned_data.get('notes'):
                        obj.notes = form.cleaned_data['notes']
                    obj.save()
                messages.success(request, 'Access granted.')
            else:
                messages.error(request, 'Please pick both a country office and a role.')

        elif action == 'revoke':
            UserCountryAccess.objects.filter(
                pk=request.POST.get('access_id'), user=user,
            ).update(is_active=False)
            messages.success(request, 'Access revoked.')

        elif action == 'reactivate':
            UserCountryAccess.objects.filter(
                pk=request.POST.get('access_id'), user=user,
            ).update(is_active=True)
            messages.success(request, 'Access reactivated.')

        return redirect('accounts:user_access', pk=pk)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class RoleListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        if request.user.is_global_admin:
            roles = Role.objects.all()
        elif co:
            roles = Role.objects.filter(country_office=co)
        else:
            roles = Role.objects.none()
        roles = (
            roles.select_related('country_office')
                 .prefetch_related('permissions')
                 .order_by('country_office__name', 'name')
        )
        return render(request, 'accounts/role_list.html', {
            'roles': roles,
            'can_manage': _can_manage_users(request.user),
        })


class RoleCreateView(UserManagerRequiredMixin, LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'accounts/role_form.html', {
            'form': RoleForm(),
            'modules': ModulePermission.MODULE_CHOICES,
            'actions': ModulePermission.ACTION_CHOICES,
            'mode': 'create',
        })

    def post(self, request):
        import re
        form = RoleForm(request.POST)
        if not form.is_valid():
            return render(request, 'accounts/role_form.html', {
                'form': form,
                'modules': ModulePermission.MODULE_CHOICES,
                'actions': ModulePermission.ACTION_CHOICES,
                'mode': 'create',
            })

        role = form.save(commit=False)
        role.code = re.sub(r'[^a-z0-9_]+', '_', role.name.lower()).strip('_')

        # Avoid collision: append a suffix if a role with same code in same CO exists
        base_code = role.code
        i = 2
        while Role.objects.filter(code=role.code, country_office=role.country_office).exists():
            role.code = f'{base_code}_{i}'
            i += 1
        role.save()

        # Wire up permissions from `perm__module__action` checkboxes
        added = 0
        for key in request.POST:
            if key.startswith('perm__'):
                parts = key.split('__')
                if len(parts) == 3:
                    _, module, action = parts
                    ModulePermission.objects.get_or_create(role=role, module=module, action=action)
                    added += 1

        messages.success(
            request,
            f'Role "{role.name}" created with {added} permission{"s" if added != 1 else ""}.'
        )
        return redirect('accounts:role_list')


class RolePermissionsView(UserManagerRequiredMixin, LoginRequiredMixin, View):
    def get(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        existing = set(role.permissions.values_list('module', 'action'))
        return render(request, 'accounts/role_permissions.html', {
            'role': role,
            'existing': existing,
            'modules': ModulePermission.MODULE_CHOICES,
            'actions': ModulePermission.ACTION_CHOICES,
            'user_count': role.user_access.filter(is_active=True).count(),
        })

    def post(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        form = RolePermissionsForm(request.POST, role=role)
        if form.is_valid():
            added, removed = form.save()
            if added or removed:
                bits = []
                if added: bits.append(f'+{added} added')
                if removed: bits.append(f'-{removed} removed')
                messages.success(request, f'Permissions updated ({", ".join(bits)}).')
            else:
                messages.info(request, 'No changes.')
        else:
            messages.error(request, 'Could not update permissions.')
        return redirect('accounts:role_permissions', pk=pk)


class RoleDeleteView(UserManagerRequiredMixin, LoginRequiredMixin, View):
    def post(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        if role.user_access.filter(is_active=True).exists():
            messages.error(
                request,
                f'Cannot delete "{role.name}" — it is still assigned to users.'
            )
        else:
            name = role.name
            role.delete()
            messages.success(request, f'Role "{name}" deleted.')
        return redirect('accounts:role_list')