# Angside — sitio web

Astro + TypeScript estricto + Tailwind CSS v4 (`@tailwindcss/vite`) + GSAP. Sitio 100 % estático.

```bash
npm install
npm run dev        # desarrollo
npm run build      # genera dist/ (Cloudflare Pages o Nginx)
npm test           # pruebas del motor del cotizador
npm run check      # astro check (TypeScript)
```

## Dónde editar

| Qué | Archivo |
|---|---|
| Precios, módulos, dependencias, hosting, mantenimiento | `src/data/pricing.ts` |
| Lógica del cotizador (cálculo, URL compartible, resumen) | `src/lib/quote-engine.ts` |
| Enlace de WhatsApp | `src/lib/whatsapp.ts` |
| Contactos y dominio | `src/config/site.ts` (o variables `PUBLIC_*`) |
| Tarjetas de servicios y precios referenciales | `src/data/services.ts` |
| Tarjetas de hosting | `src/data/hosting.ts` |
| Proyectos propios (sección opcional, oculta si está vacía) | `src/data/projects.ts` |

## Pendientes de información (no inventados)

Mientras estén vacíos, los enlaces se muestran como "Próximamente" y el botón de WhatsApp avisa que no está configurado
(el usuario aún puede usar **Copiar presupuesto**).

- `PUBLIC_WHATSAPP` (formato internacional sin `+`, ej. `58412XXXXXXX`), `PUBLIC_INSTAGRAM`, `PUBLIC_TIKTOK`, `PUBLIC_EMAIL`
  (variables de entorno en el build o directamente en `src/config/site.ts`).
- Dominio definitivo: `site.url` en `src/config/site.ts` y `site` en `astro.config.mjs` (canonical, sitemap, Open Graph, `robots.txt`).
- Fotografía real del estudio (`About.astro`) y del servidor Xeon (`Hosting.astro`): hoy son placeholders rotulados "pendiente".
- Especificaciones verificadas del Xeon Lab (solo se indica "plataforma Xeon" y "16 GB RAM").
- Datos estructurados `Organization` (JSON-LD): añadir cuando haya datos verificables.
- Imagen Open Graph propia (1200×630).
- Los precios son propuestas iniciales; confirmar tarifas finales.
- Reparto del pago del desarrollo: hoy 50 % para arrancar y 50 % al entregar (`paymentSplit` en `src/data/pricing.ts`).
- Planes de Cachicamo (`billingPlans`): precios y características copiados de su oferta pública; verificar con el proveedor y actualizar si cambian.
- Textos de condiciones (`projectTerms`: propiedad 100 % del cliente, formalización por escrito, marco legal venezolano): revisarlos con asesoría legal antes de publicar.

## Asistente de IA (Angside AI Advisor)

Botón "Consultar con IA" en el cotizador → formulario previo + Turnstile → chat con OpenRouter. Requiere el backend Django de
`backend/` (ver `backend/README.md`). Se activa con `PUBLIC_API_URL` y `PUBLIC_TURNSTILE_SITEKEY` (ver `.env.example`);
sin ellas, el asistente no aparece. Tras tocar `src/data/pricing.ts` ejecuta `npm run export:contract`.
Pruebas E2E: `node tools/advisor-test.mjs <url> <carpeta>`.

## Notas

- La sección de clientes no contiene logos, cifras ni testimonios.
- "Facturación comercial interna" no implica homologación fiscal (SENIAT); WhatsApp está sujeto a reglas y costos de Meta.
- `tools/` contiene scripts de Playwright para capturas y la prueba E2E del cotizador
  (`node tools/calc-test.mjs http://localhost:4321/` con el sitio en marcha).
"# Angsidex" 
