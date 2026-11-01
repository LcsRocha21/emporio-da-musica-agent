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

Cleaning and normalization are done in code (not by editing these files) and are
documented in the README as the project evolves.
