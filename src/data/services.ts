import { baseById, type BaseId } from './pricing';

export interface Service {
  name: string;
  description: string;
  icon: string;
  baseId: BaseId;
  from: number;
}

const s = (baseId: BaseId, name: string, description: string, icon: string): Service => ({
  baseId,
  name,
  description,
  icon,
  from: baseById(baseId)!.price,
});

export const services: readonly Service[] = [
  s('landing', 'Landing page', 'Ideal para lanzar tu marca y captar clientes.', 'monitor'),
  s('tienda', 'Tienda online', 'Vende tus productos sin límites.', 'shopping-bag'),
  s('sistema', 'Sistema a medida', 'Soluciones personalizadas para tu negocio.', 'code-xml'),
  s('automatizacion', 'Automatizaciones', 'Ahorra y elimina tareas repetitivas.', 'settings'),
];

export interface ReferencePrice {
  name: string;
  /** Texto del rango/desde; son estimados, no tarifas finales. */
  price: string;
  icon: string;
  baseId: BaseId;
  includes: string[];
}

export const referencePrices: readonly ReferencePrice[] = [
  { name: 'Landing page', price: '$180 – $400 USD', icon: 'monitor', baseId: 'landing', includes: ['Diseño personalizado', 'Adaptada a móviles', 'Formulario o botón de contacto', 'Contacto por WhatsApp'] },
  { name: 'Web corporativa', price: 'Desde $350 USD', icon: 'building-2', baseId: 'corporativa', includes: ['Varias secciones', 'Diseño adaptado a tu marca', 'Optimización básica para buscadores', 'Formulario de contacto'] },
  { name: 'Tienda online', price: 'Desde $550 USD', icon: 'shopping-bag', baseId: 'tienda', includes: ['Catálogo de productos', 'Gestión de pedidos', 'Panel administrativo', 'Pagos sujetos a evaluación'] },
  { name: 'Sistema a medida', price: 'Desde $650 USD', icon: 'code-xml', baseId: 'sistema', includes: ['Acceso con usuarios', 'Almacenamiento de datos', 'Panel administrativo', 'Módulos según alcance'] },
  { name: 'Automatizaciones', price: 'Desde $120 USD', icon: 'settings', baseId: 'automatizacion', includes: ['Una tarea o flujo definido', 'Conexión con tus herramientas', 'Pruebas antes de entregar', 'Integraciones según evaluación'] },
];
