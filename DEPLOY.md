# Torre Faro — despliegue V4.3

## Objetivo
Ejecutar la aplicación con PostgreSQL y secretos fuera del código.

## Requisitos
- Docker + Docker Compose
- Un servidor con HTTPS/reverse proxy o un proveedor que lo gestione
- Variables de entorno reales

## Pasos
1. Copiar `.env.example` a `.env` y reemplazar todos los secretos.
2. Ejecutar `./deploy_check.sh`.
3. Levantar: `docker compose up -d --build`.
4. Verificar: `curl http://127.0.0.1:8000/api/health`.
5. Ejecutar la migración con `python migrate_sqlite_to_postgres.py` usando el DATABASE_URL de producción.
6. Verificar conteos y ejecutar los tests.
7. Configurar HTTPS antes de exponer el servicio públicamente.

## Seguridad
No subir `.env`, contraseñas, tokens ni la base SQLite al repositorio. El puerto PostgreSQL del compose queda enlazado a localhost.

## Primera carga de una base PostgreSQL vacía
Después de levantar los servicios, la aplicación crea las tablas. Ejecutar dentro del contenedor:
`docker compose exec app python seed_production.py`

El seed se niega a trabajar sobre una base que ya contiene socios, salvo que se use `--force` deliberadamente.

## Backup
La imagen de aplicación incluye `pg_dump`, por lo que `/api/backup` puede generar backups PostgreSQL sin instalar herramientas adicionales en el servidor.
