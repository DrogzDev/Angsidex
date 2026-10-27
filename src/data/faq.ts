/** Preguntas frecuentes: alimentan la sección visible y el JSON-LD FAQPage (deben coincidir con lo mostrado). */
export interface Faq {
  q: string;
  a: string;
}

export const faqs: readonly Faq[] = [
  {
    q: '¿Cuánto cuesta una página web en Venezuela?',
    a: 'Una landing page parte desde $180 USD y una web corporativa desde $350 USD. El precio final depende del alcance; puedes obtener un estimado al instante en nuestra calculadora o con el asesor de IA.',
  },
  {
    q: '¿Cuánto cuesta una tienda online?',
    a: 'Una tienda online parte desde $550 USD e incluye panel de gestión. Puedes sumar módulos como pedidos, inventario, WhatsApp automatizado o tasa BCV automática según lo que necesite tu negocio.',
  },
  {
    q: '¿Hacen sistemas a medida y automatizaciones?',
    a: 'Sí. Desarrollamos sistemas empresariales personalizados desde $650 USD y automatizaciones independientes desde $120 USD para eliminar tareas repetitivas sin rehacer lo que ya tienes.',
  },
  {
    q: '¿Pueden integrar WhatsApp, facturación digital o la tasa del BCV?',
    a: 'Sí. Configuramos WhatsApp automatizado, facturación digital con planes mensuales y actualización automática de la tasa BCV y USDT para que tus precios en bolívares siempre estén al día.',
  },
  {
    q: '¿Tienen hosting y soporte después del lanzamiento?',
    a: 'Sí. Ofrecemos VPS administrado y mantenimiento mensual, además de acompañamiento continuo después de publicar tu proyecto. También puedes usar tu propio hosting.',
  },
  {
    q: '¿Cómo cotizo mi proyecto?',
    a: 'De tres formas: con el asesor de IA, que te hace las preguntas correctas; con la calculadora, eligiendo módulos tú mismo; o escribiéndonos por WhatsApp. Ninguna te compromete a nada.',
  },
];
