# Despliegue de Angside en angsidex.com

```
Visitante ─▶ angsidex.com / www ─▶ Vercel (sitio estático Astro, proyecto drogzs-projects/angsidex)
          └▶ api.angsidex.com ──▶ Cloudflare ─▶ túnel ─▶ VPS Contabo: web (Django) ─▶ db (PostgreSQL)
```

- **Frontend:** Vercel (se despliega solo con cada `git push`). Cabeceras y redirección `www → angsidex.com` en `vercel.json`.
- **DNS:** Cloudflare (zona `angsidex.com`, plan Free). Los registros que apuntan a Vercel van **sin proxy** (nube gris); `api` va con proxy y túnel.
- **Backend:** `deploy/docker-compose.yml` en el VPS: proyecto Docker `angside`, red propia y **sin puertos publicados** (no toca VeneCambio ni nada que ya corra allí).

## 1. Estado de la configuración externa

| Elemento | Estado |
|---|---|
| Dominios `angsidex.com` y `www.angsidex.com` en el proyecto Vercel | Asignados (verifican al apuntar el DNS) |
| Variable `PUBLIC_API_URL=https://api.angsidex.com` (Production) en Vercel | Creada |
| Zona `angsidex.com` en Cloudflare | Creada, **pendiente** de cambiar los nameservers en Spaceship |
| Registros DNS: 2×A `@` y CNAME `www` → Vercel; CNAME `api` → túnel | Creados |
| Túnel `angside-api` con ruta `api.angsidex.com → http://web:8000` | Creado, **falta conectarlo** desde el VPS (token) |
| SSL Full (strict), Always HTTPS, TLS ≥ 1.2 | Aplicado |

**Pendiente de ti:**
1. En Spaceship → *Nameservers → Custom*: `jillian.ns.cloudflare.com` y `kareem.ns.cloudflare.com`.
2. Vercel → proyecto → *Settings → Environment Variables*: añade `PUBLIC_TURNSTILE_SITEKEY` (y, si quieres, `PUBLIC_EMAIL`).
3. Turnstile: añade `angsidex.com` a los dominios permitidos del widget.
4. Token del túnel (Cloudflare → Networking → Tunnels → `angside-api` → *Configure*) → va en `deploy/.env` del VPS.

## 2. VPS (Ubuntu + Docker)

```bash
git clone https://github.com/DrogzDev/Angsidex.git && cd Angsidex/deploy
./install.sh          # 1ª vez: crea .env con secretos aleatorios y te dice qué 3 valores faltan
nano .env             # TUNNEL_TOKEN, TURNSTILE_SECRET, OPENROUTER_API_KEY
./install.sh          # 2ª vez: construye, migra, levanta backend + túnel y comprueba la salud
docker compose run --rm web python manage.py createsuperuser
```

`install.sh` es repetible y solo toca el proyecto `angside`. A mano, el equivalente es `docker compose up -d db` → `run --rm web python manage.py migrate` → `up -d --build web cloudflared`.

Respaldo diario: `crontab -e` → `30 3 * * * /ruta/a/Angsidex/deploy/backup.sh`. Los respaldos quedan en `deploy/backups/` (14 días).

### Conservar los datos actuales (SQLite → PostgreSQL)

En tu PC (contiene datos personales: transfiérelo cifrado y bórralo después):

```bash
cd backend
python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission --exclude sessions --exclude admin.logentry \
  --indent 2 > data.json
scp data.json usuario@IP_DEL_VPS:~/Angsidex/deploy/
```

En el VPS, **después** del `migrate` y **antes** de crear el superusuario:

```bash
docker compose run --rm -v "$PWD/data.json:/tmp/data.json:ro" web python manage.py loaddata /tmp/data.json
shred -u data.json
```

## 3. Despliegues futuros

- **Frontend:** `git push origin main` (Vercel compila y publica).
- **Backend:**
  ```bash
  cd ~/Angsidex && git pull
  cd deploy
  IMAGE_TAG=$(date +%F-%H%M) docker compose build web
  docker compose run --rm web python manage.py migrate
  IMAGE_TAG=$(date +%F-%H%M) docker compose up -d web
  ```
- Contrato de precios: si cambias `src/data/*.ts`, ejecuta `npm run export:contract` y sube también `backend/angside_ai/data/pricing.json`.

## 4. Rollback

- **Frontend:** Vercel → proyecto → *Deployments* → el despliegue anterior → *Promote to Production* (o `vercel rollback`).
- **Backend:** `IMAGE_TAG=<etiqueta anterior> docker compose up -d web`. Si falló una migración: `gunzip -c backups/angside_<fecha>.sql.gz | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'` sobre una base vacía.
- **DNS:** en Spaceship vuelve a poner `launch1.spaceship.net` y `launch2.spaceship.net` (propaga según el TTL).

## 5. Comprobaciones tras publicar

```bash
curl -I https://angsidex.com                    # 200 + cabeceras de seguridad
curl -I https://www.angsidex.com                # 301 → https://angsidex.com
curl -s https://api.angsidex.com/healthz        # {"status": "ok"}
curl -s https://api.angsidex.com/api/commercial/config | head -c 200
echo | openssl s_client -connect angsidex.com:443 -servername angsidex.com 2>/dev/null | openssl x509 -noout -dates -issuer
PANEL_USER=... PANEL_PASS=... node tools/panel-test.mjs https://angsidex.com/admin
node tools/payments-test.mjs https://angsidex.com/
```

El asesor de IA se prueba a mano con **un** mensaje real (las pruebas automáticas no gastan créditos de OpenRouter).

## Variables de entorno (nombres; los valores van en `deploy/.env` y en Cloudflare)

| Dónde | Variables |
|---|---|
| Vercel (build) | `PUBLIC_API_URL`, `PUBLIC_TURNSTILE_SITEKEY`, `PUBLIC_WHATSAPP`, `PUBLIC_INSTAGRAM`, `PUBLIC_TIKTOK`, `PUBLIC_EMAIL` |
| VPS `deploy/.env` | `POSTGRES_*`, `TUNNEL_TOKEN`, `DJANGO_*`, `ALLOWED_ORIGINS`, `TRUST_CF_CONNECTING_IP`, `TURNSTILE_SECRET`, `OPENROUTER_*`, `AI_*`, `PRIVACY_POLICY_VERSION` |
