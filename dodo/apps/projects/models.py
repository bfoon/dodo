from django.db import models
from apps.accounts.models import CountryOffice, User


class ProgrammeUnit(models.Model):
    """Thematic clusters/programme units"""
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20)
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE, related_name='programme_units')
    description = models.TextField(blank=True)
    lead = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='led_units')
    is_active = models.BooleanField(default=True)
    color = models.CharField(max_length=7, default='#0077c8')  # UNDP blue
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['code', 'country_office']
        ordering = ['name']

    def __str__(self):
        return f"{self.name} [{self.country_office.code}]"


class CPDFramework(models.Model):
    """Country Programme Document Framework"""
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE, related_name='cpd_frameworks')
    title = models.CharField(max_length=300)
    year_start = models.IntegerField()
    year_end = models.IntegerField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} ({self.year_start}–{self.year_end})"


class CPDOutcome(models.Model):
    """CPD Outcome / Result"""
    framework = models.ForeignKey(CPDFramework, on_delete=models.CASCADE, related_name='outcomes')
    programme_unit = models.ForeignKey(ProgrammeUnit, on_delete=models.SET_NULL, null=True, blank=True)
    code = models.CharField(max_length=20)
    tier = models.CharField(max_length=50, choices=[
        ('impact', 'Impact'), ('outcome', 'Outcome'), ('output', 'Output')
    ])
    title = models.TextField()
    sp_outcome = models.CharField(max_length=200, blank=True, verbose_name='SP Outcome')
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order', 'code']

    def __str__(self):
        return f"{self.code}: {self.title[:80]}"


class CPDIndicator(models.Model):
    """CPD Indicators linked to outcomes"""
    outcome = models.ForeignKey(CPDOutcome, on_delete=models.CASCADE, related_name='indicators')
    code = models.CharField(max_length=30, blank=True)
    description = models.TextField()
    sp_indicator = models.TextField(blank=True, verbose_name='SP Indicator')
    sp_data_source = models.CharField(max_length=200, blank=True)
    cpd_data_source = models.CharField(max_length=200, blank=True)
    frequency = models.CharField(max_length=100, blank=True)
    responsible_institution = models.CharField(max_length=300, blank=True)
    baseline = models.TextField(blank=True)
    end_target = models.TextField(blank=True)
    means_of_verification = models.TextField(blank=True)
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"{self.outcome.code} - {self.description[:60]}"


class Project(models.Model):
    """UNDP Project"""
    STATUS_CHOICES = [
        ('pipeline', 'Pipeline'),
        ('active', 'Active / Ongoing'),
        ('ending', 'Ending'),
        ('closed', 'Closed'),
        ('suspended', 'Suspended'),
    ]
    DONOR_TYPES = [
        ('pbf', 'PBF'),
        ('gef', 'GEF'),
        ('bilateral', 'Bilateral'),
        ('trac', 'TRAC'),
        ('other', 'Other'),
    ]

    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE, related_name='projects')
    programme_unit = models.ForeignKey(ProgrammeUnit, on_delete=models.SET_NULL, null=True, related_name='projects')
    cpd_outcomes = models.ManyToManyField(CPDOutcome, blank=True, related_name='projects')
    cpd_indicators = models.ManyToManyField(CPDIndicator, blank=True, related_name='projects')

    pims_id = models.CharField(max_length=50, blank=True, verbose_name='PIMS ID')
    title = models.CharField(max_length=400)
    short_title = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    donor = models.CharField(max_length=200, blank=True)
    donor_type = models.CharField(max_length=20, choices=DONOR_TYPES, blank=True)
    total_budget = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    project_manager = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='managed_projects')
    data_source_partner = models.CharField(max_length=300, blank=True)
    responsible_person = models.CharField(max_length=200, blank=True)

    programme_reviewer = models.CharField(max_length=200, blank=True)
    pmsu_reviewer = models.CharField(max_length=200, blank=True)
    final_clearance = models.CharField(max_length=200, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['programme_unit', 'title']

    def __str__(self):
        return f"{self.pims_id} {self.title}" if self.pims_id else self.title

    @property
    def display_title(self):
        return self.short_title or (self.title[:80] + '...' if len(self.title) > 80 else self.title)


class ProjectIndicator(models.Model):
    """Project-level indicators"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='indicators')
    cpd_indicator = models.ForeignKey(CPDIndicator, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField()
    unit_of_measure = models.CharField(max_length=100, blank=True)
    baseline = models.CharField(max_length=200, blank=True)
    target = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.project.display_title} - {self.description[:60]}"


class ReportingCycle(models.Model):
    """Quarterly reporting windows"""
    QUARTER_CHOICES = [('Q1', 'Q1'), ('Q2', 'Q2'), ('Q3', 'Q3'), ('Q4', 'Q4')]
    TYPE_CHOICES = [('progress', 'Progress Reporting'), ('verification', 'Output Verification')]

    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE, related_name='reporting_cycles')
    year = models.IntegerField()
    quarter = models.CharField(max_length=2, choices=QUARTER_CHOICES)
    cycle_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    reporting_timeline = models.CharField(max_length=100, blank=True)
    submission_deadline = models.DateField(null=True, blank=True)
    programme_review_dates = models.CharField(max_length=100, blank=True)
    pmsu_review_dates = models.CharField(max_length=100, blank=True)
    final_clearance_dates = models.CharField(max_length=100, blank=True)
    final_report_due = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ['country_office', 'year', 'quarter', 'cycle_type']
        ordering = ['year', 'quarter']

    def __str__(self):
        return f"{self.country_office.code} {self.year} {self.quarter} - {self.get_cycle_type_display()}"


class ProjectReportingStatus(models.Model):
    """Status of each project per reporting cycle"""
    STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('pending', 'Pending'),
        ('under_review', 'Under Review'),
        ('submitted', 'Submitted'),
        ('overdue', 'Overdue'),
        ('not_applicable', 'Not Applicable'),
        ('closed', 'Closed'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='reporting_statuses')
    cycle = models.ForeignKey(ReportingCycle, on_delete=models.CASCADE, related_name='project_statuses')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started')
    field_verification_dates = models.CharField(max_length=100, blank=True)
    documentation_review_dates = models.CharField(max_length=100, blank=True)
    validation_meeting_dates = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['project', 'cycle']

    def __str__(self):
        return f"{self.project.display_title} - {self.cycle} - {self.status}"

    def get_status_color(self):
        colors = {
            'submitted': 'success',
            'under_review': 'info',
            'pending': 'warning',
            'not_started': 'secondary',
            'overdue': 'danger',
            'not_applicable': 'light',
            'closed': 'dark',
        }
        return colors.get(self.status, 'secondary')


class DonorReportingTimeline(models.Model):
    """Donor-specific reporting timelines"""
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='donor_timelines')
    donor = models.CharField(max_length=100)
    reporting_frequency = models.CharField(max_length=50)
    period_1 = models.CharField(max_length=50, blank=True)
    internal_draft_1 = models.CharField(max_length=100, blank=True)
    programme_review_1 = models.CharField(max_length=100, blank=True)
    pmsu_review_1 = models.CharField(max_length=100, blank=True)
    final_submission_1 = models.CharField(max_length=100, blank=True)
    period_2 = models.CharField(max_length=50, blank=True)
    internal_draft_2 = models.CharField(max_length=100, blank=True)
    programme_review_2 = models.CharField(max_length=100, blank=True)
    pmsu_review_2 = models.CharField(max_length=100, blank=True)
    final_submission_2 = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.donor} - {self.project.display_title}"
from django.utils import timezone
from apps.accounts.models import User


class ProjectResponsibility(models.Model):
    """
    Defines WHO is responsible for WHAT on a project.
    Multiple users can have different responsibilities on the same project.
    """
    ROLE_CHOICES = [
        ('manager', 'Project Manager'),
        ('m_and_e', 'Project M&E Focal Point'),
        ('responsible_officer', 'Responsible Officer'),
        ('data_entry', 'Data Entry / Reporter'),
        ('reviewer', 'Reviewer'),
        ('approver', 'Approver'),
        ('backup', 'Backup / Alternate'),
    ]
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='responsibilities')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_responsibilities')
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)
    is_primary = models.BooleanField(default=True)
    receive_notifications = models.BooleanField(default=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ['project', 'user', 'role']
        ordering = ['project', '-is_primary', 'role']

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.get_role_display()} on {self.project.display_title}"


class ReportAssignment(models.Model):
    """
    Cycle-level assignment: who is assigned to prepare THIS quarter's report
    for THIS project? Can be delegated by head of unit.
    """
    STATUS_CHOICES = [
        ('assigned', 'Assigned'),
        ('accepted', 'Accepted'),
        ('in_progress', 'In Progress'),
        ('submitted', 'Submitted for Review'),
        ('under_review', 'Under Review'),
        ('revisions_requested', 'Revisions Requested'),
        ('approved', 'Approved'),
        ('declined', 'Declined'),
    ]
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='report_assignments')
    cycle = models.ForeignKey('projects.ReportingCycle', on_delete=models.CASCADE, related_name='assignments')
    assigned_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='report_assignments')
    assigned_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='assigned')
    due_date = models.DateField(null=True, blank=True)
    instructions = models.TextField(blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    revision_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['project', 'cycle', 'assigned_to']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.assigned_to.get_full_name()} → {self.project.display_title} {self.cycle}"
