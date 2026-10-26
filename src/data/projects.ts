/**
 * Proyectos PROPIOS de Angside (no son clientes comerciales).
 * La sección solo se muestra si hay elementos. Ejemplo:
 *   { name: 'Nombre', description: 'Qué es', url: 'https://…', image: '/images/nombre.webp' }
 */
export interface OwnProject {
  name: string;
  description: string;
  url?: string;
  image?: string;
}

export const ownProjects: readonly OwnProject[] = [];
