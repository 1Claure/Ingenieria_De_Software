"""Dashboard de estimación de agua inyectada en fracturas hidráulicas.

Fase 6 (despliegue) del TP. Ejecutar desde la raíz del proyecto con:

	streamlit run app.py

Requiere haber corrido antes la fase 3 (data/df_limpio.csv) y la fase 4
(artifacts/), porque consume los mismos datos y artefactos que el modelado.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from sklearn.metrics import mean_absolute_error

from journey_component import render_journey

from comun import (
	ENTRADAS_CATEGORICAS,
	ENTRADAS_NUMERICAS,
	OBJETIVO,
	RUTA_ARTEFACTOS,
	RUTA_DATOS_LIMPIOS,
	entrenar_modelo_final,
	importar_modelos,
)

RUTA_HERO = Path(__file__).resolve().parent / "assets" / "ypf-vaca-muerta.webp"

AZUL = "#24405E"
ARENA = "#C0622F"
VERDE = "#6B7F4E"


# ---------------------------------------------------------------------------
# Lógica pura (sin dependencias de la interfaz, para poder probarla aparte)
# ---------------------------------------------------------------------------

def fmt(valor: float, decimales: int = 0) -> str:
	"""Formato numérico en castellano: miles con punto y decimal con coma."""
	texto = f"{valor:,.{decimales}f}"
	return texto.replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")


def estimar_agua(modelo, referencia, entradas: pd.DataFrame) -> dict:
	"""Devuelve la estimación del modelo y la referencia para un caso."""
	return {
		"estimado_m3": float(modelo.predict(entradas)[0]),
		"referencia_m3": float(referencia.predict(entradas)[0]),
	}


def rangos_historicos(df: pd.DataFrame) -> pd.DataFrame:
	"""Resumen de la población de estudio para contextualizar cada estimación."""
	return df[ENTRADAS_NUMERICAS + [OBJETIVO]].agg(["min", "median", "max"]).T


def casos_similares(df: pd.DataFrame, longitud: float, cantidad: float, tipo: str, k: int = 5) -> pd.DataFrame:
	"""Los k registros históricos más cercanos al caso cargado.

	La distancia se calcula sobre las variables de entrada estandarizadas, con
	una penalización fija cuando el tipo de terminación no coincide.
	"""
	escala_long = df["longitud_rama_horizontal_m"].std()
	escala_cant = df["cantidad_fracturas"].std()
	d_long = (df["longitud_rama_horizontal_m"] - longitud) / escala_long
	d_cant = (df["cantidad_fracturas"] - cantidad) / escala_cant
	d_tipo = (df["tipo_terminacion"].fillna("") != tipo).astype(float)
	distancia = np.sqrt(d_long**2 + d_cant**2 + d_tipo**2)

	columnas = [
		"id_base_fractura_adjiv",
		"fecha_inicio_fractura",
		"tipo_terminacion",
		"longitud_rama_horizontal_m",
		"cantidad_fracturas",
		OBJETIVO,
	]
	similares = df.loc[distancia.nsmallest(k).index, columnas].copy()
	similares.insert(0, "distancia", distancia.loc[similares.index].round(3))
	return similares.reset_index(drop=True)


def figura_panorama(df: pd.DataFrame, similares: pd.DataFrame, cantidad: float, longitud: float, estimado: float):
	"""Ubica el caso cargado dentro del histórico de la base."""
	fig, ejes = plt.subplots(1, 2, figsize=(11, 4.2))
	paneles = [
		("cantidad_fracturas", "Etapas de fractura", cantidad),
		("longitud_rama_horizontal_m", "Longitud de la rama horizontal (m)", longitud),
	]
	for eje, (variable, etiqueta, valor) in zip(ejes, paneles):
		eje.scatter(df[variable], df[OBJETIVO], s=12, color="#9AAEC2", alpha=0.55, label="Histórico")
		eje.scatter(similares[variable], similares[OBJETIVO], s=60, facecolors="none", edgecolors=VERDE, linewidths=2, label="Casos similares")
		eje.scatter([valor], [estimado], s=180, marker="*", color=ARENA, zorder=5, label="Tu caso (estimado)")
		eje.set_xlabel(etiqueta, fontsize=9)
		eje.set_ylabel("Agua inyectada (m³)", fontsize=9)
		eje.grid(alpha=0.25, linestyle=":")
	ejes[0].legend(loc="upper left", fontsize=8, frameon=False)
	fig.tight_layout()
	return fig


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Agua de fractura — cuenca Neuquina", layout="wide")

# La interfaz ya está en español. Evitamos que Chrome Translate reemplace
# nodos del DOM que React necesita durante los reruns (removeChild/insertBefore).
# Script estático: no incorpora datos del usuario ni código externo.
st.html(
	"""
	<script>
	(() => {
		const root = document.documentElement;
		root.lang = "es";
		root.setAttribute("translate", "no");
		root.classList.add("notranslate");
		if (!document.head.querySelector('meta[name="google"][content="notranslate"]')) {
			const meta = document.createElement("meta");
			meta.name = "google";
			meta.content = "notranslate";
			document.head.appendChild(meta);
		}
	})();
	</script>
	""",
	unsafe_allow_javascript=True,
)

st.markdown(
	f"""
	<style>
	.stApp {{ background-color: #FAF6F0; }}
	h1, h2, h3 {{ color: {AZUL}; font-family: "Segoe UI", sans-serif; }}
	.block-container {{ max-width: none; padding: 0; }}
	[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{ gap: 0; }}
	header[data-testid="stHeader"] {{ display: none; }}
	.st-key-inicio {{ min-height: 100svh; }}
	.st-key-estimador {{ width: min(1256px, 100%); margin: 0 auto; padding: 44px clamp(20px, 5vw, 64px) 64px; }}
	div[data-testid="stSidebar"], section[data-testid="stSidebar"] {{ background-color: #20364E; }}
	div[data-testid="stSidebar"] *, section[data-testid="stSidebar"] * {{ color: #F2EDE6 !important; }}
	.hero-titulo {{ font-size: 2.6rem; font-weight: 700; color: {AZUL}; margin-bottom: 0; }}
	.hero-bajada {{ font-size: 1.15rem; color: #5A6B7B; margin-top: 0.2rem; }}
	.tarjeta {{ background: #FFFFFF; border-radius: 14px; padding: 1.1rem 1.3rem;
	           border-left: 5px solid {ARENA}; box-shadow: 0 2px 10px rgba(36,64,94,0.08); }}
	.tarjeta h3 {{ margin-top: 0; }}
	.estimado {{ background: linear-gradient(135deg, #24405E 0%, #35618B 100%); border-radius: 16px;
	           padding: 1.4rem 1.6rem; color: #FFFFFF; }}
	.estimado .etiqueta {{ font-size: 0.85rem; letter-spacing: 0.12em; text-transform: uppercase; opacity: 0.85; }}
	.estimado .numero {{ font-size: 3rem; font-weight: 700; line-height: 1.1; }}
	.paso {{ text-align: center; padding: 1.2rem 1rem; background: #FFFFFF; border-radius: 14px;
	        box-shadow: 0 2px 10px rgba(36,64,94,0.08); }}
	.paso .numero-paso {{ width: 2.4rem; height: 2.4rem; border-radius: 50%; background: {ARENA};
	                   color: #FFFFFF; font-weight: 700; font-size: 1.2rem; line-height: 2.4rem; margin: 0 auto 0.6rem; }}
	.dato {{ text-align: center; padding: 0.9rem 0.5rem; }}
	.dato .valor {{ font-size: 1.9rem; font-weight: 700; color: {AZUL}; }}
	.dato .rotulo {{ font-size: 0.85rem; color: #6B7A88; }}
	div[data-testid="stWidgetLabel"] p {{ min-height: 1.5em; margin-bottom: 0; }}
	.pie {{ color: #8A97A3; font-size: 0.82rem; margin-top: 2rem; }}
	/* Presentation only: native widgets and all calculations stay unchanged. */
	.st-key-estimador {{
		width: min(1280px, 100%); padding: 56px clamp(24px, 5vw, 64px) 72px;
		color: #233c49; font-family: "Segoe UI", Arial, sans-serif;
	}}
	.st-key-estimador [data-testid="stVerticalBlock"] {{ gap: 1rem; }}
	.st-key-estimador > [data-testid="stVerticalBlock"] {{ gap: 1rem; }}
	.st-key-estimador [data-testid="stMarkdownContainer"] p {{ line-height: 1.75; }}
	.st-key-estimador [data-testid="stCaptionContainer"] p {{ color: #687a82; font-size: .8rem; line-height: 1.75; }}
	.st-key-estimador hr {{ border-color: #d4d8d4; margin: 0 0 12px; }}
	.st-key-estimador .hero-titulo {{
		font-size: clamp(32px, 3.3vw, 48px); line-height: 1.12; letter-spacing: -.045em;
		font-weight: 500; color: #17313f; margin: 18px 0 0;
	}}
	.st-key-estimador .hero-bajada {{ font-size: 1.05rem; line-height: 1.65; color: #5c717b; margin: 0 0 6px; }}
	.st-key-estimador h3 {{
		font-size: clamp(21px, 2vw, 26px); font-weight: 550; line-height: 1.3;
		letter-spacing: -.025em; color: #183543; border-top: 1px solid #d4d8d4;
		padding: 28px 0 0; margin: 24px 0 5px;
	}}
	.st-key-estimador [data-testid="stAlert"] {{ background: transparent; border: 0; padding: 0; }}
	.st-key-estimador [data-testid="stAlertContainer"] {{
		background: #edf0ed; border: 1px solid #d7dfda; border-left: 3px solid #82998b;
		border-radius: 3px; padding: 16px 20px; color: #405b64;
	}}
	.st-key-estimador [data-testid="stAlert"] p {{ font-size: .875rem; color: inherit; line-height: 1.7; }}
	.st-key-estimador [data-testid="stAlertContentInfo"] {{ color: #405b64; }}
	.st-key-estimador [data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{ background: #faf0dd; border-left-color: #b87537; }}
	.st-key-estimador [data-testid="stHorizontalBlock"] {{ gap: 24px; }}
	.st-key-estimador [data-testid="stWidgetLabel"] p {{ font-size: .83rem; font-weight: 550; color: #324e5a; padding-bottom: 6px; }}
	.st-key-estimador [data-testid="stNumberInputContainer"],
	.st-key-estimador [data-testid="stSelectbox"] .react-aria-ComboBox > [role="group"],
	.st-key-estimador [data-baseweb="select"] > div {{
		background: #fffefa; border: 1px solid #bdc9cb; border-radius: 4px;
		min-height: 54px; box-shadow: 0 2px 3px #17313f03;
	}}
	.st-key-estimador [data-testid="stNumberInputContainer"]:focus-within,
	.st-key-estimador [data-testid="stSelectbox"] .react-aria-ComboBox > [role="group"]:focus-within,
	.st-key-estimador [data-baseweb="select"]:focus-within > div {{
		border-color: #a65b38; box-shadow: 0 0 0 2px #a65b381b;
	}}
	.st-key-estimador [data-testid="stNumberInput"] input {{
		font-size: 1.13rem; font-weight: 500; color: #193847; font-variant-numeric: tabular-nums;
		padding-left: 16px; min-height: 52px;
	}}
	.st-key-estimador [data-testid="stNumberInput"] button {{ color: #607782; background: transparent; }}
	.st-key-estimador [data-testid="stNumberInput"] button:hover {{ background: #edf0ec; color: #183543; }}
	.st-key-estimador [data-baseweb="select"] {{ font-size: .97rem; color: #193847; }}
	.st-key-estimador [data-testid="stSelectbox"] input {{ min-height: 52px; font-size: 1rem; padding-left: 16px; background: transparent; color: #193847; }}
	.st-key-estimador .estimado {{
		background: #163443; border: 1px solid #163443; border-top: 3px solid #ad7452;
		border-radius: 4px; padding: 27px 30px 30px; min-height: 155px; color: #faf5e9;
	}}
	.st-key-estimador .estimado .etiqueta {{ font-size: .7rem; letter-spacing: .12em; opacity: 1; color: #cbd7d8; line-height: 1.65; }}
	.st-key-estimador .estimado .numero {{
		font-size: clamp(38px, 3.6vw, 52px); font-weight: 450; letter-spacing: -.04em;
		font-variant-numeric: tabular-nums; line-height: 1.2; margin-top: 12px;
	}}
	.st-key-estimador [data-testid="stMetric"] {{ padding: 8px 0 14px 20px; border-left: 1px solid #cbd5d3; }}
	.st-key-estimador [data-testid="stMetricLabel"] {{ color: #627680; font-size: .78rem; line-height: 1.5; }}
	.st-key-estimador [data-testid="stMetricValue"] {{ color: #203e4b; font-size: clamp(26px, 2.4vw, 34px); font-weight: 450; letter-spacing: -.035em; font-variant-numeric: tabular-nums; }}
	.st-key-estimador [data-testid="stDataFrame"] {{ border: 1px solid #cbd4d3; border-radius: 4px; overflow: visible; background: #fffefa; }}
	.st-key-estimador [data-testid="stImage"] {{ border: 1px solid #d8ddda; border-radius: 4px; padding: 18px 12px 12px; background: #fff; }}
	.st-key-estimador [data-testid="stExpander"] {{ margin-top: 14px; }}
	.st-key-estimador [data-testid="stExpander"] details {{ border: 1px solid #cbd4d0; border-radius: 4px; background: #f1f1e9; }}
	.st-key-estimador [data-testid="stExpander"] summary {{ padding: 17px 20px; color: #203e4b; }}
	.st-key-estimador [data-testid="stExpander"] summary p {{ font-weight: 550; font-size: .9rem; }}
	.st-key-estimador [data-testid="stExpanderDetails"] {{ padding: 4px 22px 20px; }}
	.st-key-estimador .pie {{ font-size: .75rem; color: #6d7e85; border-top: 1px solid #d4d8d4; padding-top: 23px; margin-top: 28px; line-height: 1.85; }}
	@media (max-width: 760px) {{
		.st-key-estimador {{ padding: 34px 24px 46px; }}
		.st-key-estimador .hero-titulo {{ font-size: 34px; margin-top: 10px; }}
		.st-key-estimador .hero-bajada {{ font-size: 1rem; }}
		.st-key-estimador h3 {{ margin-top: 16px; padding-top: 24px; }}
		.st-key-estimador [data-testid="stHorizontalBlock"] {{ gap: 18px; }}
		.st-key-estimador .estimado {{ padding: 24px; min-height: 144px; }}
		.st-key-estimador .estimado .numero {{ font-size: 40px; }}
		.st-key-estimador [data-testid="stMetric"] {{ padding: 8px 0 10px 16px; }}
		.st-key-estimador [data-testid="stImage"] {{ padding: 10px 4px 6px; }}
	}}
	</style>
	""",
	unsafe_allow_html=True,
)


@st.cache_resource
def cargar_modelos():
	"""Carga los artefactos de la fase 4; si no se deserializan, reentrena.

	Los `.joblib` son pickles de Python, que no son compatibles entre versiones
	distintas del intérprete o de scikit-learn. Ante ese caso se reconstruye el
	mismo modelo desde `data/df_limpio.csv`, que sí es portable.
	"""
	try:
		return (*importar_modelos("modelo", "referencia", "nombre_modelo", "X_test", "y_test"), False)
	except Exception:
		return (*entrenar_modelo_final(), True)


@st.cache_data
def cargar_datos():
	datos = pd.read_csv(RUTA_DATOS_LIMPIOS)
	datos["fecha_inicio_fractura"] = pd.to_datetime(datos["fecha_inicio_fractura"], errors="coerce")
	return datos


def hay_datos():
	return RUTA_DATOS_LIMPIOS.is_file()


def render_inicio():
	render_journey(RUTA_HERO)


def render_estimador():
	st.markdown('<div class="hero-titulo">Estimador de agua inyectada</div>', unsafe_allow_html=True)
	st.markdown(
		'<div class="hero-bajada">Cargá las características de la operación y comparalas con el histórico.</div>',
		unsafe_allow_html=True,
	)

	if not hay_datos():
		st.error(
			"Falta `data/df_limpio.csv`. Ejecutá primero la fase 3 (`fase_3_data_preparation.ipynb`) "
			"desde la raíz del proyecto."
		)
		st.stop()

	modelo, referencia, nombre_modelo, X_test, y_test, reconstruido = cargar_modelos()
	if reconstruido:
		st.info(
			"El modelo guardado no se pudo cargar en este entorno (versiones distintas de Python o "
			"scikit-learn), así que se reentrenó el mismo modelo con los datos del repositorio."
		)
	df = cargar_datos()

	st.markdown("### 1. Características de la operación")
	etiquetas = {
		"longitud_rama_horizontal_m": "Longitud de la rama horizontal (m)",
		"cantidad_fracturas": "Cantidad de etapas de fractura",
	}
	unidades = {"longitud_rama_horizontal_m": "m", "cantidad_fracturas": "etapas"}
	columnas = st.columns(len(ENTRADAS_NUMERICAS) + 1)
	entradas = {}
	for col_ui, variable in zip(columnas[: len(ENTRADAS_NUMERICAS)], ENTRADAS_NUMERICAS):
		minimo = float(df[variable].min())
		maximo = float(df[variable].max())
		entradas[variable] = col_ui.number_input(
			etiquetas[variable],
			min_value=0.0,
			value=float(df[variable].median()),
			step=1.0,
		)
		col_ui.caption(f"Histórico: {fmt(minimo)} a {fmt(maximo)} {unidades[variable]}")

	categorias = sorted(df["tipo_terminacion"].dropna().unique())
	mas_frecuente = df["tipo_terminacion"].mode().iloc[0]
	entradas["tipo_terminacion"] = columnas[-1].selectbox(
		"Tipo de terminación", categorias, index=categorias.index(mas_frecuente)
	)
	columnas[-1].caption(f"Histórico: {len(categorias)} categorías")

	caso = pd.DataFrame([entradas])[ENTRADAS_NUMERICAS + ENTRADAS_CATEGORICAS]
	fuera_de_rango = [v for v in ENTRADAS_NUMERICAS if not (df[v].min() <= entradas[v] <= df[v].max())]
	if fuera_de_rango:
		st.warning(
			"Estos valores están fuera de los antecedentes observados: "
			f"{', '.join(fuera_de_rango)}. La estimación allí es una extrapolación y es poco confiable."
		)

	resultado = estimar_agua(modelo, referencia, caso)
	similares = casos_similares(
		df, entradas["longitud_rama_horizontal_m"], entradas["cantidad_fracturas"], entradas["tipo_terminacion"]
	)

	st.markdown("### 2. Estimación")
	izq, der = st.columns([1, 1])
	with izq:
		st.markdown(
			f"""
			<div class="estimado">
			<div class="etiqueta">Agua estimada para tu operación</div>
			<div class="numero">{fmt(resultado['estimado_m3'])} m³</div>
			</div>
			""",
			unsafe_allow_html=True,
		)
	with der:
		mediana_similares = float(similares[OBJETIVO].median())
		diferencia = 100 * (resultado["estimado_m3"] - mediana_similares) / mediana_similares
		c1, c2 = st.columns(2)
		c1.metric("Referencia (mediana histórica)", f"{fmt(resultado['referencia_m3'])} m³")
		c2.metric("Mediana de casos similares", f"{fmt(mediana_similares)} m³")
		st.markdown(
			f"Tu estimado se ubica un **{fmt(diferencia, 1)}%** respecto de la mediana de los "
			f"{len(similares)} casos históricos más parecidos."
		)

	st.markdown("### 3. Contraste con la base histórica")
	st.markdown(
		"Los registros más cercanos según las variables cargadas (distancia estandarizada; "
		"el tipo de terminación distinto suma penalización)."
	)
	mostrar = similares.rename(
		columns={
			"id_base_fractura_adjiv": "id",
			"fecha_inicio_fractura": "fecha",
			"tipo_terminacion": "terminación",
			"longitud_rama_horizontal_m": "longitud (m)",
			"cantidad_fracturas": "etapas",
			OBJETIVO: "agua observada (m³)",
			"distancia": "distancia",
		}
	)
	mostrar["fecha"] = mostrar["fecha"].dt.strftime("%d/%m/%Y")
	for columna in ("distancia", "longitud (m)", "etapas", "agua observada (m³)"):
		decimales = 3 if columna == "distancia" else 0
		mostrar[columna] = mostrar[columna].map(lambda x: fmt(x, decimales))
	st.dataframe(mostrar, width="stretch", hide_index=True)

	cercano = similares.iloc[0]
	st.markdown(
		f"**El más cercano:** la operación **#{int(cercano['id_base_fractura_adjiv'])}** "
		f"({cercano['fecha_inicio_fractura']:%d/%m/%Y}, {cercano['tipo_terminacion']}, "
		f"{fmt(cercano['longitud_rama_horizontal_m'])} m, {int(cercano['cantidad_fracturas'])} etapas) "
		f"registró **{fmt(cercano[OBJETIVO])} m³** de agua. Tu estimado difiere un "
		f"{fmt(100 * (resultado['estimado_m3'] - cercano[OBJETIVO]) / cercano[OBJETIVO], 1)}% de ese registro."
	)

	st.markdown("### 4. Panorama del histórico")
	figura = figura_panorama(df, similares, entradas["cantidad_fracturas"], entradas["longitud_rama_horizontal_m"], resultado["estimado_m3"])
	try:
		st.pyplot(figura)
	finally:
		plt.close(figura)
	st.caption(
		"Cada punto es una operación registrada. Los círculos verdes son los casos similares "
		"y la estrella, tu caso con la estimación obtenida."
	)

	with st.expander("Sobre el modelo y sus límites"):
		mae_test = float(mean_absolute_error(y_test, modelo.predict(X_test)))
		st.write(
			f"Modelo **{nombre_modelo}** elegido por comparación con validación cruzada temporal "
			f"sobre {len(df):,} operaciones. En la prueba temporal su error absoluto promedio fue de "
			f"**{fmt(mae_test)} m³**. Las estimaciones sirven como referencia de antecedentes; no "
			"reemplazan los cálculos de ingeniería ni la evaluación especializada. El modelo no se "
			"generaliza a pozos verticales, tight ni otras cuencas, y una estimación lejos de los "
			"antecedentes históricos es poco confiable."
		)
	st.markdown(
		f'<div class="pie">Fuente: Secretaría de Energía de la Nación — Adjunto IV, fractura de pozos '
		f"de hidrocarburos. Modelo {nombre_modelo} sobre {len(df):,} operaciones shale de la cuenca Neuquina.</div>",
		unsafe_allow_html=True,
	)


with st.container(key="inicio"):
	render_inicio()

with st.container(key="estimador"):
	st.html('<div id="estimador" tabindex="-1" style="scroll-margin-top:80px"></div>')
	st.markdown("---")
	st.markdown("**Estimación de agua en fracturas hidráulicas**")
	st.caption(
		"Reservorios shale de la cuenca Neuquina. "
		"Referencia basada en antecedentes históricos: no reemplaza los cálculos de ingeniería."
	)
	render_estimador()
