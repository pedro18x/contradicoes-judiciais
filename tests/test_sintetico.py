"""Contradições sintéticas: cada regra insere a contradição certa e o gold aponta os trechos certos."""

import pytest

from src import sintetico as st
from src.contratos import Segmentos, texto_do_trecho

# decisão fictícia sem contradição, com os fatos que as regras procuram
BASE = Segmentos(
    id="FICT-S1",
    ementa="CIVIL. LOCAÇÃO. COBRANÇA.\n1. Valor fixado com razoabilidade.\n2. Agravo interno desprovido.",
    relatorio=(
        "Trata-se de agravo interno contra decisão que manteve a condenação. A sentença julgou procedente o "
        "pedido em 12/03/2019. Alega a agravante que o valor de R$ 9.000,00 é excessivo."
    ),
    fundamentacao=(
        "A sentença julgou procedente o pedido, condenando a ré ao pagamento de R$ 10.000,00 (dez mil reais). "
        "O prazo prescricional de 3 (três) anos foi observado. O contrato foi firmado em 12/03/2019, conforme "
        "os autos. Os honorários foram fixados em 10% (dez por cento) sobre a condenação. A cobrança de "
        "R$ 10.000,00 é devida, e o prazo prescricional de 3 anos não se consumou. Desde 12/03/2019 o "
        "contrato está em vigor. Assim, a decisão agravada deve ser mantida."
    ),
    dispositivo="Ante o exposto, nego provimento ao agravo interno, mantidos os honorários de 10%.",
)


def _trechos(categoria):
    novo, g = st.REGRAS[categoria](BASE)
    assert g.categoria == categoria and g.justificativa
    return novo, texto_do_trecho(novo, g.a), texto_do_trecho(novo, g.b), g


def test_cdf1_inverte_dispositivo_e_ementa_e_aponta_a_conclusao():
    novo, a, b, g = _trechos("CDF-1")
    assert a == "Assim, a decisão agravada deve ser mantida."
    assert b.startswith("Ante o exposto, dou provimento ao agravo interno")
    assert "2. Agravo interno provido." in novo.ementa  # a ementa acompanha: só a fundamentação diverge
    assert (g.a.segmento, g.b.segmento) == ("fundamentacao", "dispositivo")


def test_ce2_inverte_so_a_ementa():
    novo, a, b, g = _trechos("CE-2")
    assert b == "2. Agravo interno provido." and a.startswith("Ante o exposto, nego provimento")
    assert (g.a.segmento, g.b.segmento) == ("dispositivo", "ementa")
    assert novo.dispositivo == BASE.dispositivo


@pytest.mark.parametrize("categoria", st.CATEGORIAS_SINTETICAS)
def test_b_e_sempre_a_frase_alterada(categoria):
    _, a, b, g = _trechos(categoria)
    assert a in getattr(BASE, g.a.segmento)  # a frase que ficou existe no texto original
    assert b not in getattr(BASE, g.b.segmento)  # a frase alterada não


def test_cdf2_valor_do_dispositivo_diverge_da_fundamentacao():
    novo, a, b, _ = _trechos("CDF-2")
    assert "10% (dez por cento)" in a and b.endswith("mantidos os honorários de 20%.")
    assert novo.fundamentacao == BASE.fundamentacao


def test_ce1_fato_do_relatorio_muda_na_fundamentacao():
    novo, a, b, _ = _trechos("CE-1")
    assert a == "A sentença julgou procedente o pedido em 12/03/2019."
    assert b.startswith("A sentença julgou improcedente o pedido")
    assert novo.relatorio == BASE.relatorio


def test_cif2_e_cif3_mudam_a_segunda_mencao_na_fundamentacao():
    _, a, b, g = _trechos("CIF-2")
    assert "R$ 10.000,00 (dez mil reais)" in a and b.startswith("A cobrança de R$ 20.000,00 é devida")
    assert g.a.fim <= g.b.inicio  # o trecho a não se desloca com a troca
    _, a, b, _ = _trechos("CIF-3")
    assert "prazo prescricional de 3 (três) anos" in a and "prazo prescricional de 10 anos" in b


def test_tese_da_parte_e_citacao_nao_viram_trecho():
    # o único "R$ 9.000,00" está na alegação da agravante; precedente citado também não conta
    s = BASE.model_copy(
        update={
            "fundamentacao": "O valor de R$ 9.000,00 (AgInt no REsp 1/SP, julgado em 1/1/2020) é razoável.",
            "dispositivo": "Ante o exposto, nego provimento, fixado o valor de R$ 9.000,00.",
        }
    )
    assert st.cdf2(s) is None and st.ce1(s) is None
    sem_conclusao = BASE.model_copy(update={"fundamentacao": "Os autos foram examinados."})
    assert st.cdf1(sem_conclusao) is None


def test_gerar_metade_alterada_categorias_rotativas_e_deterministico():
    bases = [BASE.model_copy(update={"id": f"FICT-S{i}"}) for i in range(12)]
    segs, gold = st.gerar(bases)
    assert segs == st.gerar(list(reversed(bases)))[0]  # não depende da ordem de entrada
    assert sorted(g.id for g in gold) == sorted(b.id for b in bases)
    positivos = [g for g in gold if g.contradicoes]
    assert len(positivos) == 6 and all(len(g.contradicoes) == 1 for g in positivos)
    assert sorted(g.contradicoes[0].categoria for g in positivos) == sorted(st.CATEGORIAS_SINTETICAS)
    por_id = {s.id: s for s in segs}
    for g in gold:  # o gold aponta para o texto alterado; os negativos ficam intactos
        if g.contradicoes:
            assert texto_do_trecho(por_id[g.id], g.contradicoes[0].b)
        else:
            assert por_id[g.id].model_dump(exclude={"id"}) == BASE.model_dump(exclude={"id"})


@pytest.mark.parametrize(
    "achado, novo",
    [
        ("R$ 50.000,00 (cinquenta mil reais)", "R$ 100.000,00"),
        ("30%", "15%"),
        ("5 de maio de 2019", "5 de maio de 2020"),
        ("JULGOU IMPROCEDENTE", "JULGOU PROCEDENTE"),
        ("prazo decadencial de 5 anos", "prazo decadencial de 3 anos"),
    ],
)
def test_alterar_valor(achado, novo):
    assert st._alterar_valor(achado) == novo
