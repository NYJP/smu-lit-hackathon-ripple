# Ripple

Ripple is a regulatory dependency mapping system for legal teams: it links atomic requirements extracted from external regulations to the exact sentences and clauses in an organisation's internal documents that depend on them, at `Regulation → Requirement → Document → Section → Sentence` granularity. When a rule changes — or when you simulate a change that hasn't happened yet — Ripple propagates it through the stored map and shows you precisely which passages now need review, with a confidence score, a reason, and a proposed redline you decide on. Everything runs on your own machine against a local SQLite file; the only thing that ever leaves it is text sent to OpenAI for embedding and analysis.

## Running it

```
cp .env.example .env      # then add your OPENAI_API_KEY
python run.py install     # create .venv, install Python (and, later, npm) dependencies
python run.py dev         # start the API; Ctrl+C stops it
python run.py test        # run the pytest suite
python run.py seed        # load the reference demo corpus (arrives with a later wave)
python run.py reindex     # rebuild the vec_*/fts_* mirror tables (arrives with a later wave)
```

`run.py` is the only task runner — no Makefile, no shell scripts — and works identically on Windows, macOS, and Linux. This wave ships the backend only: accounts, scoping, the full database schema, and honest `501` stubs for every endpoint that hasn't been built yet. `python run.py dev` currently starts the API alone at `http://127.0.0.1:8000` and says so; the web app arrives in the next wave. Visit `http://127.0.0.1:8000/api/v1/health` to confirm it's up, or `http://127.0.0.1:8000/api/v1/users` to see the three seeded accounts.

## Accounts are not secured

There are no passwords. Ripple ships with three named accounts, and choosing one from the list — no sign-up, no credential — selects a point of view, not a permission level. Anyone who can open this install can switch to any name and see that person's documents; anyone with filesystem access to `./data/ripple.db` can read everything in it, for every member, at once. The scoping rules (who sees which documents, who can write to them) are implemented and tested exactly as specified, because they are real product behaviour, not a security boundary — but they are a filter, not a lock. Do not deploy this anywhere it would be reachable by someone you don't already trust with the entire corpus.
