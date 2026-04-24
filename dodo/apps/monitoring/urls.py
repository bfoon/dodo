from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    path('', views.MonitoringDashboardView.as_view(), name='home'),
    path('indicators/', views.IndicatorListView.as_view(), name='indicators'),
    path('indicators/<int:pk>/data/', views.IndicatorDataEntryView.as_view(), name='indicator_data'),
    path('verification/', views.OutputVerificationListView.as_view(), name='verification'),
    path('verification/<int:pk>/update/', views.UpdateVerificationView.as_view(), name='update_verification'),
    path('visits/', views.MonitoringVisitListView.as_view(), name='visits'),
    path('visits/create/', views.CreateMonitoringVisitView.as_view(), name='create_visit'),
]
