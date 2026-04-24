"""
Celery tasks for the notifications app.
Scheduled by celery-beat per the schedule in dodo/celery.py.
"""
from celery import shared_task
from django.utils import timezone


@shared_task(name='apps.notifications.tasks.dispatch_all_reminders')
def dispatch_all_reminders():
    """
    Iterate every active deadline and dispatch any reminders due today.
    Scheduled daily at 08:00 UTC.
    """
    from apps.notifications.models import DeadlineSchedule
    from apps.notifications.services import ReminderDispatcher

    deadlines = DeadlineSchedule.objects.exclude(
        status__in=['completed', 'waived']
    ).select_related('project', 'cycle', 'template')

    total_sent = 0
    for deadline in deadlines:
        new_status = deadline.compute_status()
        if new_status != deadline.status:
            deadline.status = new_status
            deadline.save(update_fields=['status'])
        total_sent += ReminderDispatcher.dispatch_reminders_for_deadline(deadline)

    return f'Dispatched {total_sent} reminders across {deadlines.count()} deadlines'


@shared_task(name='apps.notifications.tasks.update_deadline_statuses')
def update_deadline_statuses():
    """
    Recompute status for all deadlines (upcoming/at_risk/overdue).
    Scheduled hourly.
    """
    from apps.notifications.models import DeadlineSchedule

    updated = 0
    for deadline in DeadlineSchedule.objects.exclude(status__in=['completed', 'waived']):
        new_status = deadline.compute_status()
        if new_status != deadline.status:
            deadline.status = new_status
            deadline.save(update_fields=['status'])
            updated += 1
    return f'Updated {updated} deadline statuses'


@shared_task(name='apps.notifications.tasks.expire_grants')
def expire_grants():
    """
    Deactivate expired DataAccessGrants.
    Scheduled nightly at 02:00.
    """
    from apps.notifications.models import DataAccessGrant

    today = timezone.now().date()
    expired = DataAccessGrant.objects.filter(
        is_active=True, end_date__lt=today
    )
    count = expired.update(is_active=False, revoked_at=timezone.now())
    return f'Expired {count} access grants'


@shared_task(name='apps.notifications.tasks.send_notification_email')
def send_notification_email(notification_id):
    """
    Async email send for an individual notification.
    Called from NotificationService.notify() when email delivery is deferred.
    """
    from apps.notifications.models import Notification
    from apps.notifications.services import NotificationService

    try:
        n = Notification.objects.get(pk=notification_id)
    except Notification.DoesNotExist:
        return f'Notification {notification_id} not found'

    if n.email_sent or not n.user.email:
        return f'Skipped (already sent or no email)'

    body = n.message + "\n\n"
    if n.action_url:
        body += f"Link: {n.action_url}\n\n"
    body += " — Dodo"

    if NotificationService.send_email(n.user, n.title, body):
        n.email_sent = True
        n.email_sent_at = timezone.now()
        n.save(update_fields=['email_sent', 'email_sent_at'])
        return f'Emailed {n.user.email}'
    return 'Email failed'
