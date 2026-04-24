from django.db import models
from apps.accounts.models import CountryOffice, User
from apps.projects.models import Project, CPDIndicator, ProjectIndicator, ReportingCycle


class IndicatorAchievement(models.Model):
    """Quarterly cumulative achievements per CPD indicator"""
    cpd_indicator = models.ForeignKey(CPDIndicator, on_delete=models.CASCADE, related_name='achievements')
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True)
    year = models.IntegerField()
    quarter = models.CharField(max_length=2, choices=[('Q1','Q1'),('Q2','Q2'),('Q3','Q3'),('Q4','Q4')])
    achieved_value = models.TextField(blank=True)
    is_cumulative = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    entered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    entered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['cpd_indicator', 'project', 'year', 'quarter']
        ordering = ['year', 'quarter']

    def __str__(self):
        return f"{self.cpd_indicator} - {self.year} {self.quarter}: {self.achieved_value}"


class ProjectIndicatorAchievement(models.Model):
    """Quarterly achievements per project-level indicator"""
    project_indicator = models.ForeignKey(ProjectIndicator, on_delete=models.CASCADE, related_name='achievements')
    cycle = models.ForeignKey(ReportingCycle, on_delete=models.SET_NULL, null=True)
    year = models.IntegerField()
    quarter = models.CharField(max_length=2, choices=[('Q1','Q1'),('Q2','Q2'),('Q3','Q3'),('Q4','Q4')])
    achieved_value = models.CharField(max_length=500, blank=True)
    narrative = models.TextField(blank=True)
    challenges = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    evidence_file = models.FileField(upload_to='evidence/', blank=True, null=True)
    entered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    entered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['project_indicator', 'year', 'quarter']
        ordering = ['year', 'quarter']

    def __str__(self):
        return f"{self.project_indicator} - {self.year}{self.quarter}"


class OutputVerification(models.Model):
    """Output verification records per project cycle"""
    VERIFICATION_STATUS = [
        ('pending', 'Pending'),
        ('field_verification', 'Field Verification'),
        ('documentation_review', 'Documentation Review'),
        ('validation_meeting', 'Validation Meeting'),
        ('completed', 'Completed'),
        ('not_applicable', 'Not Applicable'),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='output_verifications')
    cycle = models.ForeignKey(ReportingCycle, on_delete=models.CASCADE, related_name='output_verifications')
    verification_period = models.CharField(max_length=100, blank=True)
    field_verification_dates = models.CharField(max_length=100, blank=True)
    documentation_review_dates = models.CharField(max_length=100, blank=True)
    validation_meeting_dates = models.CharField(max_length=100, blank=True)
    final_report_due = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=VERIFICATION_STATUS, default='pending')
    verification_notes = models.TextField(blank=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['project', 'cycle']

    def __str__(self):
        return f"Verification: {self.project.display_title} - {self.cycle}"

    def get_status_color(self):
        colors = {
            'completed': 'success',
            'validation_meeting': 'info',
            'documentation_review': 'primary',
            'field_verification': 'warning',
            'pending': 'secondary',
            'not_applicable': 'light',
        }
        return colors.get(self.status, 'secondary')


class MonitoringVisit(models.Model):
    """Field monitoring visits"""
    VISIT_TYPE = [
        ('field', 'Field Visit'),
        ('remote', 'Remote Monitoring'),
        ('desk', 'Desk Review'),
        ('joint', 'Joint Monitoring'),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='monitoring_visits')
    visit_type = models.CharField(max_length=20, choices=VISIT_TYPE)
    visit_date = models.DateField()
    location = models.CharField(max_length=200, blank=True)
    purpose = models.TextField()
    findings = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    follow_up_actions = models.TextField(blank=True)
    conducted_by = models.ManyToManyField(User, blank=True, related_name='monitoring_visits')
    attachments = models.FileField(upload_to='monitoring/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-visit_date']

    def __str__(self):
        return f"{self.project.display_title} - {self.visit_date} ({self.get_visit_type_display()})"
