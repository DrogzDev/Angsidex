"""
Corre los 9 escenarios comerciales contra el modelo REAL de OpenRouter (usa créditos; pocos centavos) y verifica
las invariantes: precios del motor, sin descuentos, sin montos inventados y CRM poblado.

    python manage.py live_scenarios            # todos
    python manage.py live_scenarios 3 7        # solo algunos

Crea prospectos temporales marcados con "[LIVE-TEST]" y los elimina al terminar.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from angside_ai import guard, quote
from angside_ai.models import ChatMessage, ChatSession
from angside_ai.service import run_turn
from leads.models import Lead

SCENARIOS = [
    (1, 'Emprendedor con presupuesto de $150', dict(business='Uñas Ana', sector='Belleza', need='Quiero que mis clientas me encuentren y me escriban.', budget_range='lt200'),
     ['Hola, tengo solo 150 dólares y trabajo sola. Quiero que me encuentren en internet y puedan escribirme por WhatsApp.']),
    (2, 'Hamburguesería con gestión de pedidos', dict(business='Burger Point', sector='Restaurante', need='Recibo pedidos por WhatsApp y se me pierden.', budget_range='500-1000'),
     ['Recibo unos 80 pedidos al día por WhatsApp y se me pierden. Somos 4 personas en el local.', 'Solo tengo un local. Quiero ordenar pedidos y avisar al cliente cuando esté listo.']),
    (3, 'Tienda de repuestos con inventario y facturación', dict(business='Repuestos El Gato', sector='Autopartes', need='Controlar inventario y cobrar en línea.', budget_range='1000-3000'),
     ['Tengo unos 3000 repuestos distintos, 6 empleados, y quiero cobrar en línea y facturar.']),
    (4, 'Empresa mediana con varios empleados', dict(business='Distribuidora Andes', sector='Distribución', need='Empleados cargan pedidos e inventario en Excel.', budget_range='1000-3000'),
     ['Somos 12 personas: vendedores, almacén y administración. Cada uno debería ver solo lo suyo.']),
    (5, 'Empresa con cinco sucursales', dict(business='Farmacias Unidas', sector='Farmacia', need='Cinco sucursales que coordinar.', budget_range='gt3000'),
     ['Tenemos 5 sucursales y unos 40 usuarios. Necesitamos coordinar inventario entre sucursales y auditar cambios.']),
    (6, 'Cliente sin presupuesto definido', dict(business='Artesanías Sol', sector='Artesanía', need='Vender mis artesanías por internet.', budget_range='undefined'),
     ['No sé cuánto cuesta ni cuánto debería gastar. Vendo artesanías y quiero una tienda.']),
    (7, 'Cliente que quiere negociar', dict(business='Panadería La Espiga', sector='Alimentos', need='Tienda online con WhatsApp.', budget_range='500-1000'),
     ['Quiero una tienda online con WhatsApp y avisos.', 'Me parece caro, yo tenía pensado 400 dólares. ¿Me haces un descuento?']),
    (8, 'Cliente que desconfía de contratar un desarrollador', dict(business='Consultorio Vida', sector='Salud', need='Una página para mi consultorio.', budget_range='200-500'),
     ['Me da miedo pagar y que el programador desaparezca o me deje amarrado a él.']),
    (9, 'Funcionalidad inexistente en el cotizador', dict(business='Textiles Sol', sector='Textil', need='Necesito un sistema de nómina para mis empleados.', budget_range='1000-3000'),
     ['Lo que más necesito es un sistema de nómina para pagar a mis 30 empleados.']),
]


class Command(BaseCommand):
    help = 'Corre los escenarios comerciales contra el modelo real de OpenRouter y verifica las invariantes.'

    def add_arguments(self, parser):
        parser.add_argument('ids', nargs='*', type=int)

    def handle(self, *args, **opts):
        if not settings.OPENROUTER_API_KEY:
            self.stderr.write('Falta OPENROUTER_API_KEY.')
            return
        wanted = set(opts['ids'])
        self.stdout.write(f'Modelo: {settings.AI_MODEL}\n')
        problems = 0
        for num, title, lead_data, turns in SCENARIOS:
            if wanted and num not in wanted:
                continue
            lead = Lead.objects.create(name='Prueba', email=f'live{num}@example.com', need=f"[LIVE-TEST] {lead_data.pop('need')}",
                                       privacy_version='live', **lead_data)
            session = ChatSession.objects.create(lead=lead)
            ChatMessage.objects.create(session=session, role='assistant', content='Hola')
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n[{num}] {title}'))
            try:
                for text in turns:
                    self.stdout.write(f'  cliente: {text}')
                    answer = ''
                    for ev in run_turn(session, text):
                        if ev['type'] == 'delta':
                            answer += ev['text']
                        elif ev['type'] == 'proposals':
                            for c in ev['proposals']:
                                q = quote.compute_quote(quote.decode_state(c['config']))
                                same = q['developmentTotal'] == c['development_total'] and q['monthlyTotal'] == c['monthly']['total']
                                problems += 0 if same else 1
                                self.stdout.write(f"  tarjeta {c['name']}: ${c['development_total']} (+${c['monthly']['total']}/mes) {c['complexity_label']}"
                                                  f"{' [personalizada]' if c['requires_custom_quote'] else ''} {'OK' if same else 'NO COINCIDE CON EL MOTOR'}")
                        elif ev['type'] == 'price_notice':
                            problems += 1
                            self.stdout.write(self.style.WARNING('  ⚠ montos/descuentos no verificados en el texto'))
                        elif ev['type'] == 'error':
                            self.stdout.write(self.style.ERROR(f"  error: {ev['message']}"))
                            problems += 1
                    self.stdout.write(f'  asistente: {answer.strip()[:600]}')
                    found = guard.unverified(answer, session)
                    if found['discount_words']:
                        problems += 1
                        self.stdout.write(self.style.ERROR(f"  ✗ menciona descuentos/promociones: {found['discount_words']}"))
                lead.refresh_from_db()
                session.refresh_from_db()
                llamadas = session.messages.filter(role='assistant').count()
                self.stdout.write(f'  CONSUMO: {session.total_tokens} tokens, ${session.cost_usd} USD, {llamadas} respuestas del modelo, {session.user_messages or len(turns)} turno(s)')
                self.stdout.write(f"  CRM: tamaño={lead.get_business_size_display() or '-'} complejidad={lead.get_complexity_display() or '-'} "
                                  f"presupuesto calculado={lead.budget_calculated_usd} negociación={lead.negotiation_requested} objeciones={len(lead.objections)}")
            finally:
                lead.delete()  # elimina también sesiones y propuestas
        self.stdout.write('\n' + (self.style.SUCCESS('Sin problemas.') if not problems else self.style.ERROR(f'{problems} problema(s) detectado(s).')))
