# Example conversations

Five conversations with DJ, the store's virtual assistant. The customer-facing language is
Brazilian Portuguese, so the transcripts are in Portuguese. Under each customer message, the
"Ferramentas usadas" (tools used) block shows which tools the agent called and a preview of
what they returned, so you can see where each fact came from.

Each file is the unedited export of a real run (`python -m emporio_agent --export ...`) with
`gemini-3.5-flash`, the project's default model. They were picked among several runs made while
tuning the prompt and the tools; the problems found along the way are described in the main
README.

| # | File | What it shows |
|---|------|---------------|
| 1 | [`01-busca-e-parcelamento.md`](01-busca-e-parcelamento.md) | Catalog search with a price filter, then installments. The customer asks for 10x, but the manual sets a minimum installment value (R$ 100 above 6x), so the cap is 8x. The values come from the payment tool, not from the model. |
| 2 | [`02-devolucao.md`](02-devolucao.md) | Return by regret, **non-trivial: real-time data plus policy rules**. The tool finds the delivery date, applies the 7-day window and returns the deadline (24/02/2026). DJ asks before opening a ticket for the team and registers it only after the customer agrees. |
| 3 | [`03-garantia-e-frete.md`](03-garantia-e-frete.md) | One conversation that needs both sources: a policy question (warranty, answered from the manual via `search_policies`) and a data question (shipping to Campo Grande, answered from the catalog and shipping tools). |
| 4 | [`04-fora-do-escopo.md`](04-fora-do-escopo.md) | Out-of-scope handling: the store does not sell accessories (strings), a general-knowledge question is politely declined, and a product that is not in the catalog (saxophone) is checked before saying so. |
| 5 | [`05-verificacao-identidade.md`](05-verificacao-identidade.md) | Privacy: an order is only discussed after the customer gives the e-mail registered on it. A wrong e-mail reveals nothing, not even whether the order exists. With the right e-mail, the status and tracking code are shown. |

## About the dates

The sample orders are dated between October 2025 and March 2026, so return windows are
time-dependent. Example 2 was run with the store clock fixed at `2026-02-20T10:30:00`
(`EMPORIO_NOW`, see the main README), which puts order 7 inside its return window. The other
examples do not depend on the date.

The ticket numbers (such as `A4CD7A9D`) are generated at run time and written to a local,
git-ignored file; they do not refer to a real system.
