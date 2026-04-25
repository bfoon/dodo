from django import forms
from .models import (
    Project, ProgrammeUnit, ProjectReportingStatus, ReportingCycle,
    DonorReportingTimeline,
    CPDFramework, CPDOutcome, CPDIndicator,
)


# ---------------------------------------------------------------------------
# Existing forms (kept as-is)
# ---------------------------------------------------------------------------

class ProjectForm(forms.ModelForm):
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
            'reporting_timeline': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 1 Jan – 31 Mar',
            }),
            'submission_deadline': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'programme_review_dates': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 5–10 Apr',
            }),
            'pmsu_review_dates': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 11–15 Apr',
            }),
            'final_clearance_dates': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 16–20 Apr',
            }),
            'final_report_due': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


class ProjectFilterForm(forms.Form):
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


# ---------------------------------------------------------------------------
# New forms — Donor Timelines + CPD
# ---------------------------------------------------------------------------

class DonorReportingTimelineForm(forms.ModelForm):
    """Add/edit a donor reporting timeline. country_office is set in the view."""

    class Meta:
        model = DonorReportingTimeline
        fields = [
            'project', 'donor', 'reporting_frequency',
            'period_1', 'internal_draft_1', 'programme_review_1',
            'pmsu_review_1', 'final_submission_1',
            'period_2', 'internal_draft_2', 'programme_review_2',
            'pmsu_review_2', 'final_submission_2',
            'notes',
        ]
        widgets = {
            'project': forms.Select(attrs={'class': 'form-select'}),
            'donor': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. EU, GEF, PBF'}),
            'reporting_frequency': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'e.g. Quarterly, Biannual, Annual',
            }),
            'period_1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Jan–Jun'}),
            'internal_draft_1': forms.TextInput(attrs={'class': 'form-control'}),
            'programme_review_1': forms.TextInput(attrs={'class': 'form-control'}),
            'pmsu_review_1': forms.TextInput(attrs={'class': 'form-control'}),
            'final_submission_1': forms.TextInput(attrs={'class': 'form-control'}),
            'period_2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Jul–Dec'}),
            'internal_draft_2': forms.TextInput(attrs={'class': 'form-control'}),
            'programme_review_2': forms.TextInput(attrs={'class': 'form-control'}),
            'pmsu_review_2': forms.TextInput(attrs={'class': 'form-control'}),
            'final_submission_2': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, country_office=None, **kwargs):
        super().__init__(*args, **kwargs)
        if country_office is not None:
            self.fields['project'].queryset = Project.objects.filter(
                country_office=country_office
            ).order_by('title')
        self.fields['project'].empty_label = '— Select a project —'


class CPDFrameworkForm(forms.ModelForm):
    """Add/edit a CPD Framework. country_office is set in the view."""

    class Meta:
        model = CPDFramework
        fields = ['title', 'year_start', 'year_end', 'description', 'is_active']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. UNDP The Gambia Country Programme',
            }),
            'year_start': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 2000, 'max': 2050,
            }),
            'year_end': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 2000, 'max': 2050,
            }),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned = super().clean()
        ys, ye = cleaned.get('year_start'), cleaned.get('year_end')
        if ys and ye and ye < ys:
            self.add_error('year_end', 'End year must be after start year.')
        return cleaned


class CPDOutcomeForm(forms.ModelForm):
    """Add/edit an outcome. Both framework and programme_unit are scoped to CO."""

    class Meta:
        model = CPDOutcome
        fields = ['framework', 'programme_unit', 'code', 'tier',
                  'title', 'sp_outcome', 'order']
        widgets = {
            'framework': forms.Select(attrs={'class': 'form-select'}),
            'programme_unit': forms.Select(attrs={'class': 'form-select'}),
            'code': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'e.g. Outcome 1.1',
            }),
            'tier': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'sp_outcome': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Linked Strategic Plan outcome',
            }),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }

    def __init__(self, *args, country_office=None, **kwargs):
        super().__init__(*args, **kwargs)
        if country_office is not None:
            self.fields['framework'].queryset = CPDFramework.objects.filter(
                country_office=country_office,
            ).order_by('-is_active', '-year_start')
            self.fields['programme_unit'].queryset = ProgrammeUnit.objects.filter(
                country_office=country_office, is_active=True,
            ).order_by('name')
        self.fields['framework'].empty_label = '— Select a framework —'
        self.fields['programme_unit'].empty_label = '— Optional —'
        self.fields['programme_unit'].required = False
        self.fields['sp_outcome'].required = False


class CPDIndicatorForm(forms.ModelForm):
    """Add/edit an indicator under a CPD outcome (CO-scoped)."""

    class Meta:
        model = CPDIndicator
        fields = [
            'outcome', 'code', 'description',
            'sp_indicator', 'sp_data_source', 'cpd_data_source',
            'frequency', 'responsible_institution',
            'baseline', 'end_target',
            'means_of_verification', 'remarks',
        ]
        widgets = {
            'outcome': forms.Select(attrs={'class': 'form-select'}),
            'code': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'e.g. 1.1.a',
            }),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'sp_indicator': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'sp_data_source': forms.TextInput(attrs={'class': 'form-control'}),
            'cpd_data_source': forms.TextInput(attrs={'class': 'form-control'}),
            'frequency': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'e.g. Annual',
            }),
            'responsible_institution': forms.TextInput(attrs={'class': 'form-control'}),
            'baseline': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'end_target': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'means_of_verification': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, country_office=None, **kwargs):
        super().__init__(*args, **kwargs)
        if country_office is not None:
            self.fields['outcome'].queryset = CPDOutcome.objects.filter(
                framework__country_office=country_office,
            ).select_related('framework').order_by('framework_id', 'order', 'code')
        self.fields['outcome'].empty_label = '— Select an outcome —'
        # Most descriptive metadata is optional
        for f in ('sp_indicator', 'sp_data_source', 'cpd_data_source',
                  'frequency', 'responsible_institution',
                  'baseline', 'end_target',
                  'means_of_verification', 'remarks'):
            self.fields[f].required = False