from pathlib import Path

import pytest

from src import argmining
from src.contratos import CATEGORIAS, Pares, Proposicoes, Segmentos, ler_jsonl, texto_do_trecho

FIX = Path(__file__).parent / "fixtures"
SEGS = ler_jsonl(FIX / "segmentos.jsonl", Segmentos)
PROPS = ler_jsonl(FIX / "proposicoes.jsonl", Proposicoes)


@pytest.fixture
def resposta(monkeypatch):
    """LLM falso que devolve sempre `resposta.valor` e guarda (prompt, system)."""

    class Falso:
        def __init__(self):
            self.valor, self.chamadas = {}, []

        def __call__(self, prompt, *, system="", model=None, etapa=None):
            self.chamadas.append((prompt, system))
            return self.valor

    falso = Falso()
    monkeypatch.setattr(argmining.llm, "complete_json", falso)
    return falso


@pytest.mark.parametrize("i", range(len(SEGS)), ids=[s.id for s in SEGS])
def test_proposicoes_da_fixture_com_offsets_certos(llm_fixtures, i):
    props = argmining.proposicoes(SEGS[i])
    assert props == PROPS[i]
    for p in props.proposicoes:
        assert texto_do_trecho(SEGS[i], p) == p.texto


def test_proposicao_fora_do_texto_e_descartada(resposta, caplog):
    segs = Segmentos(id="X", ementa="", relatorio="", fundamentacao="A é B. A é B. C é D.", dispositivo="")
    resposta.valor = {"proposicoes": ["A é B.", "texto inventado", " A é B. ", "C é D.", 3, "C é D."]}
    props = argmining.proposicoes(segs)
    # o segundo "A é B." é a segunda ocorrência; o "C é D." repetido não duplica
    assert [(p.pid, p.inicio, p.fim) for p in props.proposicoes] == [
        ("p1", 0, 6),
        ("p2", 7, 13),
        ("p3", 14, 20),
    ]
    assert "texto inventado" in caplog.text
    assert len(resposta.chamadas) == 1  # segmentos vazios não chamam o LLM
    assert "Segmento: fundamentacao" in resposta.chamadas[0][0]
    assert "CDF-1" not in resposta.chamadas[0][1] and "Proposições (v1)" in resposta.chamadas[0][1]


def test_resposta_sem_lista_nao_quebra(resposta, caplog):
    resposta.valor = ["não é o formato"]
    assert argmining.proposicoes(SEGS[0]).proposicoes == []
    assert "sem a lista" in caplog.text


def test_pares_da_fixture_mais_estruturais(llm_fixtures):
    for segs, props, esperado in zip(SEGS, PROPS, ler_jsonl(FIX / "pares.jsonl", Pares)):
        assert argmining.pares(segs, props) == esperado
    rel = {p.par: p.relacao for p in argmining.pares(SEGS[0], PROPS[0]).pares}
    assert rel[("p4", "p6")] == "conclusao-dispositivo"
    assert rel[("p1", "p6")] == "ementa-dispositivo"  # par do CE-2 do gold, sem depender do LLM
    assert llm_fixtures.chamadas[-1][0] == "# Pares (v1)"


def test_pares_invalidos_sao_descartados(resposta, caplog):
    resposta.valor = {
        "conclusoes": ["p4", "p6", "p99"],  # p6 é do dispositivo: não é conclusão da fundamentação
        "pares": [
            {"a": "p2", "b": "p4", "relacao": "premissa-conclusao"},
            {"a": "p4", "b": "p2", "relacao": "premissa-premissa"},  # repetido em outra ordem
            {"a": "p2", "b": "p2", "relacao": "premissa-premissa"},
            {"a": "p2", "b": "p77", "relacao": "premissa-conclusao"},
            {"a": "p2", "b": "p3", "relacao": "inventada"},
            "lixo",
        ],
    }
    pares = argmining.pares(SEGS[0], PROPS[0])
    assert [(p.par, p.relacao) for p in pares.pares] == [
        (("p2", "p4"), "premissa-conclusao"),
        (("p4", "p6"), "conclusao-dispositivo"),
        (("p1", "p6"), "ementa-dispositivo"),
    ]
    assert "p77" in caplog.text and "p99" in caplog.text and "inventada" in caplog.text


def test_pares_com_menos_de_duas_proposicoes_nao_chama_o_llm(resposta):
    um = Proposicoes(id="X", proposicoes=PROPS[0].proposicoes[:1])
    assert argmining.pares(SEGS[0], um).pares == []
    assert resposta.chamadas == []


def test_todos_pares():
    todos = argmining.todos_pares(PROPS[0])
    n = len(PROPS[0].proposicoes)
    assert len(todos.pares) == n * (n - 1) // 2
    assert len({frozenset(p.par) for p in todos.pares}) == len(todos.pares)
    assert all(p.origem == "todos" and p.relacao == "todos" for p in todos.pares)


def test_prompt_traz_a_taxonomia():
    system = argmining.carregar_prompt("pares")
    assert "{{categorias}}" not in system
    assert "CE-2: Ementa vs. Dispositivo" in system


def test_prompts_listam_so_as_categorias_alvo():
    for nome in ("pares", "nli"):
        system = argmining.carregar_prompt(nome)
        assert all(f"- {c}:" in system for c in argmining.CATEGORIAS_ALVO)
        assert "- CIF-1:" not in system and "- CIL-1:" not in system
    assert len(argmining.CATEGORIAS_ALVO) == 7 and len(CATEGORIAS) == 9  # a taxonomia não muda
