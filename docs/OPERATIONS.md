# Operations

Setting up, running, testing and troubleshooting Ticket Drop on Windows. Commands are for PowerShell, run from the repository folder.

## 1. First setup

Needs Python 3.12 and Google Chrome. An internet connection is needed once, for Python packages from PyPI.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

`requirements.txt` lists the direct dependencies; `requirements-lock.txt` pins the exact versions that were tested. No browser download is needed: Playwright drives the installed Chrome.

Optional, only for the AI tools: install [Ollama](https://ollama.com) and run `ollama pull llama3.2` (about 2 GB). The application and every pytest test run without it.

## 2. Run the app

```powershell
.\.venv\Scripts\python.exe serve.py
```

Open http://127.0.0.1:8000 and sign in as `lejie`, `arjun`, `siti` or `wei` with the password `demo-pass`. Stop the server with Ctrl+C.

| Option | Effect |
|---|---|
| `--port 8001` | Use another port |
| `--sample-sales 0.55` | On a new database, mark about 55 percent of seats as sold to sample accounts, so the map looks like a sale in progress. Sample data only |
| `--sale-opens-in 60` | Open the sale 60 seconds after start, to see the countdown |
| `--db .local\other.db` | Use another database file |

Test cards: `4242 4242 4242 4242` pays, `4000 0000 0000 0002` is declined, `4000 0000 0000 0408` does not answer (timeout after two seconds).

## 3. Run the tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Runs every automated test (about three minutes). The tests start their own servers on free ports and do not touch the database used by `serve.py`. Subsets:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/api            # rules, fast
.\.venv\Scripts\python.exe -m pytest -m security          # attacker tests
.\.venv\Scripts\python.exe -m pytest -m concurrency       # parallel requests
.\.venv\Scripts\python.exe -m pytest -m e2e               # browser
.\.venv\Scripts\python.exe -m pytest -m e2e --headed      # watch the browser
```

Screenshots of failed browser tests go to `.local/playwright`.

## 4. Load, security and fault experiments

| Command | What it does | Time | Output |
|---|---|---|---|
| `.\.venv\Scripts\python.exe tools\run_load_test.py` | 200-fan spike at the sale opening, then a database integrity check | about 70 s | `evidence/load/` |
| `.\.venv\Scripts\python.exe tools\security_scan.py` | bandit and pip-audit (pip-audit needs internet). Exits 1 if a scan did not run, a dependency is vulnerable, or bandit finds anything beyond the triaged B105 and B311. Add `--offline` to run bandit only | under 1 min | `evidence/security/` |
| `.\.venv\Scripts\python.exe tools\fault_matrix.py` | The whole suite once per seeded fault | about 35 min | `evidence/faults/scripted.json` |
| `.\.venv\Scripts\python.exe -m ai.datagen` | Generate unusual inputs with the local model and judge them | about 2 min | `tests/data/generated_inputs.json`, `evidence/ai/` |
| `.\.venv\Scripts\python.exe tools\run_explorers.py` | Random explorer (seeds 1 to 3) and model explorer (seed 5) against the clean app and each fault | about 45 min | `evidence/faults/explorers.json`, and it **empties** `evidence/ai/explorer_transcripts.jsonl` first |
| `.\.venv\Scripts\python.exe tools\run_explorers.py --llm-seeds 6,7 --random-seeds 0 --out explorers-llm-seeds.json` | Model explorer seeds 6 and 7 only; appends to the transcripts | about 90 min | `evidence/faults/explorers-llm-seeds.json` |
| `.\.venv\Scripts\python.exe tools\build_reports.py` | Rebuild the fault comparison report from the saved results | seconds | `evidence/faults/REPORT.md` |

The reported result (three seeds for each explorer) needs both explorer commands, in that order. Running the default command again resets the transcripts, so the saved seed 6 and 7 transcripts are lost unless the second command is run again afterwards. Together the two runs made 990 model calls and used 7095 s of model time (about 2 hours) on the laptop CPU, 2176 s and 4919 s respectively, as recorded in the two result files.

To try one seeded fault by hand: `$env:TICKET_DROP_FAULTS = "limit_ignores_owned_tickets"; .\.venv\Scripts\python.exe serve.py`. Remove it afterwards with `Remove-Item Env:TICKET_DROP_FAULTS`. Never run a demo with a fault switched on.

## 5. Reset and backup

All local data is in `.local\`. To start again with a fresh sale, stop the server and delete `.local\ticket-drop.db` (and its `-wal` and `-shm` files if present); the next start creates and seeds a new one. There is nothing else to back up: the database holds only demo data.

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Address already in use` | Another program uses port 8000 | `serve.py --port 8001` |
| Tests crash at the end with `PermissionError ... pytest-current` | Some managed Windows machines block pytest's default temporary folder | Already handled: tests use `.local\pytest`. Make sure you run from the repository folder |
| Browser tests fail with a Chrome launch error | Chrome not installed, or installed elsewhere | Install Chrome, or run `.\.venv\Scripts\python.exe -m playwright install chromium` and remove `--browser-channel=chrome` from `pyproject.toml` |
| `The local model is not available` | Ollama not running or model missing | Start Ollama, then `ollama pull llama3.2`. Only the AI tools need it |
| The seat map is empty after sign-in | Server stopped | Restart `serve.py` and reload the page |
| A hold expires sooner than expected | The timer uses server time | Expected: the laptop clock is ignored on purpose |

## 7. Deployment

Not prepared. Version 1 runs on 127.0.0.1 only. The source code is published on GitHub; hosted CI results are shown there, not recorded here. The static showcase page in `site/` is prepared for GitHub Pages; its workflow runs only when started by hand, and whether it has been published is not recorded here.
