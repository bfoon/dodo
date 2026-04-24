"""
Notification dispatch service.
Sends in-app and email notifications to responsible users and heads of unit.
"""
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from .models import Notification, ReminderLog, UnitHead


class NotificationService:
    """Central service for creating and sending notifications"""

    @staticmethod
    def create(user, notification_type, title, message, **kwargs):
        """Create an in-app notification"""
        return Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=kwargs.get('priority', 'normal'),
            related_project=kwargs.get('project'),
            related_cycle=kwargs.get('cycle'),
            related_deadline=kwargs.get('deadline'),
            action_url=kwargs.get('action_url', ''),
        )

    @staticmethod
    def send_email(user, subject, message, html_message=None):
        """Send an email notification"""
        if not user.email:
            return False
        try:
            send_mail(
                subject=f'[Dodo] {subject}',
                message=message,
                html_message=html_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@undp.org'),
                recipient_list=[user.email],
                fail_silently=False,
            )
            return True
        except Exception as e:
            print(f'Email send failed for {user.email}: {e}')
            return False

    @staticmethod
    def notify(user, notification_type, title, message, send_email=True, **kwargs):
        """Create in-app + email notification in one call"""
        n = NotificationService.create(user, notification_type, title, message, **kwargs)
        if send_email and user.email:
            email_body = f"{message}\n\n"
            if kwargs.get('action_url'):
                email_body += f"Link: {kwargs['action_url']}\n\n"
            email_body += " — Dodo"
            if NotificationService.send_email(user, title, email_body):
                n.email_sent = True
                n.email_sent_at = timezone.now()
                n.save(update_fields=['email_sent', 'email_sent_at'])
        return n


class ReminderDispatcher:
    """Sends scheduled reminders based on deadline schedules"""

    @staticmethod
    def dispatch_reminders_for_deadline(deadline):
        """
        Check if any reminders are due for this deadline and send them.
        Returns count of reminders sent.
        """
        if deadline.status in ['completed', 'waived']:
            return 0

        today = timezone.now().date()
        days_remaining = (deadline.final_submission_deadline - today).days

        # Determine which reminder days apply
        template = deadline.template
        if deadline.override_reminder_days:
            reminder_days = [int(d.strip()) for d in deadline.override_reminder_days.split(',') if d.strip()]
        elif template:
            reminder_days = template.get_reminder_days()
        else:
            reminder_days = [14, 7, 3, 1]

        sent_count = 0

        # Check if today's days_remaining matches any reminder day
        if days_remaining in reminder_days and days_remaining >= 0:
            recipients = ReminderDispatcher._get_recipients(deadline)
            for user, role_label in recipients:
                # Check we haven't already sent this exact reminder
                already_sent = ReminderLog.objects.filter(
                    deadline=deadline, stage='final_submission',
                    days_before=days_remaining, recipient=user, channel='in_app'
                ).exists()
                if already_sent:
                    continue

                urgency = 'critical' if days_remaining <= 1 else 'high' if days_remaining <= 3 else 'normal'
                title = f"Report due in {days_remaining} day{'s' if days_remaining != 1 else ''}: {deadline.project.display_title}"
                message = (
                    f"The {deadline.cycle.get_cycle_type_display()} report for "
                    f"'{deadline.project.display_title}' is due on "
                    f"{deadline.final_submission_deadline.strftime('%d %B %Y')}.\n\n"
                    f"Your role: {role_label}\n"
                    f"Current stage: {deadline.get_current_stage()[1]}"
                )
                NotificationService.notify(
                    user=user, notification_type='reminder',
                    title=title, message=message, priority=urgency,
                    project=deadline.project, cycle=deadline.cycle, deadline=deadline,
                    action_url=f'/projects/{deadline.project.pk}/',
                )
                ReminderLog.objects.create(
                    deadline=deadline, stage='final_submission',
                    days_before=days_remaining, recipient=user, channel='in_app'
                )
                sent_count += 1

        # Escalation: if overdue
        if days_remaining < 0 and template and abs(days_remaining) >= template.escalation_days_after:
            sent_count += ReminderDispatcher._escalate_overdue(deadline, abs(days_remaining))

        return sent_count

    @staticmethod
    def _get_recipients(deadline):
        """Returns list of (user, role_label) tuples to notify for a deadline."""
        recipients = []
        project = deadline.project
        # Responsible users (project-level)
        for resp in project.responsibilities.filter(is_active=True, receive_notifications=True):
            recipients.append((resp.user, resp.get_role_display()))
        # Assigned user for this specific cycle
        for assignment in project.report_assignments.filter(cycle=deadline.cycle):
            if assignment.status not in ['approved', 'declined']:
                recipients.append((assignment.assigned_to, f'Assigned ({assignment.get_status_display()})'))
        # Delegated users for this cycle
        for d in project.delegations.filter(cycle=deadline.cycle, is_active=True):
            recipients.append((d.delegated_to, f'Delegated: {d.get_delegation_type_display()}'))
        # Head of unit
        if project.programme_unit:
            for head in UnitHead.objects.filter(programme_unit=project.programme_unit, is_active=True):
                recipients.append((head.user, f'Head of {project.programme_unit.name}'))
        # Deduplicate while preserving first role label
        seen = set()
        unique = []
        for user, label in recipients:
            if user.pk not in seen:
                seen.add(user.pk)
                unique.append((user, label))
        return unique

    @staticmethod
    def _escalate_overdue(deadline, days_overdue):
        """Escalate overdue reports to head of unit + CO admin"""
        sent = 0
        project = deadline.project
        # Notify unit heads
        if project.programme_unit:
            for head in UnitHead.objects.filter(programme_unit=project.programme_unit, is_active=True):
                already = ReminderLog.objects.filter(
                    deadline=deadline, stage='escalation',
                    days_before=-days_overdue, recipient=head.user, channel='in_app'
                ).exists()
                if already:
                    continue
                NotificationService.notify(
                    user=head.user, notification_type='escalation',
                    title=f'OVERDUE ({days_overdue}d): {project.display_title}',
                    message=(
                        f"The report for '{project.display_title}' ({deadline.cycle}) "
                        f"is {days_overdue} day(s) overdue.\n"
                        f"Deadline was: {deadline.final_submission_deadline.strftime('%d %B %Y')}\n\n"
                        f"As Head of {project.programme_unit.name}, please follow up or reassign."
                    ),
                    priority='critical',
                    project=project, cycle=deadline.cycle, deadline=deadline,
                    action_url=f'/projects/{project.pk}/',
                )
                ReminderLog.objects.create(
                    deadline=deadline, stage='escalation',
                    days_before=-days_overdue, recipient=head.user, channel='in_app'
                )
                sent += 1
        return sent


class DelegationNotifier:
    """Sends notifications when delegation/assignment events happen"""

    @staticmethod
    def on_delegation_created(delegation):
        NotificationService.notify(
            user=delegation.delegated_to,
            notification_type='delegation',
            title=f'Delegated: {delegation.project.display_title}',
            message=(
                f"{delegation.delegated_by.get_full_name()} has delegated "
                f"'{delegation.get_delegation_type_display()}' to you for "
                f"'{delegation.project.display_title}'"
                + (f" ({delegation.cycle})" if delegation.cycle else "") + ".\n\n"
                + (f"Instructions: {delegation.instructions}\n\n" if delegation.instructions else "")
                + f"Valid from: {delegation.start_date}"
                + (f" to {delegation.end_date}" if delegation.end_date else "")
            ),
            priority='high',
            project=delegation.project, cycle=delegation.cycle,
            action_url=f'/projects/{delegation.project.pk}/',
        )

    @staticmethod
    def on_assignment_created(assignment):
        NotificationService.notify(
            user=assignment.assigned_to,
            notification_type='delegation',
            title=f'Assignment: {assignment.project.display_title} {assignment.cycle.quarter}',
            message=(
                f"{assignment.assigned_by.get_full_name()} has assigned you to prepare "
                f"the {assignment.cycle.get_cycle_type_display()} report for "
                f"'{assignment.project.display_title}' ({assignment.cycle.year} {assignment.cycle.quarter}).\n\n"
                + (f"Due: {assignment.due_date}\n" if assignment.due_date else "")
                + (f"Instructions: {assignment.instructions}" if assignment.instructions else "")
            ),
            priority='high',
            project=assignment.project, cycle=assignment.cycle,
            action_url=f'/projects/{assignment.project.pk}/',
        )

    @staticmethod
    def on_grant_created(grant):
        NotificationService.notify(
            user=grant.granted_to,
            notification_type='access_granted',
            title='New Access Granted',
            message=(
                f"{grant.granted_by.get_full_name()} has granted you "
                f"{grant.get_access_level_display()} access to "
                f"{grant.get_resource_type_display()}: {grant.resource_name}\n\n"
                + (f"Valid from: {grant.start_date}" + (f" to {grant.end_date}" if grant.end_date else " (no expiry)")) + "\n"
                + (f"\nReason: {grant.reason}" if grant.reason else "")
            ),
            priority='normal',
        )

    @staticmethod
    def on_report_submitted(assignment):
        """Notify approver/head of unit when report is submitted"""
        project = assignment.project
        notified = set()
        if project.programme_unit:
            for head in UnitHead.objects.filter(programme_unit=project.programme_unit, is_active=True):
                if head.user.pk in notified:
                    continue
                NotificationService.notify(
                    user=head.user, notification_type='approval',
                    title=f'Review needed: {project.display_title}',
                    message=f"{assignment.assigned_to.get_full_name()} submitted a report for "
                            f"'{project.display_title}' ({assignment.cycle}). Review and approve.",
                    priority='high', project=project, cycle=assignment.cycle,
                    action_url=f'/projects/{project.pk}/',
                )
                notified.add(head.user.pk)
