Torre Faro Sistema V4.6.0

# Torre Faro — Sistema Final V4.2

V4.2 consolida el paquete candidato a producción y agrega una migración PostgreSQL validada.

## Validaciones realizadas
- Suite offline: 5 tests OK (smoke, cierre, correcciones, económico, importación/integridad/readiness/seguridad y artefactos de producción, según el entorno).
- Migración SQLite en modo `--dry-run`: OK.
- Fuente actual validada: 1 proyecto, 8 socios, 29 unidades, 1.660 gastos, 1.281 contributions, 652 movimientos, 57 parámetros.

## Importante
En este entorno no está disponible Docker/PostgreSQL, por lo que **no se afirma haber ejecutado una migración real contra PostgreSQL**. El script de migración queda listo para ejecutarse en el servidor de producción y valida conteos dentro de una única transacción.

## Siguiente paso
Configurar las credenciales reales del servidor y ejecutar el despliegue/migración. Esto requiere acceso a un proveedor de hosting o servidor que no está disponible automáticamente desde este entorno.
