from django.core.management.base import BaseCommand

from commercial.rates import refresh_rates


class Command(BaseCommand):
    help = 'Consulta las tarifas vigentes de OpenRouter para el modelo del chatbot empresarial (no consume créditos).'

    def handle(self, *args, **options):
        ok, message = refresh_rates()
        (self.stdout.write if ok else self.stderr.write)(message)
