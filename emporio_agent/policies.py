"""Policy manual ingestion and retrieval.

The store manual (``data/raw/store_policies.pdf``, 8 pages) is read with ``pypdf``,
split into one chunk per numbered section/subsection, and searched with BM25.

Why section-level BM25 instead of embeddings: the manual is tiny (about 3,000 words),
its sections are already self-contained units with meaningful titles, queries share
vocabulary with it once accents and plurals are normalized, retrieval needs no extra
API calls, and the result is deterministic and easy to test.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from emporio_agent.config import RAW_DATA_DIR
from emporio_agent.text_utils import normalize_text

POLICY_PDF = RAW_DATA_DIR / "store_policies.pdf"

# Sections written for the support team (tone of voice, standard flow, special
# situations). They are loaded into the agent's instructions instead of being
# searchable, and are never quoted to customers.
INTERNAL_SECTIONS = {"7", "7.1", "7.2", "7.3", "10"}

# Notes shown to the model next to a chunk when the manual is ambiguous,
# contradicts itself, or when a dedicated tool must be used for the exact answer.
CHUNK_NOTES = {
    "1.2": [
        "Contacts: the store phone is (67) 3341-4444 (cover page and the company data table). Section 7 of the "
        "manual gives (67) 3321-4500 as the WhatsApp number. Quote both with their labels: phone (67) 3341-4444, "
        "WhatsApp (67) 3321-4500.",
        "E-mail: use contato@emporiodamusica.com.br. The table writes the domain with an accent, which looks like a "
        "typo; the cover page has the plain version.",
    ],
    "2": ["To say whether the store is open right now, use get_current_datetime."],
    "3": [
        "The table says credit card is 'up to 12x, minimum installment R$ 100', but section 3.1 is more detailed and "
        "prevails: 2-3x at least R$ 50, 4-6x at least R$ 80, 7-12x at least R$ 100. For concrete amounts and "
        "installment values use calculate_payment_options."
    ],
    "3.1": ["For concrete amounts and installment values use calculate_payment_options."],
    "4.1": ["For a specific order use check_return_eligibility; do not work out deadlines yourself."],
    "4.2": [
        "Section 8.1 also grants a 90-day legal warranty from receipt, which overlaps with the 30-day exchange "
        "window. For a specific order use check_return_eligibility."
    ],
    "4.3": ["For a specific order use check_return_eligibility."],
    "5.1": [
        "For a concrete quote use estimate_shipping. The manual does not say which towns belong to the "
        "metropolitan region; only Campo Grande is treated as local."
    ],
    "5.2": ["For a concrete quote use estimate_shipping."],
    "6.1": [
        "These are the store's general campaigns, not offers that are active now. Only promotions returned by "
        "get_product / search_products are valid: never promise a campaign discount from this text."
    ],
}

# Customer vocabulary -> manual vocabulary. A query word starting with any trigger adds the expansion.
QUERY_EXPANSIONS = [
    (("devol", "arrepend", "reembols", "estorn", "cancel"), "troca devolucao arrependimento reembolso"),
    (("troc",), "troca devolucao preferencia defeito"),
    (("defeit", "quebr", "estrag", "problema"), "defeito garantia troca"),
    (("garant",), "garantia defeito fabricante"),
    (("endere", "local", "onde", "fica"), "endereco rua centro"),
    (("chega", "chegar", "leva"), "prazo entrega frete"),
    (("horari", "abre", "abrem", "fecha", "fecham", "funcionam", "aberto", "expediente", "domingo", "sabado",
      "feriado"), "horario funcionamento atendimento"),
    (("pag", "parcel", "cartao", "credito", "debito", "pix", "boleto", "prestac", "vezes"), "pagamento parcelamento"),
    (("entreg", "frete", "envi", "correio", "sedex", "pac", "jadlog", "prazo", "motoboy", "transport"),
     "frete entrega envio"),
    (("rastre", "codigo"), "rastreamento codigo"),
    (("promo", "desconto", "oferta", "black", "friday", "liquida"), "promocao desconto"),
    (("telefone", "whatsapp", "contato", "email", "ligar", "falar"), "telefone whatsapp email contato"),
    (("lgpd", "privacidade", "dados", "exclu"), "privacidade lgpd dados"),
    (("acessorio", "corda", "palheta", "cabo", "case", "pedal", "amplificador"), "acessorios instrumentos"),
    (("catalogo", "marca", "vende", "trabalha"), "catalogo instrumentos"),
    (("seguro", "avaria"), "seguro avaria transporte"),
    (("fundad", "historia", "cnpj", "razao", "sobre"), "sobre fundacao empresa"),
]  # fmt: skip

STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "e", "ou", "que", "se", "por", "para", "pra", "com", "sem", "ao", "aos", "eu", "me", "meu", "minha", "voce",
    "voces", "vcs", "ja", "mais", "muito", "qual", "quais", "quanto", "quando", "como", "posso", "pode", "podem",
    "vai", "tem", "ter", "ser", "sao", "foi", "esta", "estao", "isso", "essa", "esse", "loja", "gostaria", "quero",
    "queria", "saber", "preciso", "oi", "ola",
}  # fmt: skip

MIN_SCORE = 3.0  # below this a match is considered noise
RELATIVE_CUTOFF = 0.4  # drop sections scoring under 40% of the best one


@dataclass(frozen=True)
class PolicyChunk:
    section_id: str  # "4.1" or "4"
    title: str  # "Direito de Arrependimento (Compras Online)"
    parent_title: str  # "Política de Trocas e Devoluções" (same as title for top-level sections)
    text: str

    @property
    def internal(self) -> bool:
        return self.section_id in INTERNAL_SECTIONS

    @property
    def path(self) -> str:
        if self.section_id == self.top_id:
            return f"{self.section_id}. {self.title}"
        return f"{self.top_id}. {self.parent_title} > {self.section_id} {self.title}"

    @property
    def top_id(self) -> str:
        return self.section_id.split(".")[0]


# --------------------------------------------------------------------------- ingestion


def extract_manual_text(pdf_path: Path = POLICY_PDF) -> str:
    """Raw text of the PDF in layout mode (keeps table columns apart)."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)


_RUNNING_HEADER = re.compile(r"^Empório da Música\s+Manual de Políticas e Procedimentos$")
_PAGE_FOOTER = re.compile(r"^Página\s+\d+$")
_TOP_HEADING = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")
_SUB_HEADING = re.compile(r"^(\d{1,2})\.(\d{1,2})\s+(\S.*)$")
_LABEL_LINE = re.compile(r"^[A-ZÁÉÍÓÚÂÊÔÃÕÇ][^:|]{2,30}:\s")  # "Estoque: ...", "Tom de voz: ..."


def _clean_lines(raw_text: str) -> list[str]:
    cleaned = []
    for line in raw_text.replace("​", "").replace("\xa0", " ").splitlines():
        line = line.strip()
        if _RUNNING_HEADER.match(line) or _PAGE_FOOTER.match(line):
            continue
        line = re.sub(r"^•\s+", "- ", line)  # bullets
        line = re.sub(r"^(\d+\.)\s{2,}", r"\1 ", line)  # numbered list items
        line = re.sub(r"\s{2,}", " | ", line)  # table columns
        cleaned.append(line)
    return cleaned


def _paragraphs(lines: list[str]) -> str:
    """Join wrapped lines into paragraphs; blank lines and bullets start a new one."""
    paragraphs, current = [], []

    def flush():
        if current:
            paragraphs.append(" ".join(current))
            current.clear()

    for line in lines:
        if not line:
            flush()
        elif line.startswith("- ") or _LABEL_LINE.match(line):
            flush()
            current.append(line)
        else:
            current.append(line)
    flush()
    return "\n".join(paragraphs)


def parse_manual(raw_text: str) -> list[PolicyChunk]:
    """Split the manual into one chunk per numbered section / subsection."""
    lines = _clean_lines(raw_text)
    chunks: list[PolicyChunk] = []
    top_id, top_title = 0, ""
    current: dict | None = None

    def close():
        if current is not None:
            chunks.append(
                PolicyChunk(current["id"], current["title"], current["parent"], _paragraphs(current["lines"]))
            )

    for line in lines:
        top = _TOP_HEADING.match(line)
        sub = _SUB_HEADING.match(line)
        if top and int(top.group(1)) == top_id + 1:
            close()
            top_id, top_title = int(top.group(1)), top.group(2).strip()
            current = {"id": str(top_id), "title": top_title, "parent": top_title, "lines": []}
        elif sub and top_id and int(sub.group(1)) == top_id:
            close()
            current = {
                "id": f"{sub.group(1)}.{sub.group(2)}",
                "title": sub.group(3).strip(),
                "parent": top_title,
                "lines": [],
            }
        elif current is not None:
            current["lines"].append(line)
    close()

    top_ids = [c.section_id for c in chunks if "." not in c.section_id]
    if top_ids != [str(n) for n in range(1, 11)]:
        raise ValueError(f"Unexpected manual structure, found top-level sections {top_ids}")
    return chunks


@lru_cache(maxsize=1)
def load_policy_chunks() -> tuple[PolicyChunk, ...]:
    return tuple(parse_manual(extract_manual_text()))


def internal_guidelines_text() -> str:
    """Section 7 (WhatsApp service guidelines) and 10, as plain text for the agent's instructions."""
    parts = [f"{c.section_id} {c.title}\n{c.text}" for c in load_policy_chunks() if c.internal and c.text]
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- retrieval


def _stem(word: str) -> str:
    """Very light Portuguese stemming: plurals only (violões -> violao, cartões -> cartao)."""
    if word.endswith(("oes", "aes")):
        return word[:-3] + "ao"
    if len(word) > 4 and word.endswith("s"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", normalize_text(text))
    return [_stem(w) for w in words if w not in STOPWORDS]


def expand_query(query: str) -> list[str]:
    """Query tokens plus the manual's vocabulary for what the customer said."""
    raw_words = re.findall(r"[a-z0-9]+", normalize_text(query))
    expansion_words: list[str] = []
    for triggers, expansion in QUERY_EXPANSIONS:
        if any(word.startswith(trigger) for word in raw_words for trigger in triggers):
            expansion_words.append(expansion)
    tokens = tokenize(query) + tokenize(" ".join(expansion_words))
    return list(dict.fromkeys(tokens))


class PolicyIndex:
    """BM25 over the customer-facing chunks of the manual."""

    K1, B = 1.5, 0.75

    def __init__(self, chunks):
        self.chunks = [c for c in chunks if not c.internal and c.text]
        self.term_counts = [
            Counter(tokenize(f"{c.title} {c.title} {c.parent_title} {c.text}")) for c in self.chunks
        ]
        self.lengths = [sum(tc.values()) for tc in self.term_counts]
        self.avg_length = sum(self.lengths) / len(self.lengths)
        document_frequency = Counter(term for tc in self.term_counts for term in tc)
        n = len(self.chunks)
        self.idf = {t: math.log(1 + (n - df + 0.5) / (df + 0.5)) for t, df in document_frequency.items()}

    def search(self, query: str, top_k: int = 3) -> list[tuple[PolicyChunk, float]]:
        terms = expand_query(query)
        scored = []
        for chunk, counts, length in zip(self.chunks, self.term_counts, self.lengths):
            score = 0.0
            for term in terms:
                tf = counts.get(term, 0)
                if tf:
                    norm = tf * (self.K1 + 1) / (tf + self.K1 * (1 - self.B + self.B * length / self.avg_length))
                    score += self.idf[term] * norm
            if score >= MIN_SCORE:
                scored.append((chunk, score))
        scored.sort(key=lambda pair: -pair[1])
        if scored:
            scored = [pair for pair in scored if pair[1] >= RELATIVE_CUTOFF * scored[0][1]]
        return scored[:top_k]


@lru_cache(maxsize=1)
def get_index() -> PolicyIndex:
    return PolicyIndex(load_policy_chunks())
