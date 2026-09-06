# Ripple

Ripple is a regulatory dependency mapping system for legal teams: it links atomic requirements extracted from external regulations to the exact sentences and clauses in an organisation's internal documents that depend on them, at `Regulation → Requirement → Document → Section → Sentence` granularity. When a rule changes — or when you simulate a change that hasn't happened yet — Ripple propagates it through the stored map and shows you precisely which passages now need review, with a confidence score, a reason, and a proposed redline you decide on. Everything runs on your own machine against a local SQLite file; the only thing that ever leaves it is text sent to OpenAI for embedding and analysis.

## Running it

```
cp .env.example .env      # then add your OPENAI_API_KEY
py -3.12 run.py install   # create .venv and install Python/npm dependencies
py -3.12 run.py dev       # start API :8000 and web :3000; Ctrl+C stops both
py -3.12 run.py test      # run the pytest suite
```

`run.py` is the only task runner — no Makefile, no shell scripts — and works identically on Windows, macOS, and Linux. This wave ships the backend only: accounts, scoping, the full database schema, and honest `501` stubs for every endpoint that hasn't been built yet. `python run.py dev` currently starts the API alone at `http://127.0.0.1:8000` and says so; the web app arrives in the next wave. Visit `http://127.0.0.1:8000/api/v1/health` to confirm it's up, or `http://127.0.0.1:8000/api/v1/users` to see the three seeded accounts.

## Accounts are not secured

There are no passwords. Ripple ships with three named accounts, all deliberately treated as administrators. Choosing a name changes relevance ranking and explanations, never access: every account can see and act on the whole local workspace. Anyone with filesystem access to `./data/ripple.db` can read everything. Do not deploy this anywhere reachable by someone you do not already trust with the entire corpus.

Load the deterministic PDPF corpus from **Settings → Sample environment**. The former `run.py seed` command is not implemented. Model calls use the official SDK through the configured OpenRouter-compatible `OPENAI_BASE_URL`; do not replace it with the OpenAI endpoint.
