# scripts/agro — dataset de exportaciones agro (tab Agro)

`static/agro_exportaciones.json` es el contrato de datos `{meta, origTotal, nacional, porDepto}`
que consume la tab Agro: exportaciones bolivianas de 35 productos agro-alimentarios (30 con
data), 2017–2026 (2026 YTD a marzo), FOB USD + toneladas, anual y mensual, nacional / por
departamento / por país destino.

## Fuente

Microdatos de exportaciones del **INE (serie IneComex)**: registros a nivel línea NANDINA
(10 dígitos) × departamento × mes × país. Los crudos (`expYYYY/expYYYY.txt`, sep `|`,
latin-1, ~26 MB) **NO se versionan en este repo** — viven en el working tree del repo
COMEX-Bolivia (`C:\Dev\Trabajo previo\Comex\COMEX-Bolivia\data\raw\Exportaciones` en la
máquina de Diego). La fecha de descarga de los crudos se registra en
`granos_config.json → meta.fecha_descarga`.

## Regenerar

```
python scripts/agro/granos_ingest.py --raw-dir "C:\Dev\Trabajo previo\Comex\COMEX-Bolivia\data\raw\Exportaciones"
```

Escribe `static/agro_exportaciones.json` (default `--out`). El filtro de productos se define
en `scripts/agro/granos_config.json` (35 semillas, match por prefijo NANDINA con exclusiones,
p.ej. líneas "para siembra"). El builder está portado verbatim de
`pipeline/granos_ingest.py` del repo COMEX-Bolivia
(github.com/InvestmentSolutionsDDR/COMEX-Bolivia).

## Atribución

Datos: Instituto Nacional de Estadística de Bolivia (INE), estadísticas de comercio
exterior (IneComex). Datos públicos; citar "Fuente: INE Bolivia" al reutilizar.
