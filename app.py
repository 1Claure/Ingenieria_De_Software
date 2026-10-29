"""Dashboard de estimación de agua inyectada en fracturas hidráulicas.

Fase 6 (despliegue) del TP. Ejecutar desde la raíz del proyecto con:

	streamlit run app.py

Requiere haber corrido antes la fase 3 (data/df_limpio.csv) y la fase 4
(artifacts/), porque consume los mismos datos y artefactos que el modelado.
"""

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


def estimar_agua(modelo, referencia, entradas: pd.DataFrame) -> dict:
	"""Devuelve la estimación del modelo y la referencia para un caso."""
	return {
		"estimado_m3": float(modelo.predict(entradas)[0]),
		"referencia_m3": float(referencia.predict(entradas)[0]),
	}


def rangos_historicos(df: pd.DataFrame) -> pd.DataFrame:
	"""Resumen de la población de estudio para contextualizar cada estimación."""
	return df[ENTRADAS_NUMERICAS + [OBJETIVO]].agg(["min", "median", "max"]).T


@st.cache_resource
def cargar_modelos():
	return importar_modelos("modelo", "referencia", "X_test", "y_test")


@st.cache_data
def cargar_datos():
	return pd.read_csv(RUTA_DATOS_LIMPIOS)


st.set_page_config(page_title="Agua de fractura — cuenca Neuquina", layout="wide")
st.title("Estimación de agua inyectada por operación de fractura")
st.caption(
	"Reservorios no convencionales (shale) de la cuenca Neuquina. "
	"Referencia basada en antecedentes históricos; no reemplaza los cálculos de ingeniería."
)

if not RUTA_DATOS_LIMPIOS.is_file() or not RUTA_ARTEFACTOS.is_dir():
	st.error(
		"Faltan datos o artefactos. Ejecutá primero la fase 3 (`fase_3_data_preparation.ipynb`) "
		"y la fase 4 (`fase_4_modeling.ipynb`) desde la raíz del proyecto."
	)
	st.stop()

modelo, referencia, X_test, y_test = cargar_modelos()
df = cargar_datos()
rangos = rangos_historicos(df)

st.subheader("Características de la operación")
columnas = st.columns(len(ENTRADAS_NUMERICAS) + 1)
entradas = {}

for col_ui, variable in zip(columnas[: len(ENTRADAS_NUMERICAS)], ENTRADAS_NUMERICAS):
	minimo = float(df[variable].min())
	maximo = float(df[variable].max())
	mediana = float(df[variable].median())
	entradas[variable] = col_ui.number_input(
		f"{variable} (histórico: {minimo:,.0f} – {maximo:,.0f})",
		min_value=0.0,
		value=mediana,
		step=1.0,
	)

categorias = sorted(df["tipo_terminacion"].dropna().unique())
mas_frecuente = df["tipo_terminacion"].mode().iloc[0]
entradas["tipo_terminacion"] = columnas[-1].selectbox(
	"tipo_terminacion", categorias, index=categorias.index(mas_frecuente)
)

# El modelo espera las columnas en el orden de entrenamiento.
caso = pd.DataFrame([entradas])[ENTRADAS_NUMERICAS + ENTRADAS_CATEGORICAS]
fuera_de_rango = [
	v for v in ENTRADAS_NUMERICAS if not (df[v].min() <= entradas[v] <= df[v].max())
]

if fuera_de_rango:
	st.warning(
		"Estos valores están fuera de los antecedentes observados: "
		f"{', '.join(fuera_de_rango)}. La estimación allí es una extrapolación y es poco confiable."
	)

resultado = estimar_agua(modelo, referencia, caso)
mediana_historica = float(df[OBJETIVO].median())

st.subheader("Estimación")
col_est, col_ref, col_med = st.columns(3)
col_est.metric("Agua estimada", f"{resultado['estimado_m3']:,.0f} m³")
col_ref.metric("Referencia (mediana histórica)", f"{resultado['referencia_m3']:,.0f} m³")
col_med.metric("Mediana de la población", f"{mediana_historica:,.0f} m³")

st.subheader("El caso en el contexto histórico")
st.dataframe(rangos.round(0), use_container_width=True)

with st.expander("Sobre el modelo y sus límites"):
	mae_test = float(mean_absolute_error(y_test, modelo.predict(X_test)))
	st.write(
		f"Random Forest entrenado con {len(df):,} operaciones. "
		f"En la prueba temporal su error absoluto promedio fue de **{mae_test:,.0f} m³**. "
		"Las estimaciones sirven como referencia de antecedentes; no reemplazan "
		"los cálculos de ingeniería ni la evaluación especializada. "
		"El modelo no se generaliza a pozos verticales, tight ni otras cuencas."
	)
