"""Garante que as fixtures seguem os contratos e que os offsets apontam para o texto certo."""

from pathlib import Path

from src.contratos import (
    CATEGORIAS,
    Decisao,
    Gold,
    Pares,
    Predicoes,
    Proposicoes,
    Segmentos,
    ler_jsonl,
    texto_do_trecho,
)

FIX = Path(__file__).parent / "fixtures"


def test_fixtures_validam():
    for nome, modelo in [
        ("decisoes", Decisao), ("segmentos", Segmentos), ("proposicoes", Proposicoes),
        ("pares", Pares), ("predicoes", Predicoes), ("gold", Gold),
    ]:
        assert ler_jsonl(FIX / f"{nome}.jsonl", modelo), nome


def test_offsets_batem_com_texto():
    segs = {s.id: s for s in ler_jsonl(FIX / "segmentos.jsonl", Segmentos)}
    for doc in ler_jsonl(FIX / "proposicoes.jsonl", Proposicoes):
        for p in doc.proposicoes:
            assert texto_do_trecho(segs[doc.id], p) == p.texto


def test_pares_referenciam_pids_existentes():
    pids = {d.id: {p.pid for p in d.proposicoes} for d in ler_jsonl(FIX / "proposicoes.jsonl", Proposicoes)}
    for doc in ler_jsonl(FIX / "pares.jsonl", Pares):
        for par in doc.pares:
            assert set(par.par) <= pids[doc.id]


def test_taxonomia_completa():
    assert len(CATEGORIAS) == 9
