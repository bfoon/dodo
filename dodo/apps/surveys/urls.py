from django.urls import path
from . import views

app_name = 'surveys'

urlpatterns = [
    path('', views.SurveyListView.as_view(), name='list'),
    path('dashboard/', views.SurveyDashboardView.as_view(), name='dashboard'),
    path('create/', views.SurveyCreateView.as_view(), name='create'),
    path('<int:pk>/', views.SurveyDetailView.as_view(), name='detail'),
    path('<int:pk>/builder/', views.SurveyBuilderView.as_view(), name='builder'),
    path('<int:pk>/respond/', views.SurveyResponseView.as_view(), name='respond'),
    path('<int:pk>/results/', views.SurveyResultsView.as_view(), name='results'),
    path('<int:pk>/questions/add/', views.AddQuestionView.as_view(), name='add_question'),
    path('<int:pk>/questions/reorder/', views.ReorderQuestionsView.as_view(), name='reorder_questions'),
    path('questions/<int:pk>/delete/', views.DeleteQuestionView.as_view(), name='delete_question'),
    path('<int:pk>/export/', views.SurveyExportView.as_view(), name='export'),
]