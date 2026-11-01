# Empório da Música — Customer Service Agent

A text-based customer service agent ("DJ") for **Empório da Música**, a fictional
musical instruments store in Campo Grande/MS. Built in Python as the first stage of
the Artefact AI Engineer selection process.

The agent answers customers in Brazilian Portuguese, in the store's informal and
welcoming tone, and decides on its own when to query structured data (products,
prices, stock, promotions, orders) and when to consult the store's policy manual
(opening hours, returns, shipping, payment, warranty).

> **Status: work in progress.** This repository is being built in stages, with one
> commit per step. The sections below will be completed as the project evolves.

## Planned architecture

- **Agent approach:** LLM with function calling (hybrid: SQL-backed tools for
  structured data + retrieval over the policy manual).
- **Model / provider:** Google Gemini API.
- **Data layer:** CSV files loaded and cleaned into a local SQLite database.
- **Interface:** command-line chat, with conversation history persisted per session.
- **Language:** code, comments and documentation in English; the agent talks to
  customers in Portuguese (pt-BR).

## Roadmap

- [x] 1. Project skeleton and raw data
- [ ] 2. Data loading and cleaning
- [ ] 3. Agent tools (catalog, orders, promotions, payments) + tests
- [ ] 4. Policy manual retrieval
- [ ] 5. Agent loop and persona
- [ ] 6. CLI and conversation history
- [ ] 7. Example conversations
- [ ] 8. Final README (decisions, limitations, AI assistant usage)

## Setup

Requires Python 3.10 or newer.

```bash
# create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# install dependencies
pip install -r requirements.txt

# configure the model provider
cp .env.example .env             # Windows: copy .env.example .env
# then edit .env and set GEMINI_API_KEY
```

Run the tests with:

```bash
pytest
```

## Repository layout

```
data/raw/          Source data provided for the case (CSVs and policy manual PDF)
emporio_agent/     Agent source code
tests/             Automated tests
examples/          Example conversations with the agent (added in step 7)
```

See [`data/README.md`](data/README.md) for the description of the provided data.
