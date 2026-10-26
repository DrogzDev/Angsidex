FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --system --create-home --uid 10001 app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# collectstatic no necesita secretos: se ejecuta en modo DEBUG solo durante la construcción.
RUN DJANGO_DEBUG=true python manage.py collectstatic --noinput && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request as u; r = u.Request('http://127.0.0.1:8000/healthz', headers={'X-Forwarded-Proto': 'https', 'Host': 'localhost'}); u.urlopen(r, timeout=4)"

# gthread: cada respuesta SSE del asesor ocupa un hilo, no un proceso completo.
# Solo el túnel (cloudflared) llega a este puerto, así que se confía en su X-Forwarded-Proto.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--worker-class", "gthread", "--workers", "3", "--threads", "8", "--timeout", "120", "--graceful-timeout", "30", "--keep-alive", "30", "--forwarded-allow-ips", "*", "--access-logfile", "-"]
