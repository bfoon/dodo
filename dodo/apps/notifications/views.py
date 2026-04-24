from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views import View
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta, date

from .models import (
    DeadlineTemplate, DeadlineSchedule, ReportDelegation,
    Notification, DataAccessGrant, UnitHead,
)
from .services import NotificationService, ReminderDispatcher, DelegationNotifier
from .access import AccessChecker
from apps.projects.models import Project, ReportingCycle, ProgrammeUnit, ReportAssignment
from apps.accounts.models import User, CountryOffice


# ============================================================================
# NOTIFICATION CENTER
# ============================================================================

class NotificationCenterView(LoginRequiredMixin, View):
    """Lists all notifications for the current user"""
    def get(self, request):
        notifications = Notification.objects.filter(user=request.user).select_related(
            'related_project', 'related_cycle', 'related_deadline'
        )
        filter_type = request.GET.get('type')
        if filter_type == 'unread':
            notifications = notifications.filter(is_read=False)
        elif filter_type and filter_type != 'all':
            notifications = notifications.filter(notification_type=filter_type)
        return render(request, 'notifications/center.html', {
            'notifications': notifications[:100],
            'unread_count': Notification.objects.filter(user=request.user, is_read=False).count(),
            'filter_type': filter_type or 'all',
        })


class MarkNotificationReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        n = get_object_or_404(Notification, pk=pk, user=request.user)
        n.mark_read()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'ok': True})
        return redirect(n.action_url or 'notifications:center')


class MarkAllReadView(LoginRequiredMixin, View):
    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(
            is_read=True, read_at=timezone.now()
        )
        messages.success(request, 'All notifications marked as read.')
        return redirect('notifications:center')


# ============================================================================
# DEADLINE TEMPLATE MANAGEMENT (CO admin / M&E staff)
# ============================================================================

class DeadlineTemplateListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        if not co or not AccessChecker.is_co_admin(request.user, co):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')
        templates = DeadlineTemplate.objects.filter(country_office=co)
        return render(request, 'notifications/template_list.html', {'templates': templates})


class DeadlineTemplateCreateView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        if not AccessChecker.is_co_admin(request.user, co):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')
        template = None
        return render(request, 'notifications/template_form.html', {'template': template})

    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        if not AccessChecker.is_co_admin(request.user, co):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')
        DeadlineTemplate.objects.create(
            country_office=co,
            name=request.POST['name'],
            cycle_type=request.POST.get('cycle_type', 'progress'),
            internal_draft_days_before=int(request.POST.get('internal_draft_days_before', 14)),
            programme_review_days_before=int(request.POST.get('programme_review_days_before', 10)),
            pmsu_review_days_before=int(request.POST.get('pmsu_review_days_before', 6)),
            final_clearance_days_before=int(request.POST.get('final_clearance_days_before', 2)),
            reminder_days_before=request.POST.get('reminder_days_before', '14,7,3,1'),
            escalation_days_after=int(request.POST.get('escalation_days_after', 1)),
            send_email=bool(request.POST.get('send_email')),
            send_in_app=bool(request.POST.get('send_in_app')),
            notify_head_of_unit=bool(request.POST.get('notify_head_of_unit')),
            notify_responsible=bool(request.POST.get('notify_responsible')),
            description=request.POST.get('description', ''),
        )
        messages.success(request, 'Deadline template created.')
        return redirect('notifications:template_list')


class DeadlineTemplateEditView(LoginRequiredMixin, View):
    def get(self, request, pk):
        template = get_object_or_404(DeadlineTemplate, pk=pk)
        if not AccessChecker.is_co_admin(request.user, template.country_office):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')
        return render(request, 'notifications/template_form.html', {'template': template})

    def post(self, request, pk):
        template = get_object_or_404(DeadlineTemplate, pk=pk)
        if not AccessChecker.is_co_admin(request.user, template.country_office):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')
        for field in ['name', 'cycle_type', 'reminder_days_before', 'description']:
            setattr(template, field, request.POST.get(field, getattr(template, field)))
        for field in ['internal_draft_days_before', 'programme_review_days_before',
                      'pmsu_review_days_before', 'final_clearance_days_before', 'escalation_days_after']:
            setattr(template, field, int(request.POST.get(field, getattr(template, field))))
        for field in ['send_email', 'send_in_app', 'notify_head_of_unit', 'notify_responsible']:
            setattr(template, field, bool(request.POST.get(field)))
        template.save()
        messages.success(request, 'Template updated.')
        return redirect('notifications:template_list')


# ============================================================================
# DEADLINE SCHEDULE MANAGEMENT (per project/cycle)
# ============================================================================

class DeadlineScheduleView(LoginRequiredMixin, View):
    """Shows all deadline schedules and allows generating from template"""
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        projects = AccessChecker.get_accessible_projects(request.user, co)
        deadlines = DeadlineSchedule.objects.filter(
            project__in=projects
        ).select_related('project', 'cycle', 'template').order_by('final_submission_deadline')
        return render(request, 'notifications/deadlines.html', {
            'deadlines': deadlines,
            'today': timezone.now().date(),
        })


class GenerateDeadlinesView(LoginRequiredMixin, View):
    """Generate deadline schedules from a template for all projects in a cycle"""
    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        if not AccessChecker.is_co_admin(request.user, co):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')

        cycle_id = request.POST.get('cycle_id')
        template_id = request.POST.get('template_id')
        cycle = get_object_or_404(ReportingCycle, pk=cycle_id)
        template = get_object_or_404(DeadlineTemplate, pk=template_id)
        submission_date = cycle.final_report_due or cycle.submission_deadline
        if not submission_date:
            messages.error(request, 'Cycle has no final submission date set.')
            return redirect('notifications:deadlines')

        projects = Project.objects.filter(country_office=co).exclude(status='closed')
        created = 0
        for project in projects:
            deadline, was_created = DeadlineSchedule.objects.get_or_create(
                project=project, cycle=cycle,
                defaults={
                    'template': template,
                    'internal_draft_deadline': submission_date - timedelta(days=template.internal_draft_days_before),
                    'programme_review_deadline': submission_date - timedelta(days=template.programme_review_days_before),
                    'pmsu_review_deadline': submission_date - timedelta(days=template.pmsu_review_days_before),
                    'final_clearance_deadline': submission_date - timedelta(days=template.final_clearance_days_before),
                    'final_submission_deadline': submission_date,
                    'created_by': request.user,
                }
            )
            if was_created:
                created += 1
        messages.success(request, f'Generated {created} deadline schedules.')
        return redirect('notifications:deadlines')


class DeadlineEditView(LoginRequiredMixin, View):
    def get(self, request, pk):
        deadline = get_object_or_404(DeadlineSchedule, pk=pk)
        if not (AccessChecker.is_co_admin(request.user, deadline.project.country_office) or
                AccessChecker.is_head_of_unit(request.user, deadline.project.programme_unit)):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')
        return render(request, 'notifications/deadline_form.html', {'deadline': deadline})

    def post(self, request, pk):
        deadline = get_object_or_404(DeadlineSchedule, pk=pk)
        if not (AccessChecker.is_co_admin(request.user, deadline.project.country_office) or
                AccessChecker.is_head_of_unit(request.user, deadline.project.programme_unit)):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')
        for field in ['internal_draft_deadline', 'programme_review_deadline', 'pmsu_review_deadline',
                      'final_clearance_deadline', 'final_submission_deadline']:
            val = request.POST.get(field)
            if val:
                setattr(deadline, field, val)
        deadline.override_reminder_days = request.POST.get('override_reminder_days', '')
        deadline.notes = request.POST.get('notes', '')
        deadline.save()
        messages.success(request, 'Deadline updated.')
        return redirect('notifications:deadlines')


# ============================================================================
# DELEGATION (Head of Unit delegates report prep)
# ============================================================================

class DelegationListView(LoginRequiredMixin, View):
    def get(self, request):
        given = ReportDelegation.objects.filter(
            delegated_by=request.user
        ).select_related('project', 'cycle', 'delegated_to').order_by('-created_at')
        received = ReportDelegation.objects.filter(
            delegated_to=request.user
        ).select_related('project', 'cycle', 'delegated_by').order_by('-created_at')
        return render(request, 'notifications/delegations.html', {
            'given': given, 'received': received,
        })


class DelegateReportView(LoginRequiredMixin, View):
    """Head of Unit delegates report prep to a specific user"""
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        headed_units = AccessChecker.get_headed_units(request.user)
        if AccessChecker.is_super(request.user) or AccessChecker.is_co_admin(request.user, co):
            projects = Project.objects.filter(country_office=co).exclude(status='closed')
        else:
            projects = Project.objects.filter(programme_unit__in=headed_units).exclude(status='closed')
        cycles = ReportingCycle.objects.filter(country_office=co).order_by('-year', 'quarter') if co else []
        users = User.objects.filter(user_access__country_office=co, user_access__is_active=True).distinct() if co else []
        return render(request, 'notifications/delegation_form.html', {
            'projects': projects, 'cycles': cycles, 'users': users,
            'delegation_types': ReportDelegation.DELEGATION_TYPES,
        })

    def post(self, request):
        project = get_object_or_404(Project, pk=request.POST['project'])
        if not (AccessChecker.is_super(request.user) or
                AccessChecker.is_co_admin(request.user, project.country_office) or
                (project.programme_unit and AccessChecker.is_head_of_unit(request.user, project.programme_unit))):
            messages.error(request, 'Permission denied — only heads of unit and admins can delegate.')
            return redirect('notifications:delegations')

        cycle_id = request.POST.get('cycle')
        delegation = ReportDelegation.objects.create(
            project=project,
            cycle=ReportingCycle.objects.get(pk=cycle_id) if cycle_id else None,
            delegated_to=User.objects.get(pk=request.POST['delegated_to']),
            delegated_by=request.user,
            delegation_type=request.POST.get('delegation_type', 'full'),
            start_date=request.POST.get('start_date', timezone.now().date()),
            end_date=request.POST.get('end_date') or None,
            instructions=request.POST.get('instructions', ''),
        )
        DelegationNotifier.on_delegation_created(delegation)
        messages.success(request, f'Delegated to {delegation.delegated_to.get_full_name()}. Notification sent.')
        return redirect('notifications:delegations')


class RevokeDelegationView(LoginRequiredMixin, View):
    def post(self, request, pk):
        d = get_object_or_404(ReportDelegation, pk=pk)
        if d.delegated_by != request.user and not AccessChecker.is_super(request.user):
            messages.error(request, 'Permission denied.')
            return redirect('notifications:delegations')
        d.is_active = False
        d.save()
        messages.success(request, 'Delegation revoked.')
        return redirect('notifications:delegations')


# ============================================================================
# DATA ACCESS GRANTS (Admin grants granular access)
# ============================================================================

class AccessGrantListView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        if not AccessChecker.is_co_admin(request.user, co):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')
        grants = DataAccessGrant.objects.filter(
            country_office=co
        ).select_related('granted_to', 'granted_by').order_by('-created_at')
        return render(request, 'notifications/grants.html', {'grants': grants})


class GrantAccessView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        if not AccessChecker.is_co_admin(request.user, co):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')
        users = User.objects.all() if request.user.is_global_admin else \
                User.objects.filter(user_access__country_office=co).distinct()
        projects = Project.objects.filter(country_office=co)
        units = ProgrammeUnit.objects.filter(country_office=co)
        cycles = ReportingCycle.objects.filter(country_office=co)
        return render(request, 'notifications/grant_form.html', {
            'users': users, 'projects': projects, 'units': units, 'cycles': cycles,
            'resource_types': DataAccessGrant.RESOURCE_TYPES,
            'access_levels': DataAccessGrant.ACCESS_LEVELS,
        })

    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        if not AccessChecker.is_co_admin(request.user, co):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')

        resource_type = request.POST['resource_type']
        resource_id = request.POST.get('resource_id') or None
        # Resolve resource name for display
        resource_name = ''
        if resource_type == 'project' and resource_id:
            resource_name = Project.objects.get(pk=resource_id).display_title
        elif resource_type == 'programme_unit' and resource_id:
            resource_name = ProgrammeUnit.objects.get(pk=resource_id).name
        elif resource_type == 'reporting_cycle' and resource_id:
            c = ReportingCycle.objects.get(pk=resource_id)
            resource_name = f'{c.year} {c.quarter} {c.get_cycle_type_display()}'
        elif resource_type == 'all_projects':
            resource_name = f'All projects in {co.name}'
        elif resource_type == 'all_reports':
            resource_name = f'All reports in {co.name}'

        grant = DataAccessGrant.objects.create(
            granted_to=User.objects.get(pk=request.POST['granted_to']),
            granted_by=request.user,
            country_office=co,
            resource_type=resource_type,
            resource_id=int(resource_id) if resource_id else None,
            resource_name=resource_name,
            access_level=request.POST['access_level'],
            can_delegate=bool(request.POST.get('can_delegate')),
            start_date=request.POST.get('start_date', timezone.now().date()),
            end_date=request.POST.get('end_date') or None,
            reason=request.POST.get('reason', ''),
        )
        DelegationNotifier.on_grant_created(grant)
        messages.success(request, f'Access granted to {grant.granted_to.get_full_name()}.')
        return redirect('notifications:grants')


class RevokeGrantView(LoginRequiredMixin, View):
    def post(self, request, pk):
        grant = get_object_or_404(DataAccessGrant, pk=pk)
        if not AccessChecker.is_co_admin(request.user, grant.country_office):
            messages.error(request, 'Permission denied.')
            return redirect('notifications:grants')
        grant.revoke(by_user=request.user)
        messages.success(request, 'Grant revoked.')
        return redirect('notifications:grants')


# ============================================================================
# UNIT HEAD DASHBOARD
# ============================================================================

class UnitHeadDashboardView(LoginRequiredMixin, View):
    """Dashboard showing all projects/reports under the user's headed units"""
    def get(self, request):
        headed_units = AccessChecker.get_headed_units(request.user)
        if not headed_units.exists():
            messages.warning(request, 'You are not assigned as a Head of any Programme Unit.')
            return redirect('dashboard:home')

        projects = Project.objects.filter(programme_unit__in=headed_units).select_related('programme_unit')
        deadlines = DeadlineSchedule.objects.filter(
            project__in=projects
        ).select_related('project', 'cycle').order_by('final_submission_deadline')

        # Stats
        today = timezone.now().date()
        upcoming = deadlines.filter(final_submission_deadline__gte=today, status__in=['upcoming', 'in_progress']).count()
        at_risk = deadlines.filter(status='at_risk').count()
        overdue = deadlines.filter(status='overdue').count()
        completed = deadlines.filter(status='completed').count()

        assignments = ReportAssignment.objects.filter(
            project__in=projects
        ).select_related('assigned_to', 'project', 'cycle').order_by('-created_at')[:20]

        return render(request, 'notifications/unit_head_dashboard.html', {
            'headed_units': headed_units,
            'projects': projects,
            'deadlines': deadlines[:30],
            'assignments': assignments,
            'upcoming': upcoming, 'at_risk': at_risk, 'overdue': overdue, 'completed': completed,
        })


# ============================================================================
# UNIT HEAD ASSIGNMENT (super admin only)
# ============================================================================

class UnitHeadManagementView(LoginRequiredMixin, View):
    def get(self, request):
        co = getattr(request, 'active_country_office', None)
        if not AccessChecker.is_co_admin(request.user, co):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')
        heads = UnitHead.objects.filter(
            programme_unit__country_office=co
        ).select_related('user', 'programme_unit').order_by('programme_unit', '-is_primary')
        units = ProgrammeUnit.objects.filter(country_office=co, is_active=True)
        users = User.objects.filter(user_access__country_office=co, user_access__is_active=True).distinct()
        return render(request, 'notifications/unit_heads.html', {
            'heads': heads, 'units': units, 'users': users,
        })

    def post(self, request):
        co = getattr(request, 'active_country_office', None)
        if not AccessChecker.is_co_admin(request.user, co):
            messages.error(request, 'Permission denied.')
            return redirect('dashboard:home')

        action = request.POST.get('action')
        if action == 'assign':
            UnitHead.objects.update_or_create(
                user=User.objects.get(pk=request.POST['user']),
                programme_unit=ProgrammeUnit.objects.get(pk=request.POST['unit']),
                defaults={
                    'is_primary': bool(request.POST.get('is_primary')),
                    'can_delegate': bool(request.POST.get('can_delegate', True)),
                    'can_approve': bool(request.POST.get('can_approve', True)),
                    'assigned_by': request.user, 'is_active': True,
                }
            )
            messages.success(request, 'Unit Head assigned.')
        elif action == 'revoke':
            UnitHead.objects.filter(pk=request.POST['head_id']).update(is_active=False)
            messages.success(request, 'Unit Head assignment revoked.')
        return redirect('notifications:unit_heads')
