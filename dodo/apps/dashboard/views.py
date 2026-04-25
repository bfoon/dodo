from django.shortcuts import render, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.db.models import Count, Q


QUARTER_ORDER = ['Q1', 'Q2', 'Q3', 'Q4']


class DashboardView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        from apps.projects.models import (
            Project, ProgrammeUnit, ProjectReportingStatus, ReportingCycle,
        )
        from apps.surveys.models import Survey

        ctx = {'co': co}
        if co:
            projects = Project.objects.filter(country_office=co)
            ctx['total_projects'] = projects.count()
            ctx['active_projects'] = projects.filter(status='active').count()
            ctx['ending_projects'] = projects.filter(status='ending').count()
            ctx['new_projects'] = projects.filter(status='pipeline').count()

            cycle = (
                ReportingCycle.objects
                .filter(country_office=co, cycle_type='progress')
                .order_by('-year', '-quarter')
                .first()
            )

            unit_qs = (
                ProgrammeUnit.objects
                .filter(country_office=co, is_active=True)
                .annotate(
                    project_count=Count(
                        'projects',
                        filter=Q(projects__country_office=co),
                        distinct=True,
                    )
                )
                .order_by('name')
            )

            status_by_unit = {}
            if cycle:
                rows = (
                    ProjectReportingStatus.objects
                    .filter(cycle=cycle, project__country_office=co)
                    .values('project__programme_unit_id', 'status')
                    .annotate(n=Count('id'))
                )
                for r in rows:
                    uid = r['project__programme_unit_id']
                    bucket = status_by_unit.setdefault(
                        uid, {'submitted': 0, 'pending': 0, 'overdue': 0,
                              'under_review': 0, 'not_started': 0}
                    )
                    if r['status'] in bucket:
                        bucket[r['status']] = r['n']

            programme_units = []
            for u in unit_qs:
                buckets = status_by_unit.get(
                    u.pk, {'submitted': 0, 'pending': 0, 'overdue': 0,
                           'under_review': 0, 'not_started': 0}
                )
                u.submitted = buckets['submitted']
                u.pending = buckets['pending']
                u.overdue = buckets['overdue']
                programme_units.append(u)
            ctx['programme_units'] = programme_units

            if cycle:
                ctx['current_cycle'] = cycle
                statuses = ProjectReportingStatus.objects.filter(cycle=cycle)
                ctx['cycle_submitted'] = statuses.filter(status='submitted').count()
                ctx['cycle_pending'] = statuses.filter(status='pending').count()
                ctx['cycle_under_review'] = statuses.filter(status='under_review').count()
                ctx['cycle_not_started'] = statuses.filter(status='not_started').count()

            ctx['recent_surveys'] = Survey.objects.filter(country_office=co).order_by('-created_at')[:5]
            ctx['active_surveys'] = Survey.objects.filter(country_office=co, status='active').count()
        return render(request, 'dashboard/home.html', ctx)


class ClusterDashboardView(LoginRequiredMixin, View):
    """
    Programme-cluster page: a projects × cycles matrix.
    Each row is a project, each column is a quarterly progress cycle,
    and each cell shows the reporting status for that project/cycle.
    """

    def get(self, request, unit_id):
        from apps.projects.models import (
            ProgrammeUnit, Project, ReportingCycle, ProjectReportingStatus,
        )

        co = getattr(request, 'active_country_office', None)
        unit = get_object_or_404(
            ProgrammeUnit,
            pk=unit_id,
            **({'country_office': co} if co else {}),
        )

        # Project list, sorted for stable display
        projects = list(
            Project.objects
            .filter(programme_unit=unit)
            .order_by('-status', 'title')
        )

        # Pull all progress cycles for this CO, oldest → newest so the matrix
        # reads left to right like a calendar.
        cycle_qs = ReportingCycle.objects.filter(cycle_type='progress')
        if co:
            cycle_qs = cycle_qs.filter(country_office=co)
        cycles = sorted(
            cycle_qs,
            key=lambda c: (c.year, QUARTER_ORDER.index(c.quarter)
                           if c.quarter in QUARTER_ORDER else 99),
        )

        # Group cycles by year for the two-row table header
        years = []
        cycles_by_year = {}
        for c in cycles:
            if c.year not in cycles_by_year:
                cycles_by_year[c.year] = []
                years.append(c.year)
            cycles_by_year[c.year].append(c)
        year_groups = [{'year': y, 'cycles': cycles_by_year[y]} for y in years]

        # One query for all statuses, then bucket by (project_id, cycle_id)
        project_ids = [p.pk for p in projects]
        cycle_ids = [c.pk for c in cycles]
        status_lookup = {}
        if project_ids and cycle_ids:
            for s in (
                ProjectReportingStatus.objects
                .filter(project_id__in=project_ids, cycle_id__in=cycle_ids)
                .select_related('updated_by')
            ):
                status_lookup[(s.project_id, s.cycle_id)] = s

        # Build matrix rows: each project with one cell per cycle
        rows = []
        # Summary tally for the strip at the top
        totals = {'submitted': 0, 'under_review': 0, 'pending': 0,
                  'overdue': 0, 'not_started': 0, 'closed': 0,
                  'not_applicable': 0, 'total_cells': 0}

        for project in projects:
            cells = []
            project_summary = {'submitted': 0, 'pending': 0, 'overdue': 0, 'gaps': 0}
            for c in cycles:
                s = status_lookup.get((project.pk, c.pk))
                cells.append({'cycle': c, 'status': s})
                totals['total_cells'] += 1
                if s and s.status in totals:
                    totals[s.status] += 1
                    if s.status in project_summary:
                        project_summary[s.status] += 1
                else:
                    totals['not_started'] += 1
                    project_summary['gaps'] += 1
            rows.append({
                'project': project,
                'cells': cells,
                'summary': project_summary,
            })

        coverage_pct = 0
        if totals['total_cells']:
            reported = totals['submitted'] + totals['under_review'] + totals['closed']
            coverage_pct = round((reported / totals['total_cells']) * 100)

        return render(request, 'dashboard/cluster.html', {
            'unit': unit,
            'projects': projects,
            'cycles': cycles,
            'year_groups': year_groups,
            'rows': rows,
            'totals': totals,
            'coverage_pct': coverage_pct,
        })