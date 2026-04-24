"""
Celery configuration for the Dodo.
"""
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dodo.settings')

app = Celery('dodo')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


# Beat schedule — automated scheduled tasks
app.conf.beat_schedule = {
    # Daily reminder dispatch every morning at 08:00 UTC
    'dispatch-reminders-daily': {
        'task': 'apps.notifications.tasks.dispatch_all_reminders',
        'schedule': crontab(hour=8, minute=0),
    },
    # Hourly status recomputation (at_risk / overdue transitions)
    'update-deadline-statuses-hourly': {
        'task': 'apps.notifications.tasks.update_deadline_statuses',
        'schedule': crontab(minute=5),
    },
    # Clean up expired access grants nightly at 02:00
    'expire-grants-nightly': {
        'task': 'apps.notifications.tasks.expire_grants',
        'schedule': crontab(hour=2, minute=0),
    },
}


@app.task(bind=True)
def debug_task(self):
    print(f'Celery request: {self.request!r}')
