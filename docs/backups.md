# Backups (laptop-pull)

Runbook completo de la operación de backups: la laptop hace **pull desde el
VPS** vía ssh/scp/sftp built-in en OpenSSH client (sin rsync, sin software
adicional). Snapshots son inmutables → pull incremental por filename diff
vía `sftp -b` batch. Costo recurrente: $0.

**Estado:** implementado y validado end-to-end el 2026-05-08 contra el VPS
productivo. Ver `docs/history.md` para el smoke test del cutover.

---

## Setup inicial (una vez por máquina)

1. **OpenSSH client en Windows** (ya viene en Win11; en Win10 verificar con
   `Get-WindowsCapability -Online -Name OpenSSH.Client*`).
2. **Generar SSH key** específica del VPS:
   ```
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_hetzner -C "hetzner $(date +%Y-%m)"
   ```
   Subir la pública al VPS (`ssh-copy-id` o append manual a
   `/home/binance/.ssh/authorized_keys`).
3. **`apt install sqlite3` en el VPS** (~200 KB, requerido para el `.backup` consistente).
4. **Configurar `backup.env`** (gitignored):
   ```
   cp backup.env.example backup.env
   # editar con VPS_HOST, VPS_USER, VPS_PORT, VPS_DB_PATH, VPS_SNAPSHOTS_PATH,
   # SSH_KEY_PATH, LOCAL_BACKUP_ROOT
   ```
5. **Smoke test de conectividad**:
   ```
   ssh -i ~/.ssh/id_ed25519_hetzner binance@<VPS_HOST> 'echo ok && which sqlite3'
   ```

---

## Comandos diarios

```
python scripts/backup.py db          # ssh+sqlite3 .backup → scp pull → cleanup
python scripts/backup.py snapshots   # ssh+find diff → sftp -b batch get
python scripts/backup.py prune       # GFS sobre $LOCAL_BACKUP_ROOT/db/
python scripts/backup.py status      # resumen rápido
python scripts/backup.py verify      # cuenta + tamaño locales
```

---

## Pipeline interno

- **db**: SSH al VPS → `sqlite3 $VPS_DB_PATH ".backup /tmp/p2p_backup_<stamp>.db"`
  → `scp` pull a `~/backups/db/p2p_normalized_<stamp>.db` → SSH cleanup del
  tmp remoto (en `finally`, garantizado).
- **snapshots**: SSH al VPS → `find $VPS_SNAPSHOTS_PATH -type f -name '*.json*'`
  → diff con files locales por path relativo → `sftp -b` batch mode con `get`
  para los nuevos. Una sola conexión SFTP, no scp-per-file.

---

## Política de retención GFS

Solo `db/`. `snapshots/` se conservan forever (inmutables).

- **7 daily**: el más reciente de cada uno de los últimos 7 días distintos con backup.
- **4 weekly**: el más antiguo de cada una de las 4 ISO weeks inmediatamente
  anteriores al tramo daily (semanas que no se cruzan con daily).
- **3 monthly**: el más antiguo de cada uno de los 3 meses anteriores al tramo weekly.
- **Total**: hasta 14 versiones, ~125 días de cobertura.

Gaps en el calendario (días sin backup por VPS caído) se saltan: el tramo
daily son los **7 días distintos con ≥1 backup**, no los 7 días calendario.

Lógica testeada en `scripts/test_backup_retention.py` (13 casos: empty/single,
multi-per-day, gaps, steady-state, idempotencia, no-overlap entre tranches).

---

## Restaurar

```
python scripts/backup.py restore --target /tmp/restore-test
# trae la última versión por default. Para una específica:
python scripts/backup.py restore --target /tmp/restore-test \
                                  --version 2026-05-07T120000Z
```

Validación: comparar checksums con la DB local original:

```
python scripts/checksum_db.py /tmp/restore-test/p2p_normalized_*.db p2p_normalized.db
# debe imprimir "IDENTICAL"
```

---

## Estructura local

```
$LOCAL_BACKUP_ROOT/    (default: ~/backups)
├── db/
│   ├── p2p_normalized_2026-05-07T120000Z.db
│   ├── p2p_normalized_2026-05-08T120000Z.db
│   └── ...
└── snapshots/         ← mirror del VPS (inmutable, sin retención)
    └── YYYY-MM-DD/...
```

---

## Scheduling vía Windows Task Scheduler

`scripts/install_task_scheduler.ps1` registra una tarea `Binance P2P Backup`
que dispara `db && snapshots && prune` diario a las 04:00 hora local.

**No se ejecuta automáticamente** — correr explícitamente:

```
# Mostrar el plan (no registra nada)
powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Show

# Registrar la tarea
powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Register

# Ver estado
powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Status

# Desregistrar
powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Unregister
```

La tarea invoca Git Bash con `python scripts/backup.py db && snapshots && prune`
en el directorio del repo. Trigger configurable con `-Time HH:mm`.

---

## Logging

Una línea estructurada por operación a stderr, mismo estilo que `normalize.py`:

```
[backup] mode=db target=p2p_normalized_2026-05-07T120000Z.db size_mb=537.1 sqlite_backup_s=4.20 scp_pull_s=42.50
[backup] mode=snapshots remote=2700 local_before=2685 pulled=15/15 duration_s=3.10
[backup] mode=prune total=15 keep=14 deleted=1 duration_s=0.05
```

---

## Lockfile

`backup.py` usa lockfile cooperativo per-subcomando (`.backup.<cmd>.lock`,
PID-aware). Diseñado para correr vía Task Scheduler sin overlap con
instancias previas.

---

## Validación

- **Unit tests** (sin red): `python scripts/test_backup_retention.py` corre
  los 13 casos de la lógica GFS. Idempotencia, gaps, steady-state,
  oldest-of-week / oldest-of-month, no-overlap entre tranches.
- **Smoke test contra VPS** (manual, requiere VPS configurado):
  1. `ssh -i ~/.ssh/id_ed25519_hetzner binance@<VPS_HOST> 'echo ok'`
     (valida key + conectividad)
  2. Subir un `p2p_normalized.db` de prueba al VPS:
     `scp local.db binance@VPS:/opt/binance_p2p/p2p_normalized.db`
  3. `python scripts/backup.py db` → debe aparecer en `~/backups/db/`.
  4. `python scripts/backup.py restore --target /tmp/r` y comparar con
     `scripts/checksum_db.py` → `IDENTICAL`.
- **End-to-end con datos reales:** validado el 2026-05-08 (ver `docs/history.md`).
