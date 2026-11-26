# Determinantes de la estructura de capital de las empresas listadas en la BVL

- **Autora:** Imasumajj García Beltrán
- **Código de matrícula:** 2024200500F
- **Curso:** Finanzas I (055D) · Universidad Nacional del Centro del Perú · 2026-II · Unidad II
- **Tema N.º 81: Determinantes de la estructura de capital de las empresas listadas en la BVL**
- **Repositorio:** https://github.com/ImasumajjGarciaBeltran/estructura-capital-bvl

## Fuentes y endpoints (numeral 2.4.1: dos vías)
| Vía | Fuente | Endpoint | Script |
|---|---|---|---|
| API | Yahoo Finance (yfinance) | `query2.finance.yahoo.com/v8/finance/chart/{ticker}` · 20 acciones .LM + PEN=X | `01_extraccion_api.py` |
| Descarga programática | SMV, Portal de Datos Abiertos | `https://www.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx` · `obtener_BalanceGeneral`, `obtener_GanciaPerdida` | `02_scraping_web.py` |
| Scraping HTML | BCRP, BCRPData | `estadisticas.bcrp.gob.pe/estadisticas/series/{frecuencia}/resultados/{serie}/html` · PN02507AQ, PD04722MM | `02_scraping_web.py` |

**Llave común:** emisora (código RPJ de la SMV) + trimestre.

## Fecha de corte
`FECHA_INICIO = 2011-01-01` · `FECHA_CORTE = 2025-12-31` (60 trimestres, todos bajo NIIF).

## Orden de ejecución (desde esta carpeta)
1. `python codigo/01_extraccion_api.py`  (≈ 2 min)
2. `python codigo/02_scraping_web.py`    (≈ 40-60 min)
3. `python codigo/03_limpieza_datos.py`
4. `python codigo/04_analisis.py`

## Versión del lenguaje y librerías
Ver `requirements.txt`.

## Hash SHA-256 de datos_procesados_2024200500F.csv
`3d06fd24ddc910bd7810abd7e058f50843c439dba3fc13e2d8f42b0faa369c0a`  (7889 observaciones emisora-trimestre, 209 emisoras; generado el 2026-11-26 12:25)