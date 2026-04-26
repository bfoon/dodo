from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponseForbidden, JsonResponse

from apps.accounts.models import User
from apps.accounts.scoping import (
    user_units, user_projects, user_can_see_project,
    is_admin, is_me_officer, can_edit_tracker, role_label,
    user_can_edit_tracker_for, tracker_access,
)
from apps.projects.models import CPDIndicator, Project, ReportingCycle
from .models import (
    OutputVerification, MonitoringVisit,
    IndicatorAchievement, ProjectIndicatorAchievement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_quarter():
    month = timezone.now().month
    return f'Q{((month - 1) // 3) + 1}'


# Stage definitions for the verification flow. The ORDER matters:
# index in this list = stage progression. A status of 'completed' means
# all stages 0..3 are also done, even if their date fields are blank.
VERIFICATION_STAGES = [
    {'key': 'pending',              'label': 'Pending',              'short': 'Pending',    'icon': 'flag',           'date_field': None},
    {'key': 'field_verification',   'label': 'Field Verification',   'short': 'Field',      'icon': 'geo-alt',        'date_field': 'field_verification_dates'},
    {'key': 'documentation_review', 'label': 'Documentation Review', 'short': 'Docs',       'icon': 'file-earmark',   'date_field': 'documentation_review_dates'},
    {'key': 'validation_meeting',   'label': 'Validation Meeting',   'short': 'Validation', 'icon': 'people',         'date_field': 'validation_meeting_dates'},
    {'key': 'completed',            'label': 'Completed',            'short': 'Complete',   'icon': 'check2-circle',  'date_field': None},
]
STAGE_INDEX = {s['key']: i for i, s in enumerate(VERIFICATION_STAGES)}


def _stage_states(verification):
    """
    Returns a list of dicts (one per stage) with 'state' set to one of:
        done    - this stage is completed
        current - this is the active stage right now
        future  - not yet reached
        na      - the verification is marked not_applicable
    Plus a display-friendly 'date' string from the corresponding date field.
    """
    states = []
    if verification.status == 'not_applicable':
        for s in VERIFICATION_STAGES:
            states.append({**s, 'state': 'na', 'date': ''})
        return states

    current_idx = STAGE_INDEX.get(verification.status, 0)
    for i, s in enumerate(VERIFICATION_STAGES):
        if i < current_idx:
            state = 'done'
        elif i == current_idx:
            state = 'current'
        else:
            state = 'future'
        date_value = ''
        if s['date_field']:
            date_value = getattr(verification, s['date_field'], '') or ''
        # Special case: the "Complete" date shows verified_at.
        if s['key'] == 'completed' and verification.verified_at:
            date_value = verification.verified_at.strftime('%d %b %Y')
        states.append({**s, 'state': state, 'date': date_value})
    return states


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class MonitoringDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        projects_qs = user_projects(request.user, co)

        if co and projects_qs.exists():
            verifications_qs = OutputVerification.objects.filter(
                project__in=projects_qs
            ).select_related('project', 'cycle', 'verified_by')
            visits_qs = MonitoringVisit.objects.filter(
                project__in=projects_qs
            ).select_related('project').prefetch_related('conducted_by')

            if is_admin(request.user, co) or is_me_officer(request.user, co):
                indicators_qs = CPDIndicator.objects.filter(
                    outcome__framework__country_office=co
                )
            else:
                indicators_qs = CPDIndicator.objects.filter(
                    outcome__framework__country_office=co,
                    outcome__programme_unit__in=user_units(request.user, co),
                )
        else:
            verifications_qs = OutputVerification.objects.none()
            visits_qs = MonitoringVisit.objects.none()
            indicators_qs = CPDIndicator.objects.none()

        cq = _current_quarter()
        cq_months_start = {'Q1': 1, 'Q2': 4, 'Q3': 7, 'Q4': 10}[cq]
        q_start = timezone.now().replace(month=cq_months_start, day=1).date()

        stats = {
            'verifications_total': verifications_qs.count(),
            'verifications_completed': verifications_qs.filter(status='completed').count(),
            'verifications_pending': verifications_qs.exclude(
                status__in=['completed', 'not_applicable']
            ).count(),
            'visits_total': visits_qs.count(),
            'visits_this_quarter': visits_qs.filter(visit_date__gte=q_start).count(),
            'indicators_total': indicators_qs.count(),
            'indicators_with_data': indicators_qs.filter(
                achievements__isnull=False
            ).distinct().count(),
            'active_projects': projects_qs.filter(status='active').count(),
        }

        return render(request, 'monitoring/home.html', {
            'verifications': verifications_qs.order_by(
                '-verified_at', '-cycle__year', '-cycle__quarter'
            )[:10],
            'recent_visits': visits_qs.order_by('-visit_date')[:8],
            'stats': stats,
            'can_edit_tracker': can_edit_tracker(request.user, co),
            'role_label': role_label(request.user, co),
        })


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

class IndicatorListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        if not co:
            indicators = CPDIndicator.objects.none()
        elif is_admin(request.user, co) or is_me_officer(request.user, co):
            indicators = CPDIndicator.objects.filter(
                outcome__framework__country_office=co
            )
        else:
            units = user_units(request.user, co)
            indicators = CPDIndicator.objects.filter(
                outcome__framework__country_office=co,
                outcome__programme_unit__in=units,
            )
        indicators = (
            indicators
            .select_related('outcome', 'outcome__framework', 'outcome__programme_unit')
            .order_by('outcome__order', 'outcome__code', 'code', 'pk')
        )
        return render(request, 'monitoring/indicators.html', {
            'indicators': indicators,
            'can_edit_tracker': can_edit_tracker(request.user, co),
        })


class IndicatorDataEntryView(LoginRequiredMixin, View):
    QUARTERS = ['Q1', 'Q2', 'Q3', 'Q4']

    def _check_access(self, request, indicator):
        co = getattr(request, 'active_country_office', None)
        if is_admin(request.user, co) or is_me_officer(request.user, co):
            return True
        unit = indicator.outcome.programme_unit
        if unit and user_units(request.user, co).filter(pk=unit.pk).exists():
            return True
        return False

    def _context(self, indicator, request):
        current_year = timezone.now().year
        co = getattr(request, 'active_country_office', None)
        return {
            'indicator': indicator,
            'achievements': (
                indicator.achievements
                .select_related('entered_by', 'project')
                .order_by('-year', '-quarter')
            ),
            'years': list(range(current_year - 2, current_year + 3)),
            'quarters': self.QUARTERS,
            'current_year': current_year,
            'current_quarter': _current_quarter(),
            'can_edit_tracker': can_edit_tracker(request.user, co),
        }

    def get(self, request, pk):
        indicator = get_object_or_404(CPDIndicator, pk=pk)
        if not self._check_access(request, indicator):
            return HttpResponseForbidden("This indicator is not in your scope.")
        return render(
            request, 'monitoring/indicator_data.html',
            self._context(indicator, request),
        )

    def post(self, request, pk):
        indicator = get_object_or_404(CPDIndicator, pk=pk)
        if not self._check_access(request, indicator):
            return HttpResponseForbidden("Not in your scope.")
        try:
            year = int(request.POST.get('year') or timezone.now().year)
        except (TypeError, ValueError):
            year = timezone.now().year
        quarter = request.POST.get('quarter') or _current_quarter()

        IndicatorAchievement.objects.update_or_create(
            cpd_indicator=indicator,
            year=year,
            quarter=quarter,
            project=None,
            defaults={
                'achieved_value': request.POST.get('value', ''),
                'notes': request.POST.get('notes', ''),
                'entered_by': request.user,
            },
        )
        messages.success(request, f'Achievement for {year} {quarter} recorded.')
        return redirect('monitoring:indicator_data', pk=pk)


# ---------------------------------------------------------------------------
# Output Verification
# ---------------------------------------------------------------------------

class OutputVerificationListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        access = tracker_access(request.user, co)

        # Anyone with CO access (or unit access) can VIEW their scoped
        # verifications. Only tracker editors can WRITE.
        projects = user_projects(request.user, co)
        verifications = (
            OutputVerification.objects
            .filter(project__in=projects)
            .select_related('project', 'project__programme_unit',
                            'cycle', 'verified_by')
            .order_by('-cycle__year', '-cycle__quarter', 'project__title')
        )

        # Compute per-row stage states + per-row write permission.
        rows = []
        for v in verifications:
            rows.append({
                'v': v,
                'stages': _stage_states(v),
                'can_edit': access != 'none' and user_can_edit_tracker_for(
                    request.user, v.project
                ),
            })

        return render(request, 'monitoring/verification.html', {
            'rows': rows,
            'can_edit_any': access != 'none',
            'role_label': role_label(request.user, co),
            'stages': VERIFICATION_STAGES,
        })


class UpdateVerificationView(LoginRequiredMixin, View):
    """
    Tracker write — restricted to users who can edit the tracker for THIS
    project's unit (M&E officer/admin globally, or unit-scoped editor on
    this verification's unit).

    Two modes:
        - Full update (status + dates + notes via form POST)
        - Stage advance (?action=advance with `stage` parameter — for the
          new clickable-stage UI)
    """

    def _check(self, request, verification):
        if not user_can_see_project(request.user, verification.project):
            return False
        return user_can_edit_tracker_for(request.user, verification.project)

    def post(self, request, pk):
        v = get_object_or_404(OutputVerification, pk=pk)
        if not self._check(request, v):
            return HttpResponseForbidden(
                "You don't have permission to update this verification."
            )

        action = request.POST.get('action', 'update')

        if action == 'advance':
            return self._advance(request, v)
        if action == 'na':
            return self._mark_na(request, v)
        return self._full_update(request, v)

    # ---- handlers --------------------------------------------------------

    def _advance(self, request, v):
        """
        Set the verification to a specific stage by stage key. Used by the
        clickable-stage UI. If the user clicks the current stage, this
        becomes a no-op; if they click an earlier stage, it rolls back.
        """
        new_status = request.POST.get('stage')
        if new_status not in STAGE_INDEX:
            return JsonResponse({'ok': False, 'error': 'invalid stage'}, status=400)

        # Auto-stamp the date field for the stage being advanced TO, if blank.
        target_stage = VERIFICATION_STAGES[STAGE_INDEX[new_status]]
        date_field = target_stage.get('date_field')
        today = timezone.now().date().strftime('%d %b %Y')
        if date_field and not getattr(v, date_field, ''):
            setattr(v, date_field, today)

        old_status = v.status
        v.status = new_status

        # Verifier/timestamp lifecycle:
        if new_status == 'completed':
            # Always re-stamp on transition into completed so the latest
            # verifier wins. (Previous code preserved stale data.)
            v.verified_by = request.user
            v.verified_at = timezone.now()
        elif old_status == 'completed' and new_status != 'completed':
            # Rolling back from completed: clear the verifier so we don't
            # carry stale data into the next completion.
            v.verified_by = None
            v.verified_at = None

        v.save()
        return self._json_ack(v)

    def _mark_na(self, request, v):
        v.status = 'not_applicable'
        v.verified_by = None
        v.verified_at = None
        v.save()
        return self._json_ack(v)

    def _full_update(self, request, v):
        """Form-style update for the inline edit panel (period, notes, dates)."""
        new_status = request.POST.get('status')
        if new_status and new_status in STAGE_INDEX or new_status == 'not_applicable':
            old_status = v.status
            v.status = new_status
            if new_status == 'completed':
                v.verified_by = request.user
                v.verified_at = timezone.now()
            elif old_status == 'completed' and new_status != 'completed':
                v.verified_by = None
                v.verified_at = None

        for field in ('field_verification_dates',
                      'documentation_review_dates',
                      'validation_meeting_dates',
                      'verification_period'):
            if field in request.POST:
                setattr(v, field, request.POST.get(field, '').strip())

        if 'notes' in request.POST:
            v.verification_notes = request.POST.get('notes', '').strip()

        v.save()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return self._json_ack(v)

        messages.success(request, 'Verification updated.')
        return redirect(
            request.META.get('HTTP_REFERER', 'monitoring:verification')
            or 'monitoring:verification'
        )

    def _json_ack(self, v):
        return JsonResponse({
            'ok': True,
            'status': v.status,
            'status_display': v.get_status_display(),
            'status_color': v.get_status_color(),
            'verified_by': v.verified_by.get_full_name() if v.verified_by else '',
            'verified_at': v.verified_at.strftime('%d %b %Y') if v.verified_at else '',
            'field_verification_dates': v.field_verification_dates,
            'documentation_review_dates': v.documentation_review_dates,
            'validation_meeting_dates': v.validation_meeting_dates,
            'stages': [{
                'key': s['key'],
                'state': s['state'],
                'date': s['date'],
            } for s in _stage_states(v)],
        })


# ---------------------------------------------------------------------------
# Monitoring Visits
# ---------------------------------------------------------------------------

class MonitoringVisitListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        projects = user_projects(request.user, co)
        visits = (
            MonitoringVisit.objects
            .filter(project__in=projects)
            .select_related('project')
            .prefetch_related('conducted_by')
            .order_by('-visit_date', '-created_at')
        )
        return render(request, 'monitoring/visits.html', {
            'visits': visits,
            'can_create': can_edit_tracker(request.user, co)
                          or projects.exists(),
        })


class CreateMonitoringVisitView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        projects = user_projects(request.user, co)
        if not projects.exists():
            return HttpResponseForbidden(
                "You don't have any projects in scope to record a visit for."
            )
        return render(request, 'monitoring/visit_form.html', {
            'projects': projects,
            'visit_types': MonitoringVisit.VISIT_TYPE,
            'users': User.objects.filter(is_active=True).order_by(
                'first_name', 'last_name', 'email'
            ),
            'today': timezone.now().date(),
        })

    def post(self, request):
        try:
            project = get_object_or_404(Project, pk=request.POST['project'])
            if not user_can_see_project(request.user, project):
                return HttpResponseForbidden("Project not in your scope.")

            visit = MonitoringVisit.objects.create(
                project=project,
                visit_type=request.POST['visit_type'],
                visit_date=request.POST['visit_date'],
                location=request.POST.get('location', ''),
                purpose=request.POST.get('purpose', ''),
                findings=request.POST.get('findings', ''),
                recommendations=request.POST.get('recommendations', ''),
                follow_up_actions=request.POST.get('follow_up_actions', ''),
                attachments=request.FILES.get('attachments'),
            )

            conducted_ids = request.POST.getlist('conducted_by')
            if conducted_ids:
                visit.conducted_by.set(
                    User.objects.filter(pk__in=conducted_ids, is_active=True)
                )
            else:
                visit.conducted_by.add(request.user)

            messages.success(request, 'Monitoring visit recorded.')
            return redirect('monitoring:visits')
        except KeyError as e:
            messages.error(request, f'Missing required field: {e.args[0]}')
            return redirect('monitoring:create_visit')
        except Exception as e:
            messages.error(request, f'Error saving visit: {e}')
            return redirect('monitoring:create_visit')