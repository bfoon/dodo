from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q

from apps.accounts.models import User
from apps.projects.models import CPDIndicator, Project, ReportingCycle
from .models import (
    OutputVerification, MonitoringVisit,
    IndicatorAchievement, ProjectIndicatorAchievement,
)


def _current_quarter():
    """Return Q1..Q4 for today's date."""
    month = timezone.now().month
    return f'Q{((month - 1) // 3) + 1}'


class MonitoringDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)

        if co:
            verifications_qs = OutputVerification.objects.filter(
                project__country_office=co
            ).select_related('project', 'cycle')
            visits_qs = MonitoringVisit.objects.filter(project__country_office=co).select_related('project')
            projects_qs = Project.objects.filter(country_office=co)
            indicators_qs = CPDIndicator.objects.filter(outcome__framework__country_office=co)
        else:
            verifications_qs = OutputVerification.objects.none()
            visits_qs = MonitoringVisit.objects.none()
            projects_qs = Project.objects.none()
            indicators_qs = CPDIndicator.objects.none()

        # Stats for the dashboard cards
        current_year = timezone.now().year
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
            'indicators_with_data': indicators_qs.filter(achievements__isnull=False).distinct().count(),
            'active_projects': projects_qs.filter(status='active').count(),
        }

        return render(request, 'monitoring/home.html', {
            'verifications': verifications_qs.order_by('-verified_at', '-cycle__year', '-cycle__quarter')[:10],
            'recent_visits': visits_qs.order_by('-visit_date')[:8],
            'stats': stats,
        })


class IndicatorListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        # Order by outcome so {% regroup %} groups correctly in the template.
        indicators = (
            CPDIndicator.objects
            .filter(outcome__framework__country_office=co)
            .select_related('outcome', 'outcome__framework')
            .order_by('outcome__order', 'outcome__code', 'code', 'pk')
            if co else CPDIndicator.objects.none()
        )
        return render(request, 'monitoring/indicators.html', {'indicators': indicators})


class IndicatorDataEntryView(LoginRequiredMixin, View):
    QUARTERS = ['Q1', 'Q2', 'Q3', 'Q4']

    def _context(self, indicator):
        current_year = timezone.now().year
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
        }

    def get(self, request, pk):
        indicator = get_object_or_404(CPDIndicator, pk=pk)
        return render(request, 'monitoring/indicator_data.html', self._context(indicator))

    def post(self, request, pk):
        indicator = get_object_or_404(CPDIndicator, pk=pk)
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


class OutputVerificationListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        verifications = (
            OutputVerification.objects
            .filter(project__country_office=co)
            .select_related('project', 'cycle', 'verified_by')
            .order_by('-cycle__year', '-cycle__quarter', 'project__title')
            if co else OutputVerification.objects.none()
        )
        return render(request, 'monitoring/verification.html', {'verifications': verifications})


class UpdateVerificationView(LoginRequiredMixin, View):
    def post(self, request, pk):
        v = get_object_or_404(OutputVerification, pk=pk)
        new_status = request.POST.get('status')
        if new_status:
            v.status = new_status
        v.verification_notes = request.POST.get('notes', v.verification_notes)
        # Stamp verifier & time when marked completed
        if new_status == 'completed' and not v.verified_at:
            v.verified_by = request.user
            v.verified_at = timezone.now()
        v.save()
        messages.success(request, 'Verification updated.')
        return redirect(request.META.get('HTTP_REFERER', 'monitoring:verification') or 'monitoring:verification')


class MonitoringVisitListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        visits = (
            MonitoringVisit.objects
            .filter(project__country_office=co)
            .select_related('project')
            .prefetch_related('conducted_by')
            .order_by('-visit_date', '-created_at')
            if co else MonitoringVisit.objects.none()
        )
        return render(request, 'monitoring/visits.html', {'visits': visits})


class CreateMonitoringVisitView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        return render(request, 'monitoring/visit_form.html', {
            'projects': Project.objects.filter(country_office=co) if co else Project.objects.none(),
            'visit_types': MonitoringVisit.VISIT_TYPE,
            'users': User.objects.filter(is_active=True).order_by('first_name', 'last_name', 'email'),
            'today': timezone.now().date(),
        })

    def post(self, request):
        try:
            project = get_object_or_404(Project, pk=request.POST['project'])
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

            # M2M: conducted_by (may be multiple checkboxes)
            conducted_ids = request.POST.getlist('conducted_by')
            if conducted_ids:
                visit.conducted_by.set(
                    User.objects.filter(pk__in=conducted_ids, is_active=True)
                )
            else:
                # Default to the submitter so the visit has at least one participant
                visit.conducted_by.add(request.user)

            messages.success(request, 'Monitoring visit recorded.')
            return redirect('monitoring:visits')
        except KeyError as e:
            messages.error(request, f'Missing required field: {e.args[0]}')
            return redirect('monitoring:create_visit')
        except Exception as e:
            messages.error(request, f'Error saving visit: {e}')
            return redirect('monitoring:create_visit')