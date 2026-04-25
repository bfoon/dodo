import csv
from datetime import date, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from apps.projects.models import (
    Project,
    ProgrammeUnit,
    ProjectReportingStatus,
    ReportingCycle,
    CPDIndicator,
    DonorReportingTimeline,
)
from apps.monitoring.models import OutputVerification


QUARTERS = ['Q1', 'Q2', 'Q3', 'Q4']


def _year_range(center=None, back=3, forward=2):
    """Return a sensible list of years for filter dropdowns."""
    center = center or date.today().year
    return list(range(center - back, center + forward + 1))


# ---------------------------------------------------------------------------
# Reporting home
# ---------------------------------------------------------------------------
class ReportingHomeView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        today = date.today()
        # Figure out current quarter
        current_q = QUARTERS[(today.month - 1) // 3]

        stats = {
            'active_projects': 0,
            'reports_this_q': 0,
            'submitted_this_q': 0,
            'verifications_total': 0,
            'verifications_completed': 0,
            'verifications_pending': 0,
            'indicators_total': 0,
            'indicators_with_data': 0,
        }

        if co:
            project_qs = Project.objects.filter(country_office=co)
            stats['active_projects'] = project_qs.filter(status='active').count()

            cycle = ReportingCycle.objects.filter(
                country_office=co,
                year=today.year,
                quarter=current_q,
                cycle_type='progress',
            ).first()
            if cycle:
                status_qs = ProjectReportingStatus.objects.filter(cycle=cycle)
                stats['reports_this_q'] = status_qs.count()
                stats['submitted_this_q'] = status_qs.filter(
                    status__in=['submitted', 'under_review', 'closed']
                ).count()

            verif_qs = OutputVerification.objects.filter(project__country_office=co)
            stats['verifications_total'] = verif_qs.count()
            stats['verifications_completed'] = verif_qs.filter(status='completed').count()
            stats['verifications_pending'] = verif_qs.exclude(
                status__in=['completed', 'not_applicable']
            ).count()

            ind_qs = CPDIndicator.objects.filter(outcome__framework__country_office=co)
            stats['indicators_total'] = ind_qs.count()
            stats['indicators_with_data'] = ind_qs.filter(
                achievements__isnull=False
            ).distinct().count()

        return render(request, 'reporting/home.html', {
            'stats': stats,
            'today': today,
        })


# ---------------------------------------------------------------------------
# Progress report
# ---------------------------------------------------------------------------
class ProgressReportView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        today = date.today()

        try:
            year = int(request.GET.get('year', today.year))
        except (TypeError, ValueError):
            year = today.year
        quarter = request.GET.get('quarter', QUARTERS[(today.month - 1) // 3])
        if quarter not in QUARTERS:
            quarter = 'Q1'

        projects = (
            Project.objects.filter(country_office=co)
            .select_related('programme_unit')
            .order_by('programme_unit__name', 'title')
            if co else Project.objects.none()
        )

        cycle = None
        statuses_by_project = {}
        if co:
            cycle = ReportingCycle.objects.filter(
                country_office=co, year=year, quarter=quarter, cycle_type='progress',
            ).first()
            if cycle:
                statuses = (
                    ProjectReportingStatus.objects
                    .filter(cycle=cycle)
                    .select_related('project', 'updated_by')
                )
                statuses_by_project = {s.project_id: s for s in statuses}

        # Build one row per project, joining its current-cycle status (if any)
        rows = []
        summary = {
            'submitted': 0, 'under_review': 0, 'pending': 0,
            'overdue': 0, 'not_started': 0, 'not_applicable': 0, 'closed': 0,
        }
        for project in projects:
            status = statuses_by_project.get(project.pk)
            status_code = status.status if status else 'not_started'

            # Mark as overdue if pending past the cycle deadline
            if (status_code in ('pending', 'not_started')
                    and cycle and cycle.submission_deadline
                    and cycle.submission_deadline < today):
                effective_code = 'overdue'
            else:
                effective_code = status_code

            if effective_code in summary:
                summary[effective_code] += 1

            rows.append({
                'project': project,
                'status': status,
                'status_code': effective_code,
            })

        units = (
            ProgrammeUnit.objects.filter(country_office=co, is_active=True).order_by('name')
            if co else ProgrammeUnit.objects.none()
        )

        return render(request, 'reporting/progress.html', {
            'projects': projects,
            'rows': rows,
            'cycle': cycle,
            'summary': summary,
            'units': units,
            'years': _year_range(year),
            'quarters': QUARTERS,
            'year': year,
            'quarter': quarter,
            'today': today,
        })


# ---------------------------------------------------------------------------
# Output verification report
# ---------------------------------------------------------------------------
class OutputVerificationReportView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        today = date.today()

        verifications = (
            OutputVerification.objects
            .filter(project__country_office=co)
            .select_related('project', 'cycle', 'verified_by')
            .order_by('-cycle__year', '-cycle__quarter', 'project__title')
            if co else OutputVerification.objects.none()
        )

        in_progress_states = ('field_verification', 'documentation_review', 'validation_meeting')
        total = verifications.count() if co else 0
        completed = verifications.filter(status='completed').count() if co else 0
        in_progress = verifications.filter(status__in=in_progress_states).count() if co else 0
        pending = verifications.filter(status='pending').count() if co else 0
        not_applicable = verifications.filter(status='not_applicable').count() if co else 0
        applicable = total - not_applicable
        completion_rate = round((completed / applicable) * 100) if applicable else 0

        summary = {
            'completed': completed,
            'in_progress': in_progress,
            'pending': pending,
            'not_applicable': not_applicable,
            'completion_rate': completion_rate,
        }

        years = sorted(
            {v.cycle.year for v in verifications if v.cycle_id},
            reverse=True,
        ) if co else []

        return render(request, 'reporting/verification.html', {
            'verifications': verifications,
            'summary': summary,
            'years': years,
            'today': today,
        })


# ---------------------------------------------------------------------------
# Indicator achievements report
# ---------------------------------------------------------------------------
class IndicatorAchievementReportView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        today = date.today()

        try:
            year = int(request.GET.get('year', today.year))
        except (TypeError, ValueError):
            year = today.year

        indicators_qs = (
            CPDIndicator.objects
            .filter(outcome__framework__country_office=co)
            .select_related('outcome', 'outcome__framework')
            .prefetch_related('achievements')
            .order_by('outcome__tier', 'outcome__code', 'code')
            if co else CPDIndicator.objects.none()
        )

        # Build per-indicator rows with quarterly cells for the selected year
        indicators = []
        tier_counts = {'impact': 0, 'outcome': 0, 'output': 0}
        with_data = 0

        for indicator in indicators_qs:
            achievements = list(indicator.achievements.all())
            cells = []
            for q in QUARTERS:
                match = next(
                    (a for a in achievements
                     if getattr(a, 'year', None) == year and getattr(a, 'quarter', None) == q),
                    None,
                )
                cells.append(match)

            latest = None
            if achievements:
                latest = max(
                    achievements,
                    key=lambda a: (
                        getattr(a, 'year', 0) or 0,
                        QUARTERS.index(getattr(a, 'quarter', 'Q1'))
                            if getattr(a, 'quarter', None) in QUARTERS else -1,
                    ),
                )

            tier = getattr(indicator.outcome, 'tier', None)
            if tier in tier_counts:
                tier_counts[tier] += 1
            if achievements:
                with_data += 1

            indicators.append({
                'indicator': indicator,
                'cells': cells,
                'latest': latest,
            })

        total = len(indicators)
        summary = {
            'impact_count': tier_counts['impact'],
            'outcome_count': tier_counts['outcome'],
            'output_count': tier_counts['output'],
            'with_data': with_data,
            'coverage_pct': round((with_data / total) * 100) if total else 0,
        }

        return render(request, 'reporting/indicators.html', {
            'indicators': indicators,
            'summary': summary,
            'year': year,
            'years': _year_range(year),
            'today': today,
        })


# ---------------------------------------------------------------------------
# Donor reporting report
# ---------------------------------------------------------------------------
class DonorReportView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        today = date.today()
        soon = today + timedelta(days=30)

        timelines = (
            DonorReportingTimeline.objects
            .filter(country_office=co)
            .select_related('project')
            .order_by('donor', 'project__title')
            if co else DonorReportingTimeline.objects.none()
        )

        # Compute summary tiles
        unique_donors = set()
        unique_projects = set()
        upcoming = 0
        for t in timelines:
            if t.donor:
                unique_donors.add(t.donor)
            if t.project_id:
                unique_projects.add(t.project_id)
            for date_field in ('internal_draft_1', 'programme_review_1',
                               'pmsu_review_1', 'final_submission_1',
                               'final_submission_2'):
                d = getattr(t, date_field, None)
                if d and today <= d <= soon:
                    upcoming += 1
                    break

        summary = {
            'unique_donors': len(unique_donors),
            'unique_projects': len(unique_projects),
            'upcoming': upcoming,
        }

        return render(request, 'reporting/donor.html', {
            'timelines': timelines,
            'summary': summary,
            'today': today,
        })


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
class ExportReportView(LoginRequiredMixin, View):
    def get(self, request, report_type):
        co = getattr(request, 'active_country_office', None)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="{report_type}_report.csv"'
        )
        writer = csv.writer(response)

        if report_type == 'progress':
            year = int(request.GET.get('year', date.today().year))
            quarter = request.GET.get('quarter', 'Q1')
            writer.writerow([
                'PIMS ID', 'Project', 'Programme Unit', 'Project Status',
                'Report Status', 'Last Updated', 'Updated By', 'Notes',
            ])
            cycle = ReportingCycle.objects.filter(
                country_office=co, year=year, quarter=quarter, cycle_type='progress',
            ).first() if co else None
            statuses_by_project = {}
            if cycle:
                statuses_by_project = {
                    s.project_id: s
                    for s in ProjectReportingStatus.objects
                        .filter(cycle=cycle)
                        .select_related('updated_by')
                }
            projects = (
                Project.objects.filter(country_office=co).select_related('programme_unit')
                if co else Project.objects.none()
            )
            for p in projects:
                s = statuses_by_project.get(p.pk)
                writer.writerow([
                    getattr(p, 'pims_id', '') or '',
                    getattr(p, 'display_title', None) or p.title,
                    p.programme_unit.name if p.programme_unit_id else '',
                    p.get_status_display() if hasattr(p, 'get_status_display') else '',
                    s.get_status_display() if s else 'Not Started',
                    s.updated_at.strftime('%Y-%m-%d') if s and s.updated_at else '',
                    (s.updated_by.get_full_name() or s.updated_by.email)
                        if s and s.updated_by_id else '',
                    (s.notes or '') if s else '',
                ])

        elif report_type == 'verification':
            writer.writerow([
                'PIMS ID', 'Project', 'Cycle Year', 'Cycle Quarter', 'Status',
                'Verified By', 'Verified At', 'Final Report Due',
            ])
            verifications = (
                OutputVerification.objects.filter(project__country_office=co)
                .select_related('project', 'cycle', 'verified_by')
                if co else OutputVerification.objects.none()
            )
            for v in verifications:
                writer.writerow([
                    getattr(v.project, 'pims_id', '') or '',
                    getattr(v.project, 'display_title', None) or v.project.title,
                    v.cycle.year if v.cycle_id else '',
                    v.cycle.quarter if v.cycle_id else '',
                    v.get_status_display(),
                    (v.verified_by.get_full_name() or v.verified_by.email)
                        if v.verified_by_id else '',
                    v.verified_at.strftime('%Y-%m-%d') if v.verified_at else '',
                    v.final_report_due.strftime('%Y-%m-%d') if v.final_report_due else '',
                ])

        elif report_type == 'indicators':
            year = int(request.GET.get('year', date.today().year))
            writer.writerow([
                'Outcome', 'Indicator Code', 'Tier', 'Description',
                'Baseline', 'End Target',
                f'{year} Q1', f'{year} Q2', f'{year} Q3', f'{year} Q4',
            ])
            indicators = (
                CPDIndicator.objects
                .filter(outcome__framework__country_office=co)
                .select_related('outcome')
                .prefetch_related('achievements')
                if co else CPDIndicator.objects.none()
            )
            for ind in indicators:
                achievements = {
                    (a.year, a.quarter): a.achieved_value
                    for a in ind.achievements.all()
                    if getattr(a, 'year', None) == year
                }
                writer.writerow([
                    ind.outcome.code,
                    ind.code or '',
                    ind.outcome.get_tier_display() if hasattr(ind.outcome, 'get_tier_display') else '',
                    ind.description,
                    ind.baseline or '',
                    ind.end_target or '',
                    achievements.get((year, 'Q1'), ''),
                    achievements.get((year, 'Q2'), ''),
                    achievements.get((year, 'Q3'), ''),
                    achievements.get((year, 'Q4'), ''),
                ])

        elif report_type == 'donor':
            writer.writerow([
                'Donor', 'PIMS ID', 'Project', 'Frequency',
                'Period 1', 'Internal Draft 1', 'Programme Review 1',
                'PMSU Review 1', 'Final Submission 1',
                'Period 2', 'Final Submission 2', 'Notes',
            ])
            timelines = (
                DonorReportingTimeline.objects.filter(country_office=co)
                .select_related('project')
                if co else DonorReportingTimeline.objects.none()
            )
            for t in timelines:
                writer.writerow([
                    t.donor or '',
                    getattr(t.project, 'pims_id', '') or '',
                    getattr(t.project, 'display_title', None) or t.project.title,
                    t.reporting_frequency or '',
                    t.period_1 or '',
                    t.internal_draft_1 or '',
                    t.programme_review_1 or '',
                    t.pmsu_review_1 or '',
                    t.final_submission_1 or '',
                    t.period_2 or '',
                    t.final_submission_2 or '',
                    t.notes or '',
                ])

        else:
            writer.writerow(['Unknown report type', report_type])

        return response