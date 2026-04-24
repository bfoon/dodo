"""
Daily reminder dispatcher.
Schedule this via cron/celery-beat to run every morning:
    0 8 * * *  python manage.py send_reminders
"""
from django.core.management.base import BaseCommand
from apps.notifications.models import DeadlineSchedule
from apps.notifications.services import ReminderDispatcher


class Command(BaseCommand):
    help = 'Send scheduled deadline reminders and overdue escalations'

    def handle(self, *args, **kwargs):
        self.stdout.write('Dispatching reminders...')
        deadlines = DeadlineSchedule.objects.exclude(
            status__in=['completed', 'waived']
        ).select_related('project', 'cycle', 'template')

        total_sent = 0
        total_deadlines = 0
        for deadline in deadlines:
            # Update status first
            new_status = deadline.compute_status()
            if new_status != deadline.status:
                deadline.status = new_status
                deadline.save(update_fields=['status'])
            # Dispatch reminders
            sent = ReminderDispatcher.dispatch_reminders_for_deadline(deadline)
            total_sent += sent
            if sent > 0:
                total_deadlines += 1
                self.stdout.write(f'  {deadline.project.display_title} ({deadline.cycle}): {sent} reminder(s)')

        self.stdout.write(self.style.SUCCESS(
            f'\n✓ Sent {total_sent} reminder(s) across {total_deadlines} deadline(s)'
        ))
