from django import forms
from .models import (
    Project, ProgrammeUnit, ProjectReportingStatus, ReportingCycle,
    CPDFramework, CPDOutcome, CPDIndicator,
)


class ProjectForm(forms.ModelForm):
    """Create/edit a project.

    The programme_unit queryset is narrowed at __init__ time based on the active
    country office so users can only assign units within their CO.
    """

    class Meta:
        model = Project
        fields = [
            'pims_id', 'title', 'short_title', 'description',
            'programme_unit',
            'donor', 'donor_type', 'total_budget',
            'start_date', 'end_date', 'status',
            'responsible_person', 'data_source_partner',
            'programme_reviewer', 'pmsu_reviewer', 'final_clearance',
        ]
        widgets = {
            'title': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'pims_id': forms.TextInput(attrs={'class': 'form-control'}),
            'short_title': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 100}),
            'donor': forms.TextInput(attrs={'class': 'form-control'}),
            'donor_type': forms.Select(attrs={'class': 'form-select'}),
            'total_budget': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'programme_unit': forms.Select(attrs={'class': 'form-select'}),
            'responsible_person': forms.TextInput(attrs={'class': 'form-control'}),
            'data_source_partner': forms.TextInput(attrs={'class': 'form-control'}),
            'programme_reviewer': forms.TextInput(attrs={'class': 'form-control'}),
            'pmsu_reviewer': forms.TextInput(attrs={'class': 'form-control'}),
            'final_clearance': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, country_office=None, **kwargs):
        super().__init__(*args, **kwargs)
        if country_office is not None:
            self.fields['programme_unit'].queryset = ProgrammeUnit.objects.filter(
                country_office=country_office, is_active=True
            )
        self.fields['programme_unit'].required = True
        # Nice empty labels
        self.fields['programme_unit'].empty_label = '— Select a unit —'
        self.fields['donor_type'].required = False

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and end < start:
            self.add_error('end_date', 'End date cannot be before start date.')
        return cleaned


class ProjectReportingStatusForm(forms.ModelForm):
    """Update the reporting status of a project within a cycle."""

    class Meta:
        model = ProjectReportingStatus
        fields = ['status', 'notes', 'field_verification_dates',
                  'documentation_review_dates', 'validation_meeting_dates']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'field_verification_dates': forms.TextInput(attrs={'class': 'form-control'}),
            'documentation_review_dates': forms.TextInput(attrs={'class': 'form-control'}),
            'validation_meeting_dates': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ReportingCycleForm(forms.ModelForm):
    """Create or edit a reporting cycle."""

    class Meta:
        model = ReportingCycle
        fields = [
            'year', 'quarter', 'cycle_type',
            'reporting_timeline', 'submission_deadline',
            'programme_review_dates', 'pmsu_review_dates',
            'final_clearance_dates', 'final_report_due',
        ]
        widgets = {
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2020, 'max': 2040}),
            'quarter': forms.Select(attrs={'class': 'form-select'}),
            'cycle_type': forms.Select(attrs={'class': 'form-select'}),
            'reporting_timeline': forms.TextInput(attrs={'class': 'form-control'}),
            'submission_deadline': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'programme_review_dates': forms.TextInput(attrs={'class': 'form-control'}),
            'pmsu_review_dates': forms.TextInput(attrs={'class': 'form-control'}),
            'final_clearance_dates': forms.TextInput(attrs={'class': 'form-control'}),
            'final_report_due': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class ProjectFilterForm(forms.Form):
    """Sidebar / toolbar filter for the project list."""
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All statuses')] + list(Project.STATUS_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    unit = forms.ModelChoiceField(
        required=False,
        queryset=ProgrammeUnit.objects.none(),
        empty_label='All units',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Search title, PIMS ID, donor…',
        }),
    )

    def __init__(self, *args, country_office=None, **kwargs):
        super().__init__(*args, **kwargs)
        if country_office is not None:
            self.fields['unit'].queryset = ProgrammeUnit.objects.filter(
                country_office=country_office, is_active=True
            )