"""
Servidor local que imita /chat/completions de OpenRouter (streaming SSE) para pruebas de extremo a extremo
sin gastar créditos. Reproduce el flujo del asistente comercial con herramientas.
Uso: python tests/mock_openrouter.py [puerto]
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def sse(handler, chunks):
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream')
    handler.end_headers()
    for c in chunks:
        handler.wfile.write(f'data: {json.dumps(c)}\n\n'.encode())
        handler.wfile.flush()
    handler.wfile.write(b'data: [DONE]\n\n')
    handler.wfile.flush()


def text(t):
    words = t.split(' ')
    chunks = [{'choices': [{'delta': {'content': w + ' '}}]} for w in words]
    chunks.append({'choices': [], 'usage': {'prompt_tokens': 800, 'completion_tokens': len(words), 'cost': 0.0003}})
    return chunks


def call(name, args, cid):
    return [
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': cid, 'function': {'name': name, 'arguments': json.dumps(args)}}]}}]},
        {'choices': [], 'usage': {'prompt_tokens': 900, 'completion_tokens': 40, 'cost': 0.0004}},
    ]


def opt(tier, base, modules=(), hosting='externo', **extra):
    return {'tier': tier, 'base_id': base, 'module_ids': list(modules), 'hosting_id': hosting, **extra}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        msgs = body.get('messages', [])
        tools = bool(body.get('tools'))
        last = msgs[-1] if msgs else {}
        user_text = next((m['content'] for m in reversed(msgs) if m['role'] == 'user'), '').lower()
        tool_text = last.get('content', '') if last.get('role') == 'tool' else ''

        if not tools:
            sse(self, text('Con esto ya tienes un panorama claro. Si quieres, una persona del equipo puede revisar tu caso.'))
        elif 'negociar' in user_text or 'caro' in user_text or 'elevado' in user_text:
            if not last.get('role') == 'tool':
                sse(self, call('record_negotiation', {'reason': 'Considera elevado el presupuesto', 'ideal_budget_usd': 500}, 'neg1'))
            elif 'presupuesto_inicial_usd' in tool_text:
                sse(self, call('propose_options', {'options': [opt('adjusted', 'catalogo', ['whatsapp'])]}, 'neg2'))
            else:
                sse(self, text('Reduje el alcance a un catálogo con WhatsApp para acercarlo a lo que tenías previsto.'))
        elif 'sucursal' in user_text:
            if last.get('role') != 'tool':
                sse(self, call('classify_client', {'business_size': 'large', 'signals': {'branches': 5, 'users_estimate': 40}}, 'cl1'))
            elif 'business_size' in tool_text:
                sse(self, call('propose_options', {'options': [opt('recommended', 'sistema', ['inventario', 'roles', 'reportes'], 'vps-superior',
                                                                    custom_items=['Sincronización de inventario entre sucursales'])]}, 'pr1'))
            else:
                sse(self, text('La coordinación entre sucursales requiere una cotización personalizada; lo demás ya está cotizado.'))
        elif 'tienda' in user_text:
            if last.get('role') != 'tool':
                sse(self, call('classify_client', {'business_size': 'small', 'signals': {'users_estimate': 3}, 'needs_summary': 'Vender productos por internet'}, 'cl1'))
            elif 'business_size' in tool_text:
                sse(self, call('propose_options', {'options': [
                    opt('essential', 'tienda', hosting='vps-basico', benefits=[{'feature_id': 'pedidos', 'benefit': 'Ordena cada pedido y evita que se pierdan mensajes.'}]),
                    opt('recommended', 'tienda', ['whatsapp', 'notificaciones'], 'vps-basico'),
                    opt('complete', 'tienda', ['whatsapp', 'notificaciones', 'reportes', 'facturacion'], 'vps-basico', billing_plan_id='emprendedor'),
                ]}, 'pr1'))
            else:
                sse(self, text('Te recomiendo la del medio: ordena tus pedidos y te avisa por WhatsApp. La completa suma reportes y facturación digital.'))
        else:
            sse(self, text('Entendido. Cuéntame cuántos productos manejas y si ya tienes inventario.'))


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9099
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
