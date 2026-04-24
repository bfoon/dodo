from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    # Notification center
    path('', views.NotificationCenterView.as_view(), name='center'),
    path('<int:pk>/read/', views.MarkNotificationReadView.as_view(), name='mark_read'),
    path('mark-all-read/', views.MarkAllReadView.as_view(), name='mark_all_read'),

    # Deadline templates
    path('templates/', views.DeadlineTemplateListView.as_view(), name='template_list'),
    path('templates/create/', views.DeadlineTemplateCreateView.as_view(), name='template_create'),
    path('templates/<int:pk>/edit/', views.DeadlineTemplateEditView.as_view(), name='template_edit'),

    # Deadline schedules
    path('deadlines/', views.DeadlineScheduleView.as_view(), name='deadlines'),
    path('deadlines/generate/', views.GenerateDeadlinesView.as_view(), name='deadline_generate'),
    path('deadlines/<int:pk>/edit/', views.DeadlineEditView.as_view(), name='deadline_edit'),

    # Delegation
    path('delegations/', views.DelegationListView.as_view(), name='delegations'),
    path('delegations/new/', views.DelegateReportView.as_view(), name='delegate'),
    path('delegations/<int:pk>/revoke/', views.RevokeDelegationView.as_view(), name='revoke_delegation'),

    # Data access grants
    path('grants/', views.AccessGrantListView.as_view(), name='grants'),
    path('grants/new/', views.GrantAccessView.as_view(), name='grant'),
    path('grants/<int:pk>/revoke/', views.RevokeGrantView.as_view(), name='revoke_grant'),

    # Unit head management & dashboard
    path('unit-heads/', views.UnitHeadManagementView.as_view(), name='unit_heads'),
    path('unit-head-dashboard/', views.UnitHeadDashboardView.as_view(), name='unit_head_dashboard'),
]
