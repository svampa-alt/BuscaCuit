# cuit-finder

Busca el CUIT de un comercio o empresa argentina a partir de su **nombre de fantasía** y su **dirección**.

Es un programa determinístico: código + bases locales en SQLite + un método de matcheo explícito. No usa IA ni servicios externos en ninguna consulta; con las mismas bases, la misma consulta devuelve siempre lo mismo. Solo necesita Python 3.10 o superior, sin dependencias.

```
> python -m cuitfinder buscar "Carrefour Express" "Nazca 1944, CABA"

1. 30-68731043-4  INC S.A.
   puntaje 100/100  confianza ALTA  [dirección D=1.00, nombre N=0.90]
   - [sepa] calle y altura exactas (D=1.00): Nazca 1944 - CIUDAD AUTONOMA DE BUENOS AIRES, CABA [sucursal] (bandera Express; AUTOSERVICIO; 10-3-365)
   ...
```

Cada candidato sale con CUIT (dígito verificador validado), razón social, puntaje 0–100, nivel de confianza, y la lista de evidencias: de qué fuente salió y qué regla la generó.

## Instalación (Windows)

```powershell
git clone <este repo> cuit-finder
cd cuit-finder
python -m cuitfinder actualizar
```

`actualizar` descarga las fuentes (unos 720 MB) y arma `data\cuitfinder.db` (1,5 GB). La construcción tardó unos 7 minutos en la máquina de prueba, más la descarga. Opcionalmente, `pip install -e .` agrega el comando `cuitfinder` (equivale a `python -m cuitfinder`).

## Uso

| Comando | Qué hace |
|---|---|
| `python -m cuitfinder buscar "nombre" "dirección"` | Candidatos con puntaje. Opciones: `--max N`, `--detalle`, `--json`, `--todos` |
| `python -m cuitfinder validar 30-68731043-4` | Valida el dígito verificador |
| `python -m cuitfinder actualizar` | Baja todo de nuevo y reconstruye la base |
| `python -m cuitfinder descargar [--fuente X] [--forzar]` | Solo descarga a `data\raw` |
| `python -m cuitfinder construir` | Solo reconstruye la base desde `data\raw` |
| `python -m cuitfinder fuentes` | Fuentes cargadas, fecha de los datos y filas |
| `python -m cuitfinder alias agregar "fantasía" CUIT "dirección" --nota "..."` | Guarda un caso confirmado por vos |
| `python -m cuitfinder evaluar` | Mide aciertos sobre `casos\casos_reales.csv` |
| `python -m unittest discover -s tests` | Corre los tests |

La dirección conviene escribirla con localidad: `"Costa Rica 5709, Palermo, CABA"`, `"San Martín 1234, Rosario, Santa Fe"`. Sin localidad funciona, pero con menos confianza (hay una calle San Martín en cada ciudad).

## El problema de fondo

**Ningún padrón público masivo trae el nombre de fantasía de un comercio común.** ARCA publica CUIT y denominación; el Registro Nacional de Sociedades publica razón social y domicilios; ninguno dice que "El Nido" es el bar de Fulano S.R.L. Por eso el método no depende de que el nombre coincida: usa la **dirección como puente** y el nombre como confirmación.

| Vía | Cómo llega al CUIT | Dónde funciona |
|---|---|---|
| Dirección del local | Habilitaciones comerciales: domicilio → titular → CUIT | CABA |
| Domicilio fiscal o legal | Sociedades con sede en esa dirección | Todo el país, solo personas jurídicas |
| Nombre parecido a la razón social | Texto completo sobre 7,5 millones de denominaciones | Todo el país |
| Bandera | Cadenas de supermercados y estaciones de servicio | Todo el país, solo esos rubros |
| Alias | Casos que vos confirmaste (`alias.csv`) | Lo que cargues |

## Fuentes

Verificadas el 13/11/2026. `python -m cuitfinder fuentes` muestra la fecha real de los datos cargados.

| Id | Fuente | Licencia | Qué trae | Límite |
|---|---|---|---|---|
| `arca` | [ARCA, padrón de condición tributaria con denominación](https://www.afip.gob.ar/genericos/cInscripcion/archivoCompleto.asp) | Archivo público, sin licencia explícita | CUIT y denominación de todos los contribuyentes | Sin domicilio. Denominación cortada a 30 caracteres |
| `rns` | [Registro Nacional de Sociedades](https://datos.jus.gob.ar/dataset/registro-nacional-de-sociedades), Ministerio de Justicia | CC BY 4.0 | CUIT, razón social, tipo societario, domicilio fiscal y legal, actividad | Solo personas jurídicas. El domicilio fiscal muchas veces es un estudio contable |
| `gcba_hab` | [GCBA, habilitaciones aprobadas](https://data.buenosaires.gob.ar/dataset/habilitaciones-aprobadas) 2015–2024 | CC BY 2.5 AR | Domicilio del local, titular, CUIT, rubro, fecha, expediente | Solo CABA. El CSV de 2021 está desalineado y se recupera en parte |
| `gcba_hab_sin_cuit` | Mismo dataset, padrón acumulado 2026 | CC BY 2.5 AR | Domicilio del local, razón social del habilitado, rubro, disposición | **No trae CUIT**: se resuelve por razón social exacta |
| `energia` | [Secretaría de Energía, precios en surtidor](http://datos.energia.gob.ar/dataset/precios-en-surtidor) | CC BY 4.0 | CUIT, operador, dirección, localidad, bandera | Solo estaciones de servicio |
| `sepa` | [Precios Claros, base SEPA](https://datos.gob.ar/dataset/produccion-precios-claros---base-sepa) | CC BY 4.0 | CUIT, razón social, bandera y sucursales con dirección | Solo cadenas que informan precios |

Descartadas por no tener descarga masiva: IGJ/S.O.D.A. (consulta por trámite), constancia de inscripción de ARCA (por CUIT y con captcha), Boletín Oficial (buscador web). El programa no hace scraping ni saltea controles de acceso.

Del padrón acumulado de GCBA no se guardan el teléfono ni los comentarios.

## El método

Todo está en [cuitfinder/buscar.py](cuitfinder/buscar.py) y [cuitfinder/normalizar.py](cuitfinder/normalizar.py); los parámetros son constantes con nombre al principio de `buscar.py`.

### 1. Normalización

**Nombres.** Mayúsculas, sin acentos ni signos. Se quita el tipo societario del principio o del final: `S.A.`, `S R L`, `SAS`, `S.A.C.I.F.I.A.`, "Sociedad Anónima", "Sociedad de Responsabilidad Limitada", etc. Las palabras vacías (DE, LA, EL, Y…) no cuentan y las de rubro (BAR, FARMACIA, KIOSCO…) pesan 0,3: que dos nombres compartan "FARMACIA" no dice casi nada.

**Direcciones.** Se separa calle, altura y localidad. La altura es el primer número que no forma parte del nombre de la calle (no está seguido de "DE" como en *9 de Julio* ni de otro número como en *Calle 7 1234*), o el que sigue a `N°`/`Nro`. Piso, depto y local se descartan.

**Clave de calle.** Las fuentes escriben la misma calle de formas distintas: `PERON, JUAN TTE.GRAL.`, `Tte. Gral. Juan D. Perón`, `Perón`. Se expanden abreviaturas, se quitan tipo de vía, títulos e iniciales, y se ordenan las palabras: las tres dan `JUAN PERON` o un subconjunto.

**Jurisdicción.** Capital Federal, CABA, Ciudad Autónoma y los nombres de barrios porteños se unifican en `CABA`.

### 2. Candidatos

- **Por dirección:** domicilios en la misma calle (similitud de clave ≥ 0,8) y a ±20 números de la altura pedida.
- **Por nombre:** índice de texto completo (SQLite FTS5) con las palabras distintivas de la consulta; a los 400 mejores se les calcula la similitud difusa y quedan los que superan 0,6.
- **Habilitaciones sin CUIT:** se busca la razón social exacta (normalizada) en todas las denominaciones. Si hay un único CUIT, se adopta con factor 0,9; si hay entre 2 y 5 homónimos, se muestran todos con factor 0,5; si no hay ninguno, se informa el titular como candidato "SIN CUIT".

### 3. Similitud

**Nombre (N, de 0 a 1):** el máximo entre (a) cobertura ponderada de las palabras de la consulta en el candidato, castigada si al candidato le sobran palabras, y (b) parecido de cadena completa (difflib), que absorbe errores de tipeo. Por debajo de 0,6 se toma como 0.

**Dirección (D, de 0 a 1):** producto de cuatro factores.

| Factor | Valores |
|---|---|
| Calle | 1,0 igual; 0,9 una contiene a la otra; 0,8–1,0 parecida |
| Altura | 1,0 exacta; 0,55 a ≤ 20 números; 0,25 misma calle y otra altura |
| Jurisdicción | 1,0 coincide; 0,9 la consulta no dice localidad; 0,6–0,7 dudosa; 0,35 otra provincia |
| Tipo de domicilio | 1,0 local o sucursal; 0,9 fiscal; 0,85 legal |

Misma localidad en otra calle vale D = 0,10.

### 4. Puntaje y niveles

```
puntaje = 55 × D + 45 × N
```

| Ajuste | Efecto |
|---|---|
| D ≥ 0,85 y N ≥ 0,75 (nombre y dirección coinciden) | piso de 90 |
| Único titular con local en esa dirección exacta | +10 |
| Varios titulares en la dirección: el de habilitación más reciente | +3 |
| Único CUIT con ese nombre en las bases, sin evidencia de dirección | +10 |
| Alias confirmado en `alias.csv` | 97 |

La dirección pesa más que el nombre porque es la única señal que vincula un local con su titular cuando el nombre de fantasía no figura en ningún lado.

| Nivel | Puntaje | Cómo leerlo |
|---|---|---|
| ALTA | 80–100 | Nombre y dirección coinciden, o alias confirmado |
| MEDIA | 55–79 | Una sola señal fuerte: titular habilitado en esa dirección, o nombre único |
| BAJA | 35–54 | Indicio: nombre parecido sin dirección, o dirección ambigua |
| SIN CUIT | — | Se sabe quién está habilitado ahí, pero no se pudo identificar su CUIT |

Bajo 35 no se muestra, salvo con `--todos`.

**Una coincidencia no es una confirmación.** MEDIA por dirección significa "este CUIT tuvo una habilitación en ese domicilio", no "este CUIT factura hoy con ese nombre". Antes de usar un CUIT para algo que importe, verificalo en la constancia de inscripción de ARCA.

### 5. Alias: lo que el programa aprende

Cuando confirmes un caso (por una factura, por ejemplo), guardalo:

```powershell
python -m cuitfinder alias agregar "El Nido" 30-12345678-9 "Costa Rica 5709, CABA" --nota "factura 11/2026"
```

Queda en `alias.csv` (fuera de git) y la próxima búsqueda de ese nombre en esa dirección lo devuelve primero con puntaje 97. Si el alias tiene dirección, no se aplica a otra dirección: protege contra homónimos y sucursales.

## Base de datos

`data\cuitfinder.db`, tres tablas ([cuitfinder/db.py](cuitfinder/db.py)):

- `fuente`: una fila por fuente con URL, licencia, fecha de los datos y de la ingesta.
- `nombre`: CUIT, nombre original, nombre normalizado, clase (`razon_social` o `fantasia`) y fuente. Con índice de texto completo `nombre_fts`.
- `domicilio`: fuente, CUIT (puede ser nulo), titular, bandera, tipo, calle, clave de calle, altura, localidad, provincia, rubro, fecha y referencia (expediente o disposición).

Para actualizar: `python -m cuitfinder actualizar`. ARCA renueva el padrón semanalmente; el Registro de Sociedades, cada pocos meses; GCBA, sin calendario fijo. La base nueva se arma en un archivo aparte y reemplaza a la anterior recién al terminar.

`data\` no se sube a git: pesa varios GB y contiene padrones con nombres de personas físicas.

## Qué tan bien funciona

Medido el 13/11/2026 con `python -m cuitfinder evaluar` sobre [casos/casos_reales.csv](casos/casos_reales.csv): 29 casos reales cuyo titular es de conocimiento público.

| Grupo | CUIT correcto primero | Con confianza ALTA |
|---|---|---|
| A. Nombre parecido a la razón social (Café Tortoni, Arcor, Hospital Alemán) | 7 de 8 | 5 |
| B. Fantasía distinta de la razón social (McDonald's, Telefe, El Ateneo, Clarín) | **0 de 8** | 0 |
| C. Cadena dentro de un shopping (Starbucks, Havanna, Freddo) | 3 de 3 | 3 |
| D. Bandera de supermercado o estación de servicio | 10 de 10 | 10 |
| **Total** | **20 de 29 (69%)**; entre los 5 primeros: 23 (79%) | |

Lectura honesta:

- **El grupo B es el problema real y hoy no se resuelve.** Cuando la fantasía no se parece a la razón social, solo queda la dirección, y en esos casos la dirección o no figura en las bases (El Ateneo, Hospital Italiano, Telefe) o la comparten muchos titulares (McDonald's en un shopping, Clarín en un edificio del grupo). En 2 de los 8 el CUIT correcto aparece segundo con confianza BAJA.
- **Los grupos C y D son fáciles**: las direcciones de esos casos salieron de las mismas fuentes que usa el programa, así que miden que el método funciona, no que las bases cubran el caso.
- **Un error con confianza ALTA**: "Frávega" en Valentín Gómez 2813 devuelve primero a Frávega Services S.A., otra sociedad del grupo con domicilio fiscal ahí, y segunda a Frávega SACIEI. Empresas del mismo grupo en la misma dirección se confunden.
- **Vía de dirección sola** (`evaluar --muestra-direcciones 300`): consultando 300 habilitaciones de GCBA solo por domicilio, el CUIT habilitado sale primero en el 55% y entre los 5 primeros en el 79%. El resto son direcciones con varios titulares.

Casos sin titular confirmado ([casos/casos_abiertos.csv](casos/casos_abiertos.csv)), que no entran en la medición. Para "El Nido Bar", Costa Rica 5709, el programa devuelve dos candidatos de confianza MEDIA: Shakedown S.R.L. (30-71633651-0, habilitación gastronómica de 2021 en esa dirección) y Olive Palermo (30-71472726-1, habilitación de 2019 y domicilio fiscal ahí). Son titulares habilitados en ese domicilio; cuál explota hoy el bar no está verificado.

Una consulta tarda alrededor de medio segundo. Los 35 tests automáticos pasan.

## Limitaciones

- **Fuera de CABA no hay vínculo local → CUIT.** Solo se encuentra el comercio si su nombre se parece a la razón social, si funciona en el domicilio fiscal o legal de una sociedad, o si es una estación de servicio o un supermercado de cadena.
- **Unipersonales y monotributistas fuera de CABA:** el padrón de ARCA no trae domicilio, así que solo se llega por nombre, y el nombre de fantasía casi nunca es el de la persona.
- **Titular habilitado no es necesariamente quien explota hoy el local.** Las habilitaciones van de 2015 a 2024 con CUIT; puede haber cambiado de manos. Se muestra la fecha para juzgarlo.
- **Edificios y galerías:** en una misma altura puede haber decenas de titulares. El programa los lista, no adivina.
- **Homónimos:** al resolver una habilitación sin CUIT por razón social, si hay varios CUIT con ese nombre no se elige ninguno.
- **Denominaciones de ARCA cortadas a 30 caracteres:** los nombres largos se comparan por prefijo.
- **Errores de tipeo en el nombre:** se toleran al comparar, pero la búsqueda inicial por texto necesita al menos una palabra bien escrita.
- **Direcciones sin altura, esquinas ("Florida y Lavalle") y rutas con kilómetro** no se resuelven bien por dirección.
- **Calles con nombre numérico** (La Plata, por ejemplo) se parsean con reglas simples; conviene escribir `Calle 7 N° 1234`.

## Qué queda sin cubrir

- Habilitaciones comerciales de otros municipios (Rosario, Córdoba, La Plata, etc.): si publican datos abiertos con CUIT, se agregan como una función `cargar_*` más en [cuitfinder/ingesta.py](cuitfinder/ingesta.py).
- Marcas registradas (INPI) como puente fantasía → titular.
- Un paso opcional con IA o búsqueda web para los casos que quedan en SIN CUIT o sin candidatos. Hoy no existe: el programa informa que no encontró y nada más.
