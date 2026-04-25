from django.urls import path
from . import views

app_name = 'projects'

urlpatterns = [
    # Projects
    path('', views.ProjectListView.as_view(), name='list'),
    path('create/', views.ProjectCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ProjectDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.ProjectEditView.as_view(), name='edit'),
    path('<int:pk>/status/', views.UpdateProjectStatusView.as_view(), name='update_status'),

    # Reporting cycles (CRUD)
    path('reporting-cycles/', views.ReportingCycleListView.as_view(), name='cycles'),
    path('reporting-cycles/create/', views.ReportingCycleCreateView.as_view(), name='cycle_create'),
    path('reporting-cycles/<int:pk>/edit/', views.ReportingCycleEditView.as_view(), name='cycle_edit'),
    path('reporting-cycles/<int:pk>/delete/', views.ReportingCycleDeleteView.as_view(), name='cycle_delete'),

    # Tracker
    path('tracker/', views.ReportingTrackerView.as_view(), name='tracker'),

    # Donor reporting timelines (CRUD)
    path('donor-timelines/', views.DonorTimelineView.as_view(), name='donor_timelines'),
    path('donor-timelines/create/', views.DonorTimelineCreateView.as_view(), name='donor_timeline_create'),
    path('donor-timelines/<int:pk>/edit/', views.DonorTimelineEditView.as_view(), name='donor_timeline_edit'),
    path('donor-timelines/<int:pk>/delete/', views.DonorTimelineDeleteView.as_view(), name='donor_timeline_delete'),

    # CPD framework (CRUD on frameworks, outcomes, indicators)
    path('cpd/', views.CPDFrameworkView.as_view(), name='cpd'),
    path('cpd/framework/create/', views.CPDFrameworkCreateView.as_view(), name='cpd_framework_create'),
    path('cpd/framework/<int:pk>/edit/', views.CPDFrameworkEditView.as_view(), name='cpd_framework_edit'),
    path('cpd/framework/<int:pk>/delete/', views.CPDFrameworkDeleteView.as_view(), name='cpd_framework_delete'),
    path('cpd/outcome/create/', views.CPDOutcomeCreateView.as_view(), name='cpd_outcome_create'),
    path('cpd/outcome/<int:pk>/edit/', views.CPDOutcomeEditView.as_view(), name='cpd_outcome_edit'),
    path('cpd/outcome/<int:pk>/delete/', views.CPDOutcomeDeleteView.as_view(), name='cpd_outcome_delete'),
    path('cpd/indicator/create/', views.CPDIndicatorCreateView.as_view(), name='cpd_indicator_create'),
    path('cpd/indicator/<int:pk>/edit/', views.CPDIndicatorEditView.as_view(), name='cpd_indicator_edit'),
    path('cpd/indicator/<int:pk>/delete/', views.CPDIndicatorDeleteView.as_view(), name='cpd_indicator_delete'),
]