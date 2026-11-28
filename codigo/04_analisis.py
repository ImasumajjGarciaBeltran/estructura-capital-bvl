# Autora: Imasumajj García Beltrán
# Código de matrícula: 2024200500F
# Tema N.º 81: Determinantes de la estructura de capital de las empresas listadas en la BVL
# Fecha de extracción: 2026-11-25
"""Análisis (Fase 3): tablas y figuras del artículo a partir de datos_procesados.

Diseño
  Modelo 1 (principal): apalancamiento = f(H1 tamaño, H2 tangibilidad, H3 rentabilidad,
            H4 crecimiento, H5 liquidez, H6 riesgo del negocio; controles PBI, tasa de
            referencia y variación del tipo de cambio). Se estima por MCO agrupado, efectos
            fijos (EF) y efectos aleatorios (EA); la prueba de Hausman elige entre EF y EA.
  Modelo 2 (robustez): el mismo modelo con deuda financiera / activo como variable dependiente.
  Modelo 3 (confirmación de H6): el riesgo se mide con la volatilidad de la acción (Yahoo Finance)
            en las 20 emisoras con acciones líquidas.
  Anexo: Modelo 1 sin holdings y con panel balanceado (solo emisoras con los 60 trimestres).
  Panel desbalanceado: los faltantes no se imputan; cada modelo usa sus casos completos y
  tabla0a/tabla0b documentan cuántos faltan, por qué y cuán balanceado es el panel.
  Las variables de empresa entran rezagadas un trimestre (t-1) para atenuar la causalidad inversa;
  el rezago solo se usa si el trimestre anterior existe (sin saltos). Los errores estándar son de
  Driscoll-Kraay (robustos a heterocedasticidad, autocorrelación y dependencia entre emisoras).
  No se usan números aleatorios, así que no hace falta semilla.
Todas las tablas (CSV) y figuras (PNG) se guardan en /salidas.
"""
import hashlib
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches
import matplotlib.transforms
import numpy as np
import pandas as pd
from linearmodels.panel import PanelOLS, PooledOLS, RandomEffects
from scipy import stats
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tsa.stattools import adfuller

# ── 1. Parámetros ─────────────────────────────────────────────────────────
FECHA_INICIO = "2011-01-01"
FECHA_CORTE = "2025-12-31"
CODIGO = "2024200500F"
ENTRADA = Path(f"datos_procesados/datos_procesados_{CODIGO}.csv")
CARPETA_SALIDAS = Path("salidas")
ARCHIVO_LOG = Path("log_ejecucion.txt")
MIN_TRIMESTRES = 4         # trimestres mínimos por emisora dentro de cada estimación
BANDA_DK = 4               # rezagos (trimestres) del núcleo de Bartlett en Driscoll-Kraay
MIN_T_RAIZ = 20            # trimestres consecutivos mínimos por emisora en la prueba de raíz unitaria
NIVEL = 0.05

HIPOTESIS = [  # (variable, etiqueta, hipótesis, signo esperado, trade-off, pecking order)
    ("tamano", "Tamaño", "H1", "+", "+", "−"),
    ("tangibilidad", "Tangibilidad", "H2", "+", "+", "−"),
    ("rentabilidad", "Rentabilidad", "H3", "−", "+", "−"),
    ("crecimiento_ventas", "Crecimiento", "H4", "+", "−", "+"),
    ("liquidez_corriente", "Liquidez", "H5", "−", "+", "−"),
    ("riesgo_negocio", "Riesgo del negocio", "H6", "−", "−", "ambiguo"),
]
CONTROLES = [("pbi_var", "Crecimiento del PBI"), ("tasa_referencia", "Tasa de referencia"),
             ("var_tipo_cambio", "Variación del tipo de cambio")]
REZAGADAS = [h[0] for h in HIPOTESIS] + ["volatilidad"]
X_EMPRESA = [f"{v}_l1" for v in (h[0] for h in HIPOTESIS)]
X_CONTROL = [c[0] for c in CONTROLES]
ETIQUETAS = {f"{v}_l1": f"{e} (t−1)" for v, e, *_ in HIPOTESIS}
ETIQUETAS.update({c: e for c, e in CONTROLES})
NOMBRES_BASE = {v: e for v, e, *_ in HIPOTESIS}
NOMBRES_BASE.update({"apalancamiento": "Apalancamiento", "deuda_financiera": "Deuda financiera"})
ETIQUETAS.update({"volatilidad_l1": "Volatilidad de la acción (t−1)", "const": "Constante",
                  "apalancamiento": "Apalancamiento", "deuda_financiera": "Deuda financiera"})

# Estilo de las figuras (editorial): fondo blanco, ejes discretos y paleta institucional validada
# para daltonismo y contraste: verde UNCP (serie principal) y oro (segunda serie / ajuste)
from matplotlib import font_manager
PRIMARIO, ACENTO, CONTRARIO = "#157347", "#C27F00", "#B4461A"
GRIS, TEXTO, TEXTO_2 = "#9c9c9c", "#1A1F24", "#5B6470"
_disponibles = {f.name for f in font_manager.fontManager.ttflist}
FUENTE = next((f for f in ["Fira Sans", "Source Sans 3", "Roboto", "Liberation Sans", "DejaVu Sans"]
               if f in _disponibles), "DejaVu Sans")
plt.rcParams.update({"font.family": [FUENTE, "DejaVu Sans"],   # DejaVu cubre ✓ y ✗ "font.size": 9, "axes.edgecolor": "#c9cfcc",
                     "axes.labelcolor": TEXTO, "xtick.color": TEXTO_2, "ytick.color": TEXTO_2,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": "#edf0ee", "grid.linewidth": 0.8, "axes.axisbelow": True,
                     "axes.titleweight": "bold", "figure.dpi": 110, "savefig.dpi": 300,
                     "savefig.bbox": "tight", "savefig.facecolor": "white"})
SECTORES = {"AGRICOLAS": "Agrícolas", "DIVERSOS": "Diversos", "INDUSTRIALES": "Industriales",
            "MINERAS": "Mineras", "SERVICIOS PUBLICOS": "Servicios públicos"}
NOTA_FUENTE = "Fuente: SMV, BCRP y Yahoo Finance (2011-T1 a 2025-T4). Elaboración propia."


def registrar(mensaje):
    linea = f"{datetime.now():%Y-%m-%d %H:%M:%S} · 04_analisis · {mensaje}"
    print(linea)
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as log:
        log.write(linea + "\n")


def guardar_tabla(tabla, nombre, indice=False):
    tabla.to_csv(CARPETA_SALIDAS / nombre, index=indice, encoding="utf-8")
    registrar(f"tabla guardada: salidas/{nombre}")


def encabezado(figura, titulo, subtitulo, arriba=0.975):
    """Barra dorada, título y subtítulo alineados a la izquierda (estilo editorial)."""
    figura.patches.append(matplotlib.patches.Rectangle((0.005, arriba + 0.012), 0.07, 0.011,
                          transform=figura.transFigure, color=ACENTO, zorder=5))
    figura.text(0.005, arriba - 0.004, titulo, fontsize=11.5, fontweight="bold", color=TEXTO, ha="left", va="top")
    figura.text(0.005, arriba - 0.058, subtitulo, fontsize=8, color=TEXTO_2, ha="left", va="top")


def guardar_figura(figura, nombre):
    # La nota de fuente va debajo de todo lo dibujado (incluidas etiquetas rotadas)
    figura.canvas.draw()
    lector = figura.canvas.get_renderer()
    abajo = min(ax.get_tightbbox(lector).transformed(figura.transFigure.inverted()).y0 for ax in figura.axes)
    figura.text(0.0, abajo - 0.015, NOTA_FUENTE, fontsize=7, color=TEXTO_2, ha="left", va="top",
                transform=figura.transFigure)
    figura.savefig(CARPETA_SALIDAS / nombre)
    plt.close(figura)
    registrar(f"figura guardada: salidas/{nombre}")


# ── 2. Datos ──────────────────────────────────────────────────────────────
def cargar_panel():
    huella = hashlib.sha256(ENTRADA.read_bytes()).hexdigest()
    en_readme = huella in Path("README.md").read_text(encoding="utf-8") if Path("README.md").exists() else False
    registrar(f"{ENTRADA} · SHA-256 {huella} · coincide con README: {'sí' if en_readme else 'NO'}")

    d = pd.read_csv(ENTRADA, dtype={"rpj": str, "ruc": str})
    d = d.sort_values(["rpj", "anio", "trimestre"]).reset_index(drop=True)
    d["fecha"] = pd.PeriodIndex.from_fields(year=d["anio"], quarter=d["trimestre"], freq="Q").to_timestamp()
    # Rezago t-1 solo si el trimestre anterior de la misma emisora es el inmediato anterior
    numero = d["anio"] * 4 + d["trimestre"]
    consecutivo = numero.groupby(d["rpj"]).diff() == 1
    for v in REZAGADAS:
        d[f"{v}_l1"] = d.groupby("rpj")[v].shift(1).where(consecutivo)
    registrar(f"Panel: {len(d)} observaciones, {d['rpj'].nunique()} emisoras")
    return d


def muestra(d, y, xs):
    m = d.dropna(subset=[y] + xs)
    conteo = m.groupby("rpj").size()
    return m[m["rpj"].isin(conteo[conteo >= MIN_TRIMESTRES].index)].set_index(["rpj", "fecha"])


# ── 3. Panel desbalanceado: faltantes y balance ──────────────────────────
MOTIVOS_FALTANTE = {
    "apalancamiento": "—",
    "tamano": "—",
    "tangibilidad": "—",
    "rentabilidad": "El estado de resultados del trimestre no fue reportado o falta el acumulado del año anterior",
    "crecimiento_ventas": "Sin ventas en el mismo trimestre del año anterior (empresa nueva, holding o sin ingresos)",
    "liquidez_corriente": "Pasivo corriente igual a cero o no reportado",
    "riesgo_negocio": "La emisora aún no acumula 6 trimestres de historia",
    "tasa_impositiva": "Utilidad antes de impuestos ≤ 0: la tasa efectiva no está definida",
    "volatilidad": "Solo existe para las 20 emisoras con acciones en Yahoo Finance",
}


def faltantes_y_balance(d):
    """Los faltantes no se imputan: cada uno tiene un motivo económico y la estimación usa los
    casos completos de cada modelo. Imputar (p. ej. con la media) inventaría datos que la fuente no
    publica y reduciría artificialmente la varianza."""
    nombres = {**NOMBRES_BASE, "tasa_impositiva": "Tasa impositiva efectiva", "volatilidad": "Volatilidad de la acción"}
    filas = [[nombres[v], len(d) - d[v].isna().sum(), d[v].isna().sum(),
              round(d[v].isna().mean() * 100, 1), motivo] for v, motivo in MOTIVOS_FALTANTE.items()]
    tabla = pd.DataFrame(filas, columns=["variable", "observaciones", "faltantes", "porcentaje_faltante", "motivo"])
    guardar_tabla(tabla, "tabla0a_faltantes.csv")
    por_emisora = d.groupby("rpj").size()
    balance = pd.DataFrame([
        ["Emisoras", d["rpj"].nunique()],
        ["Trimestres posibles por emisora", 60],
        ["Trimestres por emisora: mínimo", int(por_emisora.min())],
        ["Trimestres por emisora: mediana", float(por_emisora.median())],
        ["Trimestres por emisora: máximo", int(por_emisora.max())],
        ["Emisoras con los 60 trimestres", int((por_emisora == 60).sum())],
        ["Observaciones de esas emisoras", int(por_emisora[por_emisora == 60].sum())],
        ["Emisoras por año: mínimo", int(d.groupby("anio")["rpj"].nunique().min())],
        ["Emisoras por año: máximo", int(d.groupby("anio")["rpj"].nunique().max())],
    ], columns=["indicador", "valor"])
    guardar_tabla(balance, "tabla0b_balance_panel.csv")
    return tabla, balance


# ── 4. Estadísticos descriptivos, correlaciones y VIF ─────────────────────
def descriptivos(d):
    variables = (["apalancamiento", "deuda_financiera"] + [h[0] for h in HIPOTESIS] + X_CONTROL
                 + ["volatilidad", "frecuencia_negociacion", "tasa_impositiva"])
    nombres = {"apalancamiento": "Apalancamiento (Y)", "deuda_financiera": "Deuda financiera (Y alt.)",
               "volatilidad": "Volatilidad de la acción", "frecuencia_negociacion": "Frecuencia de negociación",
               "tasa_impositiva": "Tasa impositiva efectiva"}
    nombres.update({h[0]: f"{h[1]} ({h[2]})" for h in HIPOTESIS})
    nombres.update(dict(CONTROLES))
    fuente = {v: "SMV" for v in ["apalancamiento", "deuda_financiera", "tasa_impositiva"] + [h[0] for h in HIPOTESIS]}
    fuente.update({"pbi_var": "BCRP", "tasa_referencia": "BCRP", "var_tipo_cambio": "Yahoo Finance",
                   "volatilidad": "Yahoo Finance", "frecuencia_negociacion": "Yahoo Finance"})
    filas = []
    for v in variables:
        s = d[v].dropna()
        filas.append([nombres[v], fuente[v], len(s), s.mean(), s.std(), s.min(), s.quantile(0.25),
                      s.median(), s.quantile(0.75), s.max()])
    tabla = pd.DataFrame(filas, columns=["variable", "fuente", "n", "media", "desv_est", "minimo", "p25",
                                         "mediana", "p75", "maximo"]).round(4)
    guardar_tabla(tabla, "tabla1_descriptivos.csv")
    return tabla


def correlaciones_y_vif(m1):
    columnas = ["apalancamiento"] + X_EMPRESA + X_CONTROL
    corr = m1[columnas].corr().round(3)
    corr.index = corr.columns = [ETIQUETAS[c] for c in columnas]
    guardar_tabla(corr, "tabla2_correlaciones.csv", indice=True)

    X = m1[X_EMPRESA + X_CONTROL].assign(const=1.0)
    vif = pd.DataFrame({"variable": [ETIQUETAS[c] for c in X_EMPRESA + X_CONTROL],
                        "vif": [variance_inflation_factor(X.values, i) for i in range(len(X_EMPRESA + X_CONTROL))]})
    vif["vif"] = vif["vif"].round(3)
    vif["diagnostico"] = np.where(vif["vif"] < 5, "sin colinealidad relevante", "revisar")
    guardar_tabla(vif, "tabla3_vif.csv")
    return corr, vif


# ── 5. Raíz unitaria (Fisher-ADF de Maddala y Wu, extensión de la ADF vista en clase) ──
def tramo_consecutivo(serie_emisora, numero):
    """Devuelve el tramo más largo de trimestres consecutivos sin datos faltantes."""
    validos = serie_emisora.notna()
    grupo = ((numero.diff() != 1) | ~validos).cumsum()
    tramos = serie_emisora[validos].groupby(grupo[validos])
    if tramos.ngroups == 0:
        return serie_emisora.iloc[:0]
    return max((t for _, t in tramos), key=len)


def raiz_unitaria(d):
    filas = []
    numero = d["anio"] * 4 + d["trimestre"]
    for v in ["apalancamiento", "deuda_financiera"] + [h[0] for h in HIPOTESIS]:
        valores_p, omitidas = [], 0
        for rpj, grupo in d.groupby("rpj"):
            serie = tramo_consecutivo(grupo[v], numero.loc[grupo.index])
            if len(serie) < MIN_T_RAIZ:
                continue
            try:                      # series casi constantes no admiten la regresión ADF
                valores_p.append(adfuller(serie.values, regression="c", maxlag=4, autolag="AIC")[1])
            except (np.linalg.LinAlgError, ValueError):
                omitidas += 1
        if omitidas:
            registrar(f"Raíz unitaria de {v}: {omitidas} emisoras omitidas por series casi constantes")
        p = np.clip(np.array(valores_p), 1e-12, 1 - 1e-12)
        fisher = -2 * np.log(p).sum()
        p_fisher = stats.chi2.sf(fisher, 2 * len(p))
        z_choi = stats.norm.ppf(p).sum() / np.sqrt(len(p))
        filas.append([NOMBRES_BASE[v], "Fisher-ADF (panel)", len(p),
                      round(fisher, 2), p_fisher, round(z_choi, 3), stats.norm.cdf(z_choi),
                      "estacionaria" if p_fisher < NIVEL else "raíz unitaria"])
    macro = d.drop_duplicates("fecha").sort_values("fecha")
    for c, etiqueta in CONTROLES:
        resultado = adfuller(macro[c].values, regression="c", maxlag=4, autolag="AIC")
        filas.append([etiqueta, "ADF (serie de tiempo)", 1, round(resultado[0], 3), resultado[1], np.nan, np.nan,
                      "estacionaria" if resultado[1] < NIVEL else "raíz unitaria"])
    tabla = pd.DataFrame(filas, columns=["variable", "prueba", "emisoras_o_series", "estadistico",
                                         "p_valor", "z_choi", "p_valor_choi", "conclusion_5pct"])
    tabla[["p_valor", "p_valor_choi"]] = tabla[["p_valor", "p_valor_choi"]].round(4)
    guardar_tabla(tabla, "tabla4_raiz_unitaria.csv")
    return tabla


# ── 6. Estimación ─────────────────────────────────────────────────────────
def ajustar(m, y, xs):
    Y = m[y]
    X = m[xs].assign(const=1.0)[["const"] + xs]
    dk = {"cov_type": "kernel", "kernel": "bartlett", "bandwidth": BANDA_DK}
    return {"MCO agrupado": PooledOLS(Y, X).fit(**dk),
            "Efectos fijos": PanelOLS(Y, X, entity_effects=True).fit(**dk),
            "Efectos aleatorios": RandomEffects(Y, X).fit(**dk),
            "_EF_clasico": PanelOLS(Y, X, entity_effects=True).fit(),
            "_EA_clasico": RandomEffects(Y, X).fit()}


def hausman(ef, ea, xs):
    """Hausman clásico con las varianzas no robustas (Wooldridge, 2010, cap. 10)."""
    diferencia = ef.params[xs] - ea.params[xs]
    varianza = ef.cov.loc[xs, xs] - ea.cov.loc[xs, xs]
    estadistico = float(diferencia @ np.linalg.pinv(varianza.values) @ diferencia)
    return abs(estadistico), stats.chi2.sf(abs(estadistico), len(xs)), len(xs)


def estrellas(p):
    return "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""


def tabla_coeficientes(resultados, nombres_modelo, xs):
    """Formato de artículo: coeficiente con estrellas y error estándar entre paréntesis debajo."""
    filas, largo = [], []
    for x in xs + ["const"]:
        fila_c, fila_e = [ETIQUETAS[x]], [""]
        for nombre, r in zip(nombres_modelo, resultados):
            if x in r.params.index:
                fila_c.append(f"{r.params[x]:.4f}{estrellas(r.pvalues[x])}")
                fila_e.append(f"({r.std_errors[x]:.4f})")
                largo.append([nombre, ETIQUETAS[x], r.params[x], r.std_errors[x], r.pvalues[x]])
            else:
                fila_c.append("")
                fila_e.append("")
        filas += [fila_c, fila_e]
    return filas, pd.DataFrame(largo, columns=["modelo", "variable", "coeficiente", "error_estandar", "p_valor"])


def pie_tabla(resultados, muestras):
    filas = [["Observaciones"] + [f"{r.nobs:,}".replace(",", " ") for r in resultados],
             ["Emisoras"] + [str(m.index.get_level_values(0).nunique()) for m in muestras],
             ["R² dentro (within)"] + [f"{r.rsquared_within:.3f}" for r in resultados],
             ["R² total (overall)"] + [f"{r.rsquared_overall:.3f}" for r in resultados]]
    return filas


def modelo_principal(d):
    xs = X_EMPRESA + X_CONTROL
    m1 = muestra(d, "apalancamiento", xs)
    r = ajustar(m1, "apalancamiento", xs)
    h, p_h, gl = hausman(r["_EF_clasico"], r["_EA_clasico"], xs)
    f_agrupado = r["Efectos fijos"].f_pooled
    preferido = "Efectos fijos" if p_h < NIVEL else "Efectos aleatorios"
    registrar(f"Modelo 1: {r['Efectos fijos'].nobs} obs · Hausman χ²({gl}) = {h:.2f}, p = {p_h:.4f} → {preferido}")

    nombres = ["MCO agrupado", "Efectos fijos", "Efectos aleatorios"]
    filas, largo = tabla_coeficientes([r[n] for n in nombres], nombres, xs)
    filas += pie_tabla([r[n] for n in nombres], [m1] * 3)
    filas += [["F de significancia de los efectos fijos", "", f"{f_agrupado.stat:.2f} (p = {f_agrupado.pval:.4f})", ""],
              [f"Hausman χ²({gl})", "", f"{h:.2f} (p = {p_h:.4f})", ""],
              ["Estimador preferido", "", preferido, ""]]
    tabla = pd.DataFrame(filas, columns=["variable"] + nombres)
    guardar_tabla(tabla, "tabla5_modelo1_principal.csv")
    guardar_tabla(largo, "tabla5b_modelo1_coeficientes.csv")
    return m1, r, preferido, (h, p_h, gl, f_agrupado)


def estimador(nombre):
    return {"Efectos fijos": lambda Y, X: PanelOLS(Y, X, entity_effects=True),
            "Efectos aleatorios": RandomEffects}[nombre]


def ajustar_uno(m, y, xs, preferido):
    X = m[xs].assign(const=1.0)[["const"] + xs]
    return estimador(preferido)(m[y], X).fit(cov_type="kernel", kernel="bartlett", bandwidth=BANDA_DK)


def modelos_robustez(d, r1, m1, preferido):
    xs1 = X_EMPRESA + X_CONTROL
    m2 = muestra(d, "deuda_financiera", xs1)
    r2 = ajustar_uno(m2, "deuda_financiera", xs1, preferido)
    xs3 = [x for x in X_EMPRESA if x != "riesgo_negocio_l1"] + ["volatilidad_l1"] + X_CONTROL
    m3 = muestra(d, "apalancamiento", xs3)
    r3 = ajustar_uno(m3, "apalancamiento", xs3, preferido)
    registrar(f"Modelo 2: {r2.nobs} obs · Modelo 3: {r3.nobs} obs, {m3.index.get_level_values(0).nunique()} emisoras")

    nombres = ["(1) Principal: apalancamiento", "(2) Deuda financiera", "(3) Riesgo de mercado (Yahoo)"]
    orden = X_EMPRESA + ["volatilidad_l1"] + X_CONTROL
    resultados = [r1[preferido], r2, r3]
    filas, largo = tabla_coeficientes(resultados, nombres, orden)
    filas += pie_tabla(resultados, [m1, m2, m3])
    filas += [["Estimador"] + [preferido] * 3]
    guardar_tabla(pd.DataFrame(filas, columns=["variable"] + nombres), "tabla6_modelos_1_2_3.csv")
    guardar_tabla(largo, "tabla6b_modelos_coeficientes.csv")

    # Anexo: el modelo 1 sin holdings (estados individuales con inversiones en subsidiarias)
    m4 = muestra(d[d["holding"] == 0], "apalancamiento", xs1)
    r4 = ajustar_uno(m4, "apalancamiento", xs1, preferido)
    # Anexo: solo emisoras presentes en los 60 trimestres (panel balanceado). Es una prueba de
    # robustez, no la muestra principal, porque dejaría fuera a las emisoras que entran o salen
    # de la bolsa (sesgo de supervivencia).
    completas = d.groupby("rpj").size()
    completas = completas[completas == 60].index
    m5 = muestra(d[d["rpj"].isin(completas)], "apalancamiento", xs1)
    r5 = ajustar_uno(m5, "apalancamiento", xs1, preferido)
    columnas = ["Modelo 1", "Modelo 1 sin holdings", "Modelo 1 solo emisoras con los 60 trimestres"]
    filas, _ = tabla_coeficientes([r1[preferido], r4, r5], columnas, xs1)
    filas += pie_tabla([r1[preferido], r4, r5], [m1, m4, m5])
    guardar_tabla(pd.DataFrame(filas, columns=["variable"] + columnas), "anexo_robustez_holdings_y_balanceado.csv")
    registrar(f"Anexo: sin holdings {r4.nobs} obs · panel balanceado {r5.nobs} obs, {len(completas)} emisoras")
    return (r2, m2), (r3, m3), (r4, m4), (r5, m5)


def contraste_hipotesis(r_pref, r2, r3):
    filas = []
    for v, etiqueta, h, esperado, to, po in HIPOTESIS:
        x = f"{v}_l1"
        coef, p = r_pref.params[x], r_pref.pvalues[x]
        signo = "+" if coef > 0 else "−"
        if p >= NIVEL:
            veredicto, teoria = "No significativa", "ninguna"
        else:
            veredicto = "Se confirma" if signo == esperado else "Signo contrario"
            apoyan = [nombre for nombre, s in [("trade-off", to), ("pecking order", po)] if s == signo]
            teoria = " y ".join(apoyan) if apoyan else "ninguna"
        filas.append([h, etiqueta, esperado, round(coef, 4), round(p, 4), signo, veredicto, teoria,
                      round(r2.params[x], 4), round(r2.pvalues[x], 4)])
    # H6 con la medida de mercado (Modelo 3)
    coef, p = r3.params["volatilidad_l1"], r3.pvalues["volatilidad_l1"]
    signo = "+" if coef > 0 else "−"
    filas.append(["H6 (mercado)", "Volatilidad de la acción", "−", round(coef, 4), round(p, 4), signo,
                  "No significativa" if p >= NIVEL else ("Se confirma" if signo == "−" else "Signo contrario"),
                  "trade-off" if (p < NIVEL and signo == "−") else "ninguna", np.nan, np.nan])
    tabla = pd.DataFrame(filas, columns=["hipotesis", "variable", "signo_esperado", "coeficiente", "p_valor",
                                         "signo_estimado", "resultado", "teoria_que_respalda",
                                         "coef_modelo2_deuda_financiera", "p_valor_modelo2"])
    guardar_tabla(tabla, "tabla7_contraste_hipotesis.csv")
    return tabla


# ── 7. Figuras ────────────────────────────────────────────────────────────
def figura_evolucion(d):
    g = d.groupby("fecha")
    med, p25, p75 = g["apalancamiento"].median(), g["apalancamiento"].quantile(0.25), g["apalancamiento"].quantile(0.75)
    deuda = g["deuda_financiera"].median()
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    fig.subplots_adjust(top=0.80, left=0.08, right=0.86, bottom=0.10)
    ax.axvspan(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31"), color="#f1f3f2", zorder=0)
    ax.text(pd.Timestamp("2020-07-01"), 0.035, "COVID-19", ha="center", fontsize=7.5, color=TEXTO_2)
    ax.fill_between(med.index, p25, p75, color=PRIMARIO, alpha=0.12, linewidth=0)
    ax.plot(med.index, med, color=PRIMARIO, lw=2.4)
    ax.plot(deuda.index, deuda, color=ACENTO, lw=2.4)
    # Rótulos directos al final de cada serie (sin leyenda aparte)
    ax.text(med.index[-1] + pd.Timedelta(days=60), med.iloc[-1], f"Apalancamiento\n(mediana: {med.iloc[-1]:.2f})",
            color=PRIMARIO, va="center", fontsize=8, fontweight="bold")
    ax.text(deuda.index[-1] + pd.Timedelta(days=60), deuda.iloc[-1], f"Deuda financiera\n(mediana: {deuda.iloc[-1]:.2f})",
            color=ACENTO, va="center", fontsize=8, fontweight="bold")
    ax.text(p75.index[2], p75.iloc[2] + 0.02, "Franja: 50 % central de las emisoras", fontsize=7.5, color=TEXTO_2)
    ax.set_ylim(0, max(0.75, p75.max() + 0.08))
    ax.set_ylabel("Proporción del activo total")
    ax.set_xlim(med.index[0], med.index[-1])
    encabezado(fig, f"La emisora típica financia alrededor del {med.mean() * 100:.0f} % de sus activos con terceros",
               f"Apalancamiento (pasivo / activo) y deuda financiera de las emisoras no financieras de la BVL, "
               f"{med.index[0].year}-{med.index[-1].year}, por trimestre")
    guardar_figura(fig, "figura1_evolucion_apalancamiento.png")


def figura_sectores(d):
    orden = d.groupby("sector")["apalancamiento"].median().sort_values().index
    datos = [d.loc[d["sector"] == s, "apalancamiento"].values for s in orden]
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    fig.subplots_adjust(top=0.74, left=0.24, right=0.97, bottom=0.14)
    estilo = dict(widths=0.55, patch_artist=True, showfliers=False, medianprops={"color": PRIMARIO, "lw": 2.6},
                  whiskerprops={"color": GRIS}, capprops={"color": GRIS}, boxprops={"edgecolor": "#b9c4be"})
    try:                                    # matplotlib ≥ 3.10
        caja = ax.boxplot(datos, orientation="horizontal", **estilo)
    except TypeError:                       # versiones anteriores
        caja = ax.boxplot(datos, vert=False, **estilo)
    for parche in caja["boxes"]:
        parche.set_facecolor("#e8f2ec")
    for k, valores in enumerate(datos, start=1):
        ax.text(np.median(valores), k + 0.36, f"{np.median(valores):.2f}", ha="center", fontsize=7.5,
                color=PRIMARIO, fontweight="bold")
    ax.set_yticks(range(1, len(orden) + 1))
    ax.set_yticklabels([f"{SECTORES.get(s, s.capitalize())}  (n = {len(x):,})".replace(",", " ")
                        for s, x in zip(orden, datos)])
    ax.set_xlabel("Apalancamiento = pasivo total / activo total")
    ax.grid(axis="y", visible=False)
    encabezado(fig, "El endeudamiento cambia según la industria",
               "Distribución del apalancamiento por sector de la SMV (caja: 50 % central; línea verde y número: mediana)")
    guardar_figura(fig, "figura2_apalancamiento_por_sector.png")


def figura_coeficientes(r_pref, m1, r2, m2, preferido):
    """Coeficientes estandarizados con IC al 95 % (Driscoll-Kraay): Modelo 1 frente a Modelo 2.
    Misma escala horizontal en ambos paneles para que los efectos sean comparables. A la derecha,
    la teoría que respalda cada hipótesis significativa del Modelo 1."""
    xs = X_EMPRESA + X_CONTROL
    etiquetas = [f"{h[2]} · {h[1]} ({h[3]})" for h in HIPOTESIS] + [f"{c[1]}" for c in CONTROLES]
    y = np.arange(len(xs))[::-1]
    paneles = [("(1) Apalancamiento total", r_pref, m1, "apalancamiento", PRIMARIO),
               ("(2) Deuda financiera", r2, m2, "deuda_financiera", ACENTO)]
    calculos = []
    for titulo, res, m, dep, color in paneles:
        escala = m[xs].std() / m[dep].std()
        calculos.append((titulo, res.params[xs] * escala, 1.96 * res.std_errors[xs] * escala,
                         res.pvalues[xs] < NIVEL, color))
    limite = max((b.abs() + e).max() for _, b, e, _, _ in calculos) * 1.08
    fig, ejes = plt.subplots(1, 2, figsize=(7.6, 4.8), sharey=True, gridspec_kw={"wspace": 0.08})
    fig.subplots_adjust(left=0.27, right=0.84, top=0.80, bottom=0.12)
    for ax, (titulo, beta, error, sig, color) in zip(ejes, calculos):
        ax.axvline(0, color=GRIS, lw=1)
        ax.axhspan(-0.5, len(CONTROLES) - 0.5, color="#f4f6f5", zorder=0)
        ax.errorbar(beta, y, xerr=error, fmt="none", ecolor="#c9cfcc", elinewidth=2.4, capsize=0, zorder=1)
        ax.scatter(beta[sig], y[sig.values], s=78, color=color, edgecolor="white", linewidth=1.6, zorder=3)
        ax.scatter(beta[~sig], y[~sig.values], s=78, facecolor="white", edgecolor=color, linewidth=1.8, zorder=3)
        ax.set_xlim(-limite, limite)
        ax.set_title(titulo, loc="left", fontsize=9.5, color=color)
        ax.set_xlabel("Coef. estandarizado · IC 95 %", fontsize=8)
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="y", length=0)
    ejes[0].set_yticks(y)
    ejes[0].set_yticklabels(etiquetas, fontsize=8)
    # Teoría que respalda cada hipótesis (Modelo 1)
    _, beta1, _, sig1, _ = calculos[0]
    mezcla = matplotlib.transforms.blended_transform_factory(ejes[1].transAxes, ejes[1].transData)
    ejes[1].text(1.04, len(xs) - 0.25, "Teoría que\nrespalda (1)", transform=mezcla, fontsize=7.5,
                 color=TEXTO_2, va="bottom", fontweight="bold")
    for k, (v, _, h, esperado, to, po) in enumerate(HIPOTESIS):
        x = f"{v}_l1"
        fila = y[k]
        if not sig1[x]:
            texto, color = "no signif.", TEXTO_2
        else:
            signo = "+" if beta1[x] > 0 else "−"
            apoyan = [n for n, s in [("Trade-off", to), ("Pecking order", po)] if s == signo]
            texto = " y ".join(apoyan) if apoyan else "ninguna"
            color = PRIMARIO if signo == esperado else CONTRARIO
            if signo != esperado:
                texto = f"✗ {texto}"
        ejes[1].text(1.04, fila, texto, transform=mezcla, fontsize=7.8, va="center", color=color, fontweight="bold")
    def unir(nombres):
        return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]
    suben = [h[1].lower() for h in HIPOTESIS if sig1[f"{h[0]}_l1"] and beta1[f"{h[0]}_l1"] > 0]
    bajan = [h[1].lower() for h in HIPOTESIS if sig1[f"{h[0]}_l1"] and beta1[f"{h[0]}_l1"] < 0]
    partes = ([f"{unir(suben)} {'eleva' if len(suben) == 1 else 'elevan'} la deuda"] if suben else []) + \
             ([f"{unir(bajan)} la {'reduce' if len(bajan) == 1 else 'reducen'}"] if bajan else [])
    titulo = "; ".join(partes) if partes else "Ningún determinante resulta significativo al 5 %"
    encabezado(fig, titulo[0].upper() + titulo[1:],
               f"Efecto de cada determinante · {preferido} con errores de Driscoll-Kraay · punto relleno: "
               "significativo al 5 %; hueco: no significativo · franja gris: controles")
    guardar_figura(fig, "figura4_coeficientes_modelos_1_y_2.png")


def figura_relaciones(m1):
    """Relación entre Y (apalancamiento) y cada X de las hipótesis, dentro de cada emisora.
    Se resta a X y a Y el promedio de su emisora (como hace el modelo de efectos fijos) y se suma
    el promedio general; luego se agrupa X en 20 intervalos de igual número de observaciones y se
    dibuja el promedio de Y en cada uno (diagrama de dispersión por intervalos)."""
    datos = m1.reset_index()
    fig, ejes = plt.subplots(2, 3, figsize=(7.6, 5.8))
    fig.subplots_adjust(hspace=0.62, wspace=0.34, top=0.80, bottom=0.09, left=0.08, right=0.99)
    y_dentro = datos["apalancamiento"] - datos.groupby("rpj")["apalancamiento"].transform("mean") \
        + datos["apalancamiento"].mean()
    for ax, (v, etiqueta, h, esperado, *_ ) in zip(ejes.ravel(), HIPOTESIS):
        x = datos[f"{v}_l1"]
        x_dentro = x - x.groupby(datos["rpj"]).transform("mean") + x.mean()
        intervalos = pd.qcut(x_dentro.rank(method="first"), 20, labels=False)
        puntos = pd.DataFrame({"x": x_dentro, "y": y_dentro}).groupby(intervalos).mean()
        pendiente, intercepto = np.polyfit(x_dentro, y_dentro, 1)
        malla = np.linspace(puntos["x"].min(), puntos["x"].max(), 50)
        signo = "+" if pendiente > 0 else "−"
        coincide = signo == esperado
        ax.plot(malla, intercepto + pendiente * malla, color=ACENTO, lw=2.2, zorder=2)
        ax.scatter(puntos["x"], puntos["y"], s=52, color=PRIMARIO, edgecolor="white", linewidth=1.5, zorder=3)
        ax.set_title(f"{h} · {etiqueta}", loc="left", fontsize=9.2, color=TEXTO)
        ax.text(0.0, 1.015, f"{'✓' if coincide else '✗'} pendiente {signo} · esperado {esperado}",
                transform=ax.transAxes, fontsize=7.3, va="bottom", ha="left",
                color=PRIMARIO if coincide else CONTRARIO, fontweight="bold")
        ax.set_title(f"{h} · {etiqueta}", loc="left", fontsize=9.2, color=TEXTO, pad=14)
        ax.set_xlabel(f"X: {etiqueta.lower()} (t−1)", fontsize=7.5)
        ax.tick_params(labelsize=7)
        ax.margins(y=0.15)
    for ax in ejes[:, 0]:
        ax.set_ylabel("Y: apalancamiento", fontsize=7.5)
    encabezado(fig, "Cada determinante frente al apalancamiento, dentro de cada emisora",
               "Puntos: promedio de Y en 20 intervalos de X · recta: tendencia lineal · relación simple, sin "
               "controlar las demás X (el efecto conjunto se estima en el Modelo 1)")
    guardar_figura(fig, "figura3_relacion_y_con_cada_x.png")


def figura_riesgo(d):
    sub = d[d["submuestra_yahoo"] == 1].groupby("ticker")[["riesgo_negocio", "volatilidad"]].mean().dropna()
    pendiente, intercepto, r, p, _ = stats.linregress(sub["riesgo_negocio"], sub["volatilidad"])
    fig, ax = plt.subplots(figsize=(7.4, 4.4))
    fig.subplots_adjust(top=0.80, left=0.10, right=0.97, bottom=0.13)
    malla = np.linspace(sub["riesgo_negocio"].min(), sub["riesgo_negocio"].max(), 50)
    ax.plot(malla, intercepto + pendiente * malla, color=ACENTO, lw=2.2, zorder=2)
    ax.scatter(sub["riesgo_negocio"], sub["volatilidad"], s=130, color=PRIMARIO, edgecolor="white",
               linewidth=2, zorder=3)
    # Se rotulan las emisoras fuera del grupo compacto de baja volatilidad y bajo riesgo
    rotuladas = sub[(sub["volatilidad"] > 0.30) | (sub["riesgo_negocio"] > 0.02)]
    for ticker, fila in rotuladas.iterrows():
        vecina_arriba = ((rotuladas["riesgo_negocio"] - fila["riesgo_negocio"]).abs() < 0.004) & \
                        (rotuladas["volatilidad"] - fila["volatilidad"]).between(0.001, 0.03)
        desplazamiento = (8, -12) if vecina_arriba.any() else (8, -3)
        ax.annotate(ticker.replace(".LM", ""), (fila["riesgo_negocio"], fila["volatilidad"]),
                    xytext=desplazamiento, textcoords="offset points", fontsize=7, color=TEXTO_2)
    ax.text(0.98, 0.04, f"Correlación r = {r:.2f} (p = {p:.3f}) · sin rótulo: riesgo ≤ 0.02 y volatilidad ≤ 0.30",
            transform=ax.transAxes, ha="right", fontsize=7.3, color=TEXTO_2)
    ax.set_xlabel("X: riesgo del negocio (desviación estándar del ROA, SMV)")
    ax.set_ylabel("Y: volatilidad anual de la acción (Yahoo Finance)")
    encabezado(fig, "El riesgo contable y el riesgo de mercado van de la mano" if (r > 0.3 and p < 0.05)
               else "Riesgo contable y riesgo de mercado en las 20 emisoras líquidas",
               "Promedio 2011-2025 de las 20 emisoras con acciones líquidas · recta dorada: tendencia lineal")
    guardar_figura(fig, "figura5_riesgo_contable_vs_mercado.png")
    return r, p


# ── 8. Programa principal ─────────────────────────────────────────────────
def main():
    CARPETA_SALIDAS.mkdir(exist_ok=True)
    registrar("Inicio de 04_analisis.py")
    d = cargar_panel()

    faltantes, balance = faltantes_y_balance(d)
    desc = descriptivos(d)
    m1, r1, preferido, pruebas = modelo_principal(d)
    corr, vif = correlaciones_y_vif(m1)
    raiz = raiz_unitaria(d)
    (r2, m2), (r3, m3), (r4, m4), (r5, m5) = modelos_robustez(d, r1, m1, preferido)
    contraste = contraste_hipotesis(r1[preferido], r2, r3)

    figura_evolucion(d)
    figura_sectores(d)
    figura_coeficientes(r1[preferido], m1, r2, m2, preferido)
    figura_relaciones(m1)
    r_riesgo, p_riesgo = figura_riesgo(d)

    with open(CARPETA_SALIDAS / "resultados_modelos.txt", "w", encoding="utf-8") as salida:
        for titulo, res in [("MODELO 1 · MCO agrupado", r1["MCO agrupado"]), ("MODELO 1 · Efectos fijos", r1["Efectos fijos"]),
                            ("MODELO 1 · Efectos aleatorios", r1["Efectos aleatorios"]), ("MODELO 2 · Deuda financiera", r2),
                            ("MODELO 3 · Riesgo de mercado (Yahoo)", r3), ("ANEXO · Modelo 1 sin holdings", r4),
                            ("ANEXO · Modelo 1 con panel balanceado (60 trimestres)", r5)]:
            salida.write(f"{'=' * 90}\n{titulo}\n{'=' * 90}\n{res.summary}\n\n")
        h, p_h, gl, f_agr = pruebas
        salida.write(f"Hausman χ²({gl}) = {h:.4f}, p = {p_h:.6f} → {preferido}\n")
        salida.write(f"F de efectos fijos = {f_agr.stat:.4f}, p = {f_agr.pval:.6f}\n")
        salida.write(f"Correlación riesgo contable - volatilidad (20 emisoras): r = {r_riesgo:.4f}, p = {p_riesgo:.6f}\n")
    registrar("resultados completos guardados: salidas/resultados_modelos.txt")

    pd.set_option("display.width", 220)
    print("\n── Contraste de hipótesis (Modelo 1, " + preferido + ")")
    print(contraste.to_string(index=False))
    print("\n── Faltantes"); print(faltantes.to_string(index=False))
    print("\n── Balance del panel"); print(balance.to_string(index=False))
    print("\n── VIF"); print(vif.to_string(index=False))
    print("\n── Raíz unitaria"); print(raiz.to_string(index=False))
    registrar("Fin de 04_analisis.py")


if __name__ == "__main__":
    main()
