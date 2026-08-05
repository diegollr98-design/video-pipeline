# Ledger de Incidentes

**Append-only.** Registro FACTUAL de incidentes/near-misses (proceso, bugs, verificación fallida…).
Vive en `.claude/` → **NO se auto-carga** (sin coste de tokens por sesión). **No editar entradas pasadas; solo añadir** (más reciente arriba).

**Uso:** materia prima de la auto-mejora. **Solo `/optimize`** promueve una entrada a regla, y solo con **≥2 incidencias independientes** de la misma clase, **o 1 de clase irreversible** (dinero/datos/seguridad/PII).

**Formato:** `- [id] fecha · clase · qué pasó · evidencia · estado`
**Estado:** `pendiente (>=2)` = registrado, sin promover · `promovido -> <regla>` = ya es regla.

<!-- entradas nuevas debajo, más reciente arriba -->
