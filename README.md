# Ripple

Ripple is a regulatory dependency mapping system for legal teams: it links atomic requirements extracted from external regulations to the exact sentences and clauses in an organisation's internal documents that depend on them, at `Regulation → Requirement → Document → Section → Sentence` granularity. When a rule changes — or when you simulate a change that hasn't happened yet — Ripple propagates it through the stored map and shows you precisely which passages now need review, with a confidence score, a reason, and a proposed redline you decide on. Everything runs on your own machine against a local SQLite file; the only thing that ever leaves it is text sent to OpenAI for embedding and analysis.

## Running it

```
cp .env.example .env      # then add your OPENAI_API_KEY
py -3.12 run.py install   # create .venv and install Python/npm dependencies
py -3.12 run.py restore   # load the bundled corpus snapshot into ./data
py -3.12 run.py dev       # start API :8000 and web :3000; Ctrl+C stops both
py -3.12 run.py test      # run the pytest suite
```

## Reproducing the corpus exactly

`./data` is gitignored, so a fresh clone starts empty. `run.py restore` copies
the snapshot in `sample-environment/snapshot/` over it, giving you the same
regulations, guidelines, documents, dependencies, impacts, and review state
the snapshot was taken from — down to the individual evidence spans and
confidence scores.

This is the only way to reproduce a corpus *exactly*. Re-running ingestion
would not: extraction and dependency mapping go through a language model, and
its output varies between runs. The snapshot avoids that entirely — embeddings
are stored inside the database file, so a restore makes no model calls, needs
no `OPENAI_API_KEY`, and costs nothing.

It refuses to overwrite an existing `./data/ripple.db`; pass `--force` when you
mean to discard what is there. Session rows are stripped from the snapshot, so
everyone starts signed out and picks an account at `/who`.

To share a corpus of your own, load it, then:

```
py -3.12 run.py snapshot  # capture ./data into sample-environment/snapshot/
```

and commit `sample-environment/snapshot/`. The `*.display.pdf` render cache is
deliberately excluded — `api/services/rendering.py` rebuilds it on demand.

For a deterministic corpus built from scratch instead, use
**Settings → Sample environment**, which seeds a scenario from
`sample-environment/scenarios.json` by literal phrase matching.

`run.py` is the only task runner — no Makefile, no shell scripts — and works identically on Windows, macOS, and Linux. This wave ships the backend only: accounts, scoping, the full database schema, and honest `501` stubs for every endpoint that hasn't been built yet. `python run.py dev` currently starts the API alone at `http://127.0.0.1:8000` and says so; the web app arrives in the next wave. Visit `http://127.0.0.1:8000/api/v1/health` to confirm it's up, or `http://127.0.0.1:8000/api/v1/users` to see the three seeded accounts.

## Accounts are not secured

There are no passwords. Ripple ships with three named accounts, all deliberately treated as administrators. Choosing a name changes relevance ranking and explanations, never access: every account can see and act on the whole local workspace. Anyone with filesystem access to `./data/ripple.db` can read everything. Do not deploy this anywhere reachable by someone you do not already trust with the entire corpus.

Load the deterministic PDPF corpus from **Settings → Sample environment**. The former `run.py seed` command is not implemented. Model calls use the official SDK through the configured OpenRouter-compatible `OPENAI_BASE_URL`; do not replace it with the OpenAI endpoint.
