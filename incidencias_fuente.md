# Incidencias de las fuentes

| Fecha | Fuente | URL u operación | Respuesta | Decisión |
|---|---|---|---|---|
| 2026-11-25 | SMV, Portal de Datos Abiertos | `WebServiceInfoFinanciera.asmx` · `obtener_InfoFinanciera` | HTTP 403 por GET y sin respuesta válida por SOAP en la prueba de fuentes | No se usa: las mismas cuentas se obtienen de `obtener_BalanceGeneral` y `obtener_GanciaPerdida`, que sí responden (HTTP 200) |
| 2026-11-25 | SMV | `https://www.smv.gob.pe/robots.txt` | HTTP 200, pero devuelve la página principal en HTML (no existe un robots.txt real) | No hay rutas prohibidas declaradas; se aplican igual pausas y User-Agent |
| 2026-11-25 | BCRP, BCRPData | `https://estadisticas.bcrp.gob.pe/robots.txt` | Código HTTP 577 (no estándar); las páginas de las series respondieron HTTP 200 | Se trata como sitio sin robots.txt; se mantienen el User-Agent identificado y pausas de 2 s |
| 2026-11-25 | BCRP, BCRPData | Series PN02507AQ y PD04722MM | La página HTML trae la serie completa (PBI desde 1980-T1 hasta 2026-T3; tasa desde 2003-09 hasta 2026-10) | El HTML se guarda intacto en `datos_crudos/bcrp/`; `03_limpieza_datos.py` usa solo 2011-T1 a 2025-T4 |
| 2026-11-25 | SMV | Campo `CIIU` de `obtener_BalanceGeneral` | Vacío en el 93 % de las filas | Las emisoras financieras se identifican por RPJ con una lista revisada a mano (`tabla_emisoras_excluidas.csv`) |
| 2026-11-25 | SMV | Campo `Moneda`: Alicorp 2025-T4 y InRetail 2013-T2 | Etiqueta “Dólares” con montos en soles: el comparativo del cierre anterior coincide exactamente con el monto en soles ya reportado | Se corrige la etiqueta solo para convertir el tamaño a soles; el dato crudo no se modifica (`tabla_correccion_moneda.csv`) |
| 2026-11-25 | SMV | Electropuno 2011-T2 (RPJ SP0006) | Activo total de 276 834 800 miles de soles, unas 980 veces el de los trimestres vecinos (error de escala) | Se excluye ese trimestre (`tabla_emisoras_excluidas.csv`) |
| 2026-11-25 | GitHub | `datos_crudos/datos_crudos_2024200500F.csv` | Aviso de tamaño: 50,7 MB, por encima de los 50 MB recomendados (el límite es 100 MB) | Se sube igual porque está bajo el límite; es la unión en formato largo de las tres fuentes |
