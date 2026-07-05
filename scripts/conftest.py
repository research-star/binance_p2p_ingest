"""conftest.py — hace colectable `python -m pytest scripts/ -q`.

Los scripts/test_*.py históricos son self-ejecutables (runner propio con
sys.exit, algunos a nivel de módulo: test_gallery_licenses.py,
test_gallery_keyword.py), así que pytest muere con INTERNALERROR/SystemExit
al intentar importarlos durante la colección. Este conftest los excluye vía
allowlist: solo se colectan las suites escritas en estilo pytest.

Al agregar una suite pytest nueva, sumarla a _PYTEST_STYLE. Los tests legacy
se siguen corriendo como siempre: `python scripts/test_<nombre>.py`.
"""
from pathlib import Path

# Suites en estilo pytest (colectables). Todo otro scripts/test_*.py se ignora.
_PYTEST_STYLE = {
    'test_i18n_bake.py',
}

collect_ignore = sorted(
    p.name for p in Path(__file__).parent.glob('test_*.py')
    if p.name not in _PYTEST_STYLE
)
