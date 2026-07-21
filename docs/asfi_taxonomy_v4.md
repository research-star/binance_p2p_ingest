# ASFI V4 — contrato, dry-run y gate de persistencia

Estado: implementación local en `feat/asfi-taxonomy-v4`. No publicada y no
persistida en `static/asfi_*.json`.

## Contrato por comunicado

- `type_id`: familia principal visible. Exactamente una.
- `subtype_id`: evento principal dentro del tipo. Exactamente uno.
- `taxonomy_key`: clave estable `type_id.subtype_id`.
- `eventos_secundarios`: otros eventos detectados que no cuentan el documento
  otra vez; se muestran como badges y participan en búsqueda.
- `tags`: señales transversales (rectificación, red de atención, operación de
  fondo, organización interna, contenido genérico, resumen IA, etc.).
- `campos_estructurados`: datos extraídos determinísticamente. Un campo ausente
  queda ausente; no se inventa ni se completa con IA.
- `taxonomy_v`: `4`.

Los 17 tipos visibles son: sanciones y procesos regulatorios; capital y cambios
societarios; emisiones y colocaciones; cupones y pagos de valores;
financiamiento; poderes y representación legal; juntas y asambleas; personal;
directorio y sindicatura; compromisos financieros; calificaciones de riesgo;
dividendos y rendimientos; uso de recursos captados; auditorías externas;
titularización; registros y autorizaciones; y el residual Otros comunicados.

El catálogo tiene 120 subtipos. Las claves viven en
`asfi_ingest/taxonomy_v4.py`. Financiamiento integra las 17 definiciones antes
separadas entre bancario y corporativo, con IDs sin colisión. El residual no se
presenta como una familia temática equivalente.

## Precedencia

1. Una sanción formal domina sobre menciones incidentales del expediente.
2. Una decisión societaria ejecutada domina sobre la junta que la aprobó; la
   junta queda como evento secundario.
3. Uso de recursos captados domina cuando el comunicado explica el destino de
   fondos de una emisión.
4. Pagos posteriores de valores dominan sobre la mención histórica de emisión.
5. Oferta pública, bono o pagaré bursátil permanece en Emisiones/Pagos; no se
   clasifica como financiamiento contractual.
6. Personal o Directorio domina sobre Poderes cuando el cambio de persona/cargo
   es el evento central.
7. Registros y autorizaciones se evalúa después de Capital y Emisiones.
8. Juntas es el frame final cuando no existe un evento más específico.

## Tablas y verificación

V4 crea el modelo, pero Fase 2A no reconstruye los 2.795 candidatos tabulares.
Campos: `source_table_status`, `source_table_verified`, `source_table_rows`,
`source_table_columns`, `source_table_totals`, `source_document_reference` y
`verification_notes`.

Estados:

- `none`: sin señal de tabla.
- `detected_unparsed`: señal detectada; falta geometría/cotejo de fuente.
- `reconstructed_unverified`: reconstrucción preliminar.
- `reconstructed_verified`: reconstrucción cotejada por FinanzasBo.
- `source_verified`: tabla literal cotejada con ASFI.

Solo `source_verified` usa “Tabla publicada por ASFI”.
`reconstructed_verified` usa “Tabla reconstruida por FinanzasBo a partir del
comunicado de ASFI”. `reconstructed_unverified` usa “Datos estructurados
preliminares — consulta el documento original”. Las fichas determinísticas usan
“Datos clave estructurados por FinanzasBo a partir del comunicado”.

Banco Solidario (`asfi:2026-07-15:003`) queda `detected_unparsed`, sin filas de
tabla y con nota Fase 2B: el total y el comprador están estructurados para la
ficha, pero el PDF exacto no fue cotejado. OLEUM (`asfi:2026-07-15:002`) queda
como `capital_societario.aportes_capitalizacion`, con junta extraordinaria
secundaria, Bs 34.000.000 y fecha límite 31-jul-2026.

## Inventario frontend

- `template.html`: markup, controles y CSS responsive.
- `static/asfi-taxonomy-v4-ui.js`: carga local de índice/meses, estado, filtros,
  hash compartible, conteos, render por día/rango, tablas y detalles.
- Día: encabezado por tipo y subtipo visible en cada fila.
- Rango: resumen por tipo → bloque de subtipo → tabla específica.
- Los subtipos sin resultados no se renderizan. La selección múltiple solo se
  ofrece después de elegir un tipo. Limpiar tema no cambia fechas.
- Búsqueda cubre entidad, texto, campos, eventos secundarios y tags.
- `.table-scroll` es el único contenedor con overflow horizontal; grids/flex
  usan `min-width:0` y contenido largo usa wrap.

El asset es copiado por `scripts/publish_dashboard.py` junto a los demás
archivos de `static/`; no requiere servidor de aplicación ni recurso externo.

## Dry-run

```powershell
python scripts\asfi_v4_dry_run.py --phase1-dir C:\ruta\a\exports_fase1
$env:ASFI_RUN_CORPUS_TEST='1'; python -m pytest scripts\test_asfi_taxonomy_v4.py -q
python scripts\build_asfi_v4_preview.py
```

El dry-run clasifica copias en memoria, guarda hashes antes/después, concilia
tipos/subtipos y audita los CSV 509/488/2.972. Solo escribe el reporte y muestra
en `tmp/`. El builder de preview solo escribe copias bajo `tmp/`.

La comparación V2/V4 admite diferencias documentadas y aprobadas por Diego
(2026-07-20). Dentro de Financiamiento: `contratacion_bancaria +5` y
`uso_linea_credito -5` — el patrón V2 encontraba `uso` dentro de otras
palabras; V4 exige que el verbo aparezca cerca de “línea de crédito”; los
totales del tipo no cambian. Además, cuatro **overrides curados**
(`_MANUAL_OVERRIDES` en `taxonomy_v4.py`) re-etiquetan los cuatro hallazgos de
la revisión manual por decisión explícita de Diego, identificándolos por huella
de contenido y sin ampliar reglas generales: `asfi:2020-03-17:040` →
`otros_residual.sin_patron_fuerte`, `asfi:2020-04-28:013` →
`dividendos.rendimientos_fondo`, `asfi:2020-09-10:002` →
`juntas_asambleas.decisiones_adoptadas` (destino elegido por Diego) y
`asfi:2020-08-31:001` → `dividendos.pago_realizado`. Efecto neto por tipo:
dividendos +1, juntas +1, emisiones −1, registros −1.

La muestra determinística contiene dos filas por cada estrato año×tipo
disponible (119 estratos, 238 filas en este universo). El JSON de diagnóstico
registra los hallazgos con su disposición final; ninguna corrección se aplicó
en silencio.

## Gate para persistir

Diego debe aprobar explícitamente el diagnóstico y la revisión visual. Recién
entonces una ejecución separada puede: correr `--reextraer`, revisar el diff de
los 74 JSON, commitear datos regenerados, abrir PR, mergear y desplegar. La
autorización de Fase 2A no cubre ninguna de esas acciones ni reprocesar PDFs.
