from pathlib import Path

from demo import destacar
from src.contratos import Proposicoes, Segmentos, ler_jsonl

FIX = Path(__file__).parent / "fixtures"


def test_destaca_trecho_da_fixture():
    segs = ler_jsonl(FIX / "segmentos.jsonl", Segmentos)[0]
    p = ler_jsonl(FIX / "proposicoes.jsonl", Proposicoes)[0].proposicoes[3]  # "Assim, é devida..."
    md = destacar(segs.fundamentacao, p.inicio, p.fim)
    assert f":red[**{p.texto}**]" in md


def test_escapa_markdown():
    md = destacar("Valor de R$ 100 e R$ 200 [sic]", 0, 5)
    assert "R\\$ 100" in md and "\\[sic\\]" in md


def test_corta_contexto():
    seg = "a" * 1000 + "TRECHO" + "b" * 1000
    md = destacar(seg, 1000, 1006, contexto=10)
    assert md == "…" + "a" * 10 + ":red[**TRECHO**]" + "b" * 10 + "…"
