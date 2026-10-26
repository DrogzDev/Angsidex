// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  site: 'https://angside.example',
  integrations: [sitemap({ filter: (page) => !page.includes('/admin') })],
  vite: { plugins: [tailwindcss()] },
});
