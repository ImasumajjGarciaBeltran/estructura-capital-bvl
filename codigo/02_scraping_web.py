# Autora: Imasumajj García Beltrán
# Código de matrícula: 2024200500F
# Tema N.º 81: Determinantes de la estructura de capital de las empresas listadas en la BVL
# Fecha de extracción: 2026-11-25
"""
02_scraping_web.py  ·  Vía 2 (descarga programática y scraping)  ·  datos crudos
--------------------------------------------------------------------------------
Parte A · SMV, Portal de Datos Abiertos (descarga programática)
    Servicio oficial: https://www.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx
    Operaciones:      obtener_BalanceGeneral  (Estado de Situación Financiera)
                      obtener_GanciaPerdida   (Estado de Resultados)
    Parámetros:       Ejercicio (2011-2025), Periodo (1-4), Tipo = I (individual)
    Cada respuesta trae TODAS las empresas supervisadas de ese trimestre. Se guardan,
    sin cambiar ningún valor, las filas de las EMPRESAS EMISORAS y de las cuentas
    declaradas en CUENTAS_SMV. La huella SHA-256 de la respuesta completa queda en el
    log, para que cualquiera pueda comprobar que el archivo vino de la SMV.

Parte B · BCRP, BCRPData (scraping de HTML)
    Se rastrean las tablas HTML públicas de dos series con requests + BeautifulSoup:
      PN02507AQ  PBI global, variación porcentual interanual (trimestral)
      PD04722MM  Tasa de referencia de la política monetaria (mensual)
    Selector: la tabla cuyo encabezado contiene «Fecha»; filas <tr> con dos celdas <td>.

Reglas de rastreo (numeral 2.4.8): se lee robots.txt, User-Agent identificable,
pausa de PAUSA_SEG segundos entre solicitudes, reintentos con espera creciente.
Un archivo crudo ya descargado NUNCA se sobrescribe con una descarga fallida.

Salidas (carpeta datos_crudos/):
  smv/smv_<operacion>_<anio>_T<trim>.csv.gz respuesta filtrada de cada trimestre (comprimida)
  smv/catalogo_cuentas_smv.csv              cuentas que la SMV usó en cada trimestre
  bcrp/bcrp_<serie>.html                    página HTML original, tal cual
  datos_crudos_2024200500F_smv.csv          todos los trimestres de la SMV juntos
  datos_crudos_2024200500F_bcrp.csv         valores de las tablas HTML del BCRP (texto original)
  datos_crudos_2024200500F.csv              las tres fuentes en formato largo (mismos valores)
Ejecutar desde la Carpeta 3:  python codigo/02_scraping_web.py
Tiempo aproximado: 40 a 60 minutos (120 consultas de varios MB a la SMV, con pausas).
"""

import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib import robotparser

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ── 1. Parámetros congelados (numeral 2.4.5) ──────────────────────────────
FECHA_INICIO = "2011-01-01"      # 2011-T1: primer año con NIIF plenas para las emisoras
FECHA_CORTE = "2025-12-31"       # 2025-T4
CODIGO = "2024200500F"
ANIOS = list(range(int(FECHA_INICIO[:4]), int(FECHA_CORTE[:4]) + 1))
TRIMESTRES = [1, 2, 3, 4]
TIPO_INFO = "I"                  # I = estados financieros individuales

SMV_SERVICIO = "https://www.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx"
SMV_NAMESPACE = "http://tempuri.org/"
SMV_OPERACIONES = ["obtener_BalanceGeneral", "obtener_GanciaPerdida"]
SMV_TIPO_EMPRESA = "EMPRESAS EMISORAS"
CUENTAS_SMV = {
    # Estado de Situación Financiera (formato D: empresas en general)
    "1D020T": "Total de activos",
    "1D040T": "Total pasivos",
    "1D07ST": "Total patrimonio",
    "1D0309": "Otros pasivos financieros corrientes (deuda financiera de corto plazo)",
    "1D0401": "Otros pasivos financieros no corrientes (deuda financiera de largo plazo)",
    "1D0205": "Propiedades, planta y equipo",
    "1D0211": "Propiedades de inversión",
    "1D01ST": "Total activos corrientes",
    "1D03ST": "Total pasivos corrientes",
    "1D0109": "Efectivo y equivalentes al efectivo",
    # Estado de Resultados
    "2D01ST": "Ingresos de actividades ordinarias",
    "2D03ST": "Ganancia (pérdida) operativa",
    "2D0402": "Gastos financieros",
    "2D04ST": "Ganancia (pérdida) antes de impuestos",
    "2D0502": "Ingreso (gasto) por impuesto",
    "2D07ST": "Ganancia (pérdida) neta del ejercicio",
}

BCRP_SERIES = {
    "PN02507AQ": ("trimestrales", "PBI global, variación porcentual interanual"),
    "PD04722MM": ("mensuales", "Tasa de referencia de la política monetaria (%)"),
}
BCRP_BASE = "https://estadisticas.bcrp.gob.pe/estadisticas/series/{frecuencia}/resultados/{serie}/html"

# Rutas RELATIVAS a la Carpeta 3 (numeral 2.4.4)
CARPETA_CRUDOS = Path("datos_crudos")
CARPETA_SMV = CARPETA_CRUDOS / "smv"
CARPETA_BCRP = CARPETA_CRUDOS / "bcrp"
ARCHIVO_LOG = Path("log_ejecucion.txt")
CORREO = os.getenv("CORREO_CONTACTO", "")
CABECERAS = {"User-Agent": f"Investigacion-academica-UNCP/{CODIGO}" + (f" ({CORREO})" if CORREO else "")}
PAUSA_SEG = 2                     # pausa entre solicitudes (mínimo exigido: 1 s)
INTENTOS = 3


# ── 2. Funciones de apoyo ─────────────────────────────────────────────────
def registrar(mensaje):
    """Escribe una línea con fecha y hora en el log y en pantalla."""
    linea = f"{datetime.now():%Y-%m-%d %H:%M:%S} · 02_scraping_web · {mensaje}"
    print(linea, flush=True)
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as log:
        log.write(linea + "\n")


def revisar_robots(url_base, ruta):
    """Lee robots.txt y registra si la ruta está permitida para nuestro User-Agent."""
    rp = robotparser.RobotFileParser()
    try:
        r = requests.get(url_base + "/robots.txt", headers=CABECERAS, timeout=30)
        es_robots = r.status_code == 200 and "<html" not in r.text[:500].lower()
        if es_robots:
            rp.parse(r.text.splitlines())
            permitido = rp.can_fetch(CABECERAS["User-Agent"], url_base + ruta)
            registrar(f"robots.txt {url_base} · HTTP {r.status_code} · {ruta} permitido: {permitido}")
            return permitido
        registrar(f"robots.txt {url_base} · HTTP {r.status_code} · sin archivo robots.txt "
                  "(no hay rutas prohibidas declaradas)")
    except requests.RequestException as error:
        registrar(f"robots.txt {url_base} · no se pudo leer: {error}")
    return True


def con_reintentos(funcion, descripcion):
    """Ejecuta una solicitud; si falla, espera y reintenta (espera creciente)."""
    for intento in range(1, INTENTOS + 1):
        try:
            r = funcion()
            if r.status_code == 200 and r.content:
                return r
            registrar(f"{descripcion} · HTTP {r.status_code} en intento {intento}")
        except requests.RequestException as error:
            registrar(f"{descripcion} · error de conexión en intento {intento}: {error}")
        time.sleep(PAUSA_SEG * 5 * intento)
    return None


# ── 3. Parte A · SMV: descarga programática de estados financieros ─────────
def sobre_soap(operacion, anio, trimestre):
    """Arma el mensaje SOAP 1.1 con los parámetros exactos que declara el WSDL."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
        f'<{operacion} xmlns="{SMV_NAMESPACE}">'
        f"<Ejercicio>{anio}</Ejercicio><Periodo>{trimestre}</Periodo><Tipo>{TIPO_INFO}</Tipo>"
        f"</{operacion}></soap:Body></soap:Envelope>"
    )


def leer_respuesta_smv(contenido):
    """El resultado llega como texto JSON dentro del XML: se extrae sin modificar valores."""
    raiz = ET.fromstring(contenido)
    for nodo in raiz.iter():
        if nodo.tag.endswith("Result"):
            return pd.DataFrame(json.loads(nodo.text or "[]"))
    return pd.DataFrame()


def descargar_smv():
    CARPETA_SMV.mkdir(parents=True, exist_ok=True)
    revisar_robots("https://www.smv.gob.pe", "/ws_od_eeff/WebServiceInfoFinanciera.asmx")
    catalogo = []
    for operacion in SMV_OPERACIONES:
        for anio in ANIOS:
            for trimestre in TRIMESTRES:
                destino = CARPETA_SMV / f"smv_{operacion}_{anio}_T{trimestre}.csv.gz"
                if destino.exists():           # ya descargado: no se repite ni se sobrescribe
                    registrar(f"SMV {operacion} {anio}-T{trimestre} · ya existe, se conserva")
                    continue
                cabeceras = dict(CABECERAS)
                cabeceras.update({"Content-Type": "text/xml; charset=utf-8",
                                  "SOAPAction": f'"{SMV_NAMESPACE}{operacion}"'})
                cuerpo = sobre_soap(operacion, anio, trimestre).encode("utf-8")
                r = con_reintentos(lambda: requests.post(SMV_SERVICIO, data=cuerpo,
                                                         headers=cabeceras, timeout=300),
                                   f"SMV {operacion} {anio}-T{trimestre}")
                time.sleep(PAUSA_SEG)
                if r is None:
                    registrar(f"SMV {operacion} {anio}-T{trimestre} · SIN DATOS tras {INTENTOS} intentos")
                    continue
                huella = hashlib.sha256(r.content).hexdigest()
                tabla = leer_respuesta_smv(r.content)
                if tabla.empty:
                    registrar(f"SMV {operacion} {anio}-T{trimestre} · HTTP {r.status_code} · 0 filas "
                              f"· sha256 {huella}")
                    continue
                catalogo.append(tabla[["Cuenta", "DescripcionCuenta"]].drop_duplicates()
                                .assign(operacion=operacion, anio=anio, trimestre=trimestre))
                filtro = tabla[(tabla["TipoEmpresa"] == SMV_TIPO_EMPRESA)
                               & (tabla["Cuenta"].isin(CUENTAS_SMV))].copy()
                filtro.insert(0, "operacion", operacion)
                filtro.insert(1, "anio_consulta", anio)
                filtro.insert(2, "trimestre_consulta", trimestre)
                filtro["fecha_extraccion"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                filtro.to_csv(destino, index=False, encoding="utf-8")
                registrar(f"SMV {operacion} {anio}-T{trimestre} · HTTP {r.status_code} · "
                          f"{len(tabla)} filas en la respuesta · {len(filtro)} filas guardadas · "
                          f"{filtro['RPJ'].nunique()} emisoras · {len(r.content):,} bytes · sha256 {huella}")
    # Catálogo de cuentas de cada trimestre (detecta cambios de código en el tiempo)
    archivo_cat = CARPETA_SMV / "catalogo_cuentas_smv.csv"
    if catalogo:
        nuevo = pd.concat(catalogo, ignore_index=True)
        if archivo_cat.exists():
            nuevo = pd.concat([pd.read_csv(archivo_cat, dtype=str), nuevo.astype(str)]).drop_duplicates()
        nuevo.to_csv(archivo_cat, index=False, encoding="utf-8")
    # Une todos los trimestres en un solo archivo crudo de la SMV
    partes = [pd.read_csv(a, dtype={"RPJ": str, "RUC": str, "CIIU": str, "Cuenta": str})
              for a in sorted(CARPETA_SMV.glob("smv_obtener_*.csv.gz"))]
    smv = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    smv.to_csv(CARPETA_CRUDOS / f"datos_crudos_{CODIGO}_smv.csv", index=False, encoding="utf-8")
    registrar(f"SMV total · {len(smv)} filas · {smv['RPJ'].nunique() if len(smv) else 0} emisoras "
              f"· {len(partes)} de {len(SMV_OPERACIONES) * len(ANIOS) * len(TRIMESTRES)} trimestres-operación")
    return smv


# ── 4. Parte B · BCRP: scraping de las tablas HTML ────────────────────────
def descargar_bcrp():
    CARPETA_BCRP.mkdir(parents=True, exist_ok=True)
    revisar_robots("https://estadisticas.bcrp.gob.pe", "/estadisticas/series/")
    filas = []
    for serie, (frecuencia, nombre) in BCRP_SERIES.items():
        url = BCRP_BASE.format(frecuencia=frecuencia, serie=serie)
        archivo_html = CARPETA_BCRP / f"bcrp_{serie}.html"
        r = con_reintentos(lambda: requests.get(url, headers=CABECERAS, timeout=120), f"BCRP {serie}")
        time.sleep(PAUSA_SEG)
        if r is not None:
            archivo_html.write_bytes(r.content)          # página original, byte por byte
            registrar(f"BCRP {serie} · HTTP {r.status_code} · {len(r.content):,} bytes · {url}")
        elif archivo_html.exists():
            registrar(f"BCRP {serie} · falló la descarga; se conserva el HTML ya guardado")
        else:
            registrar(f"BCRP {serie} · SIN DATOS")
            continue
        sopa = BeautifulSoup(archivo_html.read_bytes(), "html.parser")
        # Selector: la tabla cuya primera celda de encabezado dice «Fecha»
        tabla = next((t for t in sopa.find_all("table")
                      if t.find(["th", "td"]) and "fecha" in t.find(["th", "td"]).get_text(strip=True).lower()),
                     None)
        if tabla is None:
            registrar(f"BCRP {serie} · no se encontró la tabla con encabezado «Fecha»")
            continue
        n = 0
        for tr in tabla.find_all("tr"):
            celdas = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(celdas) >= 2 and celdas[0]:
                filas.append({"serie": serie, "nombre_serie": nombre, "frecuencia": frecuencia,
                              "fecha_texto": celdas[0], "valor_texto": celdas[1], "url": url,
                              "fecha_extraccion": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                n += 1
        registrar(f"BCRP {serie} · {n} filas leídas de la tabla HTML")
    bcrp = pd.DataFrame(filas)
    if len(bcrp):
        bcrp.to_csv(CARPETA_CRUDOS / f"datos_crudos_{CODIGO}_bcrp.csv", index=False, encoding="utf-8")
    return bcrp


# ── 5. Archivo crudo único en formato largo (los valores no cambian) ──────
def unir_crudos(smv, bcrp):
    partes = []
    if len(smv):
        partes.append(pd.DataFrame({
            "fuente": "SMV", "via": "descarga programatica", "operacion": smv["operacion"],
            "id_entidad": smv["RPJ"], "nombre_entidad": smv["NombreEmpresa"],
            "periodo": smv["anio_consulta"].astype(str) + "-T" + smv["trimestre_consulta"].astype(str),
            "variable": smv["Cuenta"], "descripcion": smv["DescripcionCuenta"],
            "valor": smv["Monto1"], "valor_2": smv.get("Monto2"), "valor_3": smv.get("Monto3"),
            "valor_4": smv.get("Monto4"), "moneda": smv["Moneda"]}))
    if len(bcrp):
        partes.append(pd.DataFrame({
            "fuente": "BCRP", "via": "scraping HTML", "operacion": "tabla HTML",
            "id_entidad": "PERU", "nombre_entidad": "Perú", "periodo": bcrp["fecha_texto"],
            "variable": bcrp["serie"], "descripcion": bcrp["nombre_serie"],
            "valor": bcrp["valor_texto"], "moneda": ""}))
    archivo_yahoo = CARPETA_CRUDOS / f"datos_crudos_{CODIGO}_yahoo.csv"
    if archivo_yahoo.exists():                       # generado antes por 01_extraccion_api.py
        y = pd.read_csv(archivo_yahoo, dtype={"rpj": str})
        y = y.melt(id_vars=["ticker", "rpj", "fecha"], value_vars=["Adj Close", "Close", "Volume"],
                   var_name="variable", value_name="valor")
        partes.append(pd.DataFrame({
            "fuente": "Yahoo Finance", "via": "API", "operacion": "yfinance.download",
            "id_entidad": y["ticker"], "nombre_entidad": y["rpj"], "periodo": y["fecha"],
            "variable": y["variable"], "descripcion": "Cotización diaria en la BVL",
            "valor": y["valor"], "moneda": "PEN/USD según ticker"}))
    todo = pd.concat(partes, ignore_index=True)
    todo.to_csv(CARPETA_CRUDOS / f"datos_crudos_{CODIGO}.csv", index=False, encoding="utf-8")
    registrar(f"Archivo crudo único · {len(todo):,} filas · fuentes: {', '.join(todo['fuente'].unique())}")


if __name__ == "__main__":
    registrar(f"Inicio · ventana {FECHA_INICIO} a {FECHA_CORTE} · User-Agent «{CABECERAS['User-Agent']}»")
    smv = descargar_smv()
    bcrp = descargar_bcrp()
    unir_crudos(smv, bcrp)
    registrar("Fin de 02_scraping_web.py")
