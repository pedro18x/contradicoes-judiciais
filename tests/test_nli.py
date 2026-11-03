from pathlib import Path

import pytest

from src import argmining, nli
from src.contratos import Gold, Pares, Predicoes, Proposicoes, Segmentos, ler_jsonl, texto_do_trecho

FIX = Path(__file__).parent / "fixtures"
SEGS = ler_jsonl(FIX / "segmentos.jsonl", Segmentos)
PROPS = ler_jsonl(FIX / "proposicoes.jsonl", Proposicoes)
PARES = ler_jsonl(FIX / "pares.jsonl", Pares)
GOLD = ler_jsonl(FIX / "gold.jsonl", Gold)


@pytest.fixture
def respostas(monkeypatch):
    """LLM falso: devolve as respostas da fila em ordem e guarda (prompt, system)."""

    class Falso:
        def __init__(self):
            self.fila, self.chamadas = [], []

        def __call__(self, prompt, *, system="", model=None, etapa=None):
            self.chamadas.append((prompt, system))
            return self.fila.pop(0) if self.fila else {"resultados": []}

    falso = Falso()
    monkeypatch.setattr(nli.llm, "complete_json", falso)
    return falso


def test_fixture_valida_como_predicoes(llm_fixtures):
    preds = nli.classificar(SEGS[0], PROPS[0], PARES[0])
    assert Predicoes.model_validate_json(preds.model_dump_json()) == preds
    assert len(preds.predicoes) == len(PARES[0].pares)
    achadas = {
        (texto_do_trecho(SEGS[0], p.a)[:25], texto_do_trecho(SEGS[0], p.b)[:25], p.categoria)
        for p in preds.predicoes
        if p.contradicao
    }
    assert achadas == {
        ("Assim, é devida a cobranç", "nego provimento ao recurs", "CDF-1"),
        ("Por outro lado, o contrat", "O contrato de locação est", "CIF-2"),
    }
    assert preds.sistema == "am+llm"
    assert preds.modelo == "ma=modelo-teste; nli=modelo-teste; esforco=medium"
    assert nli.classificar(SEGS[1], PROPS[1], PARES[1]).predicoes  # negativa: pares, nenhuma contradição
    assert not any(p.contradicao for p in nli.classificar(SEGS[1], PROPS[1], PARES[1]).predicoes)


def test_lotes_com_todos_os_pares(respostas):
    todos = argmining.todos_pares(PROPS[0])  # 6 proposições = 15 pares
    preds = nli.classificar(SEGS[0], PROPS[0], todos, sistema="todos+llm")
    assert len(respostas.chamadas) == 2  # 10 + 5
    assert respostas.chamadas[0][0].count("\n    B (") == nli.LOTE
    assert len(preds.predicoes) == 15 and preds.sistema == "todos+llm"


def test_respostas_invalidas(respostas, caplog):
    pares = Pares(id="FICT-0001", pares=PARES[0].pares[:4])
    respostas.fila = [
        {
            "resultados": [
                {"i": 0, "contradicao": True, "categoria": "XYZ-9", "justificativa": "x"},
                {"i": 1, "contradicao": False, "categoria": "CDF-1"},
                {"i": 2, "contradicao": True, "categoria": "CIF-2", "justificativa": "ok"},
                {"i": 2, "contradicao": False},  # repetido: vale o primeiro
                {"i": 3, "contradicao": True, "categoria": "CIL-1"},  # na taxonomia, fora do alvo
                {"i": 9, "contradicao": True},  # fora do lote
                "lixo",
            ]
        }
    ]
    preds = nli.classificar(SEGS[0], PROPS[0], pares).predicoes
    assert [(p.contradicao, p.categoria) for p in preds] == [
        (True, None),  # categoria fora da taxonomia
        (False, None),  # sem contradição não leva categoria
        (True, "CIF-2"),
        (True, None),  # CIL-1 não é alvo do sistema
    ]
    assert preds[2].justificativa == "ok"
    assert "XYZ-9" in caplog.text and "CIL-1" in caplog.text and "lixo" in caplog.text


def test_pid_inexistente_e_ignorado(respostas, caplog):
    pares = Pares(id="FICT-0001", pares=[PARES[0].pares[0].model_copy(update={"par": ("p1", "p99")})])
    assert nli.classificar(SEGS[0], PROPS[0], pares).predicoes == []
    assert respostas.chamadas == [] and "p99" in caplog.text


def test_exemplos_do_treino_entram_no_prompt(respostas):
    exemplos = nli.exemplos_do_gold(SEGS, GOLD)
    assert len(exemplos) == 3
    assert exemplos[2]["a"] == ("ementa", "RECURSO PROVIDO") and exemplos[2]["categoria"] == "CE-2"
    nli.classificar(SEGS[0], PROPS[0], PARES[0], exemplos=exemplos)
    system = respostas.chamadas[0][1]
    assert "Exemplos de contradições" in system and 'A (ementa): "RECURSO PROVIDO"' in system
    assert "{{" not in system
    nli.classificar(SEGS[0], PROPS[0], PARES[0])
    assert "Exemplos de contradições" not in respostas.chamadas[-1][1] and "{{" not in respostas.chamadas[-1][1]


def _prob_por_texto(notas):
    """Modelo NLI falso: P(contradição) pela 1ª palavra da premissa e da hipótese; 0,1 se não listado."""

    def prob(pares):
        return [notas.get((a.split()[0], b.split()[0]), 0.1) for a, b in pares]

    return prob


def test_local_usa_o_maior_sentido_e_categoria_por_segmento():
    # p5 ("Por outro lado...") × p2 ("O contrato...") só é alto no sentido (p2, p5); p4 × p6 é CDF-1
    prob = _prob_por_texto({("O", "Por"): 0.9, ("Assim,", "nego"): 0.8, ("RECURSO", "nego"): 0.3})
    preds = nli.classificar_local(SEGS[0], PROPS[0], PARES[0], limiar=0.5, prob_contradicao=prob)
    achadas = {(p.a.segmento, p.b.segmento, p.categoria) for p in preds.predicoes if p.contradicao}
    assert achadas == {("fundamentacao", "fundamentacao", "CIF-2"), ("fundamentacao", "dispositivo", "CDF-1")}
    assert (
        preds.sistema == "am+nli-local"
        and nli.REVISAO_LOCAL[:7] in preds.modelo
        and "limiar=0.5" in preds.modelo
    )
    assert all(p.categoria is None for p in preds.predicoes if not p.contradicao)
    assert "P(contradição) = 0.30" in {p.justificativa for p in preds.predicoes}


def test_local_limiar_ajustado_so_no_treino():
    gold = {g.id: g for g in GOLD}
    prob = _prob_por_texto({("O", "Por"): 0.9, ("Assim,", "nego"): 0.8, ("RECURSO", "nego"): 0.3})
    pontuados = {s.id: nli.pontuar_local(s, p, x, prob) for s, p, x in zip(SEGS, PROPS, PARES)}
    # 0,30 pega as 3 contradições do gold sem falso positivo: F1 = 1
    assert nli.ajustar_limiar_local(pontuados, gold) == 0.3
    # se o gold de treino não tivesse a CE-2, o melhor limiar seria acima de 0,30
    sem_ce2 = {**gold, "FICT-0001": Gold(id="FICT-0001", contradicoes=GOLD[0].contradicoes[:2])}
    assert nli.ajustar_limiar_local(pontuados, sem_ce2) == 0.8


def test_local_sem_pares_validos_nao_carrega_o_modelo(monkeypatch):
    monkeypatch.setattr(nli, "carregar_nli_local", lambda *a: pytest.fail("não devia carregar o modelo"))
    vazio = Pares(id="FICT-0001", pares=[])
    assert nli.classificar_local(SEGS[0], PROPS[0], vazio).predicoes == []


def test_prompt_v2_acrescenta_regras_sem_mudar_o_padrao(respostas):
    nli.classificar(SEGS[0], PROPS[0], PARES[0])
    preds = nli.classificar(SEGS[0], PROPS[0], PARES[0], prompt="nli_v2")
    v1, v2 = respostas.chamadas[0][1], respostas.chamadas[-1][1]
    assert "agravo interno" not in v1 and "nego provimento ao agravo interno" in v2
    assert "{{" not in v2 and '"i": 3, "contradicao": false' in v2
    assert preds.modelo.endswith("; prompt=nli_v2")
