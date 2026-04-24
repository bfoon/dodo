from .models import CountryOffice


class CountryOfficeMiddleware:
    """Attaches the current country office context to the request"""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            co_id = request.session.get('active_country_office_id')
            if co_id:
                try:
                    request.active_country_office = CountryOffice.objects.get(pk=co_id, is_active=True)
                except CountryOffice.DoesNotExist:
                    request.active_country_office = request.user.primary_country_office
            else:
                request.active_country_office = request.user.primary_country_office
                if request.active_country_office:
                    request.session['active_country_office_id'] = request.active_country_office.pk
        else:
            request.active_country_office = None
        return self.get_response(request)
