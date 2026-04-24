from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', lambda r: redirect('dashboard:home'), name='home'),
    path('accounts/', include('apps.accounts.urls', namespace='accounts')),
    path('dashboard/', include('apps.dashboard.urls', namespace='dashboard')),
    path('projects/', include('apps.projects.urls', namespace='projects')),
    path('monitoring/', include('apps.monitoring.urls', namespace='monitoring')),
    path('surveys/', include('apps.surveys.urls', namespace='surveys')),
    path('reporting/', include('apps.reporting.urls', namespace='reporting')),
    path('notifications/', include('apps.notifications.urls', namespace='notifications')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
