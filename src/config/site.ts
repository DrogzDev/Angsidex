/**
 * Configuración del sitio. Los valores en `null` están PENDIENTES de datos oficiales:
 * mientras sean null, los enlaces correspondientes se muestran desactivados.
 */
export const site = {
  name: 'Angside',
  /** Dominio público (se usa en canonical, sitemap y Open Graph). */
  url: 'https://angsidex.com',
  description:
    'Estudio de desarrollo de software: páginas web, tiendas online y sistemas personalizados para negocios en Venezuela.',
  contact: {
    /** Número en formato internacional sin "+" ni espacios. Se puede sobrescribir con PUBLIC_WHATSAPP. */
    whatsapp: (import.meta.env.PUBLIC_WHATSAPP as string | undefined) || '584145487581',
    /** Usuario sin "@". Se puede sobrescribir con PUBLIC_INSTAGRAM. */
    instagram: (import.meta.env.PUBLIC_INSTAGRAM as string | undefined) || 'angsidex',
    /** Usuario sin "@". Se puede sobrescribir con PUBLIC_TIKTOK. */
    tiktok: (import.meta.env.PUBLIC_TIKTOK as string | undefined) || 'angsidex',
    /** PENDIENTE */
    email: (import.meta.env.PUBLIC_EMAIL as string | undefined) ?? (null as string | null),
  },
} as const;

export const contactUrls = {
  whatsapp: site.contact.whatsapp ? `https://wa.me/${site.contact.whatsapp}` : null,
  instagram: site.contact.instagram ? `https://instagram.com/${site.contact.instagram}` : null,
  tiktok: site.contact.tiktok ? `https://www.tiktok.com/@${site.contact.tiktok}` : null,
  email: site.contact.email ? `mailto:${site.contact.email}` : null,
};
