# Autora: Imasumajj García Beltrán
# Código de matrícula: 2024200500F
# Tema N.º 81: Determinantes de la estructura de capital de las empresas listadas en la BVL
# Fecha de extracción: 2026-11-25
"""
01_extraccion_api.py  ·  Vía 1 (API)  ·  datos crudos
-----------------------------------------------------
Fuente: Yahoo Finance, consumida con la librería yfinance (API no oficial, sin clave).
Endpoint que usa yfinance: https://query2.finance.yahoo.com/v8/finance/chart/{ticker}
Parámetros: start = FECHA_INICIO, end = día siguiente a FECHA_CORTE, interval = 1d,
            auto_adjust = False (precios tal como los publica Yahoo).

Se descargan, SIN MODIFICAR ningún valor:
  - Cotizaciones diarias (Open, High, Low, Close, Adj Close, Volume) de 20 acciones de
    empresas no financieras que cotizan en la Bolsa de Valores de Lima (sufijo .LM).
    Cada ticker se vincula con el código RPJ que la SMV asigna a la emisora: esa es la
    llave común (emisora + trimestre) para unir con los estados financieros.
  - Tipo de cambio PEN=X (soles por dólar), para expresar en soles a las emisoras
    que reportan en dólares.

Salidas (carpeta datos_crudos/):
  datos_crudos_2024200500F_yahoo.csv   cotizaciones diarias en formato largo por ticker
  datos_crudos_2024200500F_fx.csv      tipo de cambio diario PEN=X
  log_ejecucion.txt                    fecha, hora, estado y filas de cada consulta
Nota: yfinance no expone el código HTTP; el log registra «OK» cuando la consulta
devuelve filas y el mensaje de error completo cuando falla.
Ejecutar desde la Carpeta 3:  python codigo/01_extraccion_api.py
"""

import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

# ── 1. Parámetros congelados (numeral 2.4.5) ──────────────────────────────
FECHA_INICIO = "2011-01-01"
FECHA_CORTE = "2025-12-31"
CODIGO = "2024200500F"
# Ticker en Yahoo Finance -> (código RPJ en la SMV, emisora)
TICKERS = {
    "ALICORC1.LM": ("B30006", "Alicorp S.A.A."),
    "BACKUSI1.LM": ("B30021", "Unión de Cervecerías Peruanas Backus y Johnston S.A.A."),
    "CPACASC1.LM": ("CD0005", "Cementos Pacasmayo S.A.A."),
    "UNACEMC1.LM": ("B30121", "UNACEM Corp S.A.A."),
    "FERREYC1.LM": ("B60001", "Ferreycorp S.A.A."),
    "CORAREI1.LM": ("CI0003", "Corporación Aceros Arequipa S.A."),
    "SIDERC1.LM": ("CM0003", "Empresa Siderúrgica del Perú S.A.A."),
    "ENGIEC1.LM": ("002829", "Engie Energía Perú S.A.A."),
    "LUSURC1.LM": ("B40008", "Luz del Sur S.A.A."),
    "CVERDEC1.LM": ("CM0006", "Sociedad Minera Cerro Verde S.A.A."),
    "BUENAVC1.LM": ("B20003", "Compañía de Minas Buenaventura S.A.A."),
    "MINSURI1.LM": ("A20032", "Minsur S.A."),
    "VOLCABC1.LM": ("CM0001", "Volcan Compañía Minera S.A.A."),
    "NEXAPEC1.LM": ("B20010", "Nexa Resources Perú S.A.A."),
    "ATACOBC1.LM": ("CM0007", "Nexa Resources Atacocha S.A.A."),
    "MOROCOI1.LM": ("B20013", "Compañía Minera San Ignacio de Morococha S.A.A."),
    "AUSTRAC1.LM": ("CI0006", "Austral Group S.A.A."),
    "EXALMC1.LM": ("CI0012", "Pesquera Exalmar S.A.A."),
    "CREDITC1.LM": ("B30060", "Creditex S.A.A."),
    "INRETC1.LM": ("OE5087", "InRetail Perú Corp."),
}
TICKER_FX = "PEN=X"

# Rutas RELATIVAS a la Carpeta 3 (numeral 2.4.4)
CARPETA_CRUDOS = Path("datos_crudos")
ARCHIVO_LOG = Path("log_ejecucion.txt")
ARCHIVO_PRECIOS = CARPETA_CRUDOS / f"datos_crudos_{CODIGO}_yahoo.csv"
ARCHIVO_FX = CARPETA_CRUDOS / f"datos_crudos_{CODIGO}_fx.csv"
PAUSA_SEG = 1.5                   # pausa entre solicitudes (mínimo exigido: 1 s)
INTENTOS = 3
FIN_EXCLUSIVO = (datetime.strptime(FECHA_CORTE, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
COLUMNAS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


# ── 2. Funciones de apoyo ─────────────────────────────────────────────────
def registrar(mensaje):
    """Escribe una línea con fecha y hora en el log y en pantalla."""
    linea = f"{datetime.now():%Y-%m-%d %H:%M:%S} · 01_extraccion_api · {mensaje}"
    print(linea, flush=True)
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as log:
        log.write(linea + "\n")


def descargar_ticker(ticker):
    """Descarga las cotizaciones diarias de un ticker, con reintentos."""
    for intento in range(1, INTENTOS + 1):
        try:
            datos = yf.download(ticker, start=FECHA_INICIO, end=FIN_EXCLUSIVO, interval="1d",
                                auto_adjust=False, actions=False, progress=False, threads=False)
            if isinstance(datos.columns, pd.MultiIndex):      # yfinance recientes: (campo, ticker)
                datos.columns = datos.columns.get_level_values(0)
            if len(datos):
                datos = datos.reset_index().rename(columns={"Date": "fecha"})
                datos["fecha"] = pd.to_datetime(datos["fecha"]).dt.strftime("%Y-%m-%d")
                return datos[["fecha"] + [c for c in COLUMNAS if c in datos.columns]]
            registrar(f"Yahoo {ticker} · 0 filas en intento {intento}")
        except Exception as error:                                # yfinance lanza varios tipos
            registrar(f"Yahoo {ticker} · error en intento {intento}: {error}")
        time.sleep(PAUSA_SEG * 4 * intento)
    return None


# ── 3. Cotizaciones de las 20 emisoras ────────────────────────────────────
def descargar_precios():
    previo = pd.read_csv(ARCHIVO_PRECIOS, dtype={"rpj": str}) if ARCHIVO_PRECIOS.exists() else None
    partes = []
    for ticker, (rpj, emisora) in TICKERS.items():
        datos = descargar_ticker(ticker)
        time.sleep(PAUSA_SEG)
        if datos is None:
            # Nunca se pierde lo ya descargado: si falla, se conservan las filas anteriores
            if previo is not None and ticker in set(previo["ticker"]):
                partes.append(previo[previo["ticker"] == ticker])
                registrar(f"Yahoo {ticker} · falló; se conservan las filas descargadas antes")
            else:
                registrar(f"Yahoo {ticker} · SIN DATOS")
            continue
        datos.insert(0, "ticker", ticker)
        datos.insert(1, "rpj", rpj)
        datos.insert(2, "emisora", emisora)
        datos["fecha_extraccion"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        partes.append(datos)
        registrar(f"Yahoo {ticker} ({emisora}) · OK · {len(datos)} filas · "
                  f"{datos['fecha'].min()} a {datos['fecha'].max()}")
    precios = pd.concat(partes, ignore_index=True)
    precios.to_csv(ARCHIVO_PRECIOS, index=False, encoding="utf-8")
    registrar(f"Yahoo total · {len(precios)} filas · {precios['ticker'].nunique()} tickers · {ARCHIVO_PRECIOS}")
    return precios


# ── 4. Tipo de cambio soles por dólar ─────────────────────────────────────
def descargar_fx():
    datos = descargar_ticker(TICKER_FX)
    if datos is None:
        registrar(f"Yahoo {TICKER_FX} · SIN DATOS (se conserva el archivo anterior si existe)")
        return None
    datos.insert(0, "ticker", TICKER_FX)
    datos["fecha_extraccion"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    datos.to_csv(ARCHIVO_FX, index=False, encoding="utf-8")
    registrar(f"Yahoo {TICKER_FX} · OK · {len(datos)} filas · {datos['fecha'].min()} a {datos['fecha'].max()}")
    return datos


if __name__ == "__main__":
    CARPETA_CRUDOS.mkdir(parents=True, exist_ok=True)
    registrar(f"Inicio · yfinance {yf.__version__} · ventana {FECHA_INICIO} a {FECHA_CORTE} "
              f"· {len(TICKERS)} tickers + {TICKER_FX}")
    descargar_precios()
    descargar_fx()
    registrar("Fin de 01_extraccion_api.py")
