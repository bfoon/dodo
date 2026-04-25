from django.urls import path
from . import views

app_name = 'reporting'

urlpatterns = [
    path('', views.ReportingHomeView.as_view(), name='home'),
    path('progress/', views.ProgressReportView.as_view(), name='progress'),
    path('output-verification/', views.OutputVerificationReportView.as_view(),
         name='verification'),
    path('indicator-achievements/', views.IndicatorAchievementReportView.as_view(),
         name='indicators'),
    path('donor/', views.DonorReportView.as_view(), name='donor'),

    # Single export endpoint — pick format with ?fmt=xlsx (default) or ?fmt=csv
    path('export/<str:report_type>/', views.ExportReportView.as_view(), name='export'),
]