/**
 * Precios y reglas comerciales del cotizador.
 * Todos son tarifas iniciales propuestas (USD), sujetas a alcance. Edita aquí; nada más en el código los repite.
 */

export type BaseId =
  | 'landing'
  | 'corporativa'
  | 'catalogo'
  | 'tienda'
  | 'sistema'
  | 'automatizacion'
  | 'chatbot-ia';

export type CategoryId = 'ventas' | 'admin' | 'fiscal' | 'integraciones' | 'ia';

export type DependencyId = 'auth' | 'data';

export type ModuleId =
  | 'whatsapp'
  | 'crm'
  | 'pedidos'
  | 'excel'
  | 'roles'
  | 'panel'
  | 'inventario'
  | 'facturacion'
  | 'bcv'
  | 'reportes'
  | 'reservas'
  | 'notificaciones'
  | 'auditoria'
  | 'chatbot';

export type HostingId = 'externo' | 'vps-basico' | 'vps-superior' | 'xeon';

export type BillingPlanId = 'emprendedor' | 'pymes' | 'gold';

/** Plan de facturación digital que Angside configura y gestiona: costo mensual fijo. */
export interface BillingPlan {
  id: BillingPlanId;
  name: string;
  monthly: number;
  features: string[];
}

export interface BaseOption {
  id: BaseId;
  name: string;
  price: number;
  /** Muestra "Desde": el alcance real depende de la evaluación. */
  from?: boolean;
  description: string;
  icon: string;
  /** Módulos y dependencias que ya vienen incluidos en la base (no se cobran dos veces). */
  includes: ReadonlyArray<ModuleId | DependencyId>;
  /** La base es, comercialmente, este módulo vendido solo: las reglas por módulo (p. ej. exclusión de descuentos) también le aplican. */
  sameAs?: ModuleId;
}

export interface Dependency {
  id: DependencyId;
  name: string;
  price: number;
  reason: string;
}

export interface ModuleOption {
  id: ModuleId;
  name: string;
  category: CategoryId;
  price: number;
  /** Muestra "Desde" porque el alcance real depende de la evaluación. */
  from?: boolean;
  description: string;
  icon: string;
  requires: ReadonlyArray<DependencyId>;
  /** Bases con las que este módulo no aplica. */
  incompatibleWith?: ReadonlyArray<BaseId>;
  /** Aviso que aparece en la tarjeta y en la propuesta. */
  notice?: string;
  /** Alcance del precio base: qué incluye y qué se cotiza aparte como módulo adicional. */
  scope?: { included: string[]; excluded: string[] };
}

export interface HostingOption {
  id: HostingId;
  name: string;
  monthly: number;
  from?: boolean;
  description: string;
  /** Requiere evaluación y disponibilidad antes de confirmarse. */
  needsEvaluation?: boolean;
}

export const bases: readonly BaseOption[] = [
  { id: 'landing', name: 'Landing page', price: 180, icon: 'monitor', description: 'Una página para presentar tu oferta y captar contactos.', includes: [] },
  { id: 'corporativa', name: 'Web corporativa', price: 350, icon: 'building-2', description: 'Sitio de varias secciones para presentar tu empresa.', includes: [] },
  { id: 'catalogo', name: 'Catálogo digital', price: 280, icon: 'book-open', description: 'Muestra tus productos y recibe consultas.', includes: [] },
  { id: 'tienda', name: 'Tienda online', price: 550, icon: 'shopping-bag', description: 'Vende productos en línea con panel de gestión.', includes: ['auth', 'data', 'pedidos', 'panel'] },
  { id: 'sistema', name: 'Sistema empresarial', price: 650, icon: 'code-xml', description: 'Sistema personalizado con acceso de usuarios y panel.', includes: ['auth', 'data', 'panel'] },
  { id: 'automatizacion', name: 'Automatización independiente', price: 120, icon: 'settings', description: 'Automatiza una tarea repetitiva sin rehacer tu sistema.', includes: [] },
  { id: 'chatbot-ia', name: 'Chatbot empresarial con IA', price: 100, from: true, icon: 'bot', description: 'Solo el asistente inteligente para tu negocio, sin rehacer tu página.', includes: ['chatbot'], sameAs: 'chatbot' },
];

export const dependencies: Readonly<Record<DependencyId, Dependency>> = {
  auth: { id: 'auth', name: 'Autenticación de usuarios', price: 80, reason: 'Necesaria para controlar quién entra y con qué permisos.' },
  data: { id: 'data', name: 'Almacenamiento de datos', price: 100, reason: 'Necesario para guardar y consultar registros de forma persistente.' },
};

export const categories: ReadonlyArray<{ id: CategoryId; name: string }> = [
  { id: 'ventas', name: 'Clientes y ventas' },
  { id: 'admin', name: 'Administración' },
  { id: 'fiscal', name: 'Facturación y Venezuela' },
  { id: 'integraciones', name: 'Integraciones' },
  { id: 'ia', name: 'Inteligencia artificial' },
];

const sinLanding: ReadonlyArray<BaseId> = ['landing'];

export const modules: readonly ModuleOption[] = [
  { id: 'whatsapp', name: 'WhatsApp automatizado', category: 'ventas', price: 150, icon: 'message-circle', description: 'Tu negocio responde en WhatsApp aunque no estés: saluda, contesta las preguntas frecuentes y avisa a tus clientes sobre sus pedidos o citas.', requires: [], notice: 'Sujeto a las reglas de Meta; el uso de la API puede generar costos aparte.' },
  { id: 'crm', name: 'CRM de clientes', category: 'ventas', price: 180, icon: 'users', description: 'Una libreta digital de tus clientes: quién es cada uno, qué te ha comprado y cuándo te conviene volver a contactarlo.', requires: ['data'], incompatibleWith: sinLanding },
  { id: 'pedidos', name: 'Gestión de pedidos', category: 'ventas', price: 180, icon: 'package', description: 'Recibe todos los pedidos en un solo lugar y mira en qué etapa va cada uno: recibido, en preparación o entregado.', requires: ['data'], incompatibleWith: ['landing', 'corporativa'] },
  { id: 'excel', name: 'Importación de Excel', category: 'admin', price: 100, icon: 'file-spreadsheet', description: 'Pasa tus listas de productos o clientes de Excel al sistema de una sola vez, sin escribirlas a mano.', requires: [], incompatibleWith: sinLanding, notice: 'Requiere definir columnas y formato de importación.' },
  { id: 'roles', name: 'Usuarios y roles', category: 'admin', price: 150, icon: 'shield-check', description: 'Decide quién puede ver o hacer qué: por ejemplo, que el vendedor registre ventas pero solo tú veas los reportes.', requires: ['auth'], incompatibleWith: sinLanding },
  { id: 'panel', name: 'Panel administrativo', category: 'admin', price: 180, icon: 'layout-dashboard', description: 'Una pantalla privada para cambiar textos, productos y precios tú mismo, sin depender de nadie.', requires: ['auth'], incompatibleWith: sinLanding },
  { id: 'inventario', name: 'Inventario', category: 'admin', price: 160, icon: 'boxes', description: 'Sabes cuánto tienes de cada producto, qué entra y qué sale, y te avisa cuando algo se está acabando.', requires: ['data'], incompatibleWith: ['landing', 'corporativa'] },
  { id: 'facturacion', name: 'Facturación digital', category: 'fiscal', price: 180, icon: 'receipt', description: 'Emite las facturas de tus ventas desde el mismo sistema. Nosotros la configuramos y la gestionamos; tú eliges el plan según el tamaño de tu empresa.', requires: ['data', 'auth'], incompatibleWith: ['landing', 'corporativa'], notice: 'Incluye el plan de facturación que elijas, con costo mensual fijo que cubre su gestión por parte de Angside. Las exigencias del SENIAT se evalúan por separado.' },
  { id: 'bcv', name: 'Tasa BCV y USDT automática', category: 'fiscal', price: 90, icon: 'refresh-cw', description: 'Tus precios en bolívares se actualizan solos con la tasa oficial del BCV y con la de USDT, sin que tengas que cambiarlos cada día.', requires: [] },
  { id: 'reportes', name: 'Reportes y estadísticas', category: 'fiscal', price: 120, icon: 'bar-chart-3', description: 'Resúmenes claros de tu negocio: cuánto vendes, qué se vende más y cómo vas frente al mes pasado.', requires: ['data'], incompatibleWith: sinLanding },
  { id: 'reservas', name: 'Reservas y citas', category: 'integraciones', price: 150, icon: 'calendar-check', description: 'Tus clientes eligen día y hora para su cita y tú la confirmas, sin coordinar todo por mensajes.', requires: ['data'] },
  { id: 'notificaciones', name: 'Notificaciones', category: 'integraciones', price: 90, icon: 'bell', description: 'Avisos automáticos por correo u otros canales: confirmaciones, recordatorios y novedades para tus clientes.', requires: [], notice: 'Los servicios de envío de terceros pueden tener costos propios.' },
  { id: 'auditoria', name: 'Auditoría de acciones', category: 'integraciones', price: 100, icon: 'scroll-text', description: 'Un historial de quién hizo qué y cuándo dentro del sistema, para tener claridad y control.', requires: ['data', 'auth'], incompatibleWith: sinLanding },
  {
    id: 'chatbot',
    name: 'Chatbot empresarial con inteligencia artificial',
    category: 'ia',
    price: 100,
    from: true,
    icon: 'bot',
    description: 'Integra un asistente inteligente que responde preguntas de clientes, consulta información autorizada de tu negocio y ayuda a automatizar la atención.',
    requires: [],
    notice: 'El precio es solo la implementación. El consumo de inteligencia artificial es un costo recurrente variable, aparte; hosting, mantenimiento e integraciones adicionales también se cotizan por separado.',
    scope: {
      included: [
        'Widget básico integrado a la página',
        'Personalización visual sencilla',
        'Preguntas frecuentes',
        'Respuestas basadas en información comercial proporcionada por el cliente',
        'Configuración inicial del modelo',
        'Límites de uso',
        'Mensaje para solicitar atención humana',
      ],
      excluded: [
        'Integraciones personalizadas con ERP',
        'Consulta de información sensible',
        'Operaciones sobre inventarios',
        'Cambios de pedidos',
        'Integración oficial con WhatsApp',
        'Múltiples sistemas externos',
        'Desarrollo de herramientas a medida',
        'Grandes cargas documentales o bases de conocimiento complejas',
      ],
    },
  },
];

export const hostingOptions: readonly HostingOption[] = [
  { id: 'externo', name: 'Hosting externo del cliente', monthly: 0, description: 'Usas tu propio proveedor. Coordinamos el despliegue.' },
  { id: 'vps-basico', name: 'VPS básico administrado', monthly: 15, from: true, description: 'Para proyectos pequeños.' },
  { id: 'vps-superior', name: 'VPS administrado superior', monthly: 35, from: true, description: 'Para sistemas con más carga.' },
  { id: 'xeon', name: 'Servidor Xeon compartido', monthly: 65, from: true, needsEvaluation: true, description: 'Sujeto a disponibilidad y evaluación previa.' },
];

export const maintenance = {
  name: 'Mantenimiento básico',
  monthly: 25,
  description: 'Revisiones y ajustes menores. No incluye hosting, dominio ni servicios de terceros.',
} as const;

/** Facturación digital gestionada por Angside. Rango derivado de `billingPlans`. */
export const billingService = {
  name: 'Facturación digital',
  blurb: 'Si quieres facturación digital, la configuramos y la gestionamos nosotros.',
} as const;

export const billingPlans: readonly BillingPlan[] = [
  { id: 'emprendedor', name: 'Emprendedor', monthly: 20, features: ['150 facturas de venta al mes', 'Hasta $10.000 en ventas mensuales', '1 usuario (el dueño de la cuenta)', 'Facturación digital'] },
  { id: 'pymes', name: 'Pymes', monthly: 30, features: ['1.500 facturas de venta al mes', 'Hasta $25.000 en ventas mensuales', 'Hasta 3 usuarios con roles y permisos', 'Facturación digital'] },
  { id: 'gold', name: 'Gold', monthly: 55, features: ['5.000 facturas de venta al mes', 'Sin límite de monto en ventas', 'Usuarios ilimitados con roles y permisos', 'Hasta 3 sucursales y facturación digital'] },
];

/** Cómo se paga el desarrollo: dos partes. `start` es la fracción para arrancar; el resto, al entregar. */
export const paymentSplit = { start: 0.5 } as const;

/** Qué cubre cada concepto: se muestra junto al cotizador para no mezclarlos. */
export const costNotes: readonly string[] = [
  'Hosting, dominio, mantenimiento, soporte técnico y servicios de terceros (como Meta) se presupuestan por separado del desarrollo.',
  'Los precios son estimados iniciales y pueden variar según el alcance.',
];

/** Condiciones del proyecto mostradas junto al cotizador. Revisar con asesoría legal antes de publicar. */
export const projectTerms: ReadonlyArray<{ title: string; text: string }> = [
  { title: 'Pago en dos partes', text: 'Una parte para arrancar el desarrollo y la otra al culminar, cuando ya ves todo funcionando.' },
  { title: 'El sistema es 100 % tuyo', text: 'Una vez completado el pago, el sistema te pertenece: recibes el código y la documentación, y puedes contratar a otros programadores para mantenerlo o ampliarlo.' },
  { title: 'Todo por escrito', text: 'El alcance, los pagos, los plazos y la propiedad del sistema quedan en una propuesta o contrato formal, conforme a la normativa venezolana aplicable.' },
  { title: 'Facturación digital y terceros', text: 'La facturación digital la configuramos y la gestionamos nosotros (de $20 a $55 al mes según la magnitud de tu empresa). Hosting, dominio y servicios como WhatsApp se rigen por las condiciones de cada proveedor; el cumplimiento fiscal ante el SENIAT se evalúa aparte.' },
];

export const moduleById = (id: string) => modules.find((m) => m.id === id);
export const baseById = (id: string) => bases.find((b) => b.id === id);
export const hostingById = (id: string) => hostingOptions.find((h) => h.id === id);
export const billingPlanById = (id: string) => billingPlans.find((p) => p.id === id);
export const billingRange = {
  min: Math.min(...billingPlans.map((p) => p.monthly)),
  max: Math.max(...billingPlans.map((p) => p.monthly)),
};
