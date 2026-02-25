# Reconstruction Notes

## What was done
- Located and extracted all ZIP archives into same-named folders:
  - `Include.zip` -> `Include/`
  - `activate.zip` -> `activate/`
  - `aiofiles-25.1.0.dist-info.zip` -> `aiofiles-25.1.0.dist-info/`
  - `pip-26.0.1.dist-info.zip` -> `pip-26.0.1.dist-info/`
  - `pyvenv.zip` -> `pyvenv/`
  - `static.zip` -> `static/`

## Included in `Reconstructed_Project`
- Python source files from repository root (`*.py`) moved into `src/`
- Frontend template `templates/index.html`
- KaTeX assets under `static/katex/`
- Fresh dependency manifest in `requirements.txt`

## Excluded from cleaned folder
- Virtual environment executables and activation scripts (`activate/`, `pyvenv/Scripts/`)
- Installed package trees and metadata (`Include/Lib/site-packages`, `*.dist-info`)
- Bytecode and caches (`__pycache__`, `*.pyc`)
- Runtime database files (`chatvault.sqlite3`, `chatvault.sqlite3-wal`, `chatvault.sqlite3-shm`)

## Detected issues
- `src/app.py` imports `webui`, but `webui.py` source is not present in extracted source files.
- `src/chat_api.py` imports `tools_search` and `table_tools`, but those `.py` files are missing.
- Only bytecode for these modules was found under `static/__pycache__/`.

These missing modules are likely required for a fully runnable application.


## Follow-up reconstruction
- Reconstructed missing modules and added them under `src/`:
  - `webui.py` (FastAPI app wiring + API routes used by UI)
  - `tools_search.py` (project search, web search, URL fetch)
  - `table_tools.py` (CSV inspect/transform and chart generation)
- This resolves the previous import-level blockers for these modules.
