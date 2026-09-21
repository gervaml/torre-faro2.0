# Producción — Torre Faro

## Variables obligatorias
- DATABASE_URL
- TF_ADMIN_USER
- TF_ADMIN_PASSWORD
- TF_AUTH_SECRET
- TF_ENV=production

## Backup PostgreSQL
Ejecutar desde el host con acceso a `pg_dump`:

`DATABASE_URL='postgresql://...' BACKUP_DIR=./backups ./deploy/backup_postgres.sh`

Conserva 14 días de backups locales. En producción conviene copiar además los dumps a almacenamiento externo.

## Producción con HTTPS
1. Crear DNS `TF_DOMAIN` apuntando al servidor.
2. Copiar `.env.example` a `.env` y definir secretos reales.
3. Ejecutar `docker compose -f docker-compose.prod.yml up -d --build`.
4. Ejecutar el seed solo sobre una base PostgreSQL vacía.
5. Verificar `https://$TF_DOMAIN/api/health`.
6. Hacer un backup y ejecutar el restore drill periódicamente.

Caddy gestiona HTTPS automáticamente cuando el DNS ya apunta al servidor.
