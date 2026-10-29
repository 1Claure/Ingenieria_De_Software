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

from comun import (
	ENTRADAS_CATEGORICAS,
	ENTRADAS_NUMERICAS,
	OBJETIVO,
	RUTA_ARTEFACTOS,
	RUTA_DATOS_LIMPIOS,
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

st.markdown(
	f"""
	<style>
	.stApp {{ background-color: #FAF6F0; }}
	h1, h2, h3 {{ color: {AZUL}; font-family: "Segoe UI", sans-serif; }}
	.block-container {{ padding-top: 1.5rem; }}
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
	.pie {{ color: #8A97A3; font-size: 0.82rem; margin-top: 2rem; }}
	</style>
	""",
	unsafe_allow_html=True,
)


@st.cache_resource
def cargar_modelos():
	return importar_modelos("modelo", "referencia", "nombre_modelo", "X_test", "y_test")


@st.cache_data
def cargar_datos():
	datos = pd.read_csv(RUTA_DATOS_LIMPIOS)
	datos["fecha_inicio_fractura"] = pd.to_datetime(datos["fecha_inicio_fractura"], errors="coerce")
	return datos


def hay_datos():
	return RUTA_DATOS_LIMPIOS.is_file() and RUTA_ARTEFACTOS.is_dir()


pagina = st.sidebar.radio("Navegación", ["Inicio", "Estimador"], label_visibility="collapsed")
st.sidebar.markdown(
	"--- \n**Estimación de agua en fracturas hidráulicas**  \nReservorios shale de la "
	"cuenca Neuquina.  \nReferencia basada en antecedentes históricos: no reemplaza los "
	"cálculos de ingeniería."
)


def render_inicio():
	st.markdown('<div class="hero-titulo">Estimar el agua de una fractura antes de ejecutarla</div>', unsafe_allow_html=True)
	st.markdown(
		'<div class="hero-bajada">Una referencia objetiva, a partir de 2.632 operaciones registradas en la cuenca Neuquina.</div>',
		unsafe_allow_html=True,
	)
	st.image(str(RUTA_HERO), use_column_width=True)
	st.caption(
		"Operación de fractura hidráulica en Vaca Muerta. Foto de prensa (YPF) usada solo con fines educativos en este trabajo práctico."
	)

	st.markdown("## ¿Por qué importa esta estimación?")
	izq, der = st.columns(2)
	with izq:
		st.markdown(
			f"""
			<div class="tarjeta">
			<h3>El agua es el recurso que hay que planificar</h3>
			Cada operación de fractura inyecta decenas de miles de m³ de agua. Estimar ese
			volumen <b>antes</b> de la operación permite dimensionar el abastecimiento, el
			almacenamiento y el transporte desde el registro histórico, y discutir el
			presupuesto con un número a la vista.
			</div>
			""",
			unsafe_allow_html=True,
		)
		st.markdown(
			f"""
			<div class="tarjeta" style="margin-top: 1rem; border-left-color: {VERDE};">
			<h3>Contrastar contra casos reales</h3>
			La estimación viene acompañada de los <b>casos históricos más parecidos</b>:
			pozos con longitud, etapas y terminación comparables. Sirve para detectar
			desvíos temprano: si el caso se aleja de todos los antecedentes, algo hay que revisar.
			</div>
			""",
			unsafe_allow_html=True,
		)
	with der:
		st.markdown(
			f"""
			<div class="tarjeta" style="border-left-color: {AZUL};">
			<h3>Transparencia sobre los límites</h3>
			La solución no calcula la fractura: expresa <b>qué muestran los datos</b> y hasta
			dónde alcanza. Cuando un caso se sale del rango histórico lo dice explícitamente,
			porque una estimación lejos de los antecedentes es poco confiable.
			</div>
			""",
			unsafe_allow_html=True,
		)
		st.markdown(
			f"""
			<div class="tarjeta" style="margin-top: 1rem; border-left-color: #7A5C3E;">
			<h3>Una herramienta de consulta simple</h3>
			El resultado se lee en metros cúbicos, contra una referencia ingenua (la mediana
			histórica) y contra el rango observado. Sin cajas negras: el modelo elegido es una
			regresión lineal cuyos términos se pueden explicar uno por uno.
			</div>
			""",
			unsafe_allow_html=True,
		)

	st.markdown("## Cómo funciona")
	p1, p2, p3 = st.columns(3)
	with p1:
		st.markdown(
			'<div class="paso"><div class="numero-paso">1</div><b>Cargás el caso</b><br/>'
			"Longitud de la rama, etapas y tipo de terminación del pozo.</div>",
			unsafe_allow_html=True,
		)
	with p2:
		st.markdown(
			'<div class="paso"><div class="numero-paso">2</div><b>El modelo estima</b><br/>'
			"Un modelo entrenado con datos públicos estima el agua de la operación.</div>",
			unsafe_allow_html=True,
		)
	with p3:
		st.markdown(
			'<div class="paso"><div class="numero-paso">3</div><b>Lo contrastás</b><br/>'
			"Ves los casos históricos más parecidos y dónde se ubica el caso.</div>",
			unsafe_allow_html=True,
		)

	st.markdown("---")
	c1, c2, c3, c4 = st.columns(4)
	for col, valor, rotulo in zip(
		(c1, c2, c3, c4),
		("2.632", "2011–2026", "8.017 m³", "0,70"),
		("operaciones analizadas", "período del dataset", "error promedio (MAE)", "R² en la prueba temporal"),
	):
		col.markdown(f'<div class="dato"><div class="valor">{valor}</div><div class="rotulo">{rotulo}</div></div>', unsafe_allow_html=True)

	st.markdown(
		'<div class="pie">Proyecto académico — Ingeniería de Software, Ciclo de Complementación '
		"de la Licenciatura en Ciencia de Datos. Datos públicos de la Secretaría de Energía "
		"(Adjunto IV — fractura de pozos de hidrocarburos).</div>",
		unsafe_allow_html=True,
	)


def render_estimador():
	st.markdown('<div class="hero-titulo">Estimador de agua inyectada</div>', unsafe_allow_html=True)
	st.markdown(
		'<div class="hero-bajada">Cargá las características de la operación y comparalas con el histórico.</div>',
		unsafe_allow_html=True,
	)

	if not hay_datos():
		st.error(
			"Faltan datos o artefactos. Ejecutá primero la fase 3 (`fase_3_data_preparation.ipynb`) "
			"y la fase 4 (`fase_4_modeling.ipynb`) desde la raíz del proyecto."
		)
		st.stop()

	modelo, referencia, nombre_modelo, X_test, y_test = cargar_modelos()
	df = cargar_datos()

	st.markdown("### 1. Características de la operación")
	etiquetas = {
		"longitud_rama_horizontal_m": "Longitud de la rama horizontal (m)",
		"cantidad_fracturas": "Cantidad de etapas de fractura",
	}
	columnas = st.columns(len(ENTRADAS_NUMERICAS) + 1)
	entradas = {}
	for col_ui, variable in zip(columnas[: len(ENTRADAS_NUMERICAS)], ENTRADAS_NUMERICAS):
		minimo = float(df[variable].min())
		maximo = float(df[variable].max())
		entradas[variable] = col_ui.number_input(
			f"{etiquetas[variable]} — histórico: {fmt(minimo)} a {fmt(maximo)}",
			min_value=0.0,
			value=float(df[variable].median()),
			step=1.0,
		)

	categorias = sorted(df["tipo_terminacion"].dropna().unique())
	mas_frecuente = df["tipo_terminacion"].mode().iloc[0]
	entradas["tipo_terminacion"] = columnas[-1].selectbox(
		"Tipo de terminación", categorias, index=categorias.index(mas_frecuente)
	)

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
	st.dataframe(mostrar, use_container_width=True, hide_index=True)

	cercano = similares.iloc[0]
	st.markdown(
		f"**El más cercano:** la operación **#{int(cercano['id_base_fractura_adjiv'])}** "
		f"({cercano['fecha_inicio_fractura']:%d/%m/%Y}, {cercano['tipo_terminacion']}, "
		f"{fmt(cercano['longitud_rama_horizontal_m'])} m, {int(cercano['cantidad_fracturas'])} etapas) "
		f"registró **{fmt(cercano[OBJETIVO])} m³** de agua. Tu estimado difiere un "
		f"{fmt(100 * (resultado['estimado_m3'] - cercano[OBJETIVO]) / cercano[OBJETIVO], 1)}% de ese registro."
	)

	st.markdown("### 4. Panorama del histórico")
	st.pyplot(figura_panorama(df, similares, entradas["cantidad_fracturas"], entradas["longitud_rama_horizontal_m"], resultado["estimado_m3"]))
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


if pagina == "Inicio":
	render_inicio()
else:
	render_estimador()
