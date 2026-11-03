import json
import shutil
from pathlib import Path

import pytest

from scripts import experimento
from src import baseline, nli
from src.contratos import Gold, Predicoes, Segmentos, ler_jsonl

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def dados(tmp_path, monkeypatch):
    """Corpus = as 2 fixtures, k = 2 (um fold por decisão), encoder e NLI local falsos."""
    d = tmp_path / "data"
    d.mkdir()
    for nome in ("segmentos", "gold"):
        shutil.copy(FIX / f"{nome}.jsonl", d / f"{nome}.jsonl")
    (d / "splits.json").write_text(json.dumps({"seed": 42, "k": 2, "folds": [["FICT-0001"], ["FICT-0002"]]}))
    monkeypatch.setattr(
        baseline, "carregar_encoder", lambda modelo=None: lambda frases: [[1.0, 0.0]] * len(frases)
    )
    monkeypatch.setattr(nli, "carregar_nli_local", lambda: lambda pares: [0.2] * len(pares))
    return d


def _rodar(dados, *extra):
    docs = dados.parent / "docs"
    return experimento.main(["--dados", str(dados), "--docs", str(docs), *extra]), docs


def test_ablacao_completa(dados, llm_fixtures):
    r, docs = _rodar(dados, "--sistemas", *experimento.SISTEMAS)
    for sistema in experimento.SISTEMAS:
        for k in (0, 1):
            preds = ler_jsonl(dados / "resultados" / sistema / f"fold{k}.jsonl", Predicoes)
            assert [p.id for p in preds] == [["FICT-0001"], ["FICT-0002"]][k]
            assert all(p.sistema == sistema for p in preds)
    # C (am+llm): acha CDF-1 e CIF-2 na FICT-0001 e perde a CE-2; nada na FICT-0002
    c = r["sistemas"]["am+llm"]["geral"]
    assert (c["par"]["global"]["vp"], c["par"]["global"]["fp"], c["par"]["global"]["fn"]) == (2, 0, 1)
    assert (c["decisao"]["vp"], c["decisao"]["vn"]) == (1, 1)
    assert r["ma"]["cobertura"] == 1.0 and r["ma"]["pares"] == 7
    # referências da MA com as mesmas proposições: todos os pares (teto) e os mais similares no mesmo número
    assert r["ma_referencias"]["todos"]["pares"] == 18
    assert r["ma_referencias"]["similaridade"]["pares"] == 7
    # pares classificados por sistema: B classifica todos, C e D só os da MA
    assert r["pares_classificados"] == {"todos+llm": 18, "am+llm": 7, "am+nli-local": 7}
    assert len(r["limiares"]["baseline"]) == len(r["limiares"]["am+nli-local"]) == 2
    md = (docs / "ablacao_sintetica.md").read_text()
    for sistema in experimento.SISTEMAS:
        assert f"| {sistema} |" in md
    assert "| CDF-1 |" in md and "Custo do LLM" in md
    ma = (docs / "ma.md").read_text()
    assert "| Mineração de Argumentos | 7 | 0,389 | 1,000 (3 de 3) |" in ma
    assert "| Todos os pares | 18 | 1,000 |" in ma and "| CE-2 (1) |" in ma
    assert json.loads((docs / "ablacao_sintetica.json").read_text())["k"] == 2


def test_few_shot_so_do_treino(dados, llm_fixtures):
    _rodar(dados, "--sistemas", "am+llm")
    nli_chamadas = [p for s, p in llm_fixtures.chamadas if s == "# NLI (v1)"]
    assert nli_chamadas  # houve classificação
    segs = {s.id: s for s in ler_jsonl(FIX / "segmentos.jsonl", Segmentos)}
    gold = {g.id: g for g in ler_jsonl(FIX / "gold.jsonl", Gold)}
    # no fold 0 a FICT-0001 é teste e o treino (FICT-0002) não tem contradições: sem exemplos anotados
    assert experimento.exemplos_do_treino([segs["FICT-0002"]], [gold["FICT-0002"]], 2, 42) == []
    # com o gold da FICT-0001 no treino, entra no máximo 1 exemplo por categoria quando o limite é 1
    ex = experimento.exemplos_do_treino([segs["FICT-0001"]], [gold["FICT-0001"]], 1, 42)
    assert sorted(e["categoria"] for e in ex) == ["CDF-1", "CE-2", "CIF-2"]


def test_top_k_limita_o_sistema_b(dados, llm_fixtures, monkeypatch):
    r, _ = _rodar(dados, "--sistemas", "todos+llm", "--max-pares-todos", "4")
    assert all(
        len(p.predicoes) <= 4 for p in ler_jsonl(dados / "resultados/todos+llm/fold0.jsonl", Predicoes)
    )
    assert r["sistemas"]["todos+llm"]["geral"]["decisoes"] == 2


def test_b_com_o_mesmo_numero_de_pares_da_ma(dados, llm_fixtures):
    """--max-pares-todos am: em cada decisão, B classifica tantos pares quanto a MA selecionou."""
    r, docs = _rodar(dados, "--sistemas", "todos+llm", "am+llm", "--max-pares-todos", "am")
    pasta = dados / "resultados" / "todos+llm"
    por_id = {p.id: p for k in (0, 1) for p in ler_jsonl(pasta / f"fold{k}.jsonl", Predicoes)}
    assert len(por_id["FICT-0001"].predicoes) <= 5 and len(por_id["FICT-0002"].predicoes) <= 2
    assert r["pares_classificados"]["todos+llm"] == r["pares_classificados"]["am+llm"] == 7
    assert "mesmo número de pares que a MA" in (docs / "ablacao_sintetica.md").read_text()


def test_estimar_nao_chama_o_llm(dados, llm_fixtures, capsys):
    assert _rodar(dados, "--estimar", "--sistemas", "todos+llm", "am+llm")[0] == {}
    assert llm_fixtures.chamadas == []
    out = capsys.readouterr().out
    assert "2 decisões" in out and "NLI todos+llm" in out


def test_avaliacao_pelo_rotulo_do_tribunal(dados, llm_fixtures, monkeypatch):
    """Mesmas decisões, mas só o rótulo do STJ: métrica por decisão, few-shot vindo do corpus sintético."""
    classificar, exemplos_usados = nli.classificar, []

    def espiao(segs, props, pares, exemplos=(), sistema="am+llm"):
        exemplos_usados.append((segs.id, sorted(e["categoria"] for e in exemplos)))
        return classificar(segs, props, pares, exemplos, sistema=sistema)

    monkeypatch.setattr(nli, "classificar", espiao)
    tribunal = dados.parent / "tribunal"
    tribunal.mkdir()
    shutil.copy(dados / "segmentos.jsonl", tribunal / "segmentos.jsonl")
    shutil.copy(dados / "splits.json", tribunal / "splits.json")
    (tribunal / "rotulos.json").write_text(json.dumps({"FICT-0001": True, "FICT-0002": False}))
    docs = dados.parent / "docs"
    r = experimento.main(
        ["--avaliacao", "tribunal", "--dados", str(tribunal), "--exemplos", str(dados), "--docs", str(docs),
         "--sistemas", *experimento.SISTEMAS]
    )  # fmt: skip
    c = r["sistemas"]["am+llm"]["geral"]["decisao"]
    assert (c["vp"], c["fp"], c["fn"], c["vn"], c["acuracia"]) == (1, 0, 0, 1, 1.0)
    assert r["positivos"] == 1 and "ma" not in r
    assert len(r["limiares"]["baseline"]) == len(r["limiares"]["am+nli-local"]) == 2
    # few-shot: os exemplos do corpus sintético (aqui, as fixtures) são os mesmos em todos os folds, porque
    # o corpus sintético não tem decisões do tribunal
    assert exemplos_usados and all(e == ["CDF-1", "CE-2", "CIF-2"] for _, e in exemplos_usados)
    md = (docs / "ablacao_tribunal.md").read_text()
    assert "1 com contradição reconhecida pelo STJ, 1 com a contradição alegada e rejeitada" in md
    assert "| am+llm | 1 | 0 | 0 | 1 |" in md
    # sem gabarito de trechos não há cobertura, mas a redução de pares pela MA é medida
    assert "Pares classificados" in md and "| am+llm | 7 |" in md


def test_rotulos_da_coleta(tmp_path):
    from src import evaluate

    criterios = tmp_path / "c.jsonl"
    criterios.write_text(
        '{"id": "A", "criterio": "reconhecida"}\n{"id": "B", "criterio": "rejeitada"}\n'
        '{"id": "C", "criterio": "negativa"}\n'
    )
    assert evaluate.ler_rotulos(criterios) == {"A": True, "B": False}
