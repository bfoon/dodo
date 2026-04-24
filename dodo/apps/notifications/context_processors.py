from .models import Notification, UnitHead


def notifications_context(request):
    """Adds unread count, user's headed units, and recent notifications to context"""
    ctx = {}
    if request.user.is_authenticated:
        ctx['unread_notifications_count'] = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()
        ctx['recent_notifications'] = Notification.objects.filter(
            user=request.user
        ).select_related('related_project')[:5]
        ctx['user_headed_units'] = UnitHead.objects.filter(
            user=request.user, is_active=True
        ).select_related('programme_unit')
        ctx['is_unit_head'] = ctx['user_headed_units'].exists()
    return ctx
