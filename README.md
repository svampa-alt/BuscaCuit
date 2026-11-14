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

## Motor unificado (`motor/`)
Una sola base SQLite local (no se versiona ni se publica) y un solo buscador.

```bash
python -m motor construir            # baja padron ARCA y Registro Nacional de Sociedades (~2 min, ~1,8 GB)
python -m motor buscar --nombre "El Nido Bar" --direccion "Costa Rica 5709" --provincia CABA
python -m motor lote entrada.csv salida.csv   # columnas: nombre,direccion,localidad,provincia
python -m motor construir --padron omitir --sociedades omitir --locales fuente=habilitaciones.csv
```

- Guarda todas las columnas del padron ARCA (condicion impositiva, monotributo, empleador) y del
  registro societario (domicilio fiscal y legal, actividades).
- Busca por domicilio (misma calle y altura) y por nombre (texto completo, tolera errores de tipeo).
- Estados: `CONFIRMADO` (habilitacion oficial con CUIT en esa direccion), `ALTA_CONFIANZA`
  (nombre y domicilio), `POSIBLE` (solo domicilio o solo nombre), `NO_VERIFICADO`.
- `--locales` incorpora cualquier CSV de habilitaciones o locales que traiga CUIT.

Los scripts de `scripts/` y `buscacuit.py` son la version anterior y quedan hasta migrar sus usos.
