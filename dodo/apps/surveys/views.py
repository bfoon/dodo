import json
import re
from collections import Counter, defaultdict
from datetime import timedelta
from statistics import mean, median

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from .models import (
    Answer,
    Question,
    QuestionChoice,
    Survey,
    SurveyResponse,
    SurveySection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _can_view_results(user):
    """Superusers, global admins, and (per-CO) anyone with relevant perms
    can see survey analytics."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_global_admin', False):
        return True
    from apps.accounts.models import ModulePermission
    return ModulePermission.objects.filter(
        role__user_access__user=user,
        role__user_access__is_active=True,
        module__in=('surveys', 'reporting', 'users'),
        action__in=('approve', 'edit', 'export'),
    ).exists()


def _surveys_visible_to(user, co):
    """
    Return the queryset of surveys the user can see in the list, scoped to
    the active country office.

    Visibility rules:
      • superuser or global admin   → all surveys in the CO
      • survey owner / creator       → their own surveys (always)
      • CO admin (M&E)               → all surveys in the CO
      • members of the survey's project's programme unit → that survey
      • everyone else                → only public-facing active surveys
                                        within the CO they belong to
    """
    if not user.is_authenticated:
        return Survey.objects.none()
    if co is None:
        return Survey.objects.none()

    base = Survey.objects.filter(country_office=co)

    if user.is_superuser or getattr(user, 'is_global_admin', False):
        return base

    # CO admins / users with surveys-management perms see everything in CO.
    from apps.accounts.models import ModulePermission
    is_co_admin = ModulePermission.objects.filter(
        role__user_access__user=user,
        role__user_access__country_office=co,
        role__user_access__is_active=True,
        module__in=('surveys', 'users'),
        action__in=('edit', 'approve', 'delete'),
    ).exists()
    if is_co_admin:
        return base

    # Otherwise restrict: own surveys + surveys whose project is in a unit the
    # user belongs to. We OR these together.
    from django.db.models import Q
    user_unit_ids = set()
    try:
        # Common pattern: user has explicit unit memberships through their roles
        # OR through project assignments. We pull both defensively.
        from apps.projects.models import ProgrammeUnit
        # Anyone listed as a unit lead
        user_unit_ids.update(
            ProgrammeUnit.objects.filter(lead=user).values_list('pk', flat=True)
        )
        # Anyone with any responsibility on a project in a unit
        user_unit_ids.update(
            ProgrammeUnit.objects.filter(
                projects__responsibilities__user=user,
                projects__responsibilities__is_active=True,
            ).values_list('pk', flat=True).distinct()
        )
    except Exception:
        # If models aren't quite shaped this way, fall through to creator-only
        pass

    visibility = Q(created_by=user)
    if user_unit_ids:
        visibility |= Q(project__programme_unit_id__in=user_unit_ids)
    return base.filter(visibility).distinct()


_GEO_RE = re.compile(
    r'^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*(?:,\s*(.+?))?\s*$'
)


def _parse_geo(text_value):
    if not text_value:
        return None
    m = _GEO_RE.match(str(text_value))
    if not m:
        return None
    try:
        lat = float(m.group(1)); lng = float(m.group(2))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return {'lat': lat, 'lng': lng, 'label': (m.group(3) or '').strip() or None}


# ---------------------------------------------------------------------------
# List, dashboard, create, detail
# ---------------------------------------------------------------------------

class SurveyListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        surveys = (
            _surveys_visible_to(request.user, co)
            .select_related('project')
            .prefetch_related('questions', 'responses')
        )
        status_filter = request.GET.get('status')
        if status_filter:
            surveys = surveys.filter(status=status_filter)

        # Status breakdown reflects only surveys the user can see, so the
        # count badges match the list contents.
        visible_all = _surveys_visible_to(request.user, co)
        status_breakdown = []
        for sc, sl in Survey.STATUS_CHOICES:
            status_breakdown.append((sc, sl, visible_all.filter(status=sc).count()))
        return render(request, 'surveys/list.html', {
            'surveys': surveys,
            'status_filter': status_filter,
            'status_breakdown': status_breakdown,
            'total_count': visible_all.count(),
            'type_choices': Survey.TYPE_CHOICES,
        })


class SurveyDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        return render(request, 'surveys/dashboard.html', {'co': co})


class SurveyCreateView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'surveys/form.html', {
            'survey_types': Survey.TYPE_CHOICES,
        })

    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        survey = Survey.objects.create(
            country_office=co,
            title=request.POST['title'],
            description=request.POST.get('description', ''),
            survey_type=request.POST.get('survey_type', 'quick'),
            instructions=request.POST.get('instructions', ''),
            is_anonymous=bool(request.POST.get('is_anonymous')),
            allow_multiple=bool(request.POST.get('allow_multiple')),
            created_by=request.user,
        )
        messages.success(request, f'Survey "{survey.title}" created.')
        return redirect('surveys:builder', pk=survey.pk)


class SurveyDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        required_count = survey.questions.filter(is_required=True).count()
        return render(request, 'surveys/detail.html', {
            'survey': survey, 'required_count': required_count,
        })


# ---------------------------------------------------------------------------
# Builder — FIXED
# ---------------------------------------------------------------------------

class SurveyBuilderView(LoginRequiredMixin, View):
    """
    GET  → render builder with the survey's questions.
    POST → handles three actions:
           - action=publish   : flip status to 'active'
           - action=close     : flip status to 'closed'
           - (no action)      : update survey metadata (title, type, etc.)
    """

    def get(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        # Bug #1 fix: actually pass the questions to the template.
        questions = (
            survey.questions
            .filter(is_active=True)
            .prefetch_related('choices')
            .order_by('order', 'pk')
        )
        return render(request, 'surveys/builder.html', {
            'survey': survey,
            'questions': questions,
            'question_types': Question.TYPE_CHOICES,
        })

    def post(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        action = (request.POST.get('action') or '').strip()

        # Bug #3 fix: handle publish / close actions from the header buttons.
        if action == 'publish':
            if not survey.questions.filter(is_active=True).exists():
                messages.error(
                    request,
                    "Can't publish a survey with no questions. Add at least one first."
                )
            else:
                survey.status = 'active'
                if not survey.start_date:
                    survey.start_date = timezone.now()
                survey.save()
                messages.success(request, f'Survey "{survey.title}" is now active.')
            return redirect('surveys:builder', pk=pk)

        if action == 'close':
            survey.status = 'closed'
            survey.end_date = survey.end_date or timezone.now()
            survey.save()
            messages.success(request, f'Survey "{survey.title}" closed.')
            return redirect('surveys:builder', pk=pk)

        # Default: metadata save
        for field in ('title', 'description', 'instructions', 'survey_type', 'status'):
            v = request.POST.get(field)
            if v is not None:
                setattr(survey, field, v)
        if 'is_anonymous' in request.POST:
            survey.is_anonymous = bool(request.POST.get('is_anonymous'))
        if 'allow_multiple' in request.POST:
            survey.allow_multiple = bool(request.POST.get('allow_multiple'))
        survey.save()
        messages.success(request, 'Survey saved.')
        return redirect('surveys:builder', pk=pk)


# ---------------------------------------------------------------------------
# Public response form
# ---------------------------------------------------------------------------

class SurveyResponseView(View):
    """
    Public-facing response form. Intentionally NOT login-required and renders
    on a standalone template (no app chrome) — survey URLs may be shared
    with anyone.

    States:
      • status='active' AND within window     → show the form
      • status='active' AND end_date passed   → show closed page (expired)
      • status='active' AND start_date future → show closed page (not_started)
      • any other status                       → show closed page (inactive)
    """
    def _gate(self, survey):
        """Return ('open', None) or ('closed', reason_code)."""
        now = timezone.now()
        if survey.status != 'active':
            return ('closed', 'inactive')
        if survey.start_date and now < survey.start_date:
            return ('closed', 'not_started')
        if survey.end_date and now > survey.end_date:
            return ('closed', 'expired')
        return ('open', None)

    def _closed_response(self, request, survey, reason_code):
        return render(request, 'surveys/closed.html', {
            'survey': survey,
            'reason_code': reason_code,
        }, status=410 if reason_code == 'expired' else 200)

    def get(self, request, pk):
        # Don't filter by status here — load the survey so we can show the
        # right closed-state page rather than a 404.
        survey = get_object_or_404(Survey, pk=pk)

        state, reason = self._gate(survey)
        if state == 'closed':
            return self._closed_response(request, survey, reason)

        questions = (
            survey.questions.filter(is_active=True)
                  .prefetch_related('choices')
                  .order_by('order', 'pk')
        )
        max_scale = max(
            (q.scale_max for q in questions if q.question_type in ('likert', 'rating')),
            default=10,
        )
        return render(request, 'surveys/respond.html', {
            'survey': survey,
            'questions': questions,
            'likert_range': range(1, int(max_scale) + 1),
            'required_count': sum(1 for q in questions if q.is_required),
        })

    def post(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)

        # Re-check at submit time — owner may have closed the survey while
        # the respondent was filling it in.
        state, reason = self._gate(survey)
        if state == 'closed':
            return self._closed_response(request, survey, reason)

        response = SurveyResponse.objects.create(
            survey=survey,
            respondent=request.user if request.user.is_authenticated and not survey.is_anonymous else None,
            respondent_name=request.POST.get('respondent_name', '').strip(),
            respondent_email=request.POST.get('respondent_email', '').strip(),
            ip_address=request.META.get('REMOTE_ADDR'),
        )
        for q in survey.questions.filter(is_active=True):
            field_name = f'q_{q.pk}'
            answer = Answer.objects.create(response=response, question=q)
            qtype = q.question_type

            if qtype in ('text', 'textarea'):
                answer.text_value = request.POST.get(field_name, '')

            elif qtype == 'number':
                try:
                    answer.number_value = float(request.POST.get(field_name, ''))
                except (TypeError, ValueError):
                    pass

            elif qtype == 'date':
                answer.date_value = request.POST.get(field_name) or None

            elif qtype in ('radio', 'dropdown', 'yes_no'):
                cid = request.POST.get(field_name)
                if cid and str(cid).isdigit():
                    answer.save()
                    answer.selected_choices.set([int(cid)])

            elif qtype == 'checkbox':
                cids = request.POST.getlist(field_name)
                if cids:
                    answer.save()
                    answer.selected_choices.set(
                        [int(c) for c in cids if str(c).isdigit()]
                    )

            elif qtype in ('likert', 'rating'):
                try:
                    answer.number_value = float(request.POST.get(field_name, ''))
                except (TypeError, ValueError):
                    pass

            elif qtype == 'geo':
                # Widget posts: q_{pk}_lat, q_{pk}_lng, q_{pk} (place name).
                # Compose "lat,lng" or "lat,lng,place" so the analytics map
                # parser can read it back.
                lat = (request.POST.get(f'{field_name}_lat') or '').strip()
                lng = (request.POST.get(f'{field_name}_lng') or '').strip()
                place = (request.POST.get(field_name) or '').strip()
                composed = ''
                try:
                    if lat and lng:
                        flat = float(lat); flng = float(lng)
                        if -90 <= flat <= 90 and -180 <= flng <= 180:
                            composed = f'{flat},{flng}'
                            if place:
                                composed = f'{composed},{place}'
                except ValueError:
                    pass
                answer.text_value = composed or place

            elif qtype == 'file':
                uploaded = request.FILES.get(field_name)
                if uploaded:
                    answer.file_value = uploaded

            elif qtype == 'ranking':
                ranks = {}
                for ch in q.choices.all():
                    raw = request.POST.get(f'{field_name}_rank_{ch.pk}')
                    if raw and raw.strip():
                        try:
                            ranks[str(ch.pk)] = int(raw)
                        except ValueError:
                            pass
                if ranks:
                    answer.text_value = json.dumps(ranks)

            elif qtype == 'section_header':
                answer.delete()
                continue

            else:
                answer.text_value = request.POST.get(field_name, '')

            answer.save()

        response.is_complete = True
        response.completed_at = timezone.now()
        response.save()
        return render(request, 'surveys/thankyou.html', {'survey': survey})


# ---------------------------------------------------------------------------
# Question CRUD
# ---------------------------------------------------------------------------

class AddQuestionView(LoginRequiredMixin, View):
    """Bug #2 fix: parse the `choices` textarea (one per line) — not a list."""

    def post(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        order = (
            survey.questions.aggregate(m=Count('id'))['m'] or 0
        ) + 1

        question = Question.objects.create(
            survey=survey,
            question_type=request.POST['question_type'],
            text=request.POST.get('text', '').strip(),
            description=request.POST.get('description', ''),
            order=order,
            is_required=bool(request.POST.get('is_required')),
            scale_min=self._int(request.POST.get('scale_min'), 1),
            scale_max=self._int(request.POST.get('scale_max'), 5),
            scale_min_label=request.POST.get('scale_min_label', '').strip(),
            scale_max_label=request.POST.get('scale_max_label', '').strip(),
        )

        # Auto-create yes/no choices if needed
        if question.question_type == 'yes_no':
            QuestionChoice.objects.bulk_create([
                QuestionChoice(question=question, text='Yes', value='yes', order=0),
                QuestionChoice(question=question, text='No', value='no', order=1),
            ])

        # Parse the textarea: one choice per line.
        # Also accept the legacy form field name `choice` (multiple inputs)
        # so the view stays backward compatible.
        choice_lines = []
        if 'choices' in request.POST:
            raw = request.POST.get('choices', '')
            choice_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        elif 'choice' in request.POST:
            choice_lines = [
                c.strip() for c in request.POST.getlist('choice') if c.strip()
            ]

        if question.question_type in ('radio', 'checkbox', 'dropdown') and choice_lines:
            QuestionChoice.objects.bulk_create([
                QuestionChoice(question=question, text=line, order=i)
                for i, line in enumerate(choice_lines)
            ])

        messages.success(request, 'Question added.')
        return redirect('surveys:builder', pk=pk)

    @staticmethod
    def _int(val, default):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default


class ReorderQuestionsView(LoginRequiredMixin, View):
    def post(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
        order_data = payload.get('order', [])
        for new_order, q_id in enumerate(order_data, start=1):
            Question.objects.filter(pk=q_id, survey=survey).update(order=new_order)
        return JsonResponse({'ok': True})


class DeleteQuestionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        q = get_object_or_404(Question, pk=pk)
        survey_id = q.survey_id
        q.delete()
        # Re-tighten ordering so the visual numbers stay 1..N
        for i, remaining in enumerate(
            Question.objects.filter(survey_id=survey_id).order_by('order', 'pk'),
            start=1,
        ):
            if remaining.order != i:
                Question.objects.filter(pk=remaining.pk).update(order=i)
        messages.success(request, 'Question deleted.')
        return redirect('surveys:builder', pk=survey_id)


# ---------------------------------------------------------------------------
# Results — comprehensive analytics for admins (unchanged from prior turn)
# ---------------------------------------------------------------------------

class SurveyResultsView(LoginRequiredMixin, View):
    def get(self, request, pk):
        survey = get_object_or_404(Survey, pk=pk)
        if not _can_view_results(request.user):
            return HttpResponseForbidden(
                "You don't have permission to view survey results. "
                "M&E admins or superusers only."
            )

        questions = list(
            survey.questions.filter(is_active=True)
                  .prefetch_related('choices', 'answers__selected_choices')
                  .order_by('order')
        )
        responses = list(
            survey.responses.select_related('respondent')
                  .prefetch_related('answers__selected_choices')
                  .order_by('-started_at')
        )

        total_responses = len(responses)
        complete_responses = sum(1 for r in responses if r.is_complete)
        completion_rate = round((complete_responses / total_responses) * 100, 1) if total_responses else 0.0
        avg_duration_seconds = self._avg_duration(responses)

        timeline_chart = self._timeline_chart(responses)
        qtype_chart = self._qtype_distribution_chart(questions)

        question_blocks = []
        geo_points = []
        for q in questions:
            block = self._analyze_question(q)
            if block:
                question_blocks.append(block)
            if q.question_type == 'geo':
                geo_points.extend(self._collect_geo_points(q))

        map_block = self._map_block(geo_points) if geo_points else None
        recent = responses[:25]

        return render(request, 'surveys/results.html', {
            'survey': survey,
            'total_responses': total_responses,
            'complete_responses': complete_responses,
            'completion_rate': completion_rate,
            'avg_duration': avg_duration_seconds,
            'questions': questions,
            'question_count': len(questions),
            'required_count': sum(1 for q in questions if q.is_required),
            'recent': recent,
            'timeline_chart_json': json.dumps(timeline_chart) if timeline_chart else 'null',
            'qtype_chart_json': json.dumps(qtype_chart) if qtype_chart else 'null',
            'question_blocks_json': json.dumps(question_blocks),
            'question_blocks': question_blocks,
            'map_block_json': json.dumps(map_block) if map_block else None,
            'has_geo': bool(map_block),
        })

    @staticmethod
    def _avg_duration(responses):
        durations = []
        for r in responses:
            if r.is_complete and r.started_at and r.completed_at:
                d = (r.completed_at - r.started_at).total_seconds()
                if 0 <= d <= 60 * 60 * 24:
                    durations.append(d)
        return round(mean(durations)) if durations else 0

    @staticmethod
    def _timeline_chart(responses):
        if not responses:
            return None
        buckets = defaultdict(int)
        for r in responses:
            if r.started_at:
                buckets[r.started_at.date()] += 1
        if not buckets:
            return None
        days = sorted(buckets)
        start, end = days[0], days[-1]
        filled = []
        cursor = start
        while cursor <= end:
            filled.append((cursor, buckets.get(cursor, 0)))
            cursor += timedelta(days=1)
        return {
            'data': [{
                'type': 'scatter', 'mode': 'lines+markers',
                'x': [d.isoformat() for d, _ in filled],
                'y': [n for _, n in filled],
                'fill': 'tozeroy',
                'line': {'color': '#0077c8', 'width': 2.5},
                'marker': {'color': '#0077c8', 'size': 7},
                'name': 'Responses',
                'hovertemplate': '<b>%{x|%d %b %Y}</b><br>%{y} response(s)<extra></extra>',
            }],
            'layout': {
                'margin': {'l': 40, 'r': 16, 't': 16, 'b': 40},
                'xaxis': {'gridcolor': '#f1f5f9'},
                'yaxis': {'gridcolor': '#f1f5f9', 'rangemode': 'tozero'},
                'plot_bgcolor': '#ffffff', 'paper_bgcolor': '#ffffff',
                'showlegend': False, 'height': 240,
            },
        }

    @staticmethod
    def _qtype_distribution_chart(questions):
        if not questions:
            return None
        type_label = dict(Question.TYPE_CHOICES)
        c = Counter(q.question_type for q in questions)
        items = sorted(c.items(), key=lambda kv: -kv[1])
        palette = ['#0077c8', '#16a34a', '#7c3aed', '#f59e0b', '#dc2626',
                   '#0891b2', '#db2777', '#84cc16', '#64748b', '#ea580c']
        return {
            'data': [{
                'type': 'pie',
                'labels': [type_label.get(k, k) for k, _ in items],
                'values': [v for _, v in items],
                'hole': 0.55,
                'textinfo': 'label+percent',
                'textfont': {'size': 11},
                'marker': {'colors': palette[:len(items)]},
                'hovertemplate': '<b>%{label}</b><br>%{value} question(s)<extra></extra>',
            }],
            'layout': {
                'margin': {'l': 8, 'r': 8, 't': 8, 'b': 8},
                'paper_bgcolor': '#ffffff',
                'showlegend': False, 'height': 240,
            },
        }

    def _analyze_question(self, q):
        answers = list(q.answers.all())
        answered = sum(1 for a in answers if self._is_answered(a, q))
        skipped = len(answers) - answered
        base = {
            'id': q.pk, 'order': q.order, 'text': q.text,
            'type': q.question_type,
            'type_label': q.get_question_type_display(),
            'is_required': q.is_required,
            'description': q.description,
            'answered': answered, 'skipped': skipped, 'total': len(answers),
        }
        if q.question_type in ('radio', 'dropdown', 'yes_no'):
            base.update(self._categorical(q, answers, multi=False))
        elif q.question_type == 'checkbox':
            base.update(self._categorical(q, answers, multi=True))
        elif q.question_type in ('likert', 'rating'):
            base.update(self._numeric_scale(q, answers))
        elif q.question_type == 'number':
            base.update(self._number(q, answers))
        elif q.question_type == 'date':
            base.update(self._date(q, answers))
        elif q.question_type in ('text', 'textarea'):
            base.update(self._text(q, answers))
        elif q.question_type == 'geo':
            base.update(self._geo_summary(q, answers))
        elif q.question_type == 'file':
            base.update({'render': 'simple_count',
                         'detail': f'{answered} file(s) uploaded'})
        elif q.question_type == 'section_header':
            return None
        else:
            base.update({'render': 'unsupported'})
        return base

    @staticmethod
    def _is_answered(a, q):
        if q.question_type in ('text', 'textarea', 'geo'):
            return bool((a.text_value or '').strip())
        if q.question_type == 'number' or q.question_type in ('likert', 'rating'):
            return a.number_value is not None
        if q.question_type == 'date':
            return a.date_value is not None
        if q.question_type in ('radio', 'checkbox', 'dropdown', 'yes_no'):
            return a.selected_choices.exists()
        if q.question_type == 'file':
            return bool(a.file_value)
        return False

    def _categorical(self, q, answers, multi=False):
        choices = list(q.choices.all().order_by('order'))
        labels = [c.text for c in choices]
        counts = Counter()
        for a in answers:
            for ch in a.selected_choices.all():
                counts[ch.text] += 1
        values = [counts.get(c.text, 0) for c in choices]
        total_picks = sum(values)
        order = sorted(range(len(labels)), key=lambda i: -values[i])
        labels_sorted = [labels[i] for i in order]
        values_sorted = [values[i] for i in order]
        chart = {
            'data': [{
                'type': 'bar', 'orientation': 'h',
                'x': values_sorted, 'y': labels_sorted,
                'marker': {'color': '#0077c8'},
                'hovertemplate': '<b>%{y}</b><br>%{x} response(s)<extra></extra>',
            }],
            'layout': {
                'margin': {'l': 160, 'r': 24, 't': 8, 'b': 32},
                'xaxis': {'gridcolor': '#f1f5f9', 'rangemode': 'tozero', 'tickformat': 'd'},
                'yaxis': {'automargin': True, 'autorange': 'reversed'},
                'plot_bgcolor': '#ffffff', 'paper_bgcolor': '#ffffff',
                'showlegend': False,
                'height': max(180, 32 * len(labels) + 60),
            },
        }
        top_label, top_val = (labels_sorted[0], values_sorted[0]) if values_sorted else (None, 0)
        return {
            'render': 'categorical', 'multi': multi, 'chart': chart,
            'total_picks': total_picks, 'top_label': top_label,
            'top_pct': round((top_val / total_picks * 100), 1) if total_picks else 0.0,
            'choice_count': len(choices),
        }

    def _numeric_scale(self, q, answers):
        values = [float(a.number_value) for a in answers if a.number_value is not None]
        if not values:
            return {'render': 'empty'}
        scale = list(range(int(q.scale_min), int(q.scale_max) + 1))
        counts = Counter(int(round(v)) for v in values)
        bar_values = [counts.get(s, 0) for s in scale]
        labels = [str(s) for s in scale]
        if q.scale_min_label and scale:
            labels[0] = f'{scale[0]} — {q.scale_min_label}'
        if q.scale_max_label and len(scale) > 1:
            labels[-1] = f'{scale[-1]} — {q.scale_max_label}'
        heat = ['#ef4444', '#f59e0b', '#eab308', '#84cc16', '#16a34a',
                '#16a34a', '#16a34a', '#16a34a', '#16a34a', '#16a34a']
        colors = [heat[min(i, len(heat) - 1)] for i in range(len(scale))]
        chart = {
            'data': [{
                'type': 'bar', 'x': labels, 'y': bar_values,
                'marker': {'color': colors},
                'text': bar_values, 'textposition': 'outside',
                'hovertemplate': '<b>Score %{x}</b><br>%{y} response(s)<extra></extra>',
            }],
            'layout': {
                'margin': {'l': 40, 'r': 16, 't': 24, 'b': 60},
                'xaxis': {'tickangle': 0},
                'yaxis': {'gridcolor': '#f1f5f9', 'rangemode': 'tozero', 'tickformat': 'd'},
                'plot_bgcolor': '#ffffff', 'paper_bgcolor': '#ffffff',
                'showlegend': False, 'height': 260,
            },
        }
        return {
            'render': 'numeric_scale', 'chart': chart,
            'mean': round(mean(values), 2),
            'median': round(median(values), 2),
            'min': min(values), 'max': max(values),
            'count': len(values),
            'scale_label': f'{q.scale_min}–{q.scale_max}',
        }

    def _number(self, q, answers):
        values = [a.number_value for a in answers if a.number_value is not None]
        if not values:
            return {'render': 'empty'}
        chart = {
            'data': [{
                'type': 'histogram', 'x': values,
                'marker': {'color': '#0077c8'},
                'hovertemplate': '<b>Range %{x}</b><br>%{y} response(s)<extra></extra>',
            }],
            'layout': {
                'margin': {'l': 40, 'r': 16, 't': 16, 'b': 40},
                'bargap': 0.05,
                'xaxis': {'gridcolor': '#f1f5f9'},
                'yaxis': {'gridcolor': '#f1f5f9', 'rangemode': 'tozero', 'tickformat': 'd'},
                'plot_bgcolor': '#ffffff', 'paper_bgcolor': '#ffffff',
                'showlegend': False, 'height': 240,
            },
        }
        return {
            'render': 'number', 'chart': chart,
            'mean': round(mean(values), 2),
            'median': round(median(values), 2),
            'min': round(min(values), 2),
            'max': round(max(values), 2),
            'count': len(values),
        }

    def _date(self, q, answers):
        dates = [a.date_value for a in answers if a.date_value]
        if not dates:
            return {'render': 'empty'}
        buckets = Counter(dates)
        days = sorted(buckets)
        chart = {
            'data': [{
                'type': 'bar',
                'x': [d.isoformat() for d in days],
                'y': [buckets[d] for d in days],
                'marker': {'color': '#7c3aed'},
                'hovertemplate': '<b>%{x|%d %b %Y}</b><br>%{y} response(s)<extra></extra>',
            }],
            'layout': {
                'margin': {'l': 40, 'r': 16, 't': 16, 'b': 40},
                'xaxis': {'gridcolor': '#f1f5f9', 'type': 'date'},
                'yaxis': {'gridcolor': '#f1f5f9', 'rangemode': 'tozero', 'tickformat': 'd'},
                'plot_bgcolor': '#ffffff', 'paper_bgcolor': '#ffffff',
                'showlegend': False, 'height': 240,
            },
        }
        return {
            'render': 'date', 'chart': chart,
            'min_date': days[0].isoformat(),
            'max_date': days[-1].isoformat(),
            'count': len(dates),
        }

    @staticmethod
    def _text(q, answers, top_n=8):
        texts = [(a.text_value or '').strip() for a in answers]
        texts = [t for t in texts if t]
        if not texts:
            return {'render': 'empty'}
        stop = {
            'the','a','an','and','or','but','is','are','was','were','i','you',
            'we','they','he','she','it','this','that','of','in','on','at','to',
            'for','with','as','by','be','been','being','have','has','had','do',
            'does','did','not','no','so','if','then','than','too','very','just',
            'my','me','our','us','their','them','his','her','its','all','any',
            'some','more','most','much','many','will','would','should','could',
            'can','may','might',
        }
        words = []
        for t in texts:
            for w in re.findall(r"[a-zA-Z']{3,}", t.lower()):
                if w not in stop:
                    words.append(w)
        word_chart = None
        if words:
            top = Counter(words).most_common(top_n)
            word_chart = {
                'data': [{
                    'type': 'bar', 'orientation': 'h',
                    'x': [n for _, n in reversed(top)],
                    'y': [w for w, _ in reversed(top)],
                    'marker': {'color': '#0891b2'},
                    'hovertemplate': '<b>%{y}</b><br>mentioned %{x} time(s)<extra></extra>',
                }],
                'layout': {
                    'margin': {'l': 100, 'r': 24, 't': 8, 'b': 32},
                    'xaxis': {'gridcolor': '#f1f5f9', 'rangemode': 'tozero', 'tickformat': 'd'},
                    'yaxis': {'automargin': True},
                    'plot_bgcolor': '#ffffff', 'paper_bgcolor': '#ffffff',
                    'showlegend': False,
                    'height': max(160, 28 * len(top) + 40),
                },
            }
        return {
            'render': 'text', 'word_chart': word_chart,
            'samples': texts[:10],
            'count': len(texts),
            'avg_length': round(mean(len(t) for t in texts), 1),
        }

    @staticmethod
    def _geo_summary(q, answers):
        points = []
        for a in answers:
            p = _parse_geo(a.text_value)
            if p:
                points.append(p)
        return {
            'render': 'geo_summary',
            'count': len(points),
            'first_point': points[0] if points else None,
        }

    @staticmethod
    def _collect_geo_points(q):
        result = []
        for a in q.answers.all():
            p = _parse_geo(a.text_value)
            if p:
                p['question'] = q.text[:80]
                result.append(p)
        return result

    @staticmethod
    def _map_block(points):
        if not points:
            return None
        lats = [p['lat'] for p in points]
        lngs = [p['lng'] for p in points]
        center = {'lat': sum(lats) / len(lats), 'lng': sum(lngs) / len(lngs)}
        spread = max(max(lats) - min(lats), max(lngs) - min(lngs))
        if spread < 0.01:    zoom = 13
        elif spread < 0.1:   zoom = 11
        elif spread < 1:     zoom = 8
        elif spread < 10:    zoom = 5
        else:                zoom = 3
        hover = []
        for p in points:
            label = p.get('label') or 'Response location'
            hover.append(f'{label}<br>{p["lat"]:.4f}, {p["lng"]:.4f}<br><i>{p.get("question", "")}</i>')
        return {
            'data': [{
                'type': 'scattermapbox',
                'lat': lats, 'lon': lngs, 'mode': 'markers',
                'marker': {'size': 12, 'color': '#0077c8', 'opacity': 0.85},
                'text': hover, 'hoverinfo': 'text',
            }],
            'layout': {
                'mapbox': {'style': 'open-street-map', 'center': center, 'zoom': zoom},
                'margin': {'l': 0, 'r': 0, 't': 0, 'b': 0},
                'height': 480, 'showlegend': False,
            },
            'count': len(points),
        }