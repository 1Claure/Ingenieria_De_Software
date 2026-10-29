# Recorrido de Inicio: fuente Blender v3

La escena representa una instalación petrolera en terreno seco, un corte geológico continuo y un pozo con cinco etapas. La geometría es ilustrativa; los cálculos predictivos de la aplicación permanecen separados de estos recursos visuales.

La fuente editable es `patagonia-realistic-90.blend`, con sus texturas empaquetadas. El recorrido actual utiliza un único mundo GLB y una cámara Three.js que avanza y retrocede según el scroll.

## Exportar el mundo actual

Desde la raíz del repositorio, con Blender 4.5 disponible en el PATH:

```bash
blender --background --python scripts/export_journey_world.py
```

El exportador lee esta escena y `textures/`, utiliza funciones de `scripts/render_journey.py` y genera:

- `static/journey/world/patagonia.glb`
- `static/journey/world/manifest.json`
- `assets/journey-world/patagonia-web.blend`

Para exportar nuevamente la geometría preparada:

```bash
blender --background --python scripts/export_journey_world.py -- --prepared
```

El GLB incluye sus texturas. Streamlit sirve el modelo y el manifiesto mediante `server.enableStaticServing = true`. El despliegue utiliza el bundle JavaScript ya compilado; no necesita ejecutar Blender ni Node.

Las secuencias de imágenes y los archivos de trabajo de exploraciones anteriores fueron eliminados. `scripts/render_journey.py` se conserva porque el exportador actual importa sus funciones para construir geometría.

## Editar y ejecutar la aplicación

Para reconstruir el bundle después de modificar los archivos JavaScript:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

Con Python 3.11 o posterior, instalar las dependencias de `requirements.txt` y ejecutar desde la raíz:

```bash
python -m streamlit run app.py
```

## Texturas PBR y licencia

Se descargaron mapas oficiales de 1024×1024 desde Poly Haven:

- [Dry Ground Rocks](https://polyhaven.com/a/dry_ground_rocks): suelo y grava.
- [Metal Plate](https://polyhaven.com/a/metal_plate): plataformas metálicas desgastadas.
- [Blue Metal Plate](https://polyhaven.com/a/blue_metal_plate): pintura industrial gastada.
- [Cliff Side](https://polyhaven.com/a/cliff_side): roca, estratos y grietas.

Poly Haven publica estos recursos con [licencia CC0](https://polyhaven.com/license). `textures/provenance.json` conserva las URL oficiales, los tamaños, los espacios de color y las sumas MD5/SHA-256 de cada mapa. Los diffuse usan sRGB; roughness, metallic y normal GL usan Non-Color. El cielo se genera con Nishita dentro de Blender.
