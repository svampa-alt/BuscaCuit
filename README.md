# BuscaCuit

Buscador abierto de CUIT argentinos por razón social, nombre comercial y domicilio.

## Principios
- No inventar CUIT ni presentar coincidencias como identificaciones confirmadas.
- Mantener fuente, fecha, denominación y evidencia de cada resultado.
- Procesar únicamente datos públicos con condiciones de reutilización compatibles.
- No publicar padrones con datos personales sin revisión de licencia, privacidad y finalidad.

## Arquitectura
- GitHub Pages: interfaz estática.
- GitHub Actions: construcción, controles y actualización de índices permitidos.
- Motor de búsqueda: coincidencia normalizada y clasificación de evidencia.

Estado: prototipo inicial en desarrollo.

## Evidencias multifuente (etapa 2)
Se incorporaron cuatro fuentes identificadas: Registro Nacional de Sociedades,
habilitaciones GCBA, avisos societarios del Boletin Oficial y padron ARCA.
La descarga automatica del Registro Nacional y del ultimo CSV GCBA ya existe
en `scripts/cruce_sociedades.py`. BORA y ARCA se incorporan mediante
**exportaciones CSV obtenidas legitimamente**; no se simula una API publica
ni se eluden captchas. Cada fila conserva organismo, catalogo, archivo, numero
de fila, fecha de consulta e identificador reproducible.

Ejemplo con un CSV oficial de avisos descargado previamente:
```bash
python scripts/cruce_sociedades.py --name "El Nido" --address "Costa Rica 5709" \
  --city Palermo --province CABA \
  --evidence-catalog bora_sociedades=avisos.csv \
  --evidence-catalog arca_padron=padron.csv \
  --output output/cruce_sociedades.json
```
Se puede usar solo una de las opciones `--evidence-catalog`.
Para normalizar un CSV sin ejecutar la busqueda:
```bash
python scripts/fuentes_evidencia.py --fuente bora_sociedades --csv avisos.csv --salida output/avisos_normalizados.json
```
**Limitacion:** los datos CSV de BORA/ARCA no se descargan automaticamente;
la coincidencia documental no confirma la titularidad de un comercio.
No subir padrones personales ni datos privados al repositorio.
