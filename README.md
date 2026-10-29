# Ingenieria_De_Software
Trabajo Práctico Integrador realizado durante el cursado de la asignatura Ingeniería de Software, correspondiente al Ciclo de Complementación de la Lic. en Ciencia de Datos.

El proyecto sigue las fases de CRISP-DM sobre el dataset público de **fractura hidráulica de pozos de hidrocarburos en Argentina** (Adjunto IV, Secretaría de Energía), con el objetivo de estimar el agua inyectada por operación a partir de sus características técnicas.

## Estructura

| Ruta | Contenido |
|---|---|
| `fase_1_business_understanding.ipynb` … `fase_6_deploy.ipynb` | Las seis fases de CRISP-DM, en orden. |
| `comun.py` | Rutas, carga de datos y especificación del modelo compartida por las fases. |
| `data/` | Dataset crudo descargado y `df_limpio.csv` (salida de la fase 3). |
| `artifacts/` | Modelos y datos de prueba generados por la fase 4 (no se versionan). |
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

## Flujo de datos

```
data/*.csv (crudo)  --fase 3-->  data/df_limpio.csv  --fase 4-->  artifacts/*.joblib  --fase 5-->  métricas y gráficos
```

La fase 5 consume exactamente la misma partición de prueba que entrenó la fase 4: la lee de los artefactos, no la recalcula.
