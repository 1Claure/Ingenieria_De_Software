from pathlib import Path

import joblib
import pandas as pd

#------------------------------------------------------------------
RAIZ_PROYECTO = Path.cwd()
RUTA_ARTEFACTOS = RAIZ_PROYECTO / "artifacts"

RUTA_DATOS = Path("data") / "datos-de-fractura-de-pozos-de-hidrocarburos-adjunto-iv-actualizacin-diaria.csv"

COLUMNAS_FECHA = (
	"fecha_inicio_fractura",
	"fecha_fin_fractura",
	"fecha_data",
)


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
