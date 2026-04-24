from django import forms
from apps.accounts.models import User
from apps.projects.models import Project, CPDIndicator
from .models import (
    MonitoringVisit, OutputVerification,
    IndicatorAchievement, ProjectIndicatorAchievement,
)


class MonitoringVisitForm(forms.ModelForm):
    """Create/edit a monitoring visit."""

    conducted_by = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('first_name', 'last_name', 'email'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = MonitoringVisit
        fields = [
            'project', 'visit_type', 'visit_date', 'location',
            'purpose', 'findings', 'recommendations', 'follow_up_actions',
            'conducted_by', 'attachments',
        ]
        widgets = {
            'project': forms.Select(attrs={'class': 'form-select'}),
            'visit_type': forms.Select(attrs={'class': 'form-select'}),
            'visit_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'purpose': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'findings': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'recommendations': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'follow_up_actions': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, country_office=None, **kwargs):
        super().__init__(*args, **kwargs)
        if country_office is not None:
            self.fields['project'].queryset = Project.objects.filter(country_office=country_office)
        self.fields['project'].empty_label = '— Select a project —'


class OutputVerificationUpdateForm(forms.ModelForm):
    """Update the status and notes of an output verification."""

    class Meta:
        model = OutputVerification
        fields = ['status', 'verification_notes', 'verification_period',
                  'field_verification_dates', 'documentation_review_dates',
                  'validation_meeting_dates', 'final_report_due']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'verification_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'verification_period': forms.TextInput(attrs={'class': 'form-control'}),
            'field_verification_dates': forms.TextInput(attrs={'class': 'form-control'}),
            'documentation_review_dates': forms.TextInput(attrs={'class': 'form-control'}),
            'validation_meeting_dates': forms.TextInput(attrs={'class': 'form-control'}),
            'final_report_due': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class IndicatorAchievementForm(forms.ModelForm):
    """Record a CPD indicator achievement for a given year/quarter."""

    class Meta:
        model = IndicatorAchievement
        fields = ['year', 'quarter', 'achieved_value', 'notes', 'is_cumulative']
        widgets = {
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2020, 'max': 2040}),
            'quarter': forms.Select(attrs={'class': 'form-select'}),
            'achieved_value': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class ProjectIndicatorAchievementForm(forms.ModelForm):
    """Record a project-level indicator achievement."""

    class Meta:
        model = ProjectIndicatorAchievement
        fields = ['year', 'quarter', 'achieved_value', 'narrative',
                  'challenges', 'recommendations', 'evidence_file']
        widgets = {
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2020, 'max': 2040}),
            'quarter': forms.Select(attrs={'class': 'form-select'}),
            'achieved_value': forms.TextInput(attrs={'class': 'form-control'}),
            'narrative': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'challenges': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'recommendations': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }