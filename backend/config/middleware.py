class ApiNoStoreMiddleware:
    """Las respuestas de la API (sesión, cotizaciones, asesor) nunca se guardan en cachés compartidas ni en el navegador."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/api/') and 'Cache-Control' not in response:
            response['Cache-Control'] = 'no-store'
        return response
