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
- [x] 2. Data loading and cleaning (see [`data/README.md`](data/README.md))
- [x] 3. Agent tools (catalog, payments, shipping, orders, returns) + tests
- [x] 4. Policy manual retrieval (section-level BM25 over the PDF)
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

## Try the agent's tools (no API key needed)

The tools are the part of the agent that touches real data. You can call each one from
the terminal and see exactly what the LLM will receive:

```bash
python -m emporio_agent.tools                                   # list the tools
python -m emporio_agent.tools get_product product="Takamine GD20"
python -m emporio_agent.tools search_products category=violões max_price=1000
python -m emporio_agent.tools calculate_payment_options product_ids=95
python -m emporio_agent.tools estimate_shipping city=Dourados product_ids=95
python -m emporio_agent.tools search_policies query="posso devolver meu pedido?"
python -m emporio_agent.tools get_order_status order_id=8 customer_email=anacarol.ferreira@coldmail.com
```

To test time-dependent rules (return windows, opening hours) at a given moment, set
`EMPORIO_NOW`, e.g. on Windows PowerShell `$env:EMPORIO_NOW="2025-10-30T10:00:00"` or on
Linux/macOS `EMPORIO_NOW=2025-10-30T10:00:00 python -m emporio_agent.tools ...`.

| Tool | What it does |
|---|---|
| `search_products` | Browse the catalog by category, price range (promotional price when active), string type, etc. |
| `get_product` | One product: price, promotion, PIX price, stock, specs; alternatives when unavailable |
| `calculate_payment_options` | PIX, debit, boleto and valid credit card installment plans |
| `estimate_shipping` | Shipping cost / carriers / delivery time by city |
| `get_order_status` | Order status and tracking, or the list of a customer's orders (identity check required) |
| `check_return_eligibility` | Applies the regret / defect / preference rules and deadlines to an order |
| `search_policies` | Searches the policy manual: hours, contacts, payment rules, returns, shipping, warranty, privacy |
| `get_current_datetime` | Current time and whether the store is open |
| `handoff_to_human` | Registers a request for the human team (24 business hours) |

Design principles: prices, stock, promotions, installments, deadlines and dates are
computed in code (never by the LLM); every tool returns ready-to-quote display strings;
order data is only returned after the customer proves their identity.

## Policy manual retrieval

`emporio_agent/policies.py` reads `data/raw/store_policies.pdf` with `pypdf` (layout mode,
which keeps table columns apart), removes page headers/footers and splits it into one
chunk per numbered section (26 chunks, e.g. `4.1 Direito de Arrependimento`). Chunks are
searched with BM25, plus accent-insensitive matching, light plural stemming and a small
list of query expansions that map customer words to the manual's vocabulary ("devolver"
finds "arrependimento", "abre" finds "horário de funcionamento").

Why not embeddings / a vector database: the manual is about 3,000 words, its sections are
already self-contained units with descriptive titles, retrieval needs no extra API calls,
and the behavior is deterministic and unit-tested (see `tests/test_policies.py`). With a
much larger manual, a hybrid BM25 + embeddings retriever would be the natural next step.

- **Weak matches return nothing.** For off-topic questions the tool says the manual has no
  answer, and the agent is told to offer a hand-over instead of guessing.
- **Internal sections** (section 7 on tone of voice and service flow, and section 10) are
  not searchable by customers' questions; they are used to write the agent's instructions.
- **Notes on inconsistencies.** Where the manual is ambiguous or contradicts itself, the
  retrieved chunk carries a note for the model (see `CHUNK_NOTES`). The raw text is never
  edited. Exact figures (installments, shipping, deadlines) always come from the dedicated
  tools, never from the model reading the manual.

## Assumptions made so far

The case allows reasonable assumptions as long as they are documented. These are the
ones that affect the tools (data assumptions are in [`data/README.md`](data/README.md)):

- **Installments.** The manual contradicts itself: the payment table says "up to 12x,
  minimum installment R$ 100", while section 3.1 gives tiered minimums. Section 3.1 is
  followed (more detailed): 1x no minimum, 2-3x at least R$ 50, 4-6x at least R$ 80,
  7-12x at least R$ 100. "Except below R$ 50" is read as a R$ 50 minimum installment.
- **PIX.** 5% off the list price, never on top of a promotional price (per item).
- **Price filters** compare the price the customer actually pays (promotional when active),
  not the PIX price.
- **Metropolitan region.** The manual does not define it, so only Campo Grande gets the
  local courier/free-shipping rules; every other city is treated as carrier shipping.
- **"Contrabaixo".** The manual lists contrabaixos among large items needing an individual
  freight quote, meaning double basses. The catalog uses "Contrabaixo" for electric bass
  guitars, which are *not* treated as large items. Acoustic drum kits and pianos are.
- **Order status meaning.** `pending` = waiting for payment confirmation, `confirmed` =
  paid and being prepared, `shipped` = dispatched. The manual does not define them.
- **Return windows.** The data has no actual delivery date, so the estimated delivery date
  is used as the receipt date. Regret and preference: 7 days from receipt; defect exchange:
  30 days from purchase, then the 90-day legal warranty from receipt and the manufacturer
  warranty. Orders are assumed to be online purchases (right of withdrawal applies).
- **Identity check.** The customer must give the e-mail or phone registered on the order.
  A real deployment would use the WhatsApp sender number or a one-time code instead.
- **Holidays** are not detected: the store hours tool only knows the weekly schedule.
- **Contacts in the manual disagree.** The cover page and the company table give the phone /
  WhatsApp as (67) 3341-4444, while section 7 says the WhatsApp channel is (67) 3321-4500.
  The agent quotes both with their labels (phone and WhatsApp). The company table also
  writes the e-mail domain with an accent (`empóriodamusica`), which is treated as a typo:
  `contato@emporiodamusica.com.br` (the cover page spelling) is used. These should be
  confirmed with the store.
- **Campaigns are not offers.** Section 6.1 lists campaigns (Black Friday 15-30%, Dia do
  Músico, ...) in general terms. Only promotions active in the data are valid, so the
  agent never promises a campaign discount even in November.
- **Defect rules overlap.** Section 4.2 gives 30 days from purchase to exchange a defective
  item, and section 8.1 a 90-day legal warranty from receipt. The returns tool applies
  the 30-day exchange first and then points to the legal/manufacturer warranty.
- **Partner stores.** The manual says to suggest partner stores for accessories "when
  possible", but names none, so the agent does not invent any.

## Repository layout

```
data/raw/          Source data provided for the case (CSVs and policy manual PDF)
emporio_agent/     Agent source code
tests/             Automated tests
examples/          Example conversations with the agent (added in step 7)
```

See [`data/README.md`](data/README.md) for the description of the provided data.
