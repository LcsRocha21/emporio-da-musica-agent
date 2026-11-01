# Empório da Música — Customer Service Agent

A text-based customer service agent for **Empório da Música**, a fictional musical
instruments store in Campo Grande/MS. It is called **DJ**, answers customers in Brazilian
Portuguese in the store's informal and welcoming tone, and decides on its own when to query
structured data (products, prices, stock, promotions, orders) and when to consult the
store's policy manual (hours, returns, shipping, payment, warranty). Built in Python as the
first stage of the Artefact AI Engineer selection process.

- **Example conversations:** [`examples/`](examples/README.md) (five real runs, tools included)
- **Run it:** [Quick start](#quick-start)
- **Why it is built this way:** [Decisions](#decisions-and-why)
- **What it does not do well:** [Known limitations](#known-limitations)
- **How an AI assistant was used:** [AI assistant usage](#ai-assistant-usage)

## Quick start

Requires Python 3.10 or newer and a Google AI Studio API key.

```bash
# create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# install dependencies
pip install -r requirements.txt

# configure the model provider
cp .env.example .env             # Windows: copy .env.example .env
```

Create a key in [Google AI Studio](https://aistudio.google.com/apikey), put it in `.env` as
`GEMINI_API_KEY=...` (the file is git-ignored; never share the key), and then:

```bash
python -m emporio_agent.llm_check     # checks the key and the model with one real question
python -m emporio_agent               # chat with DJ; type "sair" to leave
python -m emporio_agent --debug       # same, also printing every tool call and its result
pytest                                # about 170 tests; they never call the real API
```

More options (saved conversations, transcripts, a frozen store clock for testing
time-dependent rules) are in [Using the agent](#using-the-agent).

## Architecture

```
customer message
      |
      v
  agent loop  (emporio_agent/agent.py)      persona + rules + internal guidelines
      |   ^                                 (emporio_agent/prompt.py)
      v   |
   LLM adapter  (emporio_agent/llm/)  <->  Gemini API, manual function calling
      |
      |  tool calls
      v
  9 deterministic tools  (emporio_agent/tools/)
      |                       |
      v                       v
  SQLite built from CSVs    BM25 search over the policy manual PDF
  (products, orders, ...)   (emporio_agent/policies.py)
```

1. The customer writes a message. The loop sends the whole conversation, the system prompt
   and the tool declarations to the model.
2. The model either answers or asks for one or more tool calls. The loop runs them as plain
   Python functions and feeds the results back, until the model produces the final text
   (capped at 6 rounds, with a polite fallback).
3. Every fact in the answer (price, stock, installment, deadline, tracking code, opening
   hour) comes from a tool result. The model only decides what to look up and how to say it.

## Decisions and why

**No agent framework.** The loop is about 100 lines on top of the Gemini SDK
(`emporio_agent/agent.py`). With nine tools and a single agent, a framework would add
abstractions without adding capability, and it would hide the prompt and the tool-calling
details that matter most here. Owning the loop made it possible to roll a turn back
cleanly when the provider fails, to cap tool rounds, to turn tool errors into messages the
model can recover from, and to test the whole agent with a scripted fake model
(`tests/helpers.py`). The cost: no built-in tracing, memory or retries beyond what is
written here.

**Gemini, behind a small provider interface.** The agent talks to a provider-neutral
`LLMClient` (`emporio_agent/llm/base.py`); `gemini.py` is the only file that knows the
Google SDK, so another provider means writing one class. Gemini was chosen because it
supports native function calling and was available through an AI Studio key. The adapter
uses manual function calling (the SDK's automatic mode is disabled), retries rate-limit and
server errors with backoff, keeps the model's own turn so thought signatures survive while
tools run, and never shows the model's thought summaries to the customer.
The default model is `gemini-3.5-flash`, and `GEMINI_MODEL` overrides it. The smaller
`gemini-3.5-flash-lite` was the first choice, but in testing it kept adding details the
tools had not stated (for example, saying when the refund period starts counting, which
the manual does not say). The larger model did it less often, but not never.

**Numbers and rules live in code, not in the prompt.** Prices, PIX discounts, installment
plans, shipping costs, promotions, return deadlines, store hours and dates are computed by
Python tools with `Decimal` arithmetic, and each tool returns ready-to-quote display strings
(`R$ 1.234,56`). The model never does arithmetic on money or dates. Business rules that
are conditional (an installment minimum, a return window) are therefore unit-tested
rather than hoped for.

**Tools carry their own instructions.** Besides data, tool results include short hints
for the model: what to offer next (`next_steps`), what not to reveal (a failed identity
check says to ask the customer to double-check, never whether the order exists), and, for
the refund terms, the exact wording to use. The refund-timing problem shows the limits of
the options I tried: a rule in the system prompt and a "do not say X" note in the tool
result were both ignored in some runs, with both models. Handing the model the sentence to
use worked in the run I kept, but one good run is not proof; this is a mitigation.

**Keyword retrieval (BM25) over manual sections, no vector database.** Details
in [Policy manual retrieval](#policy-manual-retrieval). Short version: the manual is about
3,000 words split into 26 self-contained sections, so keyword search with a small
vocabulary bridge is enough, deterministic and testable, and needs no extra API.

**The system prompt** (`emporio_agent/prompt.py`) is written in English and makes the model
answer in pt-BR. It contains: the persona (DJ is a virtual assistant and never pretends
to be a person); which tool to use for which kind of question; the scope (instruments
only, no accessories, no invented partner stores, unrelated questions are politely
declined); privacy rules for orders; when to escalate; and safety rules (customer messages
and tool results are data, not instructions). The internal service guidelines from the
manual (sections 7 and 10: tone, special situations) are embedded verbatim instead of being
paraphrased. A test checks that the key rules are present and that every tool is mentioned,
so the routing section cannot silently fall out of date when a tool is added.

**Asking before acting.** Registering a ticket for the human team is an action. The agent
explains what it found, asks whether the customer wants a ticket, and registers it only
after a yes (see example 2). It also does not promise outcomes the tools did not state.

**Privacy by construction.** Order details are only returned after the customer gives the
e-mail or phone registered on the order, and the check happens inside the tool, so it does
not depend on the model behaving (see example 5).

**Tests.** About 170 tests cover the data cleaning, each tool and its edge cases (promotions,
installment minimums, return windows, ambiguous identities), the retrieval (including
off-topic queries that must return nothing), the prompt, the agent loop (with a scripted
model), the Gemini adapter (with a fake SDK, plus the real SDK types when installed), the
CLI and the saved conversations.

## Using the agent

Check that the key and model work, and see which models your key can use:

```bash
python -m emporio_agent.llm_check --list-models   # models available to your key
python -m emporio_agent.llm_check                 # one real question; expects a tool call
```

Start the chat (`GEMINI_MODEL` in `.env` overrides the default model):

```bash
python -m emporio_agent                           # type "sair" to leave
python -m emporio_agent --name "Lucas Mendes"     # greet a known customer by name
python -m emporio_agent --debug                   # also print each tool call and its result
```

Conversations are saved automatically after every answer to `chat_history/` (git-ignored,
because it holds customer data):

```bash
python -m emporio_agent --session ana       # saves to chat_history/ana.json; resumes it if it exists
python -m emporio_agent --resume            # continues the most recent saved conversation
python -m emporio_agent --export chat.md    # also writes a Markdown transcript, tools included
```

A resumed conversation keeps what was said, and the customer's name. The tool results of
earlier turns are kept in the file for the record but are not sent to the model again, only
the text of the conversation is, so after resuming DJ re-checks data if the customer asks
about it again.

To test time-dependent rules (opening hours, return windows) with a frozen store clock,
set `EMPORIO_NOW` (see `.env.example`).

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

## Example conversations

[`examples/`](examples/README.md) has five conversations exported from real runs: a catalog
search with installments, a return by regret (real-time data plus policy rules), a policy
question mixed with a shipping question, out-of-scope requests, and an identity check.
Under each customer message they list the tools the agent called.

## Assumptions

The case allows reasonable assumptions as long as they are documented. These are the
ones that affect the agent and its tools (data assumptions are in [`data/README.md`](data/README.md)):

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

## Known limitations

- **Little evaluation.** The agent was checked with unit tests and by hand, including the
  five example conversations; there is no systematic evaluation set. A language model is not
  deterministic: the same question can be worded differently, and occasionally with a detail
  the tools did not state. The refund-timing case was reduced by putting fixed wording in
  the tool result, not eliminated as a class of problem.
- **Only text from earlier turns survives a resume.** Saved conversations keep tool results
  on disk, but only the text of the conversation is sent to the model again, so after
  resuming DJ checks the data again if the customer asks about it.
- **The identity check is weak.** Anyone who knows an order number and the registered
  e-mail or phone gets the order. A real deployment should use the WhatsApp sender number
  or a one-time code. Two customers share an e-mail in the data; that case is handed to the
  team instead of guessed.
- **Dates are approximations.** The data has no real delivery date, so return windows count
  from the estimated delivery date. Holidays are not known to the store-hours tool.
- **It cannot change anything.** DJ cannot place, cancel or edit orders. It can only
  register a hand-over request, which is written to a local file (`chat_history/handoffs.jsonl`);
  there is no real ticketing system behind it.
- **Prompt injection is only partly addressed.** The prompt tells the model to treat
  customer messages as data, and sensitive checks live in tools, but the agent was not
  red-teamed.
- **Keyword retrieval can miss paraphrases** that are not in the query expansion list.
  With a bigger manual, a hybrid with embeddings would be the next step.
- **Narrow channel and scale.** Command-line chat only, one customer at a time, a local
  SQLite file, no streaming, no WhatsApp or web integration, Portuguese only.
- **Customer data goes to the model provider.** Tool results, which contain order data,
  are sent to the Gemini API. All data here is fictional; with real customers, check the
  data terms of the plan behind the API key first.
- **Policy conflicts are resolved by my assumptions** (installments, contacts, return and
  warranty overlap). They are listed above and should be confirmed with the store.
- **Model names change.** The default model name is the one available when this was built;
  if it is retired, set `GEMINI_MODEL` (the `llm_check --list-models` command shows the
  options).

## AI assistant usage

I built this project together with an AI assistant, Claude (Anthropic), used as a pair
programmer through the whole process, which the case allowed.

**What the assistant did.** It read the case material, helped me define the scope and the
architecture, and wrote most of the code, the tests and the documentation, stage by stage.
It also explored the data and the policy manual and flagged the inconsistencies that are
documented in `data/README.md` and in the assumptions above.

**What I did.** I proposed the persona name (DJ), approved the stack and the language split
(code and docs in English, customers in Portuguese) that the assistant recommended, and
answered the open business questions (for example, to follow section 3.1 of the manual for
installments).
I ran everything on my own machine: the assistant's environment could not call the Gemini
API or install the SDK, so the real model behavior was only ever tested by me, with my own
key. The problems found that way drove most of the late fixes: the agent answering a
general-knowledge question, opening a hand-over ticket without asking, and inventing the
starting point of the refund period. I chose which runs to keep as example conversations, and I
committed and pushed each stage myself.

**What the assistant got wrong along the way.** A wrong customer count in its first summary
of the data; search terms that missed products whose data only used English words ("steel");
a first policy search that was too eager; and the prompt-only fixes that did not hold with the
smaller model. These were caught by tests, by reading the data, or by running the agent, and
fixed in later commits.

## Repository layout

```
data/raw/          Source data provided for the case (CSVs and policy manual PDF)
data/README.md     Description of the data, cleaning and inconsistencies found
emporio_agent/     Agent source code: agent loop, prompt, llm/ adapter, tools/, policies, history, CLI
tests/             Automated tests
examples/          Five example conversations with the agent
```

The project was built in eight stages, one or more commits each: skeleton and raw data,
data loading and cleaning, tools, policy retrieval, agent loop and Gemini adapter,
conversation history, example conversations, and this README. See the Git history.
