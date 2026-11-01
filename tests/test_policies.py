import pytest

from emporio_agent.policies import (
    get_index,
    internal_guidelines_text,
    load_policy_chunks,
    parse_manual,
    tokenize,
)
from emporio_agent.tools.policies import search_policies


def sections(query, top_k=3):
    return [r["section"] for r in search_policies(query, top_k)["results"]]


def chunk(section_id):
    return next(c for c in load_policy_chunks() if c.section_id == section_id)


# ------------------------------------------------------------------ ingestion


def test_manual_is_split_into_the_expected_sections():
    ids = [c.section_id for c in load_policy_chunks()]
    assert [i for i in ids if "." not in i] == [str(n) for n in range(1, 11)]
    for expected in ("1.2", "3.1", "4.1", "4.2", "4.3", "4.4", "5.1", "5.2", "5.3", "6.1", "6.2", "8.1", "8.3"):
        assert expected in ids
    assert chunk("4.1").title == "Direito de Arrependimento (Compras Online)"
    assert chunk("4.1").path.startswith("4. Política de Trocas e Devoluções > 4.1")


def test_page_headers_and_footers_are_removed():
    full_text = " ".join(c.text for c in load_policy_chunks())
    assert "Página" not in full_text
    assert "Manual de Políticas e Procedimentos" not in full_text


def test_tables_and_bullets_survive_extraction():
    assert "Segunda a Sexta-feira | 09:00 às 18:00" in chunk("2").text
    assert "Sábado | 09:00 às 13:00" in chunk("2").text
    assert "PIX | Pagamento à vista | 5% de desconto sobre o preço de tabela" in chunk("3").text
    assert "- Parcelamento de 4x a 6x: sem juros, parcela mínima de R$ 80,00." in chunk("3.1").text
    assert "PAC (Correios) | 5 a 12 dias úteis | Sim | Incluído" in chunk("5.2").text


def test_labelled_paragraphs_are_kept_apart():
    lines = chunk("6.2").text.splitlines()
    assert any(line.startswith("Cumulatividade:") for line in lines)
    assert any(line.startswith("Estoque:") for line in lines)
    assert any(line.startswith("Comunicação:") for line in lines)


def test_internal_sections_are_flagged_and_available_for_the_prompt():
    internal = {c.section_id for c in load_policy_chunks() if c.internal}
    assert internal == {"7", "7.1", "7.2", "7.3", "10"}
    text = internal_guidelines_text()
    assert "Tom de voz" in text and "Promoção expirada" in text


def test_unexpected_structure_fails_loudly():
    with pytest.raises(ValueError, match="Unexpected manual structure"):
        parse_manual("1. Only one section\nSome text\n")


# ------------------------------------------------------------------ retrieval


@pytest.mark.parametrize(
    "query, expected_first",
    [
        ("Qual o endereço da loja?", "1.2"),
        ("Que horas vocês abrem no sábado?", "2"),
        ("Fecham no feriado?", "2"),
        ("Me arrependi da minha compra, posso devolver meu pedido?", "4.1"),
        ("Posso trocar a cor do violão?", "4.3"),
        ("Comprei e veio com defeito", "4.2"),
        ("Vocês vendem cordas de violão?", "1"),
        ("qual o formato do código de rastreamento", "5.3"),
        ("Quais dados pessoais vocês coletam?", "9"),
        ("Como excluir meus dados?", "9"),
        ("O que a garantia não cobre?", "8.3"),
        ("Tem promoção de black friday?", "6.1"),
        ("Quando a loja foi fundada?", "1.2"),
    ],
)
def test_customer_questions_find_the_right_section_first(query, expected_first):
    assert sections(query)[0] == expected_first


@pytest.mark.parametrize(
    "query, expected_somewhere",
    [
        ("Aceitam pix?", "3"),
        ("Posso parcelar em 12x?", "3.1"),
        ("Posso pagar metade no pix e metade no cartão?", "3.1"),
        ("o boleto demora pra compensar?", "3"),
        ("Quanto custa o frete pra Dourados?", "5.2"),
        ("entregam em Campo Grande?", "5.1"),
        ("Quanto tempo leva pra chegar em Corumbá?", "5.2"),
        ("Como funciona a garantia?", "8.1"),
        ("Qual o telefone de vocês?", "1.2"),
        ("Aceitam acessórios para troca?", "4.4"),
    ],
)
def test_customer_questions_find_the_right_section_in_the_top_results(query, expected_somewhere):
    assert expected_somewhere in sections(query, top_k=4)


def test_irrelevant_questions_return_nothing_instead_of_a_wrong_answer():
    for query in ("receita de bolo", "qual o clima hoje", "quem é o dono da loja"):
        result = search_policies(query)
        assert result["results"] == []
        assert "handoff_to_human" in result["note"]


def test_internal_guidelines_are_never_returned_to_the_customer_flow():
    queries = ["tom de voz", "fluxo de atendimento", "reclamação", "promoção expirada", "disposições finais",
               "qual o horário de retorno de uma reclamação"]
    for query in queries:
        assert not {"7", "7.1", "7.2", "7.3", "10"} & set(sections(query, top_k=5))


def test_plural_and_accent_variants_match():
    assert tokenize("Violões") == tokenize("violao") == ["violao"]
    assert tokenize("devoluções") == ["devolucao"]
    assert sections("DEVOLUÇÃO") == sections("devolucao")


def test_top_k_is_respected_and_bounded():
    assert len(sections("pagamento e frete e troca", top_k=2)) <= 2
    assert len(search_policies("pagamento", top_k=99)["results"]) <= 5
    assert len(search_policies("pagamento", top_k=0)["results"]) == 1


# ------------------------------------------------------------------ notes about inconsistencies


def test_contact_section_carries_the_phone_and_email_notes():
    result = search_policies("qual o telefone e o e-mail da loja?")["results"][0]
    assert result["section"] == "1.2"
    notes = " ".join(result["notes"])
    assert "(67) 3341-4444" in notes and "(67) 3321-4500" in notes
    assert "contato@emporiodamusica.com.br" in notes
    assert "emporiodamusica" in result["text"] or "empóriodamusica" in result["text"]  # raw text stays untouched


def test_installment_conflict_is_resolved_in_favour_of_section_3_1():
    results = search_policies("posso parcelar em 12x?")["results"]
    note = " ".join(n for r in results for n in r.get("notes", []))
    assert "3.1" in note and "calculate_payment_options" in note


def test_promotion_campaigns_are_not_presented_as_active_offers():
    result = search_policies("tem promoção de black friday?")["results"][0]
    assert result["section"] == "6.1"
    assert "never promise" in " ".join(result["notes"])


def test_index_only_contains_customer_facing_chunks():
    assert all(not c.internal and c.text for c in get_index().chunks)
