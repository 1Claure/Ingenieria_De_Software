from pathlib import Path

import joblib
import pandas as pd
import requests

#------------------------------------------------------------------
# Las rutas se anclan al archivo y no al directorio de trabajo: así las
# notebooks funcionan igual sin importar desde dónde se abra Jupyter.
RAIZ_PROYECTO = Path(__file__).resolve().parent
RUTA_ARTEFACTOS = RAIZ_PROYECTO / "artifacts"

RUTA_DATOS = RAIZ_PROYECTO / "data" / "datos-de-fractura-de-pozos-de-hidrocarburos-adjunto-iv-actualizacin-diaria.csv"
RUTA_DATOS_LIMPIOS = RAIZ_PROYECTO / "data" / "df_limpio.csv"

COLUMNAS_FECHA = (
	"fecha_inicio_fractura",
	"fecha_fin_fractura",
	"fecha_data",
)

# Especificación del modelo, compartida por la fase 4 (entrenamiento) y la
# fase 5 (evaluación) para que ambas no puedan divergir.
OBJETIVO = "agua_inyectada_m3"
ENTRADAS_NUMERICAS = ["longitud_rama_horizontal_m", "cantidad_fracturas"]
ENTRADAS_CATEGORICAS = ["tipo_terminacion"]
CORTE_TEMPORAL = pd.Timestamp("2025-01-01")
FECHA_REVISION = pd.Timestamp("2026-10-28")

def descargar_dataset():
	url = "https://datos.energia.gob.ar/dataset/71fa2e84-0316-4a1b-af68-7f35e41f58d7/resource/2280ad92-6ed3-403e-a095-50139863ab0d/download/datos-de-fractura-de-pozos-de-hidrocarburos-adjunto-iv-actualizacin-diaria.csv"
	headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

	# Realizar la descarga en bloques (stream) para evitar sobrecargar memoria
	with requests.get(url, headers=headers, stream=True, timeout=60) as r:
		r.raise_for_status()
		with open(RUTA_DATOS, "wb") as f:
			for chunk in r.iter_content(chunk_size=8192):
				f.write(chunk)

	print("Descarga completada con éxito.")

def leer_dataframe_con_fechas() -> pd.DataFrame:
	"""Carga el dataset y enriquece sus columnas temporales."""
	df = pd.read_csv(RUTA_DATOS)

	# Convertir las fechas originales.
	df[list(COLUMNAS_FECHA)] = df[list(COLUMNAS_FECHA)].apply(
		pd.to_datetime,
		errors="raise",
	)

	# Enriquecer las fechas de inicio y fin de fractura.
	for prefijo, columna in (
		("inicio", "fecha_inicio_fractura"),
		("fin", "fecha_fin_fractura"),
	):
		fecha = df[columna]

		df[f"{prefijo}_anio"] = fecha.dt.year
		df[f"{prefijo}_mes"] = fecha.dt.month
		df[f"{prefijo}_dia"] = fecha.dt.day
		df[f"{prefijo}_dia_semana"] = fecha.dt.dayofweek
		df[f"{prefijo}_trimestre"] = fecha.dt.quarter

	# Duración de cada fractura.
	df["duracion_fractura"] = df["fecha_fin_fractura"] - df["fecha_inicio_fractura"]

	df["duracion_fractura_dias"] = df["duracion_fractura"].dt.total_seconds() / 86_400

	# Timestamp Unix de la fecha de carga.
	df["fecha_data_timestamp"] = df["fecha_data"].astype("int64") / 1_000_000_000

	return df

#------------------------------------------------------------------

def exportar_modelos(**artefactos) -> None:
	"""Guarda modelos, datos y otros artefactos para reutilizarlos."""
	RUTA_ARTEFACTOS.mkdir(parents=True, exist_ok=True)

	for nombre, objeto in artefactos.items():
		ruta = RUTA_ARTEFACTOS / f"{nombre}.joblib"
		joblib.dump(objeto, ruta)


def importar_modelos(*nombres):
	"""Carga uno o varios artefactos previamente guardados."""
	objetos = []

	for nombre in nombres:
		ruta = RUTA_ARTEFACTOS / f"{nombre}.joblib"

		if not ruta.is_file():
			raise FileNotFoundError(f"No existe el artefacto: {ruta}")

		objetos.append(joblib.load(ruta))

	if len(objetos) == 1:
		return objetos[0]

	return tuple(objetos)


def entrenar_modelo_final():
	"""Reconstruye el modelo final de la fase 4 a partir de `data/df_limpio.csv`.

	Respaldo para cuando los `.joblib` no se pueden deserializar, que suele
	pasar entre versiones distintas de Python o scikit-learn (un pickle no es
	compatible entre entornos). El modelo final es el ganador de la comparación
	de la fase 4: Ridge con escalado, contra una referencia de mediana.
	"""
	from sklearn.compose import ColumnTransformer
	from sklearn.dummy import DummyRegressor
	from sklearn.impute import SimpleImputer
	from sklearn.linear_model import Ridge
	from sklearn.pipeline import Pipeline
	from sklearn.preprocessing import OneHotEncoder, StandardScaler

	try:
		codificador = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
	except TypeError:  # scikit-learn anterior a 1.2
		codificador = OneHotEncoder(handle_unknown="ignore", sparse=False)

	df = pd.read_csv(RUTA_DATOS_LIMPIOS)
	df["fecha_inicio_fractura"] = pd.to_datetime(df["fecha_inicio_fractura"], errors="coerce")

	entradas = ENTRADAS_NUMERICAS + ENTRADAS_CATEGORICAS
	datos = df[[*entradas, OBJETIVO, "idpozo", "fecha_inicio_fractura"]].copy()
	train = datos.loc[datos["fecha_inicio_fractura"] < CORTE_TEMPORAL].copy()
	test = datos.loc[datos["fecha_inicio_fractura"] >= CORTE_TEMPORAL].copy()
	compartidos = set(train["idpozo"]).intersection(test["idpozo"])
	train = train.loc[~train["idpozo"].isin(compartidos)].copy()
	if train.empty or test.empty:
		raise ValueError("La partición temporal quedó vacía; revisar data/df_limpio.csv.")

	prep = ColumnTransformer(
		[
			("num", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]), ENTRADAS_NUMERICAS),
			("cat", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", codificador)]), ENTRADAS_CATEGORICAS),
		]
	)
	modelo = Pipeline([("prep", prep), ("regresor", Ridge(alpha=1.0))])
	modelo.fit(train[entradas], train[OBJETIVO])

	referencia = DummyRegressor(strategy="median")
	referencia.fit(train[entradas], train[OBJETIVO])

	return modelo, referencia, "Ridge", test[entradas], test[OBJETIVO]
