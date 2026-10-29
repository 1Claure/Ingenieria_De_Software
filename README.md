# Ingenieria_De_Software
Trabajo Práctico Integrador realizado durante el cursado de la asignatura Ingeniería de Software, correspondiente al Ciclo de Complementación de la Lic. en Ciencia de Datos.

El proyecto sigue las fases de CRISP-DM sobre el dataset público de **fractura hidráulica de pozos de hidrocarburos en Argentina** (Adjunto IV, Secretaría de Energía), con el objetivo de estimar el agua inyectada por operación a partir de sus características técnicas.

## Estructura

| Ruta | Contenido |
|---|---|
| `fase_1_business_understanding.ipynb` … `fase_6_deploy.ipynb` | Las seis fases de CRISP-DM, en orden. |
| `comun.py` | Rutas, carga de datos y especificación del modelo compartida por las fases. |
| `app.py` | Dashboard de Streamlit (fase 6): estima el agua de una operación y la compara con los antecedentes históricos. |
| `data/` | Dataset crudo descargado y `df_limpio.csv` (salida de la fase 3). |
| `artifacts/` | Modelo entrenado y datos de prueba generados por la fase 4 (se versionan para poder desplegar el dashboard). |
| `backend/` | API de ejemplo para exponer predicciones (FastAPI). |
| `catedra/` | Consignas y ejemplo de la cátedra. |
| `requirements.txt` | Dependencias del proyecto. |

## Cómo ejecutar

```bash
pip install -r requirements.txt
```

Las notebooks pueden abrirse desde cualquier directorio; las rutas de datos y artefactos se resuelven desde la raíz del proyecto. El orden de ejecución es:

1. **Fase 3** (`fase_3_data_preparation.ipynb`) — limpia el dataset crudo y genera `data/df_limpio.csv`.
2. **Fase 4** (`fase_4_modeling.ipynb`) — entrena el modelo y guarda los artefactos en `artifacts/`.
3. **Fase 5** (`fase_5_evaluation.ipynb`) — evalúa contra la referencia leyendo esos artefactos.

La fase 2 puede ejecutarse en cualquier momento para explorar datos; no es requisito de las anteriores. Para actualizar el CSV fuente hay que descomentar `descargar_dataset()` en la fase 2.

### Dashboard (fase 6)

Con la fase 4 ya ejecutada, el dashboard se levanta con:

```bash
streamlit run app.py
```

Para publicarlo con un link abierto se puede usar [Streamlit Community Cloud](https://share.streamlit.io): al entrar con GitHub, elegir este repositorio, la rama `george-branch` y `app.py` como archivo de entrada. Como el modelo entrenado está versionado en `artifacts/` y los datos en `data/`, no hace falta ejecutar nada más. Después de un `push`, el link se actualiza solo.

## Flujo de datos

```
data/*.csv (crudo)  --fase 3-->  data/df_limpio.csv  --fase 4-->  artifacts/*.joblib  --fase 5-->  métricas y gráficos
```

La fase 5 consume exactamente la misma partición de prueba que entrenó la fase 4: la lee de los artefactos, no la recalcula.
