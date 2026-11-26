# Autora: Imasumajj García Beltrán
# Código de matrícula: 2024200500F
# Tema N.º 81: Determinantes de la estructura de capital de las empresas listadas en la BVL
# Fecha de extracción: 2026-11-25
"""Limpieza (Fase 2): de los datos crudos a un panel emisora-trimestre listo para estimar.

Pasos
  1. SMV: tipificación de montos y paso de formato largo (una fila por cuenta) a ancho
     (una fila por emisora y trimestre).
  2. Filtro de la muestra: se excluyen las emisoras financieras y las que están en liquidación,
     los trimestres con activo menor que 1 millón y los errores de escala aislados; se corrigen las
     etiquetas de moneda que contradicen los comparativos. Cada paso queda contado en /salidas.
  3. Variables contables: apalancamiento, deuda financiera, tamaño, tangibilidad, rentabilidad,
     crecimiento de ventas, tasa impositiva efectiva, liquidez corriente y riesgo del negocio. Las cuentas de
     resultados se llevan a últimos doce meses (UDM) para quitar la estacionalidad.
  4. Yahoo Finance: volatilidad y frecuencia de negociación de cada acción por trimestre.
  5. BCRP: crecimiento del PBI y tasa de referencia promedio por trimestre; Yahoo Finance (PEN=X):
     tipo de cambio de cierre y su variación en el trimestre.
  6. Unión por emisora (RPJ) + trimestre, recorte de valores extremos al 1 % y 99 %
     (winsorizado, se marca cuántas variables se recortaron en cada fila).
  7. Diccionario de variables, hash SHA-256 y README.
Los datos crudos solo se leen: nunca se modifican.
"""
import hashlib
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ── 1. Parámetros ─────────────────────────────────────────────────────────
FECHA_INICIO = "2011-01-01"
FECHA_CORTE = "2025-12-31"
CODIGO = "2024200500F"
PERCENTILES_WINSOR = (0.01, 0.99)
ACTIVO_MINIMO = 1000             # miles: vehículos sin operaciones con activo menor que 1 millón
MIN_DIAS_VOLATILIDAD = 10
VENTANA_RIESGO = 8               # trimestres para la volatilidad del ROA (riesgo del negocio)
MIN_TRIM_RIESGO = 6              # trimestres mínimos dentro de esa ventana        # retornos diarios mínimos para calcular la volatilidad de un trimestre

CRUDO_SMV = Path(f"datos_crudos/datos_crudos_{CODIGO}_smv.csv")
CRUDO_YAHOO = Path(f"datos_crudos/datos_crudos_{CODIGO}_yahoo.csv")
CRUDO_FX = Path(f"datos_crudos/datos_crudos_{CODIGO}_fx.csv")
CRUDO_BCRP = Path(f"datos_crudos/datos_crudos_{CODIGO}_bcrp.csv")
SALIDA = Path(f"datos_procesados/datos_procesados_{CODIGO}.csv")
ARCHIVO_LOG = Path("log_ejecucion.txt")
CARPETA_SALIDAS = Path("salidas")

# Cuentas SMV (formato D, empresas no financieras)
BALANCE = {"1D020T": "activo", "1D040T": "pasivo", "1D07ST": "patrimonio",
           "1D0309": "deuda_fin_cte", "1D0401": "deuda_fin_nocte", "1D0205": "ppe",
           "1D0211": "prop_inversion", "1D01ST": "activo_cte", "1D03ST": "pasivo_cte",
           "1D0109": "efectivo"}
RESULTADOS = {"2D01ST": "ventas", "2D03ST": "util_operativa", "2D0402": "gasto_fin",
              "2D04ST": "util_antes_imp", "2D0502": "impuesto", "2D07ST": "util_neta"}

# Emisoras del sector financiero: su estructura de capital está regulada (encaje, patrimonio
# efectivo), por eso la literatura las excluye. La SMV no trae el CIIU en el 93 % de las filas,
# así que la lista se arma por RPJ revisando la actividad de cada emisora del sector DIVERSOS.
FINANCIERAS = {
    "B60051": "Credicorp Ltd. (holding financiero)",
    "OE2305": "Intercorp Financial Services Inc. (holding financiero)",
    "OE5132": "Credicorp Capital Perú S.A.A. (banca de inversión)",
    "OE2258": "Diviso Grupo Financiero S.A. (holding financiero)",
    "OE3108": "Edyficar Perú S.A. (holding de Mibanco)",
    "OE6804": "Factotal Perú S.A. (factoring)",
    "CD0009": "Transacciones Financieras S.A. (servicios financieros)",
    "BV0001": "Grupo BVL S.A.A. (bolsa de valores)",
    "J01554": "Nuam Internacional SpA (bolsa de valores)",
    "OE7005": "NISA Asset Management S.A. (administradora de activos)",
    "OE5100": "Grupo ACP Corp. S.A. (grupo de microfinanzas)",
}
# Holdings no financieros: sus estados individuales muestran sobre todo inversiones en
# subsidiarias, así que se marcan (holding = 1) para una prueba de robustez sin ellos.
HOLDINGS = {"B30121", "B30207", "B50003", "B60001", "B80031", "B80049", "B80057", "CD0001",
            "J40120", "J40582", "J40846", "L01796", "OE4977", "OE5087", "OE5665", "OE7816",
            "OE8099", "B30031"}

MESES_BCRP = {"Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4, "May": 5, "Jun": 6, "Jul": 7,
              "Ago": 8, "Sep": 9, "Set": 9, "Oct": 10, "Nov": 11, "Dic": 12}


def registrar(mensaje):
    linea = f"{datetime.now():%Y-%m-%d %H:%M:%S} · 03_limpieza_datos · {mensaje}"
    print(linea)
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as log:
        log.write(linea + "\n")


def guardar_tabla(tabla, nombre, indice=False):
    ruta = CARPETA_SALIDAS / nombre
    tabla.to_csv(ruta, index=indice, encoding="utf-8")
    registrar(f"tabla guardada: {ruta}")


# ── 2. SMV: de formato largo a ancho ──────────────────────────────────────
def cargar_smv():
    smv = pd.read_csv(CRUDO_SMV, dtype={"RPJ": str, "Cuenta": str, "CIIU": str, "RUC": str})
    for columna in ["Monto1", "Monto2", "Monto3", "Monto4"]:
        smv[columna] = pd.to_numeric(smv[columna], errors="coerce")
    smv["anio"] = smv["anio_consulta"].astype(int)
    smv["trimestre"] = smv["trimestre_consulta"].astype(int)
    smv["moneda"] = np.where(smv["Moneda"].str.startswith("S"), "PEN", "USD")
    registrar(f"SMV leído: {len(smv)} filas, {smv['RPJ'].nunique()} emisoras")
    llave = ["RPJ", "anio", "trimestre"]

    balance = smv[smv["Cuenta"].isin(BALANCE)]
    ancho_bg = balance.pivot_table(index=llave, columns="Cuenta", values="Monto1", aggfunc="first")
    ancho_bg = ancho_bg.rename(columns=BALANCE)

    resultados = smv[smv["Cuenta"].isin(RESULTADOS)]
    partes = []
    for monto, sufijo in [("Monto1", "_trim"), ("Monto2", "_trim_ant"),
                          ("Monto3", "_acum"), ("Monto4", "_acum_ant")]:
        ancho = resultados.pivot_table(index=llave, columns="Cuenta", values=monto, aggfunc="first")
        partes.append(ancho.rename(columns={c: RESULTADOS[c] + sufijo for c in ancho.columns}))
    ancho_gp = pd.concat(partes, axis=1)

    smv = corregir_moneda(smv, llave)
    atributos = (smv.sort_values(llave).groupby(llave)
                 .agg(emisora=("NombreEmpresa", "last"), sector=("TipoSector", "last"),
                      ruc=("RUC", "last"), moneda=("moneda", "last")))
    panel = atributos.join(ancho_bg, how="left").join(ancho_gp, how="left").reset_index()
    # El nombre y el sector se fijan con el último reporte de cada emisora
    ultimo = panel.sort_values(["anio", "trimestre"]).groupby("RPJ")[["emisora", "sector"]].last()
    panel = panel.drop(columns=["emisora", "sector"]).merge(ultimo, on="RPJ")
    panel["sector"] = panel["sector"].replace({"INDUSTRIALES DEL TRABAJO": "INDUSTRIALES"})
    registrar(f"SMV en formato ancho: {len(panel)} emisora-trimestres")
    return panel


def corregir_moneda(smv, llave):
    """La etiqueta 'Moneda' de la SMV a veces está mal (p. ej. Alicorp 2025-T4 figura en dólares
    con montos en soles). Cada balance trae como comparativo (Monto2) el activo total del cierre
    del año anterior. Si la etiqueta cambió, pero ese comparativo es igual (±2 %) al activo que se
    reportó en ese cierre, o al comparativo del trimestre previo del mismo año, los montos siguen
    en la misma moneda: se corrige la etiqueta. Un cambio real de moneda (p. ej. Minsur en 2012)
    no pasa la prueba, porque el comparativo se reexpresa en la nueva moneda."""
    activo = (smv[smv["Cuenta"] == "1D020T"].sort_values(llave)
              .set_index(llave)[["Monto1", "Monto2", "moneda"]].copy())
    correcciones = []
    for rpj, anio, trimestre in activo.index:
        fila = activo.loc[(rpj, anio, trimestre)]
        # Prueba 1: comparativo de hoy = activo que se reportó al cierre del año anterior
        # Prueba 2: comparativo de hoy = comparativo del trimestre previo del mismo año
        pruebas = [((rpj, anio - 1, 4), "Monto1", "cierre del año anterior")]
        if trimestre > 1:
            pruebas.append(((rpj, anio, trimestre - 1), "Monto2", "trimestre previo del mismo año"))
        for referencia, columna, nombre in pruebas:
            if referencia not in activo.index:
                continue
            previo = activo.loc[referencia]
            if (fila["moneda"] != previo["moneda"] and previo[columna] > 0
                    and abs(fila["Monto2"] / previo[columna] - 1) < 0.02):
                correcciones.append((rpj, anio, trimestre, fila["moneda"], previo["moneda"], nombre,
                                     fila["Monto2"], previo[columna]))
                activo.loc[(rpj, anio, trimestre), "moneda"] = previo["moneda"]
                break
    tabla = pd.DataFrame(correcciones, columns=["rpj", "anio", "trimestre", "moneda_smv", "moneda_corregida",
                                                "prueba", "comparativo_reportado", "valor_de_referencia"])
    guardar_tabla(tabla, "tabla_correccion_moneda.csv")
    registrar(f"Etiquetas de moneda corregidas: {len(tabla)} emisora-trimestres")
    corregida = activo["moneda"].rename("moneda_corregida")
    smv = smv.merge(corregida, left_on=llave, right_index=True, how="left")
    smv["moneda"] = smv["moneda_corregida"].fillna(smv["moneda"])
    return smv.drop(columns="moneda_corregida")


# ── 3. Filtro de la muestra ───────────────────────────────────────────────
def filtrar_muestra(panel):
    pasos = [("Emisoras-trimestre descargadas de la SMV (2011-T1 a 2025-T4)", panel)]
    excluidas = []

    financieras = panel["RPJ"].isin(FINANCIERAS)
    for rpj, motivo in FINANCIERAS.items():
        if rpj in set(panel["RPJ"]):
            excluidas.append((rpj, panel.loc[panel["RPJ"] == rpj, "emisora"].iat[0],
                              "sector financiero", motivo))
    panel = panel[~financieras]
    pasos.append(("Sin emisoras del sector financiero", panel))

    en_liquidacion = panel["emisora"].str.contains("LIQUIDACION|LIQUIDACIÓN", case=False)
    for rpj, nombre in panel.loc[en_liquidacion, ["RPJ", "emisora"]].drop_duplicates().values:
        excluidas.append((rpj, nombre, "en liquidación", "el nombre registrado indica liquidación"))
    panel = panel[~en_liquidacion]
    pasos.append(("Sin emisoras en liquidación", panel))

    panel = panel[panel["activo"].notna() & (panel["activo"] > 0)]
    pasos.append(("Con activo total positivo", panel))
    sin_operaciones = panel["activo"] < ACTIVO_MINIMO
    for rpj, nombre, n in (panel[sin_operaciones].groupby(["RPJ", "emisora"]).size().reset_index().values):
        excluidas.append((rpj, nombre, "sin operaciones", f"{n} trimestres con activo menor que 1 millón"))
    panel = panel[~sin_operaciones]
    pasos.append(("Con activo de al menos 1 millón (en miles, moneda de reporte)", panel))
    panel = panel[panel["pasivo"].notna()]
    pasos.append(("Con pasivo total reportado (variable dependiente)", panel))

    # Error de escala aislado: el activo de un solo trimestre es ≥ 50 veces (o ≤ 1/50) el de los
    # trimestres vecinos, p. ej. un reporte en soles en vez de miles de soles.
    panel = panel.sort_values(["RPJ", "anio", "trimestre"])
    anterior = panel.groupby("RPJ")["activo"].shift(1)
    siguiente = panel.groupby("RPJ")["activo"].shift(-1)
    salto = ((panel["activo"] / anterior >= 50) & (panel["activo"] / siguiente >= 50)) | \
            ((panel["activo"] / anterior <= 1 / 50) & (panel["activo"] / siguiente <= 1 / 50))
    for rpj, nombre, anio, trimestre in panel.loc[salto, ["RPJ", "emisora", "anio", "trimestre"]].values:
        excluidas.append((rpj, nombre, "error de escala aislado", f"solo el trimestre {anio}-T{trimestre}"))
    panel = panel[~salto]
    pasos.append(("Sin errores de escala aislados en el activo", panel))

    tabla = pd.DataFrame([(paso, len(d), d["RPJ"].nunique()) for paso, d in pasos],
                         columns=["paso", "observaciones", "emisoras"])
    guardar_tabla(tabla, "tabla_filtro_muestra.csv")
    guardar_tabla(pd.DataFrame(excluidas, columns=["rpj", "emisora", "motivo", "detalle"]),
                  "tabla_emisoras_excluidas.csv")
    print(tabla.to_string(index=False))
    registrar(f"Muestra final: {len(panel)} emisora-trimestres de {panel['RPJ'].nunique()} emisoras")
    return panel.copy()


# ── 4. Tipo de cambio de fin de trimestre ─────────────────────────────────
def tipo_cambio_trimestral():
    fx = pd.read_csv(CRUDO_FX, parse_dates=["fecha"])
    fx["periodo"] = fx["fecha"].dt.to_period("Q")
    ordenado = fx.sort_values("fecha").groupby("periodo")["Close"]
    cierre = ordenado.last().rename("tipo_cambio")
    # Variación dentro del trimestre (cierre / primer dato del trimestre - 1, en %): así también
    # existe para 2011-T1, porque la serie empieza el 3 de enero de 2011
    variacion = ((cierre / ordenado.first() - 1) * 100).rename("var_tipo_cambio")
    if not cierre.between(2.0, 5.0).all():
        registrar("ADVERTENCIA: tipo de cambio fuera de 2-5 soles por dólar en algún trimestre")
    registrar(f"Tipo de cambio PEN=X: {len(cierre)} trimestres "
              f"({cierre.min():.3f} a {cierre.max():.3f} soles por dólar)")
    return pd.concat([cierre, variacion], axis=1)


# ── 5. Variables contables ────────────────────────────────────────────────
def ultimos_doce_meses(panel, cuenta):
    """Monto de los últimos doce meses (UDM) con el acumulado del año:
    UDM_t = acumulado_t + (anual del año anterior - acumulado del año anterior a la misma fecha).
    El anual del año anterior se toma del 4.º trimestre del mismo año (columna comparativa, en la
    misma moneda); si falta, del 4.º trimestre del año anterior siempre que la moneda coincida."""
    acum, acum_ant = panel[f"{cuenta}_acum"], panel[f"{cuenta}_acum_ant"]
    t4 = panel[panel["trimestre"] == 4]
    anual_ant_mismo = t4.set_index(["RPJ", "anio"])[f"{cuenta}_acum_ant"]
    anual_previo = t4.assign(anio=t4["anio"] + 1).set_index(["RPJ", "anio"])
    llave = pd.MultiIndex.from_frame(panel[["RPJ", "anio"]])
    anual_ant = pd.Series(anual_ant_mismo.reindex(llave).values, index=panel.index)
    respaldo = pd.Series(anual_previo[f"{cuenta}_acum"].reindex(llave).values, index=panel.index)
    misma_moneda = pd.Series(anual_previo["moneda"].reindex(llave).values, index=panel.index) == panel["moneda"]
    anual_ant = anual_ant.fillna(respaldo.where(misma_moneda))
    udm = acum + anual_ant - acum_ant
    return udm.where(panel["trimestre"] != 4, acum)


def razon(numerador, denominador):
    return (numerador / denominador).where(denominador != 0).replace([np.inf, -np.inf], np.nan)


def variables_contables(panel, fx):
    panel["periodo"] = pd.PeriodIndex.from_fields(year=panel["anio"], quarter=panel["trimestre"], freq="Q")
    panel["tipo_cambio"] = panel["periodo"].map(fx["tipo_cambio"])
    panel["var_tipo_cambio"] = panel["periodo"].map(fx["var_tipo_cambio"])
    factor = np.where(panel["moneda"] == "USD", panel["tipo_cambio"], 1.0)

    for cuenta in ["ventas", "util_neta", "util_antes_imp", "impuesto"]:
        panel[f"{cuenta}_udm"] = ultimos_doce_meses(panel, cuenta)

    deuda_fin = panel["deuda_fin_cte"].fillna(0) + panel["deuda_fin_nocte"].fillna(0)
    tangibles = panel["ppe"].fillna(0) + panel["prop_inversion"].fillna(0)

    # Montos en miles de soles (los reportes en dólares se convierten al tipo de cambio de cierre)
    panel["activo_total"] = panel["activo"] * factor
    panel["pasivo_total"] = panel["pasivo"] * factor
    panel["patrimonio_total"] = panel["patrimonio"] * factor
    panel["deuda_financiera_total"] = deuda_fin * factor
    panel["ventas_udm_soles"] = panel["ventas_udm"] * factor
    panel["utilidad_neta_udm_soles"] = panel["util_neta_udm"] * factor

    # Variable dependiente y alternativa
    panel["apalancamiento"] = razon(panel["pasivo"], panel["activo"])
    panel["deuda_financiera"] = razon(deuda_fin, panel["activo"])
    # Determinantes contables (no dependen de la moneda, salvo el tamaño)
    panel["tamano"] = np.log(panel["activo_total"])
    panel["tangibilidad"] = razon(tangibles, panel["activo"])
    panel["rentabilidad"] = razon(panel["util_neta_udm"], panel["activo"])
    ventas_ant = panel["ventas_trim_ant"]
    panel["crecimiento_ventas"] = razon(panel["ventas_trim"] - ventas_ant, ventas_ant.abs()).where(ventas_ant > 0)
    # Impuesto: la SMV lo reporta en negativo cuando es gasto
    tasa = razon(-panel["impuesto_udm"], panel["util_antes_imp_udm"])
    panel["tasa_impositiva"] = tasa.where(panel["util_antes_imp_udm"] > 0).clip(0, 1)
    panel["liquidez_corriente"] = razon(panel["activo_cte"], panel["pasivo_cte"])
    # Riesgo del negocio: desviación estándar del ROA de cada trimestre (utilidad neta del trimestre /
    # activo) en los últimos 8 trimestres reportados por la emisora, incluido el actual
    panel = panel.sort_values(["RPJ", "anio", "trimestre"])
    roa_trim = razon(panel["util_neta_trim"], panel["activo"]).clip(-1, 1)
    panel["riesgo_negocio"] = (roa_trim.groupby(panel["RPJ"])
                               .transform(lambda s: s.rolling(VENTANA_RIESGO, min_periods=MIN_TRIM_RIESGO).std()))

    panel["patrimonio_negativo"] = (panel["patrimonio"] < 0).astype(int)
    panel["holding"] = panel["RPJ"].isin(HOLDINGS).astype(int)
    registrar(f"Variables contables calculadas para {len(panel)} emisora-trimestres")
    return panel


# ── 6. Yahoo Finance: mercado ─────────────────────────────────────────────
def variables_mercado():
    yahoo = pd.read_csv(CRUDO_YAHOO, parse_dates=["fecha"], dtype={"rpj": str})
    yahoo = yahoo.sort_values(["ticker", "fecha"])
    yahoo["periodo"] = yahoo["fecha"].dt.to_period("Q")
    yahoo["negocio"] = yahoo["Volume"].fillna(0) > 0
    # Retornos solo entre días con negociación: en días sin operaciones Yahoo repite el precio
    negociados = yahoo[yahoo["negocio"] & (yahoo["Adj Close"] > 0)].copy()
    negociados["retorno"] = negociados.groupby("ticker")["Adj Close"].transform(lambda p: np.log(p).diff())

    def resumen(grupo):
        return pd.Series({"volatilidad": grupo["retorno"].std() * np.sqrt(252)
                          if grupo["retorno"].notna().sum() >= MIN_DIAS_VOLATILIDAD else np.nan,
                          "dias_negociados": grupo["retorno"].notna().sum()})

    vol = negociados.groupby(["ticker", "rpj", "periodo"]).apply(resumen, include_groups=False)
    frecuencia = yahoo.groupby(["ticker", "rpj", "periodo"])["negocio"].mean().rename("frecuencia_negociacion")
    mercado = vol.join(frecuencia, how="outer").reset_index()
    registrar(f"Yahoo Finance: {mercado['ticker'].nunique()} acciones, {len(mercado)} acción-trimestres")
    return mercado[["rpj", "ticker", "periodo", "volatilidad", "frecuencia_negociacion"]]


# ── 7. BCRP: entorno macroeconómico ───────────────────────────────────────
def fecha_bcrp(texto, frecuencia):
    texto = str(texto).strip()
    if frecuencia.startswith("trimestr"):            # 'T111' -> 2011-T1
        anio = int(texto[2:])
        return pd.Period(year=anio + (1900 if anio >= 50 else 2000), quarter=int(texto[1]), freq="Q")
    anio = int(texto[-2:])                            # 'Ene11' -> enero de 2011
    return pd.Period(year=anio + (1900 if anio >= 50 else 2000), month=MESES_BCRP[texto[:3]], freq="M")


def variables_macro():
    bcrp = pd.read_csv(CRUDO_BCRP, dtype=str)
    bcrp["valor"] = pd.to_numeric(bcrp["valor_texto"].str.replace(",", ""), errors="coerce")
    bcrp["fecha"] = [fecha_bcrp(t, f) for t, f in zip(bcrp["fecha_texto"], bcrp["frecuencia"])]

    pbi = bcrp[bcrp["serie"] == "PN02507AQ"].set_index("fecha")["valor"].rename("pbi_var")
    tasa = bcrp[bcrp["serie"] == "PD04722MM"].copy()
    tasa["periodo"] = [f.asfreq("Q") for f in tasa["fecha"]]
    tasa = tasa.groupby("periodo")["valor"].mean().rename("tasa_referencia")
    pbi.index = pd.PeriodIndex(pbi.index, freq="Q")
    tasa.index = pd.PeriodIndex(tasa.index, freq="Q")
    macro = pd.concat([pbi, tasa], axis=1)
    macro.index.name = "periodo"
    registrar(f"BCRP: PBI en {pbi.notna().sum()} trimestres, tasa de referencia en {tasa.notna().sum()} trimestres")
    return macro


# ── 8. Winsorizado ────────────────────────────────────────────────────────
def winsorizar(panel, columnas):
    recortes = pd.Series(0, index=panel.index)
    filas = []
    for columna in columnas:
        bajo, alto = panel[columna].quantile(PERCENTILES_WINSOR)
        fuera = (panel[columna] < bajo) | (panel[columna] > alto)
        recortes += fuera.astype(int)
        filas.append((columna, round(bajo, 6), round(alto, 6), int((panel[columna] < bajo).sum()),
                      int((panel[columna] > alto).sum()), int(panel[columna].notna().sum())))
        panel[columna] = panel[columna].clip(bajo, alto)
    panel["n_winsorizados"] = recortes
    tabla = pd.DataFrame(filas, columns=["variable", "percentil_1", "percentil_99", "recortados_abajo",
                                         "recortados_arriba", "observaciones"])
    guardar_tabla(tabla, "tabla_winsorizado.csv")
    return panel


# ── 9. Programa principal ─────────────────────────────────────────────────
def main():
    CARPETA_SALIDAS.mkdir(exist_ok=True)
    SALIDA.parent.mkdir(exist_ok=True)
    registrar("Inicio de 03_limpieza_datos.py")

    panel = filtrar_muestra(cargar_smv())
    panel = variables_contables(panel, tipo_cambio_trimestral())

    inicio, corte = pd.Period(FECHA_INICIO, "Q"), pd.Period(FECHA_CORTE, "Q")
    panel = panel[(panel["periodo"] >= inicio) & (panel["periodo"] <= corte)]

    mercado = variables_mercado()
    sin_cruce = sorted(set(mercado["rpj"]) - set(panel["RPJ"]))
    if sin_cruce:
        registrar(f"ADVERTENCIA: RPJ de Yahoo sin emisora en la muestra SMV: {sin_cruce}")
    panel = panel.merge(mercado.rename(columns={"rpj": "RPJ"}), on=["RPJ", "periodo"], how="left")
    panel = panel.merge(variables_macro(), left_on="periodo", right_index=True, how="left")
    panel["submuestra_yahoo"] = panel["ticker"].notna().astype(int)

    if panel.duplicated(["RPJ", "periodo"]).any():
        raise ValueError("Hay emisora-trimestres duplicados en el panel")

    continuas = ["apalancamiento", "deuda_financiera", "tamano", "tangibilidad", "rentabilidad",
                 "crecimiento_ventas", "liquidez_corriente", "riesgo_negocio", "volatilidad"]
    panel = winsorizar(panel, continuas)

    panel = panel.sort_values(["RPJ", "periodo"]).reset_index(drop=True)
    panel.insert(0, "id", range(1, len(panel) + 1))
    panel["periodo"] = panel["periodo"].astype(str).str.replace("Q", "-T")
    final = panel.rename(columns={"RPJ": "rpj"})[[
        "id", "rpj", "emisora", "sector", "ruc", "anio", "trimestre", "periodo", "moneda", "tipo_cambio",
        "activo_total", "pasivo_total", "patrimonio_total", "deuda_financiera_total",
        "ventas_udm_soles", "utilidad_neta_udm_soles",
        "apalancamiento", "deuda_financiera", "tamano", "tangibilidad", "rentabilidad",
        "crecimiento_ventas", "tasa_impositiva", "liquidez_corriente", "riesgo_negocio",
        "ticker", "volatilidad", "frecuencia_negociacion", "pbi_var", "tasa_referencia", "var_tipo_cambio",
        "holding", "patrimonio_negativo", "submuestra_yahoo", "n_winsorizados"]]
    final = final.rename(columns={"moneda": "moneda_reporte"})

    final.to_csv(SALIDA, index=False, encoding="utf-8")
    huella = hashlib.sha256(SALIDA.read_bytes()).hexdigest()
    registrar(f"{SALIDA}: {len(final)} filas, {final['rpj'].nunique()} emisoras, "
              f"{final.shape[1]} columnas · SHA-256 {huella}")

    # Cobertura: cuántos datos aporta cada fuente (ninguna fuente es decorativa)
    fuentes = {"SMV": ["apalancamiento", "deuda_financiera", "tamano", "tangibilidad", "rentabilidad",
                       "crecimiento_ventas", "tasa_impositiva", "liquidez_corriente", "riesgo_negocio"],
               "Yahoo Finance": ["volatilidad", "frecuencia_negociacion"],
               "BCRP": ["pbi_var", "tasa_referencia"],
               "Yahoo Finance (PEN=X)": ["tipo_cambio", "var_tipo_cambio"]}
    cobertura = pd.DataFrame([(f, v, int(final[v].notna().sum()), round(final[v].notna().mean() * 100, 1))
                              for f, vs in fuentes.items() for v in vs],
                             columns=["fuente", "variable", "observaciones", "porcentaje"])
    guardar_tabla(cobertura, "tabla_cobertura_fuentes.csv")
    por_anio = final.groupby("anio").agg(observaciones=("id", "size"), emisoras=("rpj", "nunique"),
                                         submuestra_yahoo=("submuestra_yahoo", "sum"))
    guardar_tabla(por_anio, "tabla_observaciones_por_anio.csv", indice=True)
    por_sector = final.groupby("sector").agg(observaciones=("id", "size"), emisoras=("rpj", "nunique"),
                                             apalancamiento_medio=("apalancamiento", "mean")).round(3)
    guardar_tabla(por_sector, "tabla_observaciones_por_sector.csv", indice=True)

    print("\nCobertura por fuente:\n" + cobertura.to_string(index=False))
    print("\nObservaciones por año:\n" + por_anio.to_string())
    print("\nObservaciones por sector:\n" + por_sector.to_string())

    crear_diccionario()
    actualizar_readme(huella, len(final), final["rpj"].nunique())
    registrar("Fin de 03_limpieza_datos.py")


# ── 10. Diccionario de variables y README ─────────────────────────────────
def crear_diccionario():
    smv = "SMV, Portal de Datos Abiertos: WebServiceInfoFinanciera.asmx"
    bg, gp = smv + " · obtener_BalanceGeneral", smv + " · obtener_GanciaPerdida"
    yahoo = "Yahoo Finance (yfinance): query2.finance.yahoo.com/v8/finance/chart/{ticker}"
    bcrp = "BCRP, BCRPData (scraping HTML): estadisticas.bcrp.gob.pe/estadisticas/series/"
    filas = [
        ("id", "Número correlativo de la observación", "número", "—", "03_limpieza_datos.py"),
        ("rpj", "Código RPJ de la emisora en la SMV; con 'periodo' forma la llave del panel", "texto", "—", smv),
        ("emisora", "Razón social según el último reporte a la SMV", "texto", "—", smv),
        ("sector", "Sector de la SMV: AGRICOLAS, DIVERSOS, INDUSTRIALES, MINERAS o SERVICIOS PUBLICOS", "texto", "—", smv),
        ("ruc", "RUC de la emisora", "texto", "—", smv),
        ("anio / trimestre / periodo", "Año, trimestre (1 a 4) y periodo en formato AAAA-Tn", "número / texto", "trimestral", smv),
        ("moneda_reporte", "Moneda en que la emisora presenta sus estados (PEN o USD)", "texto", "trimestral", smv),
        ("tipo_cambio", "Tipo de cambio de cierre de trimestre (último dato del trimestre)", "soles por dólar", "trimestral", yahoo + " · PEN=X"),
        ("activo_total", "Total de activos (cuenta 1D020T)", "miles de S/", "trimestral", bg),
        ("pasivo_total", "Total de pasivos (1D040T)", "miles de S/", "trimestral", bg),
        ("patrimonio_total", "Total de patrimonio (1D07ST)", "miles de S/", "trimestral", bg),
        ("deuda_financiera_total", "Otros pasivos financieros corrientes (1D0309) + no corrientes (1D0401)", "miles de S/", "trimestral", bg),
        ("ventas_udm_soles", "Ingresos de actividades ordinarias (2D01ST), últimos doce meses", "miles de S/", "trimestral", gp),
        ("utilidad_neta_udm_soles", "Ganancia neta del ejercicio (2D07ST), últimos doce meses", "miles de S/", "trimestral", gp),
        ("apalancamiento", "Y · Pasivo total / activo total (winsorizado 1-99 %)", "razón", "trimestral", bg),
        ("deuda_financiera", "Y alternativa · Deuda financiera / activo total (winsorizado)", "razón", "trimestral", bg),
        ("tamano", "X · Logaritmo natural del activo total en miles de soles (winsorizado)", "ln(miles de S/)", "trimestral", bg + " + PEN=X"),
        ("tangibilidad", "X · (Propiedades, planta y equipo + propiedades de inversión) / activo total (winsorizado)", "razón", "trimestral", bg),
        ("rentabilidad", "X · ROA: ganancia neta de los últimos doce meses / activo total (winsorizado)", "razón", "trimestral", gp + " + " + bg),
        ("crecimiento_ventas", "X · Variación de las ventas del trimestre frente al mismo trimestre del año anterior (winsorizado)", "razón", "trimestral", gp),
        ("tasa_impositiva", "X · Impuesto a las ganancias / utilidad antes de impuestos, últimos doce meses; acotada a [0, 1]; vacía si la utilidad es ≤ 0", "razón", "trimestral", gp),
        ("liquidez_corriente", "X · Activo corriente / pasivo corriente (winsorizado)", "veces", "trimestral", bg),
        ("riesgo_negocio", "X · Riesgo del negocio: desviación estándar del ROA trimestral (utilidad neta del trimestre / activo) en los últimos 8 trimestres reportados, con mínimo 6 (winsorizado)", "razón", "trimestral", gp + " + " + bg),
        ("ticker", "Código de la acción en Yahoo Finance (solo submuestra de 20 emisoras)", "texto", "—", yahoo),
        ("volatilidad", "X · Desviación estándar anualizada de los retornos logarítmicos diarios del precio ajustado, solo días con negociación (winsorizado)", "razón anual", "trimestral", yahoo),
        ("frecuencia_negociacion", "X · Proporción de días del trimestre con volumen negociado mayor que cero", "proporción", "trimestral", yahoo),
        ("pbi_var", "Control · PBI real, variación porcentual interanual (serie PN02507AQ)", "%", "trimestral", bcrp + "trimestrales/resultados/PN02507AQ/html"),
        ("tasa_referencia", "Control · Tasa de referencia de la política monetaria, promedio de los tres meses (PD04722MM)", "%", "trimestral", bcrp + "mensuales/resultados/PD04722MM/html"),
        ("var_tipo_cambio", "Control · Variación del tipo de cambio dentro del trimestre: cierre / primer dato del trimestre - 1 (positivo = depreciación del sol)", "%", "trimestral", yahoo + " · PEN=X"),
        ("holding", "1 si la emisora es un holding no financiero (estados individuales); 0 si no", "0/1", "—", "03_limpieza_datos.py"),
        ("patrimonio_negativo", "1 si el patrimonio del trimestre es negativo; 0 si no", "0/1", "trimestral", bg),
        ("submuestra_yahoo", "1 si la emisora-trimestre tiene datos de Yahoo Finance; 0 si no", "0/1", "trimestral", "03_limpieza_datos.py"),
        ("n_winsorizados", "Número de variables de la fila recortadas al percentil 1 o 99", "número", "trimestral", "03_limpieza_datos.py"),
    ]
    dic = pd.DataFrame(filas, columns=["variable", "definicion", "unidad", "frecuencia", "fuente_y_endpoint"])
    dic["fecha_inicio"] = FECHA_INICIO
    dic["fecha_corte"] = FECHA_CORTE
    dic.to_excel("diccionario_variables.xlsx", index=False)
    registrar("diccionario_variables.xlsx creado")


def actualizar_readme(huella, filas, emisoras):
    readme = Path("README.md")
    if not readme.exists():
        return
    texto = readme.read_text(encoding="utf-8")
    bloque = (f"## Hash SHA-256 de datos_procesados_{CODIGO}.csv\n"
              f"`{huella}`  ({filas} observaciones emisora-trimestre, {emisoras} emisoras; "
              f"generado el {datetime.now():%Y-%m-%d %H:%M})\n")
    patron = r"## Hash SHA-256 de datos_procesados_[^\n]*\n(?:(?!\n## ).)*"
    if re.search(patron, texto, flags=re.S):
        texto = re.sub(patron, bloque.rstrip("\n"), texto, flags=re.S)
    else:
        texto += "\n" + bloque
    readme.write_text(texto, encoding="utf-8")
    registrar("README.md: hash SHA-256 actualizado")


if __name__ == "__main__":
    main()
