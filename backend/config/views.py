from django.db import connection
from django.http import JsonResponse


def healthz(request):
    """Comprobación de salud para Docker y Cloudflare: responde 200 solo si la base de datos contesta."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)
    return JsonResponse({'status': 'ok'})
