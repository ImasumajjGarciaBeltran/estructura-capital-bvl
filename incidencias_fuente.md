# Incidencias de las fuentes

| Fecha | Fuente | URL u operación | Respuesta | Decisión |
|---|---|---|---|---|
| 2026-11-25 | SMV, Portal de Datos Abiertos | `WebServiceInfoFinanciera.asmx` · `obtener_InfoFinanciera` | HTTP 403 por GET y sin respuesta válida por SOAP en la prueba de fuentes | No se usa: las mismas cuentas se obtienen de `obtener_BalanceGeneral` y `obtener_GanciaPerdida`, que sí responden (HTTP 200) |
| 2026-11-25 | SMV | `https://www.smv.gob.pe/robots.txt` | HTTP 200, pero devuelve la página principal en HTML (no existe un robots.txt real) | No hay rutas prohibidas declaradas; se aplican igual pausas y User-Agent |
