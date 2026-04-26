from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, HttpResponseForbidden
from django.urls import reverse
from django.db.models import Q

from .forms import (
    ProjectForm, ProjectReportingStatusForm,
    ReportingCycleForm, DonorReportingTimelineForm,
    CPDFrameworkForm, CPDOutcomeForm, CPDIndicatorForm,
)
from .models import (
    Project, ProgrammeUnit, ProjectReportingStatus, ReportingCycle,
    DonorReportingTimeline, CPDFramework, CPDOutcome, CPDIndicator,
)

from apps.accounts.scoping import (
    is_admin, is_me_officer, role_label,
    tracker_access, user_can_edit_tracker_for, user_can_see_project,
    user_projects, user_units,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_co_admin(request):
    """
    Return True if the current user can manage configuration in their active
    country office. Superusers always pass; otherwise we check a couple of
    common attribute names so this works whether your accounts app uses
    `is_co_admin`, `is_country_office_admin`, or a method.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_global_admin', False):
        return True
    co = getattr(request, 'active_country_office', None)
    if co is None:
        return False
    # Common access patterns — try whichever your app provides.
    for attr in ('is_co_admin', 'is_country_office_admin'):
        flag = getattr(user, attr, None)
        if callable(flag):
            try:
                if flag(co):
                    return True
            except TypeError:
                if flag():
                    return True
        elif flag:
            return True
    # AccessChecker fallback (matches the README's described pattern)
    checker = getattr(user, 'access', None)
    if checker and hasattr(checker, 'is_co_admin'):
        try:
            return bool(checker.is_co_admin(co))
        except Exception:
            return False
    return False


class CountryAdminRequiredMixin(UserPassesTestMixin):
    """403 unless the user is a CO admin / superuser for the active CO."""
    raise_exception = True

    def test_func(self):
        return _is_co_admin(self.request)


# ---------------------------------------------------------------------------
# Projects (unchanged)
# ---------------------------------------------------------------------------

class ProjectListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        projects = (
            Project.objects.filter(country_office=co).select_related('programme_unit')
            if co else Project.objects.none()
        )
        units = ProgrammeUnit.objects.filter(country_office=co) if co else ProgrammeUnit.objects.none()

        status_filter = request.GET.get('status')
        unit_filter = request.GET.get('unit')
        if status_filter:
            projects = projects.filter(status=status_filter)
        if unit_filter:
            projects = projects.filter(programme_unit_id=unit_filter)

        return render(request, 'projects/list.html', {
            'projects': projects, 'units': units,
            'status_choices': Project.STATUS_CHOICES,
            'status_filter': status_filter, 'unit_filter': unit_filter,
        })


class ProjectDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        statuses = (
            ProjectReportingStatus.objects.filter(project=project)
            .select_related('cycle').order_by('-cycle__year', '-cycle__quarter')
        )
        return render(request, 'projects/detail.html', {
            'project': project, 'statuses': statuses,
        })


class ProjectCreateView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        return render(request, 'projects/form.html', {
            'units': ProgrammeUnit.objects.filter(country_office=co) if co else ProgrammeUnit.objects.none(),
            'status_choices': Project.STATUS_CHOICES,
            'donor_types': Project.DONOR_TYPES,
        })

    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        try:
            p = Project.objects.create(
                country_office=co,
                programme_unit=ProgrammeUnit.objects.get(pk=request.POST['programme_unit']),
                pims_id=request.POST.get('pims_id', ''),
                title=request.POST['title'],
                short_title=request.POST.get('short_title', ''),
                description=request.POST.get('description', ''),
                donor=request.POST.get('donor', ''),
                donor_type=request.POST.get('donor_type', ''),
                total_budget=request.POST.get('total_budget') or None,
                start_date=request.POST['start_date'],
                end_date=request.POST['end_date'],
                status=request.POST.get('status', 'active'),
                responsible_person=request.POST.get('responsible_person', ''),
                data_source_partner=request.POST.get('data_source_partner', ''),
                created_by=request.user,
            )
            messages.success(request, f'Project "{p.display_title}" created.')
            return redirect('projects:detail', pk=p.pk)
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('projects:create')


class ProjectEditView(LoginRequiredMixin, View):
    SIMPLE_FIELDS = (
        'pims_id', 'title', 'short_title', 'description',
        'donor', 'donor_type', 'status',
        'responsible_person', 'data_source_partner',
        'programme_reviewer', 'pmsu_reviewer', 'final_clearance',
    )

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        co = getattr(request, 'active_country_office', None)
        return render(request, 'projects/form.html', {
            'project': project,
            'units': ProgrammeUnit.objects.filter(country_office=co) if co else ProgrammeUnit.objects.none(),
            'status_choices': Project.STATUS_CHOICES,
            'donor_types': Project.DONOR_TYPES,
        })

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        for field in self.SIMPLE_FIELDS:
            val = request.POST.get(field)
            if val is not None:
                setattr(project, field, val)

        unit_id = request.POST.get('programme_unit')
        if unit_id:
            try:
                project.programme_unit = ProgrammeUnit.objects.get(pk=unit_id)
            except ProgrammeUnit.DoesNotExist:
                messages.error(request, 'Selected programme unit not found.')

        for date_field in ('start_date', 'end_date'):
            val = request.POST.get(date_field)
            if val:
                setattr(project, date_field, val)

        budget = request.POST.get('total_budget')
        if budget == '':
            project.total_budget = None
        elif budget is not None:
            try:
                project.total_budget = budget
            except (TypeError, ValueError):
                pass

        try:
            project.save()
            messages.success(request, 'Project updated.')
        except Exception as e:
            messages.error(request, f'Error saving project: {e}')
            return redirect('projects:edit', pk=pk)
        return redirect('projects:detail', pk=pk)

# ---------------------------------------------------------------------------
# Reporting Cycles — list + create / edit / delete via modals
# ---------------------------------------------------------------------------

class ReportingCycleListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        cycles = (
            ReportingCycle.objects.filter(country_office=co)
            .order_by('-year', 'quarter', 'cycle_type')
            if co else ReportingCycle.objects.none()
        )
        form = ReportingCycleForm()
        return render(request, 'projects/cycles.html', {
            'cycles': cycles,
            'today': timezone.now().date(),
            'form': form,
            'can_manage': _is_co_admin(request),
        })


VALID_QUARTERS = ('Q1', 'Q2', 'Q3', 'Q4')
VALID_TYPES = ('progress', 'verification')


def _today_year_quarter():
    today = timezone.now().date()
    quarter = f'Q{((today.month - 1) // 3) + 1}'
    return today.year, quarter


class ReportingCycleCreateView(LoginRequiredMixin, View):
    """
    Create a new reporting cycle. Supports prefill via query string:
        ?year=2026&quarter=Q2&type=progress
    so the dashboard "Create cycle" link can drop you in with values
    already filled.
    """

    def _check_permission(self, request):
        co = getattr(request, 'active_country_office', None)
        return is_admin(request.user, co) or is_me_officer(request.user, co)

    def _initial(self, request):
        today_year, today_quarter = _today_year_quarter()
        try:
            year = int(request.GET.get('year') or today_year)
        except (TypeError, ValueError):
            year = today_year

        quarter = request.GET.get('quarter') or today_quarter
        if quarter not in VALID_QUARTERS:
            quarter = today_quarter

        cycle_type = request.GET.get('type') or 'progress'
        if cycle_type not in VALID_TYPES:
            cycle_type = 'progress'

        return {
            'year': year,
            'quarter': quarter,
            'cycle_type': cycle_type,
            'today_year': today_year,
            'today_quarter': today_quarter,
            'is_prefilled': bool(
                request.GET.get('year') or request.GET.get('quarter')
            ),
        }

    def get(self, request):
        if not self._check_permission(request):
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden(
                "Only M&E officers and administrators can create cycles."
            )
        return render(request, 'projects/cycle_form.html', {
            'mode': 'create',
            'initial': self._initial(request),
            'years': list(range(timezone.now().year - 1, timezone.now().year + 4)),
            'quarters': VALID_QUARTERS,
            'cycle_types': VALID_TYPES,
        })

    def post(self, request):
        if not self._check_permission(request):
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Permission denied.")

        co = getattr(request, 'active_country_office', None)
        if not co:
            messages.error(request, 'No active country office.')
            return redirect('projects:cycle_create')

        try:
            year = int(request.POST.get('year'))
        except (TypeError, ValueError):
            messages.error(request, 'Invalid year.')
            return redirect('projects:cycle_create')

        quarter = request.POST.get('quarter')
        cycle_type = request.POST.get('cycle_type')
        if quarter not in VALID_QUARTERS or cycle_type not in VALID_TYPES:
            messages.error(request, 'Invalid quarter or cycle type.')
            return redirect('projects:cycle_create')

        # Idempotent: if a cycle already exists for this (CO, year, quarter,
        # cycle_type), update it rather than failing with IntegrityError.
        cycle, created = ReportingCycle.objects.update_or_create(
            country_office=co,
            year=year,
            quarter=quarter,
            cycle_type=cycle_type,
            defaults={
                'reporting_timeline': request.POST.get('reporting_timeline', ''),
                'submission_deadline': request.POST.get('submission_deadline') or None,
                'programme_review_dates': request.POST.get('programme_review_dates', ''),
                'pmsu_review_dates': request.POST.get('pmsu_review_dates', ''),
                'final_clearance_dates': request.POST.get('final_clearance_dates', ''),
                'final_report_due': request.POST.get('final_report_due') or None,
            },
        )
        verb = 'created' if created else 'updated'
        messages.success(
            request,
            f'Reporting cycle {year} {quarter} ({cycle.get_cycle_type_display()}) {verb}.',
        )
        return redirect('projects:cycles')


class ReportingCycleEditView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def get(self, request, pk):
        """Return cycle data as JSON for the modal to populate."""
        co = getattr(request, 'active_country_office', None)
        cycle = get_object_or_404(ReportingCycle, pk=pk, country_office=co)
        return JsonResponse({
            'id': cycle.pk,
            'year': cycle.year,
            'quarter': cycle.quarter,
            'cycle_type': cycle.cycle_type,
            'reporting_timeline': cycle.reporting_timeline,
            'submission_deadline': cycle.submission_deadline.isoformat() if cycle.submission_deadline else '',
            'programme_review_dates': cycle.programme_review_dates,
            'pmsu_review_dates': cycle.pmsu_review_dates,
            'final_clearance_dates': cycle.final_clearance_dates,
            'final_report_due': cycle.final_report_due.isoformat() if cycle.final_report_due else '',
        })

    def post(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        cycle = get_object_or_404(ReportingCycle, pk=pk, country_office=co)
        form = ReportingCycleForm(request.POST, instance=cycle)
        if form.is_valid():
            form.save()
            messages.success(request, f'Cycle {cycle.year} {cycle.quarter} updated.')
        else:
            messages.error(request, 'Please fix the form errors.')
        return redirect('projects:cycles')


class ReportingCycleDeleteView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def post(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        cycle = get_object_or_404(ReportingCycle, pk=pk, country_office=co)
        label = f'{cycle.year} {cycle.quarter} ({cycle.get_cycle_type_display()})'
        cycle.delete()
        messages.success(request, f'Cycle {label} deleted.')
        return redirect('projects:cycles')


# ---------------------------------------------------------------------------
# Tracker (unchanged)
# ---------------------------------------------------------------------------

QUARTER_ORDER = ['Q1', 'Q2', 'Q3', 'Q4']
ALL_QUARTERS = ['Q1', 'Q2', 'Q3', 'Q4']


class ReportingTrackerView(LoginRequiredMixin, View):
    def get(self, request):
        from apps.projects.models import (
            ProgrammeUnit, Project, ProjectReportingStatus, ReportingCycle,
        )

        co = getattr(request, 'active_country_office', None)
        access = tracker_access(request.user, co)

        if access == 'none':
            return HttpResponseForbidden(
                "The reporting tracker is reserved for M&E officers, "
                "country-office administrators, and unit-attached editors. "
                "Contact your country-office administrator if you need access."
            )

        # Filters
        try:
            year = int(request.GET.get('year') or timezone.now().year)
        except (TypeError, ValueError):
            year = timezone.now().year
        cycle_type = request.GET.get('type') or 'progress'
        if cycle_type not in ('progress', 'verification'):
            cycle_type = 'progress'

        unit_filter_id = request.GET.get('unit')

        # Available years for the selector
        year_qs = (
            ReportingCycle.objects
            .filter(country_office=co, cycle_type=cycle_type) if co
            else ReportingCycle.objects.none()
        )
        years = sorted(set(year_qs.values_list('year', flat=True)), reverse=True)
        if year not in years and years:
            year = years[0]
        if not years:
            years = [timezone.now().year]

        # Cycles for the selected year, ordered Q1..Q4
        cycles = list(
            year_qs.filter(year=year)
            .order_by('quarter')
        )
        cycles_by_quarter = {c.quarter: c for c in cycles}

        # Visible units (scoped)
        visible_units = user_units(request.user, co)
        if unit_filter_id and access == 'global':
            visible_units = visible_units.filter(pk=unit_filter_id)

        # Projects within those units
        projects_qs = (
            Project.objects
            .filter(country_office=co, programme_unit__in=visible_units)
            .select_related('programme_unit')
            .order_by('programme_unit__name', 'title')
        )

        # Status rows for current year+cycle_type
        cycle_ids = [c.pk for c in cycles]
        status_rows = {}
        if cycle_ids:
            for s in ProjectReportingStatus.objects.filter(
                    project__in=projects_qs, cycle_id__in=cycle_ids,
            ).select_related('cycle'):
                status_rows[(s.project_id, s.cycle.quarter)] = s

        # Group projects by unit for the cluster-row layout
        groups_dict = {}
        for p in projects_qs:
            unit = p.programme_unit
            key = unit.pk if unit else None
            if key not in groups_dict:
                groups_dict[key] = {'unit': unit, 'rows': []}
            row_statuses = {}
            for q in ALL_QUARTERS:
                row_statuses[q] = status_rows.get((p.pk, q))
            groups_dict[key]['rows'].append({
                'project': p,
                'statuses': row_statuses,
                'can_edit': user_can_edit_tracker_for(request.user, p),
            })

        # Stable ordering by unit name; "no unit" group goes last
        tracker_data = sorted(
            groups_dict.values(),
            key=lambda g: (g['unit'] is None, g['unit'].name if g['unit'] else ''),
        )

        return render(request, 'projects/tracker.html', {
            'tracker_data': tracker_data,
            'years': years,
            'year': year,
            'quarters': ALL_QUARTERS,
            'cycles_by_quarter': cycles_by_quarter,
            'cycle_type': cycle_type,
            'tracker_access': access,
            'role_label': role_label(request.user, co),
            'unit_options': user_units(request.user, co) if access == 'global' else None,
            'unit_filter_id': unit_filter_id,
        })


class UpdateProjectStatusView(LoginRequiredMixin, View):
    """
    Tracker write — used by the per-cell dropdown.
    Enforces: actor must be able to edit THIS project's unit.
    """

    def post(self, request, pk):
        from apps.projects.models import (
            Project, ProjectReportingStatus, ReportingCycle,
        )

        project = get_object_or_404(Project, pk=pk)
        if not user_can_see_project(request.user, project):
            return HttpResponseForbidden("Project not in your scope.")
        if not user_can_edit_tracker_for(request.user, project):
            return HttpResponseForbidden(
                "Only M&E officers, administrators, and editors assigned to "
                "this unit can update its tracker."
            )

        cycle_id = request.POST.get('cycle_id')
        new_status = request.POST.get('status')
        notes = request.POST.get('notes', '').strip()

        if not cycle_id or not new_status:
            messages.error(request, 'Cycle and status are required.')
            return redirect(request.META.get('HTTP_REFERER', 'projects:tracker'))

        cycle = get_object_or_404(ReportingCycle, pk=cycle_id)
        valid_statuses = {c[0] for c in ProjectReportingStatus.STATUS_CHOICES}
        if new_status not in valid_statuses:
            messages.error(request, 'Invalid status.')
            return redirect(request.META.get('HTTP_REFERER', 'projects:tracker'))

        obj, _ = ProjectReportingStatus.objects.update_or_create(
            project=project, cycle=cycle,
            defaults={
                'status': new_status,
                'notes': notes or '',
                'updated_by': request.user,
            },
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'ok': True,
                'status': obj.status,
                'status_display': obj.get_status_display(),
                'status_color': obj.get_status_color(),
            })

        messages.success(
            request, f'Updated {project.display_title} for {cycle.year} {cycle.quarter}.'
        )
        return redirect(request.META.get('HTTP_REFERER', 'projects:tracker'))


# ---------------------------------------------------------------------------
# Donor Reporting Timelines — list + CRUD via modals
# ---------------------------------------------------------------------------

class DonorTimelineView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        timelines = (
            DonorReportingTimeline.objects.filter(country_office=co)
            .select_related('project').order_by('donor', 'project__title')
            if co else DonorReportingTimeline.objects.none()
        )
        projects = (
            Project.objects.filter(country_office=co).order_by('title')
            if co else Project.objects.none()
        )
        return render(request, 'projects/donor_timelines.html', {
            'timelines': timelines,
            'projects': projects,
            'form': DonorReportingTimelineForm(country_office=co),
            'can_manage': _is_co_admin(request),
        })


class DonorTimelineCreateView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        if not co:
            messages.error(request, 'No active country office.')
            return redirect('projects:donor_timelines')

        form = DonorReportingTimelineForm(request.POST, country_office=co)
        if form.is_valid():
            t = form.save(commit=False)
            t.country_office = co
            t.save()
            messages.success(request, f'Donor timeline for {t.donor} added.')
        else:
            messages.error(
                request,
                'Please fix: ' + '; '.join(
                    f'{k}: {", ".join(v)}' for k, v in form.errors.items()
                )
            )
        return redirect('projects:donor_timelines')


class DonorTimelineEditView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def get(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        t = get_object_or_404(DonorReportingTimeline, pk=pk, country_office=co)
        return JsonResponse({
            'id': t.pk,
            'project': t.project_id,
            'donor': t.donor,
            'reporting_frequency': t.reporting_frequency,
            'period_1': t.period_1,
            'internal_draft_1': t.internal_draft_1,
            'programme_review_1': t.programme_review_1,
            'pmsu_review_1': t.pmsu_review_1,
            'final_submission_1': t.final_submission_1,
            'period_2': t.period_2,
            'internal_draft_2': t.internal_draft_2,
            'programme_review_2': t.programme_review_2,
            'pmsu_review_2': t.pmsu_review_2,
            'final_submission_2': t.final_submission_2,
            'notes': t.notes,
        })

    def post(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        t = get_object_or_404(DonorReportingTimeline, pk=pk, country_office=co)
        form = DonorReportingTimelineForm(request.POST, instance=t, country_office=co)
        if form.is_valid():
            form.save()
            messages.success(request, f'Donor timeline for {t.donor} updated.')
        else:
            messages.error(request, 'Please fix the form errors.')
        return redirect('projects:donor_timelines')


class DonorTimelineDeleteView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def post(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        t = get_object_or_404(DonorReportingTimeline, pk=pk, country_office=co)
        label = f'{t.donor} — {t.project.display_title}'
        t.delete()
        messages.success(request, f'Timeline removed: {label}.')
        return redirect('projects:donor_timelines')


# ---------------------------------------------------------------------------
# CPD Framework — frameworks, outcomes, indicators all manageable
# ---------------------------------------------------------------------------

class CPDFrameworkView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        frameworks = (
            CPDFramework.objects.filter(country_office=co).order_by('-is_active', '-year_start')
            if co else CPDFramework.objects.none()
        )
        outcomes = (
            CPDOutcome.objects.filter(framework__country_office=co)
            .select_related('framework', 'programme_unit')
            .prefetch_related('indicators')
            .order_by('framework_id', 'order', 'code')
            if co else CPDOutcome.objects.none()
        )
        units = (
            ProgrammeUnit.objects.filter(country_office=co, is_active=True)
            if co else ProgrammeUnit.objects.none()
        )
        return render(request, 'projects/cpd.html', {
            'frameworks': frameworks,
            'outcomes': outcomes,
            'units': units,
            'tier_options': [
                ('impact', 'Impact'),
                ('outcome', 'Outcome'),
                ('output', 'Output'),
            ],
            'framework_form': CPDFrameworkForm(),
            'outcome_form': CPDOutcomeForm(country_office=co),
            'indicator_form': CPDIndicatorForm(country_office=co),
            'can_manage': _is_co_admin(request),
        })


# --- Frameworks ---
class CPDFrameworkCreateView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        if not co:
            messages.error(request, 'No active country office.')
            return redirect('projects:cpd')
        form = CPDFrameworkForm(request.POST)
        if form.is_valid():
            fw = form.save(commit=False)
            fw.country_office = co
            fw.save()
            messages.success(request, f'Framework "{fw.title}" added.')
        else:
            messages.error(request, 'Please fix the form errors.')
        return redirect('projects:cpd')


class CPDFrameworkEditView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def get(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        fw = get_object_or_404(CPDFramework, pk=pk, country_office=co)
        return JsonResponse({
            'id': fw.pk, 'title': fw.title,
            'year_start': fw.year_start, 'year_end': fw.year_end,
            'description': fw.description, 'is_active': fw.is_active,
        })

    def post(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        fw = get_object_or_404(CPDFramework, pk=pk, country_office=co)
        form = CPDFrameworkForm(request.POST, instance=fw)
        if form.is_valid():
            form.save()
            messages.success(request, f'Framework "{fw.title}" updated.')
        else:
            messages.error(request, 'Please fix the form errors.')
        return redirect('projects:cpd')


class CPDFrameworkDeleteView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def post(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        fw = get_object_or_404(CPDFramework, pk=pk, country_office=co)
        title = fw.title
        fw.delete()
        messages.success(request, f'Framework "{title}" deleted.')
        return redirect('projects:cpd')


# --- Outcomes ---
class CPDOutcomeCreateView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        form = CPDOutcomeForm(request.POST, country_office=co)
        if form.is_valid():
            o = form.save()
            messages.success(request, f'Outcome "{o.code}" added.')
        else:
            messages.error(request, 'Please fix the form errors.')
        return redirect('projects:cpd')


class CPDOutcomeEditView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def get(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        o = get_object_or_404(CPDOutcome, pk=pk, framework__country_office=co)
        return JsonResponse({
            'id': o.pk,
            'framework': o.framework_id,
            'programme_unit': o.programme_unit_id or '',
            'code': o.code,
            'tier': o.tier,
            'title': o.title,
            'sp_outcome': o.sp_outcome,
            'order': o.order,
        })

    def post(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        o = get_object_or_404(CPDOutcome, pk=pk, framework__country_office=co)
        form = CPDOutcomeForm(request.POST, instance=o, country_office=co)
        if form.is_valid():
            form.save()
            messages.success(request, f'Outcome "{o.code}" updated.')
        else:
            messages.error(request, 'Please fix the form errors.')
        return redirect('projects:cpd')


class CPDOutcomeDeleteView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def post(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        o = get_object_or_404(CPDOutcome, pk=pk, framework__country_office=co)
        code = o.code
        o.delete()
        messages.success(request, f'Outcome "{code}" deleted.')
        return redirect('projects:cpd')


# --- Indicators ---
class CPDIndicatorCreateView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        form = CPDIndicatorForm(request.POST, country_office=co)
        if form.is_valid():
            ind = form.save()
            messages.success(request, f'Indicator added under {ind.outcome.code}.')
        else:
            messages.error(request, 'Please fix the form errors.')
        return redirect('projects:cpd')


class CPDIndicatorEditView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def get(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        i = get_object_or_404(CPDIndicator, pk=pk, outcome__framework__country_office=co)
        return JsonResponse({
            'id': i.pk,
            'outcome': i.outcome_id,
            'code': i.code,
            'description': i.description,
            'sp_indicator': i.sp_indicator,
            'sp_data_source': i.sp_data_source,
            'cpd_data_source': i.cpd_data_source,
            'frequency': i.frequency,
            'responsible_institution': i.responsible_institution,
            'baseline': i.baseline,
            'end_target': i.end_target,
            'means_of_verification': i.means_of_verification,
            'remarks': i.remarks,
        })

    def post(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        i = get_object_or_404(CPDIndicator, pk=pk, outcome__framework__country_office=co)
        form = CPDIndicatorForm(request.POST, instance=i, country_office=co)
        if form.is_valid():
            form.save()
            messages.success(request, 'Indicator updated.')
        else:
            messages.error(request, 'Please fix the form errors.')
        return redirect('projects:cpd')


class CPDIndicatorDeleteView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def post(self, request, pk):
        co = getattr(request, 'active_country_office', None)
        i = get_object_or_404(CPDIndicator, pk=pk, outcome__framework__country_office=co)
        i.delete()
        messages.success(request, 'Indicator deleted.')
        return redirect('projects:cpd')