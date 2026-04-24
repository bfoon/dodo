from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.contrib import messages
from .models import User, CountryOffice, Role, UserCountryAccess, ModulePermission
from django import forms


class UserLoginForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address', 'autofocus': True}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}))


class CustomLoginView(View):
    template_name = 'accounts/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard:home')
        return render(request, self.template_name, {'form': UserLoginForm()})

    def post(self, request):
        form = UserLoginForm(request.POST)
        if form.is_valid():
            user = authenticate(request, username=form.cleaned_data['email'], password=form.cleaned_data['password'])
            if user:
                login(request, user)
                return redirect(request.GET.get('next', 'dashboard:home'))
            messages.error(request, 'Invalid email or password.')
        return render(request, self.template_name, {'form': form})


class ProfileView(LoginRequiredMixin, View):
    def get(self, request):
        accesses = request.user.user_access.filter(is_active=True).select_related('country_office', 'role')
        return render(request, 'accounts/profile.html', {'accesses': accesses})


class SwitchOfficeView(LoginRequiredMixin, View):
    def post(self, request, co_id):
        co = get_object_or_404(CountryOffice, pk=co_id, is_active=True)
        if request.user.is_global_admin or request.user.user_access.filter(country_office=co, is_active=True).exists():
            request.session['active_country_office_id'] = co.pk
            messages.success(request, f'Switched to {co.name}')
        else:
            messages.error(request, 'Access denied.')
        return redirect(request.META.get('HTTP_REFERER', 'dashboard:home'))


class UserListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        if request.user.is_global_admin:
            users = User.objects.all().select_related('primary_country_office')
        elif co:
            users = User.objects.filter(user_access__country_office=co, user_access__is_active=True).distinct()
        else:
            users = User.objects.none()
        return render(request, 'accounts/user_list.html', {'users': users})


class UserCreateView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'accounts/user_form.html', {
            'country_offices': CountryOffice.objects.filter(is_active=True),
            'roles': Role.objects.filter(is_active=True),
        })

    def post(self, request):
        try:
            user = User.objects.create_user(
                email=request.POST['email'], username=request.POST['email'],
                first_name=request.POST.get('first_name', ''), last_name=request.POST.get('last_name', ''),
                password=request.POST.get('password', 'UNDP@2026!'),
                position=request.POST.get('position', ''),
            )
            co_id, role_id = request.POST.get('country_office'), request.POST.get('role')
            if co_id and role_id:
                co = CountryOffice.objects.get(pk=co_id)
                role = Role.objects.get(pk=role_id)
                user.primary_country_office = co
                user.save()
                UserCountryAccess.objects.create(user=user, country_office=co, role=role, granted_by=request.user)
            messages.success(request, f'User {user.get_full_name()} created.')
            return redirect('accounts:user_list')
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('accounts:user_create')


class UserAccessView(LoginRequiredMixin, View):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return render(request, 'accounts/user_access.html', {
            'target_user': user,
            'accesses': user.user_access.filter(is_active=True).select_related('country_office', 'role'),
            'country_offices': CountryOffice.objects.filter(is_active=True),
            'roles': Role.objects.filter(is_active=True),
        })

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if request.POST.get('action') == 'grant':
            co = get_object_or_404(CountryOffice, pk=request.POST.get('country_office'))
            role = get_object_or_404(Role, pk=request.POST.get('role'))
            UserCountryAccess.objects.get_or_create(user=user, country_office=co, role=role,
                defaults={'granted_by': request.user, 'is_active': True})
            messages.success(request, 'Access granted.')
        elif request.POST.get('action') == 'revoke':
            UserCountryAccess.objects.filter(pk=request.POST.get('access_id')).update(is_active=False)
            messages.success(request, 'Access revoked.')
        return redirect('accounts:user_access', pk=pk)


class RoleListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        roles = Role.objects.filter(country_office=co).prefetch_related('permissions') if co else Role.objects.all()
        return render(request, 'accounts/role_list.html', {'roles': roles})


class RoleCreateView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'accounts/role_form.html', {
            'country_offices': CountryOffice.objects.filter(is_active=True),
            'modules': ModulePermission.MODULE_CHOICES,
            'actions': ModulePermission.ACTION_CHOICES,
        })

    def post(self, request):
        import re
        co = get_object_or_404(CountryOffice, pk=request.POST.get('country_office'))
        code = re.sub(r'[^a-z0-9_]', '_', request.POST['name'].lower())
        role, created = Role.objects.get_or_create(code=code, country_office=co,
            defaults={'name': request.POST['name'], 'description': request.POST.get('description', '')})
        if created:
            for key in request.POST:
                if key.startswith('perm__'):
                    parts = key.split('__')
                    if len(parts) == 3:
                        ModulePermission.objects.get_or_create(role=role, module=parts[1], action=parts[2])
            messages.success(request, f'Role "{role.name}" created.')
        else:
            messages.warning(request, 'Role already exists.')
        return redirect('accounts:role_list')


class RolePermissionsView(LoginRequiredMixin, View):
    def get(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        return render(request, 'accounts/role_permissions.html', {
            'role': role, 'perms': role.permissions.all(),
            'modules': ModulePermission.MODULE_CHOICES, 'actions': ModulePermission.ACTION_CHOICES,
        })
