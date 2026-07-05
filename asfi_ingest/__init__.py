"""asfi_ingest — Módulo ASFI/RMV: Reporte Informativo diario de la Dirección de
Supervisión de Valores (hechos relevantes del mercado de valores boliviano).

Piezas:
  - parser.py:  PDF del reporte → items estructurados (sección/categoría/entidad/texto/tags).
  - fetch.py:   descarga vía proxy residencial con exit Bolivia (appweb2 geo-bloquea
                IPs no bolivianas — ver HANDOFF § ASFI).
  - resumen.py: one-liner IA (Haiku) por item, con candado de gasto + cap mensual
                propio (tabla asfi_api_spend), mismo patrón que noticias_ingest/resumen_ia.

Orquestador: ingest_asfi.py (raíz del repo).
"""
