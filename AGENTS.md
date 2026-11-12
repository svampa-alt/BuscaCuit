# Instrucciones operativas — BuscaCuit

## Objetivo invariable
Identificar con evidencia verificable el CUIT del titular de un establecimiento comercial argentino a partir de nombre de fantasía, dirección, actividad y fuentes públicas. Caso de regresión: El Nido Bar, Costa Rica 5709, Palermo, CABA. No confundir coincidencia nominal con titularidad.

## Fuente de verdad
- GitHub Issues: única cola de tareas y registro de estado. No mantener PLAN.md ni ESTADO.json paralelos.
- Código, pruebas y ejecuciones de GitHub Actions: evidencia técnica.
- Antes de modificar código, leer Issues abiertas, archivos existentes y resultados de Actions. No duplicar trabajo ni reiniciar desde cero.
- Trabajar sobre UNA Issue habilitada por vez, respetando dependencias. Registrar en ella enlaces a commits, pruebas, artefactos y fuentes.
- No cerrar una Issue por crear código, un commit, una prueba sintética o un workflow: exigir el criterio de aceptación y evidencia real. Si falta algo, dejar abierta con diagnóstico concreto.

## Protocolo de ejecución
1. Revisar estado actual del repositorio y comprobar que la Issue no esté resuelta.
2. Establecer entrada, salida y criterios verificables; limitar cambios al alcance de la Issue.
3. Ejecutar implementación o investigación con datos reales y fuentes permitidas.
4. Correr pruebas; comprobar resultados y efectos adversos. Ante fallo, registrar el error exacto.
5. Publicar evidencia reproducible y actualizar la Issue; cerrar únicamente al cumplir TODOS los criterios.
6. Si una dependencia o permiso impide avanzar, marcar bloqueo en la Issue. No repetir indefinidamente: máximo dos reintentos sin cambio de hipótesis; luego registrar bloqueo.
7. Si hay cambios concurrentes, releer antes de escribir; no forzar sobrescrituras ni hacer force-push.

## Reglas de evidencia
- Mantener URL, organismo, fecha de consulta, documento, dirección, razón social y CUIT cuando existan.
- Estados de identificación: CONFIRMADO (documento oficial vincula CUIT y establecimiento); ALTA_CONFIANZA (fuentes independientes convergen); POSIBLE; NO_VERIFICADO.
- Distancia y jurisdicción son señales de ranking, no exclusiones automáticas. Diferenciar domicilio fiscal, comercial y sucursales.
- No inventar domicilios, CUIT, titularidades, fuentes ni resultados.
- No publicar padrones ni datos personales masivos. Respetar permisos, licencias, privacidad y límites de consulta.

## Seguridad y costos
- Repositorio privado; no divulgar secretos ni datos privados.
- No contratar servicios, generar gastos, habilitar APIs pagas ni instalar agentes externos sin autorización.
- Los workflows automáticos solo ejecutan acciones expresamente codificadas y autorizadas; AGENTS.md no crea un agente autónomo por sí solo.
- No modificar repositorios ajenos ni otros proyectos.

## Informe de cada ejecución
Informar: tarea/Issue, trabajo efectivamente ejecutado, evidencia comprobada, fallos, bloqueos y próximo paso habilitado. Distinguir siempre implementado de validado.
