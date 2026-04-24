from django.db import models
from django.utils import timezone
from apps.accounts.models import User, CountryOffice


class DeadlineTemplate(models.Model):
    """
    Reusable deadline templates per Country Office.
    e.g. 'Q1 Progress Reporting' with configurable offsets for draft, review, clearance.
    """
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE, related_name='deadline_templates')
    name = models.CharField(max_length=200)
    cycle_type = models.CharField(max_length=20, choices=[
        ('progress', 'Progress Reporting'),
        ('verification', 'Output Verification'),
        ('donor', 'Donor Reporting'),
        ('custom', 'Custom'),
    ])
    # Configurable timeline stages (as offsets in days from the cycle's submission deadline)
    internal_draft_days_before = models.IntegerField(default=14, help_text='Days before final deadline to complete internal draft')
    programme_review_days_before = models.IntegerField(default=10, help_text='Days before final deadline for programme unit review')
    pmsu_review_days_before = models.IntegerField(default=6, help_text='Days before final deadline for PMSU review')
    final_clearance_days_before = models.IntegerField(default=2, help_text='Days before final deadline for DRR/RR clearance')

    # Reminder schedule (days before each deadline, multiple allowed)
    reminder_days_before = models.CharField(
        max_length=100, default='14,7,3,1',
        help_text='Comma-separated days to send reminders (e.g. 14,7,3,1)'
    )
    # Escalation: if missed by X days, alert head of unit
    escalation_days_after = models.IntegerField(default=1, help_text='Days after deadline before escalating to head of unit')

    # Notification channels
    send_email = models.BooleanField(default=True)
    send_in_app = models.BooleanField(default=True)
    notify_head_of_unit = models.BooleanField(default=True)
    notify_responsible = models.BooleanField(default=True)

    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['country_office', 'name']

    def __str__(self):
        return f"{self.name} [{self.country_office.code}]"

    def get_reminder_days(self):
        try:
            return sorted([int(d.strip()) for d in self.reminder_days_before.split(',') if d.strip()], reverse=True)
        except (ValueError, TypeError):
            return [14, 7, 3, 1]


class DeadlineSchedule(models.Model):
    """
    Concrete deadline instance for a specific project + reporting cycle.
    Generated from a DeadlineTemplate but fully editable per instance.
    """
    STATUS_CHOICES = [
        ('upcoming', 'Upcoming'),
        ('in_progress', 'In Progress'),
        ('at_risk', 'At Risk'),
        ('overdue', 'Overdue'),
        ('completed', 'Completed'),
        ('waived', 'Waived'),
    ]
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='deadlines')
    cycle = models.ForeignKey('projects.ReportingCycle', on_delete=models.CASCADE, related_name='deadlines')
    template = models.ForeignKey(DeadlineTemplate, on_delete=models.SET_NULL, null=True, blank=True)

    # Configurable dates — override template defaults
    internal_draft_deadline = models.DateField()
    programme_review_deadline = models.DateField()
    pmsu_review_deadline = models.DateField()
    final_clearance_deadline = models.DateField()
    final_submission_deadline = models.DateField()

    # Stage completion tracking
    internal_draft_completed_at = models.DateTimeField(null=True, blank=True)
    programme_review_completed_at = models.DateTimeField(null=True, blank=True)
    pmsu_review_completed_at = models.DateTimeField(null=True, blank=True)
    final_clearance_completed_at = models.DateTimeField(null=True, blank=True)
    final_submission_completed_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='upcoming')
    override_reminder_days = models.CharField(max_length=100, blank=True, help_text='Override template reminders, comma-separated')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_deadlines')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['project', 'cycle']
        ordering = ['final_submission_deadline']

    def __str__(self):
        return f"{self.project.display_title} — {self.cycle} (Due {self.final_submission_deadline})"

    def get_current_stage(self):
        """Returns the current active stage based on completion"""
        if self.final_submission_completed_at:
            return ('completed', 'Completed')
        if self.final_clearance_completed_at:
            return ('submission', 'Awaiting Final Submission')
        if self.pmsu_review_completed_at:
            return ('clearance', 'Awaiting DRR/RR Clearance')
        if self.programme_review_completed_at:
            return ('pmsu', 'Awaiting PMSU Review')
        if self.internal_draft_completed_at:
            return ('programme', 'Awaiting Programme Review')
        return ('draft', 'Awaiting Internal Draft')

    def get_days_until_deadline(self):
        return (self.final_submission_deadline - timezone.now().date()).days

    def is_overdue(self):
        return self.get_days_until_deadline() < 0 and not self.final_submission_completed_at

    def compute_status(self):
        if self.final_submission_completed_at:
            return 'completed'
        days = self.get_days_until_deadline()
        if days < 0:
            return 'overdue'
        elif days <= 3:
            return 'at_risk'
        elif self.internal_draft_completed_at:
            return 'in_progress'
        return 'upcoming'


class ReportDelegation(models.Model):
    """
    Head of Unit delegates report preparation to a specific user for a project/cycle.
    This grants the delegated user temporary edit access to that specific project's reporting.
    """
    DELEGATION_TYPES = [
        ('draft', 'Draft Preparation'),
        ('full', 'Full Report Preparation'),
        ('review', 'Review Only'),
        ('data_entry', 'Data Entry Only'),
    ]
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='delegations')
    cycle = models.ForeignKey('projects.ReportingCycle', on_delete=models.CASCADE, null=True, blank=True, related_name='delegations')
    delegated_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_delegations')
    delegated_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_delegations')
    delegation_type = models.CharField(max_length=20, choices=DELEGATION_TYPES, default='full')
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True, help_text='Delegation expires after this date (optional)')
    instructions = models.TextField(blank=True, help_text='Instructions or context for the delegated user')
    is_active = models.BooleanField(default=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.delegated_by} → {self.delegated_to} for {self.project.display_title}"

    def is_currently_active(self):
        if not self.is_active:
            return False
        today = timezone.now().date()
        if self.end_date and today > self.end_date:
            return False
        return today >= self.start_date


class Notification(models.Model):
    """In-app notifications for users"""
    NOTIFICATION_TYPES = [
        ('reminder', 'Deadline Reminder'),
        ('overdue', 'Overdue Alert'),
        ('escalation', 'Escalation'),
        ('delegation', 'Delegation Assignment'),
        ('approval', 'Approval Request'),
        ('status_change', 'Status Change'),
        ('mention', 'Mention'),
        ('report_submitted', 'Report Submitted'),
        ('report_cleared', 'Report Cleared'),
        ('access_granted', 'Access Granted'),
        ('system', 'System'),
    ]
    PRIORITY_CHOICES = [
        ('low', 'Low'), ('normal', 'Normal'), ('high', 'High'), ('critical', 'Critical'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    title = models.CharField(max_length=200)
    message = models.TextField()
    # Link to the related object
    related_project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, null=True, blank=True)
    related_cycle = models.ForeignKey('projects.ReportingCycle', on_delete=models.CASCADE, null=True, blank=True)
    related_deadline = models.ForeignKey(DeadlineSchedule, on_delete=models.CASCADE, null=True, blank=True)
    action_url = models.CharField(max_length=500, blank=True)
    # Email tracking
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    # Read status
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.email}: {self.title}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class ReminderLog(models.Model):
    """Tracks which reminders have been sent to prevent duplicates"""
    deadline = models.ForeignKey(DeadlineSchedule, on_delete=models.CASCADE, related_name='reminder_logs')
    stage = models.CharField(max_length=30)
    days_before = models.IntegerField()
    recipient = models.ForeignKey(User, on_delete=models.CASCADE)
    sent_at = models.DateTimeField(auto_now_add=True)
    channel = models.CharField(max_length=20, choices=[('email', 'Email'), ('in_app', 'In-App'), ('sms', 'SMS')])
    success = models.BooleanField(default=True)

    class Meta:
        unique_together = ['deadline', 'stage', 'days_before', 'recipient', 'channel']
        ordering = ['-sent_at']

    def __str__(self):
        return f"{self.recipient.email} - {self.stage} - {self.days_before}d before"


class DataAccessGrant(models.Model):
    """
    Granular data-level access grants.
    Allows admin/super users to give specific users access to specific objects
    (project, cluster, report, indicator) with specific actions (view, edit, download).
    This is ABOVE and beyond role-based permissions.
    """
    RESOURCE_TYPES = [
        ('project', 'Single Project'),
        ('programme_unit', 'Programme Unit / Cluster'),
        ('reporting_cycle', 'Reporting Cycle'),
        ('survey', 'Survey'),
        ('indicator', 'CPD Indicator'),
        ('all_projects', 'All Projects in CO'),
        ('all_reports', 'All Reports in CO'),
    ]
    ACCESS_LEVELS = [
        ('view', 'View Only'),
        ('edit', 'View & Edit'),
        ('delete', 'View, Edit & Delete'),
        ('approve', 'View, Edit & Approve'),
        ('download', 'View & Download'),
        ('full', 'Full Access (Admin-level for this resource)'),
    ]

    granted_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='data_grants')
    granted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_data_grants')
    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE)

    resource_type = models.CharField(max_length=30, choices=RESOURCE_TYPES)
    resource_id = models.IntegerField(null=True, blank=True, help_text='ID of the specific resource (null for all_*)')
    resource_name = models.CharField(max_length=300, blank=True, help_text='Cached display name of the resource')

    access_level = models.CharField(max_length=20, choices=ACCESS_LEVELS)
    can_delegate = models.BooleanField(default=False, help_text='Can this user delegate their access to others?')

    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    reason = models.TextField(blank=True, help_text='Why was this grant given?')
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='revoked_grants')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['granted_to', 'is_active']),
            models.Index(fields=['resource_type', 'resource_id']),
        ]

    def __str__(self):
        return f"{self.granted_to.email} → {self.get_resource_type_display()}:{self.resource_name} [{self.access_level}]"

    def is_currently_valid(self):
        if not self.is_active:
            return False
        today = timezone.now().date()
        if today < self.start_date:
            return False
        if self.end_date and today > self.end_date:
            return False
        return True

    def revoke(self, by_user):
        self.is_active = False
        self.revoked_at = timezone.now()
        self.revoked_by = by_user
        self.save()


class UnitHead(models.Model):
    """
    Designates Heads of Unit (Programme Unit / Cluster Leads).
    Heads of Unit automatically receive escalations and can view all reports
    under their unit, and delegate report preparation.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='unit_head_assignments')
    programme_unit = models.ForeignKey('projects.ProgrammeUnit', on_delete=models.CASCADE, related_name='heads')
    is_primary = models.BooleanField(default=True, help_text='Primary head (vs deputy)')
    can_delegate = models.BooleanField(default=True)
    can_approve = models.BooleanField(default=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='assigned_unit_heads')
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['user', 'programme_unit']
        ordering = ['programme_unit', '-is_primary']

    def __str__(self):
        role = 'Head' if self.is_primary else 'Deputy'
        return f"{role} of {self.programme_unit.name}: {self.user.get_full_name()}"
