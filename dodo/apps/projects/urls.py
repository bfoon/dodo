from django.urls import path
from . import views

app_name = 'projects'

urlpatterns = [
    path('', views.ProjectListView.as_view(), name='list'),
    path('create/', views.ProjectCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ProjectDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.ProjectEditView.as_view(), name='edit'),
    path('<int:pk>/status/', views.UpdateProjectStatusView.as_view(), name='update_status'),
    path('reporting-cycles/', views.ReportingCycleListView.as_view(), name='cycles'),
    path('tracker/', views.ReportingTrackerView.as_view(), name='tracker'),
    path('donor-timelines/', views.DonorTimelineView.as_view(), name='donor_timelines'),
    path('cpd/', views.CPDFrameworkView.as_view(), name='cpd'),
]
