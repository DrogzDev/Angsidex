import { baseById, hostingById, type HostingId } from './pricing';

export interface HostingCard {
  id: HostingId;
  name: string;
  tagline: string;
  features: string[];
  cta: string;
}

const monthly = (id: HostingId) => hostingById(id)!.monthly;

const SALE_PRICE = 700;
const SALE_DISCOUNT = 50;
const exampleBase = baseById('sistema')!;
const exampleSaving = (exampleBase.price * SALE_DISCOUNT) / 100;

/** Los recursos concretos (CPU, RAM, disco) se definen en cada propuesta; aquí no se prometen. */
export const hostingCards: readonly (HostingCard & { monthly: number })[] = [
  {
    id: 'vps-basico',
    name: 'VPS básico',
    tagline: 'Para sitios y sistemas pequeños.',
    features: ['Administrado por Angside', 'Despliegue de tu proyecto', 'Recursos definidos en la propuesta'],
    cta: 'Solicitar',
    monthly: monthly('vps-basico'),
  },
  {
    id: 'vps-superior',
    name: 'VPS superior',
    tagline: 'Para proyectos con más carga o varios servicios.',
    features: ['Administrado por Angside', 'Más recursos que el básico', 'Recursos definidos en la propuesta'],
    cta: 'Solicitar',
    monthly: monthly('vps-superior'),
  },
];

export const xeonLab = {
  id: 'xeon' as HostingId,
  name: 'Angside Xeon Lab',
  tagline: 'Servicio sujeto a evaluación y disponibilidad.',
  features: ['Plataforma Xeon', '16 GB de RAM', 'Alojamiento de aplicaciones y procesos', 'Configuraciones personalizadas'],
  monthly: monthly('xeon'),
  /** El equipo también se vende: quien lo compra obtiene descuento en un sistema que corre en él. */
  sale: {
    price: SALE_PRICE,
    systemDiscountPercent: SALE_DISCOUNT,
    /** Ejemplo con el Sistema empresarial: el descuento aplica solo al sistema; el equipo se paga completo. */
    example: { base: exampleBase.name, basePrice: exampleBase.price, saving: exampleSaving, discounted: exampleBase.price - exampleSaving },
    note: 'El descuento aplica únicamente al desarrollo del sistema, no al equipo. Debe ser un sistema que pueda correr en él, se confirma en la propuesta y no se acumula con el descuento de contado.',
  },
  /** Lo que trae el equipo, tal como está armado. */
  specs: [
    { label: 'Procesador', value: 'Intel Xeon E5-2660 v4 · 2,0 GHz · 14 núcleos / 28 hilos' },
    { label: 'Caché', value: '35 MB' },
    { label: 'Socket y consumo', value: 'FCLGA2011-3 · 105 W' },
    { label: 'Placa base', value: 'QIYIDA X99 LGA2011-3 con ranura M.2, DDR4, SATA, USB y PCI-E x16' },
    { label: 'Memoria RAM', value: '16 GB DDR4 a 2133 MHz' },
    { label: 'Almacenamiento', value: 'SSD M.2 de 500 GB' },
  ],
  image: { src: '/media/xeon-lab.webp', alt: 'Equipo Angside Xeon Lab con iluminación azul, visto por el panel de cristal', width: 650, height: 795 },
  /** Galería del popup: foto y videos del equipo (archivos optimizados en public/media). */
  gallery: [
    { type: 'image' as const, src: '/media/xeon-lab.webp', poster: '/media/xeon-lab.webp', label: 'Foto del equipo', width: 650, height: 795 },
    { type: 'video' as const, src: '/media/xeon-video-1.mp4', poster: '/media/xeon-video-1.webp', label: 'Video: el equipo por fuera', width: 720, height: 1280 },
    { type: 'video' as const, src: '/media/xeon-video-2.mp4', poster: '/media/xeon-video-2.webp', label: 'Video: iluminación encendida', width: 720, height: 1280 },
  ],
};
