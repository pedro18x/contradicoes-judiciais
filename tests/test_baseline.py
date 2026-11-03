"""Baseline com um encoder falso (temas por palavra-chave): nenhum teste baixa modelo."""

from pathlib import Path

import numpy as np
import pytest

from src import baseline, evaluate
from src.contratos import ContradicaoGold, Gold, Segmentos, Trecho, ler_jsonl, texto_do_trecho
from src.preprocess import sentencas

FIX = Path(__file__).parent / "fixtures"
SEGS = {s.id: s for s in ler_jsonl(FIX / "segmentos.jsonl", Segmentos)}
GOLD = {g.id: g for g in ler_jsonl(FIX / "gold.jsonl", Gold)}
TEMAS = ["provi", "contrato", "alug", "dano", "indeniz", "recurso"]


def encoder_falso(frases):
    """Vetor = temas presentes na frase. Frases do mesmo tema ficam com cosseno alto."""
    return np.array([[float(t in f.lower()) for t in TEMAS] + [0.1] for f in frases])


def _achadas(preds):
    segs = SEGS[preds.id]
    return {
        (p.categoria, texto_do_trecho(segs, p.a), texto_do_trecho(segs, p.b))
        for p in preds.predicoes
        if p.contradicao
    }


def test_detecta_ce2_e_cif2_na_fixture():
    achadas = _achadas(baseline.prever(SEGS["FICT-0001"], limiar=0.7, encoder=encoder_falso))
    ementa = "CIVIL. CONTRATO DE LOCAÇÃO. COBRANÇA DE ALUGUÉIS. RECURSO PROVIDO."
    assert ("CE-2", ementa, "Ante o exposto, nego provimento ao recurso especial.") in achadas
    vigente = "O contrato de locação estava vigente entre janeiro e junho de 2020, conforme documentos juntados aos autos."
    assert (
        "CIF-2",
        vigente,
        "Por outro lado, o contrato de locação foi rescindido em dezembro de 2019.",
    ) in achadas


def test_negativo_sem_contradicao():
    preds = baseline.prever(SEGS["FICT-0002"], limiar=0.7, encoder=encoder_falso)
    assert preds.sistema == "baseline" and "limiar=0.7" in preds.modelo
    assert preds.predicoes  # comparou pares parecidos...
    assert not _achadas(preds)  # ...mas todos têm a mesma polaridade


def test_limiar_filtra_pares_pouco_parecidos():
    alto = baseline.prever(SEGS["FICT-0001"], limiar=0.95, encoder=encoder_falso)
    baixo = baseline.prever(SEGS["FICT-0001"], limiar=0.5, encoder=encoder_falso)
    assert len(alto.predicoes) < len(baixo.predicoes)
    assert all("cosseno" in p.justificativa for p in baixo.predicoes)


@pytest.mark.parametrize(
    "a, b, esperado",
    [
        ("O recurso foi provido.", "O recurso não foi provido.", "polaridade oposta"),
        ("Dou provimento ao recurso.", "Nego provimento ao recurso.", "polaridade oposta"),
        ("RECURSO IMPROVIDO.", "RECURSO PROVIDO.", "polaridade oposta"),
        # concordância negativa: "não ... nenhuma" continua sendo uma negação só
        ("Não há nenhuma prova do pagamento.", "Há prova do pagamento.", "polaridade oposta"),
        ("Não há prova do pagamento.", "Não há nenhuma prova do pagamento.", None),
        ("O contrato estava vigente.", "O contrato foi rescindido.", "antônimos: vigente × rescindido"),
        ("As cobranças são devidas.", "A cobrança é indevida.", "antônimos: devido × indevido"),
        # negação + antônimo dizem o mesmo
        ("Os embargos não são cabíveis.", "Os embargos são incabíveis.", None),
        ("O contrato não foi rescindido.", "O contrato estava vigente.", None),
    ],
)
def test_regras(a, b, esperado):
    assert baseline._conflito(baseline._palavras(a), baseline._palavras(b)) == esperado


def test_f1_pares():
    g = GOLD["FICT-0001"]
    perfeito = baseline.Predicoes(
        id=g.id,
        sistema="baseline",
        modelo="x",
        predicoes=[
            baseline.Predicao(a=c.b, b=c.a, contradicao=True) for c in g.contradicoes
        ],  # ordem trocada
    )
    assert baseline.f1_pares([perfeito], [g]) == 1.0
    metade = perfeito.model_copy(update={"predicoes": perfeito.predicoes[:1]})
    assert baseline.f1_pares([metade], [g]) == pytest.approx(2 * 1 * (1 / 3) / (1 + 1 / 3))
    # trecho previsto que cobre o trecho gold inteiro também acerta (CE-2: ementa toda × "RECURSO PROVIDO")
    ementa_toda = Trecho(segmento="ementa", inicio=0, fim=len(SEGS[g.id].ementa))
    ce2 = baseline.Predicao(a=ementa_toda, b=g.contradicoes[2].b, contradicao=True)
    assert evaluate.acerta(ce2, g.contradicoes[2])


def test_f1_um_para_um_e_cobertura_do_gold():
    fund = "Primeira. Segunda. Terceira. Quarta."
    s1, s2, s3, s4 = (Trecho(segmento="fundamentacao", inicio=a, fim=b) for a, b in sentencas(fund))
    tres = Trecho(segmento="fundamentacao", inicio=s1.inicio, fim=s3.fim)
    gold = Gold(id="x", contradicoes=[ContradicaoGold(categoria="CIF-2", a=tres, b=s4)])

    def preds(*pares):
        ps = [baseline.Predicao(a=a, b=b, contradicao=True) for a, b in pares]
        return baseline.Predicoes(id="x", sistema="baseline", modelo="m", predicoes=ps)

    # a frase alterada (s4) com outra frase da fundamentação acerta; as outras duas são repetição
    m = evaluate.metricas([preds((s1, s4), (s2, s4), (s3, s4))], [gold])
    assert (m["par"]["global"]["f1"], m["par"]["global"]["fp"], m["par"]["vp_estrito"]) == (1.0, 0, 0)
    # sem a frase alterada: não acerta
    assert baseline.f1_pares([preds((s1, s2))], [gold]) == 0.0
    # duas predições no mesmo par gold: uma acerta, a outra é repetição
    assert baseline.f1_pares([preds((tres, s4), (s4, tres))], [gold]) == 1.0


# Par gold com cosseno 0,6: o melhor limiar é 0,6 se o treino tem esse par como contradição; se o
# treino não tem nenhuma, nenhum limiar dá F1 > 0 e o empate vai para o maior (0,95).
VETORES = {"O contrato estava vigente.": [1.0, 0.0], "O contrato foi rescindido.": [0.6, 0.8]}
FOLDS = [["d0", "d1"], ["d2", "d3"], ["d4", "d5"]]


def encoder_controlado(frases):
    return np.array([VETORES[f] for f in frases])


def _decisoes():
    segs, gold = [], []
    for i in range(6):
        fund = "O contrato estava vigente. O contrato foi rescindido."
        segs.append(Segmentos(id=f"d{i}", ementa="", relatorio="", fundamentacao=fund, dispositivo=""))
        a, b = (Trecho(segmento="fundamentacao", inicio=x, fim=y) for x, y in sentencas(fund))
        gold.append(Gold(id=f"d{i}", contradicoes=[ContradicaoGold(categoria="CIF-2", a=a, b=b)]))
    return segs, gold


def _sem_gold(gold, ids):
    return [g.model_copy(update={"contradicoes": []}) if g.id in ids else g for g in gold]


def test_limiar_de_cada_fold_usa_so_o_gold_de_treino():
    segs, gold = _decisoes()
    preds, limiares = baseline.validacao_cruzada(segs, gold, FOLDS, encoder=encoder_controlado)
    assert [p.id for p in preds] == [id for f in FOLDS for id in f]
    assert limiares == [0.6, 0.6, 0.6]
    assert all(p.predicoes[0].contradicao and "limiar=0.6" in p.modelo for p in preds)

    # mexer no gold do fold 0 (teste) não muda o limiar do fold 0...
    _, limiares = baseline.validacao_cruzada(
        segs, _sem_gold(gold, FOLDS[0]), FOLDS, encoder=encoder_controlado
    )
    assert limiares[0] == 0.6
    # ...mexer no gold dos folds de treino muda
    _, limiares = baseline.validacao_cruzada(
        segs, _sem_gold(gold, FOLDS[1] + FOLDS[2]), FOLDS, encoder=encoder_controlado
    )
    assert limiares[0] == 0.95

    with pytest.raises(ValueError, match="d9"):
        baseline.validacao_cruzada(segs, gold, FOLDS + [["d9"]], encoder=encoder_controlado)
