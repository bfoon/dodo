def user_context(request):
    ctx = {}
    if request.user.is_authenticated:
        ctx['active_country_office'] = getattr(request, 'active_country_office', None)
        ctx['accessible_country_offices'] = request.user.get_country_offices()
    return ctx
