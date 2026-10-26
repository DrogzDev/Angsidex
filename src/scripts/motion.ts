/**
 * Animaciones GSAP. El contenido es visible por defecto; solo se oculta (html.js-anim)
 * cuando el usuario no pidió movimiento reducido, y se restaura si GSAP falla.
 */
const root = document.documentElement;

function reveal() {
  root.classList.remove('js-anim');
  document.querySelectorAll<HTMLElement>('[data-hero],[data-reveal],[data-hero-title] .inner').forEach((el) => {
    el.style.opacity = '';
    el.style.transform = '';
  });
}

async function run() {
  if (!root.classList.contains('js-anim')) return;
  // Red de seguridad: si algo tarda demasiado, mostramos todo.
  const safety = window.setTimeout(reveal, 3500);

  try {
    const [{ gsap }, { ScrollTrigger }] = await Promise.all([import('gsap'), import('gsap/ScrollTrigger')]);
    gsap.registerPlugin(ScrollTrigger);
    window.clearTimeout(safety);

    // Los elementos visibles ahora los controla GSAP
    gsap.set('[data-hero]', { opacity: 0, y: 12 });
    // y: 0 evita que GSAP lea el translateY(%) del CSS inicial como píxeles
    gsap.set('[data-hero-title] .inner', { y: 0, yPercent: 105 });
    root.classList.remove('js-anim');

    const edges = gsap.utils.toArray<SVGPathElement>('[data-edge]');
    const nodes = gsap.utils.toArray<SVGCircleElement>('[data-node]');
    gsap.set(edges, { strokeDashoffset: 1 });
    gsap.set(nodes, { opacity: 0 });

    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } });
    tl.to('[data-hero-title] .inner', { yPercent: 0, duration: 0.7, stagger: 0.09 })
      .to('[data-hero]', { opacity: 1, y: 0, duration: 0.5, stagger: 0.07 }, '-=0.45')
      .to(edges, { strokeDashoffset: 0, duration: 1.1, stagger: { each: 0.012, from: 'random' }, ease: 'power2.inOut' }, 0.15)
      .to(nodes, { opacity: 1, duration: 0.4, stagger: 0.02 }, 0.9);

    // Parallax ligero del wireframe
    const art = document.querySelector('[data-parallax]');
    if (art) {
      gsap.to(art, {
        yPercent: -8,
        ease: 'none',
        scrollTrigger: { trigger: '#inicio', start: 'top top', end: 'bottom top', scrub: 0.6 },
      });
    }

    // Entrada de secciones: una sola vez, sin retrasar el contenido
    document.querySelectorAll<HTMLElement>('.section').forEach((sec) => {
      const items = sec.querySelectorAll<HTMLElement>('.section-head, .card, .mod, .svc, .values li, .chan');
      if (!items.length) return;
      gsap.from(items, {
        opacity: 0,
        y: 16,
        duration: 0.5,
        ease: 'power2.out',
        stagger: 0.035,
        clearProps: 'opacity,transform',
        scrollTrigger: { trigger: sec, start: 'top 82%', once: true },
      });
    });
  } catch {
    window.clearTimeout(safety);
    reveal();
  }
}

void run();
