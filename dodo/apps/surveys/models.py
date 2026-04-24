from django.db import models
from apps.accounts.models import CountryOffice, User
from apps.projects.models import Project


class Survey(models.Model):
    """Dynamic survey/data collection tool"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('closed', 'Closed'),
        ('archived', 'Archived'),
    ]
    TYPE_CHOICES = [
        ('baseline', 'Baseline Survey'),
        ('midterm', 'Midterm Assessment'),
        ('endline', 'Endline Survey'),
        ('monitoring', 'Monitoring Survey'),
        ('quick', 'Quick Survey'),
        ('verification', 'Output Verification'),
        ('custom', 'Custom'),
    ]

    country_office = models.ForeignKey(CountryOffice, on_delete=models.CASCADE, related_name='surveys')
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name='surveys')
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    survey_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='quick')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    instructions = models.TextField(blank=True)
    is_anonymous = models.BooleanField(default=False)
    allow_multiple = models.BooleanField(default=False, help_text='Allow same user to submit multiple times')
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_surveys')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_response_count(self):
        return self.responses.count()

    def get_completion_rate(self):
        total = self.responses.count()
        complete = self.responses.filter(is_complete=True).count()
        return round((complete / total * 100), 1) if total > 0 else 0


class SurveySection(models.Model):
    """Survey sections/pages"""
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name='sections')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.survey.title} - {self.title}"


class Question(models.Model):
    """Dynamic survey question"""
    TYPE_CHOICES = [
        ('text', 'Short Text'),
        ('textarea', 'Long Text / Paragraph'),
        ('number', 'Number'),
        ('date', 'Date'),
        ('radio', 'Single Choice (Radio)'),
        ('checkbox', 'Multiple Choice (Checkbox)'),
        ('dropdown', 'Dropdown Select'),
        ('likert', 'Likert Scale'),
        ('rating', 'Star Rating'),
        ('file', 'File Upload'),
        ('matrix', 'Matrix / Grid'),
        ('ranking', 'Ranking'),
        ('yes_no', 'Yes / No'),
        ('geo', 'Geographic Location'),
        ('section_header', 'Section Header'),
    ]

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name='questions')
    section = models.ForeignKey(SurveySection, on_delete=models.SET_NULL, null=True, blank=True)
    question_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    text = models.TextField(verbose_name='Question Text')
    description = models.TextField(blank=True, verbose_name='Help Text / Description')
    order = models.IntegerField(default=0)
    is_required = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    # For rating/likert
    scale_min = models.IntegerField(default=1)
    scale_max = models.IntegerField(default=5)
    scale_min_label = models.CharField(max_length=50, blank=True)
    scale_max_label = models.CharField(max_length=50, blank=True)
    # Conditional logic
    depends_on = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='conditional_questions')
    depends_on_value = models.CharField(max_length=200, blank=True)
    # Validation
    min_value = models.FloatField(null=True, blank=True)
    max_value = models.FloatField(null=True, blank=True)
    max_length = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Q{self.order}: {self.text[:60]}"


class QuestionChoice(models.Model):
    """Choices for radio/checkbox/dropdown questions"""
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField(max_length=300)
    value = models.CharField(max_length=200, blank=True)
    order = models.IntegerField(default=0)
    is_other = models.BooleanField(default=False)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.question} - {self.text}"


class SurveyResponse(models.Model):
    """Individual survey submission"""
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name='responses')
    respondent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    respondent_name = models.CharField(max_length=200, blank=True)
    respondent_email = models.EmailField(blank=True)
    is_complete = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        name = self.respondent_name or (str(self.respondent) if self.respondent else 'Anonymous')
        return f"{self.survey.title} - {name} - {self.started_at.date()}"


class Answer(models.Model):
    """Individual answer to a question within a response"""
    response = models.ForeignKey(SurveyResponse, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    text_value = models.TextField(blank=True)
    number_value = models.FloatField(null=True, blank=True)
    date_value = models.DateField(null=True, blank=True)
    selected_choices = models.ManyToManyField(QuestionChoice, blank=True, related_name='answers')
    file_value = models.FileField(upload_to='survey_uploads/', blank=True, null=True)

    class Meta:
        unique_together = ['response', 'question']

    def __str__(self):
        return f"{self.response} - {self.question}"

    def get_display_value(self):
        q_type = self.question.question_type
        if q_type in ('text', 'textarea'):
            return self.text_value
        elif q_type == 'number':
            return self.number_value
        elif q_type == 'date':
            return self.date_value
        elif q_type in ('radio', 'checkbox', 'dropdown'):
            return ', '.join([c.text for c in self.selected_choices.all()])
        elif q_type in ('likert', 'rating'):
            return self.number_value
        return self.text_value
