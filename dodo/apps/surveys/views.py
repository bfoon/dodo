from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count

from .models import (
    Survey, SurveySection, Question, QuestionChoice,
    SurveyResponse, Answer,
)
from apps.projects.models import Project


# Reusable range used by respond.html to render Likert/rating scale points.
LIKERT_RANGE = list(range(1, 11))  # supports scales up to 1..10


class SurveyListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        surveys_qs = (
            Survey.objects.filter(country_office=co).select_related('project').prefetch_related('questions')
            if co else Survey.objects.none()
        )

        status_filter = request.GET.get('status') or ''
        if status_filter:
            surveys = surveys_qs.filter(status=status_filter)
        else:
            surveys = surveys_qs

        # Pre-roll status breakdown so the template doesn't need a dict-lookup filter.
        counts = dict(surveys_qs.values_list('status').annotate(n=Count('pk')).values_list('status', 'n'))
        status_breakdown = [
            (code, label, counts.get(code, 0))
            for code, label in Survey.STATUS_CHOICES
        ]

        return render(request, 'surveys/list.html', {
            'surveys': surveys,
            'status_filter': status_filter,
            'status_breakdown': status_breakdown,
            'status_choices': Survey.STATUS_CHOICES,
            'type_choices': Survey.TYPE_CHOICES,
            'total_count': surveys_qs.count(),
        })


class SurveyCreateView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        return render(request, 'surveys/create.html', {
            'projects': Project.objects.filter(country_office=co) if co else Project.objects.none(),
            'survey_types': Survey.TYPE_CHOICES,
        })

    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        project_id = request.POST.get('project')
        try:
            survey = Survey.objects.create(
                country_office=co,
                project=Project.objects.get(pk=project_id) if project_id else None,
                title=request.POST['title'],
                description=request.POST.get('description', ''),
                survey_type=request.POST.get('survey_type', 'quick'),
                instructions=request.POST.get('instructions', ''),
                is_anonymous=bool(request.POST.get('is_anonymous')),
                created_by=request.user,
            )
            messages.success(request, f'Survey "{survey.title}" created. Add questions below.')
            return redirect('surveys:builder', pk=survey.pk)
        except KeyError as e:
            messages.error(request, f'Missing required field: {e.args[0]}')
            return redirect('surveys:create')
        except Exception as e:
            messages.error(request, f'Error creating survey: {e}')
            return redirect('surveys:create')


class SurveyDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        required_count = survey.questions.filter(is_required=True, is_active=True).count()
        return render(request, 'surveys/detail.html', {
            'survey': survey,
            'required_count': required_count,
        })


class SurveyBuilderView(LoginRequiredMixin, View):
    def get(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        questions = survey.questions.prefetch_related('choices').order_by('order')
        return render(request, 'surveys/builder.html', {
            'survey': survey,
            'questions': questions,
            'question_types': Question.TYPE_CHOICES,
        })

    def post(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        action = request.POST.get('action')
        if action == 'publish':
            survey.status = 'active'
            survey.save()
            messages.success(request, 'Survey published.')
        elif action == 'close':
            survey.status = 'closed'
            survey.save()
            messages.success(request, 'Survey closed.')
        return redirect('surveys:builder', pk=pk)


class AddQuestionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        last_order = survey.questions.count()

        def _int_or(default, key):
            try:
                return int(request.POST.get(key) or default)
            except (TypeError, ValueError):
                return default

        q = Question.objects.create(
            survey=survey,
            question_type=request.POST['question_type'],
            text=request.POST['text'],
            description=request.POST.get('description', ''),
            is_required=bool(request.POST.get('is_required')),
            order=last_order + 1,
            scale_min=_int_or(1, 'scale_min'),
            scale_max=_int_or(5, 'scale_max'),
            scale_min_label=request.POST.get('scale_min_label', ''),
            scale_max_label=request.POST.get('scale_max_label', ''),
        )

        # For yes/no, auto-create the two choices so respond.html can render them
        if q.question_type == 'yes_no':
            QuestionChoice.objects.create(question=q, text='Yes', value='yes', order=0)
            QuestionChoice.objects.create(question=q, text='No', value='no', order=1)
        else:
            choices_raw = request.POST.get('choices', '')
            for i, choice_text in enumerate(choices_raw.split('\n')):
                choice_text = choice_text.strip()
                if choice_text:
                    QuestionChoice.objects.create(question=q, text=choice_text, order=i)

        messages.success(request, 'Question added.')
        return redirect('surveys:builder', pk=pk)


class DeleteQuestionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        q = get_object_or_404(Question, pk=pk)
        survey_pk = q.survey.pk
        q.delete()
        messages.success(request, 'Question deleted.')
        return redirect('surveys:builder', pk=survey_pk)


class SurveyResponseView(View):
    def get(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        # Let closed/draft surveys render so the "not accepting responses" banner shows
        questions = (
            survey.questions.filter(is_active=True)
            .prefetch_related('choices')
            .order_by('order')
        )
        return render(request, 'surveys/respond.html', {
            'survey': survey,
            'questions': questions,
            'likert_range': LIKERT_RANGE,
        })

    def post(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk, status='active')

        # Capture basic response info (respect anonymity)
        if survey.is_anonymous:
            respondent_name = ''
            respondent_email = ''
            respondent = None
        else:
            respondent_name = request.POST.get('respondent_name', '')
            respondent_email = request.POST.get('respondent_email', '')
            respondent = request.user if request.user.is_authenticated else None

        # Capture IP (respect X-Forwarded-For if present)
        ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR')

        response = SurveyResponse.objects.create(
            survey=survey,
            respondent=respondent,
            respondent_name=respondent_name,
            respondent_email=respondent_email,
            is_complete=True,
            completed_at=timezone.now(),
            ip_address=ip or None,
        )

        for question in survey.questions.filter(is_active=True):
            key = f'q_{question.pk}'
            answer = Answer.objects.create(response=response, question=question)

            qt = question.question_type
            if qt in ('text', 'textarea'):
                answer.text_value = request.POST.get(key, '')
            elif qt == 'number':
                val = request.POST.get(key)
                try:
                    answer.number_value = float(val) if val not in (None, '') else None
                except ValueError:
                    answer.number_value = None
            elif qt == 'date':
                val = request.POST.get(key)
                answer.date_value = val if val else None
            elif qt in ('radio', 'dropdown', 'yes_no'):
                choice_id = request.POST.get(key)
                if choice_id:
                    answer.save()  # Need PK before M2M .set()
                    answer.selected_choices.set([choice_id])
                    continue
            elif qt == 'checkbox':
                choice_ids = request.POST.getlist(key)
                if choice_ids:
                    answer.save()
                    answer.selected_choices.set(choice_ids)
                    continue
            elif qt in ('likert', 'rating'):
                val = request.POST.get(key)
                try:
                    answer.number_value = float(val) if val not in (None, '') else None
                except ValueError:
                    answer.number_value = None
            elif qt == 'file':
                f = request.FILES.get(key)
                if f:
                    answer.file_value = f
            elif qt == 'geo':
                # Combine lat/lng into text_value for now
                lat = request.POST.get(f'{key}_lat', '')
                lng = request.POST.get(f'{key}_lng', '')
                place = request.POST.get(key, '')
                parts = []
                if place:
                    parts.append(place)
                if lat and lng:
                    parts.append(f'({lat}, {lng})')
                answer.text_value = ' '.join(parts)
            elif qt == 'ranking':
                # Store "choice_pk:rank, choice_pk:rank, ..." in text_value
                rankings = []
                for c in question.choices.all():
                    r = request.POST.get(f'{key}_rank_{c.pk}')
                    if r:
                        rankings.append(f'{c.pk}:{r}')
                answer.text_value = ','.join(rankings)
            elif qt == 'section_header':
                # Section headers collect nothing; skip saving an answer
                answer.delete()
                continue
            else:
                answer.text_value = request.POST.get(key, '')

            answer.save()

        messages.success(request, 'Your response has been recorded. Thank you!')
        return render(request, 'surveys/thankyou.html', {'survey': survey})


class SurveyResultsView(LoginRequiredMixin, View):
    def get(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        questions = (
            survey.questions.filter(is_active=True)
            .prefetch_related('choices', 'answers')
            .order_by('order')
        )
        responses = survey.responses.filter(is_complete=True)

        results = []
        for q in questions:
            q_answers = Answer.objects.filter(response__survey=survey, question=q)
            result = {'question': q, 'total': q_answers.count(), 'data': []}

            if q.question_type in ('radio', 'checkbox', 'dropdown', 'yes_no'):
                for choice in q.choices.all():
                    cnt = q_answers.filter(selected_choices=choice).count()
                    result['data'].append({'label': choice.text, 'count': cnt})
            elif q.question_type in ('text', 'textarea'):
                result['data'] = list(
                    q_answers.exclude(text_value='').values_list('text_value', flat=True)[:20]
                )
            results.append(result)

        return render(request, 'surveys/results.html', {
            'survey': survey,
            'results': results,
            'total_responses': responses.count(),
        })