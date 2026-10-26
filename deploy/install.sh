#!/usr/bin/env bash
# Instalación de Angside en el VPS (Ubuntu + Docker). Solo toca el proyecto Docker "angside":
# no usa puertos del servidor ni modifica otros contenedores.
#
# Uso:   cd Angsidex/deploy && ./install.sh
# Repetirlo es seguro: si ya existe .env no lo sobrescribe.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31mError: %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "Docker no está instalado."
docker compose version >/dev/null 2>&1 || die "Falta el plugin 'docker compose'."
command -v openssl >/dev/null || die "Falta openssl."

# --- 1) .env con secretos generados ---
if [ ! -f .env ]; then
  say "Creando .env con secretos aleatorios"
  cp .env.example .env
  chmod 600 .env
  set_var() { sed -i "s|^$1=.*|$1=$2|" .env; }
  set_var POSTGRES_PASSWORD "$(openssl rand -hex 24)"
  set_var DJANGO_SECRET_KEY "$(openssl rand -base64 60 | tr -d '\n=+/' | cut -c1-64)"
  set_var DJANGO_ADMIN_URL "gestion-$(openssl rand -hex 4)/"
  echo "Listo. Faltan 3 valores que solo tú tienes."
fi

missing=()
for v in TUNNEL_TOKEN TURNSTILE_SECRET OPENROUTER_API_KEY; do
  [ -n "$(grep -E "^$v=" .env | cut -d= -f2-)" ] || missing+=("$v")
done
if [ "${#missing[@]}" -gt 0 ]; then
  printf '\nEdita %s/.env y completa: %s\n' "$(pwd)" "${missing[*]}"
  echo "  · TUNNEL_TOKEN: Cloudflare → Networking → Tunnels → angside-api → Configure → copia el token"
  echo "  · TURNSTILE_SECRET / OPENROUTER_API_KEY: tus claves privadas"
  echo "Luego vuelve a ejecutar ./install.sh"
  exit 0
fi

# --- 2) Base de datos y migraciones ---
say "Levantando PostgreSQL"
docker compose up -d db
docker compose build web
say "Aplicando migraciones"
docker compose run --rm web python manage.py migrate --noinput

# --- 3) Servicios ---
say "Levantando backend y túnel"
docker compose up -d web cloudflared
sleep 8
docker compose ps

say "Comprobando"
if docker compose exec -T web python -c "import urllib.request as u; print(u.urlopen(u.Request('http://127.0.0.1:8000/healthz', headers={'X-Forwarded-Proto':'https'}), timeout=5).read().decode())"; then
  echo "Backend sano."
else
  die "El backend no respondió; revisa: docker compose logs web"
fi
docker compose logs --tail=5 cloudflared | grep -qi "registered tunnel connection" && echo "Túnel conectado." || echo "Aún no se ve el túnel conectado: docker compose logs -f cloudflared"

cat <<EOF

Siguientes pasos:
  1) Crear tu superusuario:   docker compose run --rm web python manage.py createsuperuser
  2) (Opcional) Importar tus datos actuales: ver deploy/README.md → "Conservar los datos actuales".
  3) Respaldo diario:         (crontab -e)  30 3 * * * $(pwd)/backup.sh
  4) Probar:                  curl -s https://api.angsidex.com/healthz
  5) Admin de Django en:      https://api.angsidex.com/$(grep -E '^DJANGO_ADMIN_URL=' .env | cut -d= -f2-)
EOF
