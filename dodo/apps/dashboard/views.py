from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.db.models import Count, Q


class DashboardView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        from apps.projects.models import Project, ProgrammeUnit, ProjectReportingStatus, ReportingCycle
        from apps.monitoring.models import OutputVerification
        from apps.surveys.models import Survey

        ctx = {'co': co}
        if co:
            projects = Project.objects.filter(country_office=co)
            ctx['total_projects'] = projects.count()
            ctx['active_projects'] = projects.filter(status='active').count()
            ctx['ending_projects'] = projects.filter(status='ending').count()
            ctx['new_projects'] = projects.filter(status='pipeline').count()

            ctx['programme_units'] = ProgrammeUnit.objects.filter(country_office=co, is_active=True).annotate(
                project_count=Count('projects'),
                submitted=Count('projects__reporting_statuses', filter=Q(projects__reporting_statuses__status='submitted')),
                pending=Count('projects__reporting_statuses', filter=Q(projects__reporting_statuses__status='pending')),
                overdue=Count('projects__reporting_statuses', filter=Q(projects__reporting_statuses__status='overdue')),
            )

            # Latest cycle stats
            cycle = ReportingCycle.objects.filter(country_office=co, cycle_type='progress').order_by('-year', '-quarter').first()
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
    def get(self, request, unit_id):
        from apps.projects.models import ProgrammeUnit, Project, ProjectReportingStatus
        unit = ProgrammeUnit.objects.get(pk=unit_id)
        projects = Project.objects.filter(programme_unit=unit).prefetch_related('reporting_statuses__cycle')
        return render(request, 'dashboard/cluster.html', {'unit': unit, 'projects': projects})
