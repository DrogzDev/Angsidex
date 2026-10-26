# Angside AI Advisor — backend (Django)

API del asistente comercial: formulario previo + Cloudflare Turnstile + chat con OpenRouter (streaming y herramientas)
+ captación de prospectos. El sitio (Astro) vive en la carpeta superior.

## Puesta en marcha

```bash
cd backend
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env        # completar (ver abajo)
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py createsuperuser   # para ver los prospectos en /admin/
.venv\Scripts\python manage.py runserver 8765
```

En el sitio: `PUBLIC_API_URL=http://localhost:8765` y `PUBLIC_TURNSTILE_SITEKEY` en `../.env` (y volver a construir con `npm run build`).
Si `PUBLIC_API_URL` está vacío, el asistente y su botón **no se muestran**.

## Variables de entorno (`.env`, nunca en el repo)

| Variable | Uso |
|---|---|
| `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` | Django. Sin `DEBUG` la clave es obligatoria. |
| `ALLOWED_ORIGINS` | Dominios del sitio autorizados por CORS. |
| `TURNSTILE_SECRET` | Secret de Turnstile. Prueba: `1x0000000000000000000000000000000AA`. |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODELS` | IA. Cambiar de modelo **no** requiere tocar el frontend. |
| `AI_MAX_USER_MESSAGES_PER_SESSION`, `AI_MAX_TOKENS_PER_SESSION`, `AI_MAX_OUTPUT_TOKENS` | Topes por conversación. |
| `AI_DAILY_BUDGET_USD`, `AI_MONTHLY_BUDGET_USD` | Presupuesto de IA: al agotarse, el asistente se desactiva con un mensaje amable. |
| `TRUST_CF_CONNECTING_IP` | Solo si el origen recibe únicamente tráfico de Cloudflare. |

## Modelo de IA

Por defecto `z-ai/glm-5.3-flash-20260826` (GLM-5.3 Flash). Verificado en la API pública de OpenRouter: soporta `tools`,
`tool_choice` y `structured_outputs` ($0,15/M tokens de entrada, $0,50/M de salida). Se usa con streaming y razonamiento bajo y
oculto (`AI_REASONING_EFFORT`). Cambiarlo es solo cambiar `OPENROUTER_MODEL`; el frontend no lo conoce.
**No se ha probado contra OpenRouter real** (solo contra un simulador): corre `python manage.py live_scenarios` con tu clave.

## Endpoints (`/api/ai/`)

- `POST sessions` — valida el formulario, verifica Turnstile **en el servidor** (token de un solo uso), crea prospecto y sesión
  (idempotente con `Idempotency-Key`; reutiliza la sesión reciente del mismo contacto). Devuelve un token firmado de sesión.
- `GET sessions/<id>` — historial para reanudar.
- `POST sessions/<id>/messages` — mensaje del usuario; respuesta `text/event-stream` con eventos `delta`, `proposals` (tarjetas validadas), `profile`, `negotiation`, `contact_requested`, `price_notice`, `error`, `done`.
- `POST sessions/<id>/request-contact` — el visitante pide contacto; con `proposal_id` solicita una propuesta concreta (solo de su sesión).
- `PATCH sessions/<id>/profile` — el visitante corrige su clasificación (pequeño / mediano / grande). Es informativa: **nunca cambia los precios**.

Los límites (IP, contacto, sesión), el tope de mensajes/tokens y el presupuesto se aplican en el servidor y se guardan en base de datos
(funcionan con varios procesos). Los logs no contienen claves, tokens de CAPTCHA ni cuerpos de respuestas de proveedores.

## Fuente única de precios

Los precios y reglas salen de `../src/data/pricing.ts`. Tras cambiarlos:

```bash
cd ..
npm run export:contract    # regenera backend/angside_ai/data/pricing.json y tests/fixtures/quote_cases.json
cd backend && .venv\Scripts\python -m pytest
```

`angside_ai/quote.py` replica `quote-engine.ts`; los 276 casos de paridad garantizan que ambos den los mismos totales. La IA no
calcula: solo elige ids de módulos con `propose_options` y Django calcula todo.

## Asesor comercial: cómo funciona

1. **Descubrimiento:** saludo natural y una pregunta a la vez; no repite lo que ya está en el formulario.
2. **`classify_client`:** tamaño orientativo (small/medium/large; editable por el cliente; no afecta precios), necesidades, presupuesto
   indicado y señales de alcance (usuarios, sucursales, volumen, integraciones, seguridad…).
3. **`propose_options`:** de 1 a 3 opciones (Esencial, Recomendada, Completa o Ajustada). Django valida cada una con el motor y calcula
   precio, pagos en dos partes, costos recurrentes y **complejidad** (`complexity.py`, solo por alcance: Básica, Intermedia, Avanzada o
   Personalizada). Lo que no existe en el cotizador va en `custom_items` y se muestra como "Requiere cotización personalizada" sin
   precio. El plazo siempre es "Pendiente de evaluación" (no hay una regla de estimación aprobada). Los beneficios por funcionalidad se
   descartan si traen cifras, descuentos o promesas. Llegan al chat como **tarjetas** (datos del servidor, no texto libre).
4. **Negociación:** `record_negotiation` (motivo, presupuesto inicial = recomendada vigente, presupuesto ideal) y `record_objection`; la
   IA recalcula con un alcance menor, nunca aprueba descuentos y ofrece contacto humano (`request_contact`).
5. **Guardia de precios:** si el texto libre menciona montos que no vienen del catálogo, de las propuestas ni del propio visitante (o
   palabras de descuento), se avisa en el chat y queda registrado.
6. **CRM (Django Admin):** tamaño, complejidad, necesidades, funcionalidades recomendadas, propuestas de cada ronda, presupuesto
   indicado y calculado, objeciones, negociación y contacto. Exportación CSV.

Umbrales de complejidad (`angside_ai/complexity.py`): puntos por tipo de proyecto, funcionalidades, integraciones, roles/auditoría,
usuarios, sucursales, volumen y procesos; hasta 2 básica, 3–6 intermedia, 7 o más avanzada. Es **personalizada** si hay desarrollo a
medida, integración con sistemas existentes, seguridad/disponibilidad/auditoría especiales, infraestructura especial, 4+ sucursales o
200+ usuarios. Son reglas propuestas: ajústalas a tu criterio comercial.

## Pruebas

```bash
.venv\Scripts\python -m pytest   # API, límites, CAPTCHA, herramientas, paridad con TypeScript y las 9 conversaciones simuladas
```

`tests/test_scenarios.py` simula (con un guion de herramientas en lugar del modelo) los 9 escenarios del encargo y comprueba que cada
precio coincide exactamente con el motor, que el tamaño del cliente no cambia los precios y que ninguna herramienta acepta precios ni
descuentos.

Contra el modelo real (gasta créditos; deja el CRM limpio):

```bash
python manage.py live_scenarios        # o: live_scenarios 3 7
```

E2E con el simulador de OpenRouter (sin gastar créditos):

```bash
python tests/mock_openrouter.py 9099
set OPENROUTER_API_KEY=mock & set OPENROUTER_BASE_URL=http://127.0.0.1:9099 & python manage.py runserver 8765
node ../tools/advisor-test.mjs http://localhost:4399/ <carpeta-de-capturas>
```

## Modalidades de pago, descuento de contado y chatbot IA (app `commercial`)

**Una sola fuente de verdad**: Django Admin → *Configuración comercial*. El cotizador de Astro descarga `GET /api/commercial/config`
al cargar y el asesor GLM lee la misma configuración (prompt y herramientas). Si la API no responde, el cotizador usa los valores
por defecto de `src/data/commercial.ts` (los mismos que siembran la base la primera vez, vía `npm run export:contract`).

- **Editable en el admin**: descuento de contado (activar/desactivar, %, desarrollo mínimo), mínimo para financiar, cada plan
  (incremento, inicial, nº de cuotas, periodicidad), modelo de IA del chatbot, tarifas de respaldo, consultas por conversación,
  tokens por consulta, margen, límite mensual, niveles de uso y reglas por módulo (excluir del descuento / costo mínimo).
- **Validación administrativa**: una regla por módulo con *costo mínimo de implementación* no se guarda si el precio con descuento
  queda por debajo, salvo que se excluya del descuento. Subir el % del descuento también se bloquea si rompe una regla existente.
- **Versionado**: cada cambio genera una `PricingVersion` inmutable (misma configuración = misma versión). Las cotizaciones registradas
  (`SavedQuote`) y las propuestas del asesor guardan su versión: los presupuestos históricos no cambian en silencio.
- **Tarifas de OpenRouter**: `python manage.py refresh_ai_rates` (o la acción *Actualizar tarifas desde OpenRouter* en el admin)
  consulta el listado público de modelos (sin clave ni créditos), guarda la fecha y, si falla, conserva la tarifa de respaldo.
- **API**: `GET /api/commercial/config` y `POST /api/commercial/quotes` (registra la cotización enviada por WhatsApp: recalcula los
  importes en el servidor, no guarda datos personales; limitado por IP).
- **Asesor**: herramientas `get_payment_options`, `select_payment_mode` y `request_payment_plan_negotiation` (deriva a una persona).
  El modelo solo elige ids; descuentos, porcentajes e importes los calcula `commercial/engine.py`. El guardia marca porcentajes o
  montos que no existan en la configuración vigente.
- **Chatbot empresarial** es un producto aparte de Angside AI Advisor: sus tarifas y estimaciones no tocan `AI_DAILY_BUDGET_USD`
  ni `AI_PRICE_*`. Esta entrega cubre su cotización y estimación; el runtime del chatbot de cada cliente no está incluido.

Pruebas: `tests/test_commercial.py` (motor, admin, versiones, API, herramientas, guardia) y `tests/test_quote_parity.py` (paridad TS ↔ Python).
E2E visual: `node ../tools/payments-test.mjs http://127.0.0.1:4321/ <carpeta-de-capturas>`.

## Pendiente / decisiones abiertas

- Sin notificaciones automáticas al equipo (correo/WhatsApp) cuando un prospecto solicita contacto o negocia: hoy se consulta en `/admin/`.
- No hay regla de estimación de plazos aprobada: las tarjetas dicen "Pendiente de evaluación".
- La política de privacidad (`/privacidad`) es un **borrador**: revisar con asesoría legal. Versión en `PRIVACY_POLICY_VERSION`.
- Producción: Postgres, HTTPS, proxy sin buffering para SSE (ya se envía `X-Accel-Buffering: no`) y un servidor WSGI/ASGI con hilos.

## Panel de administración (frontend `/admin`)

Login por sesión de Django con CSRF. Flujo: `GET /api/panel/csrf` → `POST /api/panel/login` (cabecera `X-CSRFToken`) → cookie `angside_sid` (HttpOnly, SameSite=Lax). Los endpoints de datos (`overview`, `leads`, `quotes`) exigen `is_staff`; los usuarios sin ese permiso reciben `role: "client"` en `/api/panel/me` (base del futuro portal de clientes).

- **Mismo sitio:** la cookie es SameSite=Lax, así que el frontend y la API deben compartir dominio registrable (p. ej. `angside.com` y `api.angside.com`). En desarrollo, abre el sitio y la API con el mismo host (`localhost` o `127.0.0.1`; el panel alinea el host de la API automáticamente).
- **Variables:** `ALLOWED_ORIGINS` debe listar el origen del frontend (se usa para CORS con credenciales y `CSRF_TRUSTED_ORIGINS`). En producción las cookies son `Secure`.
- **Límites de intentos:** `panel_login_ip` (10 / 15 min) y `panel_login_user` (6 / 15 min) en `RATE_LIMITS`.
- Crear usuarios del equipo: `python manage.py createsuperuser` o desde Django Admin con «Es staff».
