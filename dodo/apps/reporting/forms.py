from django import forms
from apps.projects.models import Project, ProgrammeUnit


QUARTER_CHOICES = [
    ('Q1', 'Q1'), ('Q2', 'Q2'), ('Q3', 'Q3'), ('Q4', 'Q4'),
]


class ProgressReportFilterForm(forms.Form):
    """Filter for the quarterly progress report."""
    year = forms.IntegerField(
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'min': 2020, 'max': 2040,
        }),
    )
    quarter = forms.ChoiceField(
        choices=QUARTER_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    unit = forms.ModelChoiceField(
        queryset=ProgrammeUnit.objects.none(),
        required=False,
        empty_label='All units',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )

    def __init__(self, *args, country_office=None, **kwargs):
        super().__init__(*args, **kwargs)
        if country_office is not None:
            self.fields['unit'].queryset = ProgrammeUnit.objects.filter(
                country_office=country_office, is_active=True
            )


class IndicatorReportFilterForm(forms.Form):
    """Filter for the indicator achievements report."""
    year = forms.IntegerField(
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'min': 2020, 'max': 2040,
        }),
    )
    tier = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All tiers'),
            ('impact', 'Impact'),
            ('outcome', 'Outcome'),
            ('output', 'Output'),
        ],
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )


class VerificationReportFilterForm(forms.Form):
    """Filter for the output verification report."""
    status = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All statuses'),
            ('pending', 'Pending'),
            ('field_verification', 'Field Verification'),
            ('documentation_review', 'Documentation Review'),
            ('validation_meeting', 'Validation Meeting'),
            ('completed', 'Completed'),
            ('not_applicable', 'Not Applicable'),
        ],
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    year = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'min': 2020, 'max': 2040,
        }),
    )