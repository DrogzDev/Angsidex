/** Construye el enlace wa.me con el mensaje prellenado. Devuelve null si no hay número configurado. */
export function buildWhatsAppUrl(phone: string | null, message: string): string | null {
  const digits = (phone ?? '').replace(/\D/g, '');
  if (!digits) return null;
  return `https://wa.me/${digits}?text=${encodeURIComponent(message)}`;
}
