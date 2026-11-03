import json
import shutil
from pathlib import Path

import pytest

from scripts import erros, nli_v2
from src import nli
from src.contratos import Predicoes, Segmentos, ler_jsonl, texto_do_trecho

FIX = Path(__file__).parent / "fixtures"
RAIZ = Path(__file__).parent.parent
SEGS = {s.id: s for s in ler_jsonl(FIX / "segmentos.jsonl", Segmentos)}
PREDS = ler_jsonl(FIX / "predicoes.jsonl", Predicoes)


@pytest.fixture
def sem_contradicao(monkeypatch):
    """NLI falso que nunca vê contradição; guarda o system de cada chamada."""
    systems = []

    def falso(prompt, *, system="", model=None, etapa=None):
        systems.append(system)
        return {"resultados": [{"i": i, "contradicao": False} for i in range(nli.LOTE)]}

    monkeypatch.setattr(nli.llm, "complete_json", falso)
    monkeypatch.setattr(nli_v2.llm, "custo_acumulado", lambda: {"chamadas": 0, "usd": 0.0})
    return systems


def _dados(tmp_path, tribunal: bool) -> Path:
    d = tmp_path / "data"
    (d / "resultados" / "am+llm").mkdir(parents=True)
    shutil.copy(FIX / "segmentos.jsonl", d / "segmentos.jsonl")
    if tribunal:
        (d / "rotulos.json").write_text(json.dumps({"FICT-0001": True, "FICT-0002": False}))
    else:
        shutil.copy(FIX / "gold.jsonl", d / "gold.jsonl")
    (d / "splits.json").write_text(json.dumps({"folds": [["FICT-0001"], ["FICT-0002"]]}))
    for k, p in enumerate(PREDS):
        (d / "resultados" / "am+llm" / f"fold{k}.jsonl").write_text(p.model_dump_json() + "\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    shutil.copy(RAIZ / "docs" / "resultados" / "ablacao_tribunal.json", docs)
    return d


def test_remontar_mantem_pares_e_ordem():
    pred = PREDS[0]
    props, pares = nli_v2.remontar(SEGS[pred.id], pred)
    texto = {p.pid: (p.segmento, p.texto) for p in props.proposicoes}
    assert [(texto[a], texto[b]) for a, b in (x.par for x in pares.pares)] == [
        (
            (x.a.segmento, texto_do_trecho(SEGS[pred.id], x.a)),
            (x.b.segmento, texto_do_trecho(SEGS[pred.id], x.b)),
        )
        for x in pred.predicoes
    ]


def test_tribunal_reclassifica_so_as_marcadas_e_cruza_a_revisao(tmp_path, sem_contradicao):
    d = _dados(tmp_path, tribunal=True)
    contradicao = next(x for x in PREDS[0].predicoes if x.contradicao)
    revisao = tmp_path / "revisao.csv"
    erros.escrever_csv(
        revisao,
        [
            {
                **dict.fromkeys(erros.COLUNAS, ""),
                "item": "1",
                "decisao": "FICT-0001",
                "segmento_a": contradicao.a.segmento,
                "trecho_a": texto_do_trecho(SEGS["FICT-0001"], contradicao.a),
                "segmento_b": contradicao.b.segmento,
                "trecho_b": texto_do_trecho(SEGS["FICT-0001"], contradicao.b),
                "avaliacao": "incorreta",
            }
        ],
    )
    args = [
        "--avaliacao",
        "tribunal",
        "--dados",
        str(d),
        "--docs",
        str(tmp_path / "docs"),
        "--revisao",
        str(revisao),
    ]
    assert "1 decisões marcadas por C (v1)" in nli_v2.main([*args, "--estimar"]) and not sem_contradicao
    texto = nli_v2.main(args)
    assert all("agravo interno" in s for s in sem_contradicao)  # só o prompt v2
    assert "| reconhecida | 1 | 0 |" in texto and "| rejeitada | 0 | 0 |" in texto
    assert "| v1 | 1,000 | 1,000 | 1,000 | 1,000 | 1 | 0 | 0 | 1 |" in texto
    assert "| v2 | — | 0,000 | 0,000 | 0,500 | 0 | 0 | 1 | 1 |" in texto
    assert "| incorreta | 1 | 0 | 1 | 0 |" in texto
    assert "Sem as 1 decisões revisadas" in texto
    v2 = ler_jsonl(d / "resultados" / "am+llm-v2" / "tribunal.jsonl", Predicoes)
    assert [p.id for p in v2] == ["FICT-0001"] and v2[0].modelo.endswith("prompt=nli_v2")
    assert (tmp_path / "docs" / "nli_v2_tribunal.md").read_text(encoding="utf-8") == texto


def test_sintetica_compara_v1_e_v2_na_amostra(tmp_path, sem_contradicao):
    d = _dados(tmp_path, tribunal=False)
    texto = nli_v2.main(
        ["--avaliacao", "sintetica", "--dados", str(d), "--docs", str(tmp_path / "docs"), "--n", "2"]
    )
    assert "1 decisões com contradição inserida e 1 intactas" in texto
    assert "| v1 | 1,000 | 0,667 | 0,800 | 2 | 0 | 1 |" in texto
    assert "| v2 | — | 0,000 | 0,000 | 0 | 0 | 3 |" in texto
