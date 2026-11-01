# Data

All files in `data/raw/` were provided by the store for the case and are kept
unmodified except for their file names, which were simplified.

| File | Original name | Content |
|---|---|---|
| `products.csv` | `desafio_tecnico_ai_eng - products.csv` | Product catalog (price, stock, status, specs as JSON) |
| `categories.csv` | `desafio_tecnico_ai_eng - categories.csv` | Product categories |
| `customers.csv` | `desafio_tecnico_ai_eng - customers.csv` | Customers |
| `orders.csv` | `desafio_tecnico_ai_eng - orders.csv` | Orders (status, payment, tracking, estimated delivery) |
| `order_items.csv` | `desafio_tecnico_ai_eng - order_items.csv` | Items of each order |
| `promotions.csv` | `desafio_tecnico_ai_eng - promotions.csv` | Promotions (only rows with `is_active = 1` are valid) |
| `store_policies.pdf` | `políticas_da_loja.pdf` | Internal policies and procedures manual (v2.1) |

## Cleaning

The raw files are never edited. `emporio_agent/data_loader.py` loads them into a
SQLite database (`data/store.db`, git-ignored) that is built automatically the
first time it is needed, and rebuilt whenever a CSV is newer than the database.
To rebuild it manually:

```bash
python -m emporio_agent.data_loader
```

What the loader does:

- **Availability label.** Catalog `status` and `stock_quantity` are combined into a
  single `availability` value: `in_stock`, `out_of_stock` (active but stock 0),
  `discontinued` or `coming_soon`. The agent never has to reason about two columns.
- **Promotions.** Only `is_active = 1` rows are valid (the `active_promotions` view).
  Past promotions are kept in the table but never offered. If a product ever had
  several active promotions, the largest discount would win, since the manual says
  promotions are not cumulative.
- **Payment method.** `credit_6x` is split into `payment_type = credit` and
  `installments = 6`.
- **Empty values.** Blank tracking codes and delivery estimates become `NULL`.
- **Specs.** The JSON `specs` is kept as-is and also flattened into filterable
  columns: `string_material` (nylon/steel), `string_count`, `has_pickup`, `color`.
- **Search text.** Each product gets an accent-free, lowercase `search_text` built
  from its name, category, description and specs, plus Portuguese aliases for
  English spec values (`steel` → "aço", pickup → "eletroacústico"), so
  "violão de aço" finds products whose data only says `steel`.
- **Customers.** Phones are also stored as digits only and e-mails lowercased, to
  make identity checks for order lookups reliable.

## Inconsistencies found in the source data

They are recorded in the `data_issues` table instead of being silently "fixed":

| Issue | Detail | How it is handled |
|---|---|---|
| Duplicate e-mail | Customers 11 and 43 ("Bruno Carvalho Martins" / "Bruno Martins") share an e-mail | Both rows are kept. Orders are checked against the customer who owns that order, so the duplicate cannot expose another person's order |
| Order total mismatch | Orders 3 and 20 are R$ 48 and R$ 88 below the sum of their items at current prices | `total_brl` is treated as the amount actually charged (prices or discounts may have changed since the order) |
| `coming_soon` product already sold | Product 130 (Kala KA-ABP-CTG) is `coming_soon` but appears in non-cancelled orders 3 and 14 | The catalog status is used when talking about availability: it is not offered as purchasable |
| Empty categories | Woodwinds, brass and orchestral strings have no products, although the manual mentions a catalog of 300+ instruments | The agent says it has nothing in those categories in the catalog instead of making products up |

Other things worth knowing:

- Product 96 is `active` with zero stock, and product 113 is `discontinued`:
  both are reported as unavailable.
- Order data has only an *estimated* delivery date, no actual delivery date. Return
  windows are therefore computed from the estimate (documented where used).
- The sample orders date from 2025 to March 2026. To test time-based rules at a
  specific moment, set `EMPORIO_NOW` (see `.env.example`).
