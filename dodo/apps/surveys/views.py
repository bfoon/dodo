import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse, HttpResponseBadRequest

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


class ReorderQuestionsView(LoginRequiredMixin, View):
    """Accepts {"order": [pk, pk, pk, ...]} and rewrites each question's
    `order` field to match the new position.

    The list must contain exactly the set of question PKs that already belong
    to this survey — extras or missing IDs are rejected to keep the operation
    consistent and prevent cross-survey ID injection.
    """

    def post(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)

        # Optional country-office scoping — only allow reordering surveys in
        # the user's active CO if the middleware sets one.
        co = getattr(request, 'active_country_office', None)
        if co is not None and survey.country_office_id != getattr(co, 'pk', None):
            return JsonResponse({'ok': False, 'error': 'Not authorized for this survey.'}, status=403)

        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return HttpResponseBadRequest('Invalid JSON payload.')

        order = payload.get('order') or []
        if not isinstance(order, list):
            return HttpResponseBadRequest('"order" must be a list.')

        try:
            order_ids = [int(x) for x in order]
        except (TypeError, ValueError):
            return HttpResponseBadRequest('All IDs in "order" must be integers.')

        existing_ids = set(survey.questions.values_list('pk', flat=True))
        if set(order_ids) != existing_ids:
            return JsonResponse({
                'ok': False,
                'error': 'Submitted order does not match the survey questions.',
            }, status=400)

        with transaction.atomic():
            for new_order, qid in enumerate(order_ids, start=1):
                Question.objects.filter(pk=qid, survey=survey).update(order=new_order)

        return JsonResponse({'ok': True, 'count': len(order_ids)})


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


class SurveyDashboardView(LoginRequiredMixin, View):
    """Cross-survey analytics dashboard.

    Aggregates responses, survey types, geographic data, and question-type
    breakdowns across all surveys in the user's active country office.
    Supports a ?days= filter (30, 90, 365, 0=all) and ?survey= for a single survey.
    """

    DAYS_OPTIONS = [
        (30, 'Last 30 days'),
        (90, 'Last 90 days'),
        (365, 'Last 12 months'),
        (0, 'All time'),
    ]

    def get(self, request):
        import re
        from datetime import timedelta
        from collections import defaultdict, OrderedDict

        co = getattr(request, 'active_country_office', None)

        # --- Filters ---
        try:
            days = int(request.GET.get('days', 90))
        except (TypeError, ValueError):
            days = 90
        if days not in {30, 90, 365, 0}:
            days = 90

        survey_filter_id = request.GET.get('survey') or ''
        try:
            survey_filter_id = int(survey_filter_id) if survey_filter_id else None
        except (TypeError, ValueError):
            survey_filter_id = None

        now = timezone.now()
        cutoff = now - timedelta(days=days) if days else None

        # --- Base querysets ---
        if co:
            surveys_qs = Survey.objects.filter(country_office=co)
        else:
            surveys_qs = Survey.objects.none()

        responses_qs = SurveyResponse.objects.filter(
            survey__in=surveys_qs,
            is_complete=True,
        )
        if cutoff:
            responses_qs = responses_qs.filter(completed_at__gte=cutoff)
        if survey_filter_id:
            responses_qs = responses_qs.filter(survey_id=survey_filter_id)
            scoped_surveys = surveys_qs.filter(pk=survey_filter_id)
        else:
            scoped_surveys = surveys_qs

        # --- KPIs ---
        total_surveys = surveys_qs.count()
        active_surveys = surveys_qs.filter(status='active').count()
        total_responses = responses_qs.count()

        unique_respondents = (
            responses_qs.exclude(respondent_email='')
            .values('respondent_email').distinct().count()
        )
        # Plus authenticated respondents (no email but a respondent FK)
        unique_authed = (
            responses_qs.exclude(respondent__isnull=True)
            .values('respondent_id').distinct().count()
        )
        unique_respondents = max(unique_respondents, unique_authed)

        # Avg completion rate across surveys with at least one response
        completion_values = []
        for s in scoped_surveys:
            total = s.responses.count()
            if total:
                done = s.responses.filter(is_complete=True).count()
                completion_values.append(done / total * 100)
        avg_completion = round(sum(completion_values) / len(completion_values), 1) if completion_values else 0

        # Responses last 7 days (regardless of the days filter, for the "trend" KPI)
        last_week_cutoff = now - timedelta(days=7)
        responses_last_week = responses_qs.filter(completed_at__gte=last_week_cutoff).count()

        kpis = {
            'total_surveys': total_surveys,
            'active_surveys': active_surveys,
            'total_responses': total_responses,
            'unique_respondents': unique_respondents,
            'avg_completion': avg_completion,
            'responses_last_week': responses_last_week,
        }

        # --- Responses over time (daily buckets) ---
        # Decide bucket size based on the date range
        if days == 0:
            # All-time: bucket monthly to avoid 1000+ data points
            bucket_fmt = '%Y-%m'
            bucket_label_fmt = '%b %Y'
        elif days >= 365:
            bucket_fmt = '%Y-%m'
            bucket_label_fmt = '%b %Y'
        elif days >= 90:
            bucket_fmt = '%Y-%W'  # weekly
            bucket_label_fmt = None  # built below
        else:
            bucket_fmt = '%Y-%m-%d'
            bucket_label_fmt = '%d %b'

        timeline = defaultdict(int)
        for r in responses_qs.values('completed_at'):
            ts = r['completed_at']
            if not ts:
                continue
            timeline[ts.strftime(bucket_fmt)] += 1
        # Sort keys chronologically
        sorted_keys = sorted(timeline.keys())
        time_labels = []
        time_values = []
        for k in sorted_keys:
            time_values.append(timeline[k])
            if bucket_fmt == '%Y-%m-%d':
                from datetime import datetime
                time_labels.append(datetime.strptime(k, bucket_fmt).strftime(bucket_label_fmt))
            elif bucket_fmt == '%Y-%m':
                from datetime import datetime
                time_labels.append(datetime.strptime(k + '-01', '%Y-%m-%d').strftime(bucket_label_fmt))
            else:  # weekly
                # k is like "2026-15"; show as "W15 '26"
                year, week = k.split('-')
                time_labels.append(f"W{week} '{year[2:]}")

        timeline_data = {'labels': time_labels, 'values': time_values}

        # --- Survey type distribution ---
        type_counts = (
            scoped_surveys.values('survey_type')
            .annotate(c=Count('pk'))
            .order_by('-c')
        )
        type_label_map = dict(Survey.TYPE_CHOICES)
        type_data = {
            'labels': [type_label_map.get(t['survey_type'], t['survey_type']) for t in type_counts],
            'values': [t['c'] for t in type_counts],
        }

        # --- Top surveys by response count ---
        top_surveys = (
            scoped_surveys.annotate(rcount=Count('responses', filter=None))
            .filter(rcount__gt=0)
            .order_by('-rcount')[:10]
        )
        top_surveys_data = {
            'labels': [s.title[:50] + ('…' if len(s.title) > 50 else '') for s in top_surveys],
            'values': [s.rcount for s in top_surveys],
            'ids': [s.pk for s in top_surveys],
        }

        # --- Question type breakdown across all surveys ---
        qtype_counts = (
            Question.objects.filter(survey__in=scoped_surveys, is_active=True)
            .values('question_type').annotate(c=Count('pk'))
            .order_by('-c')
        )
        qtype_label_map = dict(Question.TYPE_CHOICES)
        qtype_data = {
            'labels': [qtype_label_map.get(q['question_type'], q['question_type']) for q in qtype_counts],
            'values': [q['c'] for q in qtype_counts],
        }

        # --- Geographic data: extract lat/lng from geo answers ---
        # Geo answers are stored as text_value like "Place Name (12.345, -56.789)"
        # We extract any number pair in parentheses.
        geo_pattern = re.compile(r'\(\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\)')
        geo_points = []
        geo_answers = (
            Answer.objects
            .filter(
                response__in=responses_qs,
                question__question_type='geo',
            )
            .exclude(text_value='')
            .select_related('response', 'response__survey')
            .values('text_value', 'response__survey__title', 'response__completed_at')
        )
        for ga in geo_answers:
            text = ga['text_value'] or ''
            m = geo_pattern.search(text)
            if not m:
                continue
            try:
                lat = float(m.group(1))
                lng = float(m.group(2))
            except ValueError:
                continue
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                # Strip the (lat, lng) part for the popup display
                place = geo_pattern.sub('', text).strip()
                geo_points.append({
                    'lat': lat,
                    'lng': lng,
                    'survey': ga['response__survey__title'],
                    'place': place or 'Response location',
                    'date': ga['response__completed_at'].strftime('%d %b %Y') if ga['response__completed_at'] else '',
                })

        # --- Recent activity feed ---
        recent_responses = list(
            responses_qs.select_related('survey', 'respondent')
            .order_by('-completed_at')[:12]
        )

        # --- Survey list for dropdown ---
        survey_choices = list(
            surveys_qs.order_by('title').values('pk', 'title')
        )

        return render(request, 'surveys/dashboard.html', {
            'kpis': kpis,
            'days': days,
            'days_options': self.DAYS_OPTIONS,
            'survey_filter_id': survey_filter_id,
            'survey_choices': survey_choices,
            'timeline_data': timeline_data,
            'type_data': type_data,
            'top_surveys_data': top_surveys_data,
            'qtype_data': qtype_data,
            'geo_points': geo_points,
            'recent_responses': recent_responses,
        })