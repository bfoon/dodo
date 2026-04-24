from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q

from .models import (
    Project, ProgrammeUnit, ProjectReportingStatus, ReportingCycle,
    DonorReportingTimeline, CPDFramework, CPDOutcome,
)


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
            'projects': projects,
            'units': units,
            'status_choices': Project.STATUS_CHOICES,
            'status_filter': status_filter,
            'unit_filter': unit_filter,
        })


class ProjectDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        statuses = (
            ProjectReportingStatus.objects
            .filter(project=project)
            .select_related('cycle')
            .order_by('-cycle__year', '-cycle__quarter')
        )
        return render(request, 'projects/detail.html', {
            'project': project,
            'statuses': statuses,
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
    # Simple text fields that are always safe to save from POST.
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

        # Simple text / choice fields
        for field in self.SIMPLE_FIELDS:
            val = request.POST.get(field)
            if val is not None:
                setattr(project, field, val)

        # Programme unit (FK)
        unit_id = request.POST.get('programme_unit')
        if unit_id:
            try:
                project.programme_unit = ProgrammeUnit.objects.get(pk=unit_id)
            except ProgrammeUnit.DoesNotExist:
                messages.error(request, 'Selected programme unit not found.')

        # Dates
        for date_field in ('start_date', 'end_date'):
            val = request.POST.get(date_field)
            if val:
                setattr(project, date_field, val)

        # Budget (decimal, optional)
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


class ReportingCycleListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        cycles = (
            ReportingCycle.objects.filter(country_office=co).order_by('-year', 'quarter', 'cycle_type')
            if co else ReportingCycle.objects.none()
        )
        return render(request, 'projects/cycles.html', {
            'cycles': cycles,
            'today': timezone.now().date(),
        })


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

        # Prefetch cycles for this year/type once; then prefetch statuses in bulk.
        cycles_qs = ReportingCycle.objects.filter(
            country_office=co, year=year, cycle_type=cycle_type
        ) if co else ReportingCycle.objects.none()
        cycles_by_quarter = {c.quarter: c for c in cycles_qs}

        # Bulk-fetch statuses for these cycles so we avoid N+1 queries.
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

        # Projects without a unit (shouldn't normally happen, but defensive)
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
            'tracker_data': tracker_data,
            'year': year,
            'quarters': quarters,
            'cycle_type': cycle_type,
            'years': [2024, 2025, 2026, 2027, 2028],
            'cycles': cycles_qs,
        })


class DonorTimelineView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        timelines = (
            DonorReportingTimeline.objects
            .filter(country_office=co)
            .select_related('project')
            .order_by('donor', 'project__title')
            if co else DonorReportingTimeline.objects.none()
        )
        return render(request, 'projects/donor_timelines.html', {
            'timelines': timelines,
        })


class CPDFrameworkView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        frameworks = (
            CPDFramework.objects.filter(country_office=co).order_by('-is_active', '-year_start')
            if co else CPDFramework.objects.none()
        )
        outcomes = (
            CPDOutcome.objects
            .filter(framework__country_office=co)
            .select_related('framework', 'programme_unit')
            .prefetch_related('indicators')
            .order_by('framework_id', 'order', 'code')
            if co else CPDOutcome.objects.none()
        )
        return render(request, 'projects/cpd.html', {
            'frameworks': frameworks,
            'outcomes': outcomes,
            'tier_options': [
                ('impact', 'Impact'),
                ('outcome', 'Outcomes'),
                ('output', 'Outputs'),
            ],
        })