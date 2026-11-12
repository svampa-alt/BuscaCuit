# Etapa 2 — Inventario de fuentes oficiales (12/11/2026)

Este inventario registra **acceso documental verificado**, no conectores automáticos ni autorización de descarga masiva. El estado de cada fuente es deliberadamente conservador. Las condiciones de reutilización y automatización se deben revisar por fuente antes de incorporar un scraper.

| Fuente | URL oficial | Campos útiles y forma de acceso | Restricción / límite | Estado |
|---|---|---|---|---|
| ARCA — padrón | https://www.arca.gob.ar/buscador-consultas-publicas/ | CUIT y denominación; padrón ya descargado por workflow existente | Coincidencia nominal no prueba comercio; verificar campos concretos del archivo y condiciones de redistribución | Integración existente; no modificada |
| ARCA — constancia pública | https://www.arca.gob.ar/buscador-consultas-publicas/ | Validación de CUIT candidato y datos públicos de inscripción | Consulta por CUIT; no implica búsqueda inversa por nombre de fantasía | Página de consulta verificada; sin automatización |
| ARCA — Registro Único Tributario | https://arca.gob.ar/registro-unico-tributario/tus-datos/ | Describe domicilio legal, fiscal, establecimientos, actividades | Información registral del contribuyente, no se presume consulta pública masiva | Documentación verificada; sin acceso público a datos ajenos comprobado |
| GCBA — permisos de área gastronómica | https://buenosaires.gob.ar/sites/default/files/2023-11/Permisos%20AG%20calzada%2010-11%20%281%29.pdf | Nombre comercial, domicilio y resolución | El permiso de área gastronómica no identifica necesariamente al titular fiscal; examinar resolución original | Ejemplo real documentado |
| Boletín Oficial CABA | https://boletinoficial.buenosaires.gob.ar/buscador | Resoluciones, repartición, fechas, palabras clave, documentos oficiales | Interfaz web; no se verificó API ni licencia para extracción masiva | Buscador verificado; sin automatización |
| Boletín Oficial de la República Argentina | https://www.boletinoficial.gob.ar/busquedaAvanzada/all | Edictos societarios, denominaciones, domicilios, fechas y avisos | Los avisos pueden describir sociedad sin vincularla con el local | Buscador verificado; sin automatización |
| BORA — línea de tiempo de sociedades | https://timeline.boletinoficial.gob.ar/ | Historia societaria y personas relacionadas a partir de avisos | El sitio advierte errores/omisiones por extracción mediante IA; cotejar siempre con aviso original | Aplicación verificada; sin automatización |
| IGJ — consulta de trámites | https://www.argentina.gob.ar/justicia/igj/como-ingresar-y-usar-soda/buscar-y-consultar-tramites | Razón social, CUIT y datos de trámites | Consultar trámites de terceros requiere cinco identificadores exactos; no es buscador libre de CUIT | Documentación verificada; sin automatización |
| IGJ — S.O.D.A. | https://www.argentina.gob.ar/justicia/igj/sistema-online-de-documentacion-abierta-de-igj-soda-0 | Presentaciones registrales incorporadas progresivamente | Acceso por trámites; puede requerir autenticación y pagos | Documentación verificada; sin automatización |
| GCBA — antecedentes de habilitación | https://buenosaires.gob.ar/tramites/solicitud-de-antecedentes-de-habilitaciones-en-locales-comerciales | Antecedentes por domicilio y período | Requiere miBA nivel 3 y solicitud formal; no usar como API | Trámite verificado; no automatizable anónimamente |
| GCBA — habilitación comercial | https://buenosaires.gob.ar/tramites/habilitacion-de-actividad-economica | Trámite vincula CUIT solicitante y ubicación del local | No demuestra disponibilidad pública de esa vinculación | Documentación verificada; sin automatización |

## Caso real de control: El Nido

**Fuente oficial:** listado de permisos de área gastronómica GCBA (PDF enlazado arriba).

**Registro encontrado:** `Costa Rica 5709 | El Nido | RS-2023-25177794-GCABA-COMUNA14`.

**Qué acredita:** asociación oficial entre nombre comercial, dirección y número de resolución en ese listado.

**Qué NO acredita:** CUIT, identidad del titular de habilitación, ni que el permisionario sea el sujeto que factura.

**Siguiente verificación documental:** obtener el texto íntegro de `RS-2023-25177794-GCABA-COMUNA14` en fuente oficial y comprobar si identifica titular/CUIT. No inferirlos.

## Reglas para la integración

1. Cada relación debe guardar `fuente_url`, `documento_id`, `fecha_consulta`, `nombre_comercial`, `domicilio`, `titular`, `cuit`, `tipo_relacion` y `evidencia` cuando efectivamente existan; dejar ausentes los campos desconocidos.
2. Separar acceso público, consulta autenticada, trámites pagos y disponibilidad de API; no saltar controles de acceso.
3. La cercanía geográfica ordena candidatos; no descarta domicilios fiscales lejanos ni prueba titularidad.
4. El permiso de área gastronómica, el nombre de fantasía y la constancia de inscripción por separado **no** bastan para confirmar titularidad comercial.
5. La integración automática y la validación de descarga real pertenecen a las siguientes implementaciones; ninguna se declara terminada aquí.

## Frecuencia y formato

- ARCA: workflow del padrón existente tiene cron semanal; no inferir frecuencia de publicación de datos.
- Boletines: publicaciones periódicas consultables por fecha; la disponibilidad de exportación o API no fue comprobada.
- GCBA PDF: documento fechado 2023-11 según su ruta; no hay actualización automática comprobada.
- IGJ y habilitaciones: acceso mediante interfaces o trámites; frecuencia de actualización no comprobada.
