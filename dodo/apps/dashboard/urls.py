from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.DashboardView.as_view(), name='home'),
    path('cluster/<int:unit_id>/', views.ClusterDashboardView.as_view(), name='cluster'),
]
