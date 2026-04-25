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


class UpdateProjectStatusView(LoginRequiredMixin, View):
    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        cycle_id = request.POST.get('cycle_id')
        status = request.POST.get('status')
        if cycle_id and status:
            cycle = get_object_or_404(ReportingCycle, pk=cycle_id)
            obj, _ = ProjectReportingStatus.objects.get_or_create(project=project, cycle=cycle)
            obj.status = status
            if 'notes' in request.POST:
                obj.notes = request.POST.get('notes', '')
            obj.updated_by = request.user
            obj.save()
            messages.success(request, 'Status updated.')
        return redirect(request.META.get('HTTP_REFERER', 'projects:tracker'))


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


class ReportingCycleCreateView(CountryAdminRequiredMixin, LoginRequiredMixin, View):
    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        if not co:
            messages.error(request, 'No active country office.')
            return redirect('projects:cycles')

        form = ReportingCycleForm(request.POST)
        if form.is_valid():
            cycle = form.save(commit=False)
            cycle.country_office = co
            try:
                cycle.save()
                messages.success(
                    request,
                    f'Cycle {cycle.year} {cycle.quarter} ({cycle.get_cycle_type_display()}) created.'
                )
            except Exception as e:
                messages.error(request, f'Could not create cycle: {e}')
        else:
            messages.error(
                request,
                'Please fix the errors: ' + '; '.join(
                    f'{k}: {", ".join(v)}' for k, v in form.errors.items()
                )
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

class ReportingTrackerView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        year = int(request.GET.get('year', timezone.now().year))
        cycle_type = request.GET.get('type', 'progress')
        quarters = ['Q1', 'Q2', 'Q3', 'Q4']

        projects = (
            Project.objects.filter(country_office=co).select_related('programme_unit')
            if co else Project.objects.none()
        )
        units = (
            ProgrammeUnit.objects.filter(country_office=co, is_active=True)
            if co else ProgrammeUnit.objects.none()
        )

        cycles_qs = ReportingCycle.objects.filter(
            country_office=co, year=year, cycle_type=cycle_type
        ) if co else ReportingCycle.objects.none()
        cycles_by_quarter = {c.quarter: c for c in cycles_qs}

        cycle_ids = [c.pk for c in cycles_by_quarter.values()]
        statuses_qs = ProjectReportingStatus.objects.filter(
            project__in=projects, cycle_id__in=cycle_ids
        ) if cycle_ids else ProjectReportingStatus.objects.none()
        status_map = {(s.project_id, s.cycle_id): s for s in statuses_qs}

        tracker_data = []
        for unit in units:
            unit_projects = projects.filter(programme_unit=unit)
            rows = []
            for project in unit_projects:
                row = {'project': project, 'statuses': {}}
                for q in quarters:
                    cycle = cycles_by_quarter.get(q)
                    row['statuses'][q] = status_map.get((project.pk, cycle.pk)) if cycle else None
                rows.append(row)
            tracker_data.append({'unit': unit, 'rows': rows})

        orphan_projects = projects.filter(programme_unit__isnull=True)
        if orphan_projects.exists():
            rows = []
            for project in orphan_projects:
                row = {'project': project, 'statuses': {}}
                for q in quarters:
                    cycle = cycles_by_quarter.get(q)
                    row['statuses'][q] = status_map.get((project.pk, cycle.pk)) if cycle else None
                rows.append(row)
            tracker_data.append({
                'unit': type('Unit', (), {
                    'name': 'Unassigned', 'color': '#94a3b8', 'pk': None,
                })(),
                'rows': rows,
            })

        return render(request, 'projects/tracker.html', {
            'tracker_data': tracker_data, 'year': year, 'quarters': quarters,
            'cycle_type': cycle_type, 'years': [2024, 2025, 2026, 2027, 2028],
            'cycles': cycles_qs,
        })


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