from pathlib import Path

from src import llm, pipeline
from src.contratos import texto_do_trecho

TEXTO = (Path(__file__).parent / "fixtures" / "exemplo.txt").read_text(encoding="utf-8")


def test_run_de_ponta_a_ponta(llm_fixtures):
    segs, preds = pipeline.run(TEXTO, id="X")
    assert segs.id == preds.id == "X"
    for p in preds.predicoes:
        assert texto_do_trecho(segs, p.a).strip()
        assert texto_do_trecho(segs, p.b).strip()
    assert any(p.contradicao for p in preds.predicoes)


def test_cli(capsys, llm_fixtures):
    pipeline.main(str(Path(__file__).parent / "fixtures" / "exemplo.txt"))
    saida = capsys.readouterr().out
    assert "2 contradição(ões)" in saida
    assert "[CDF-1] Conclusão Invertida" in saida


def test_cada_etapa_usa_o_modelo_configurado(provedor_fixtures, monkeypatch):
    monkeypatch.setenv("LLM_MODEL_MA", "modelo-ma")
    monkeypatch.setenv("LLM_MODEL_NLI", "modelo-nli")
    _, preds = pipeline.run(TEXTO, id="X")
    modelos = {}
    for titulo, modelo in provedor_fixtures:
        modelos.setdefault(titulo.split(" (")[0], set()).add(modelo)
    assert modelos == {"# Proposições": {"modelo-ma"}, "# Pares": {"modelo-ma"}, "# NLI": {"modelo-nli"}}
    assert preds.modelo.startswith("ma=modelo-ma; nli=modelo-nli;")
    assert {e: list(m) for e, m in llm.custo_acumulado()["por_etapa"].items()} == {
        "ma": ["modelo-ma"],
        "nli": ["modelo-nli"],
    }
