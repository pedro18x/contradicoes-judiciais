import csv
import json
import shutil
from pathlib import Path

import pytest

from scripts import erros
from src.contratos import Gold, Predicao, Predicoes, ler_jsonl

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def dados(tmp_path):
    """Predições de exemplo das fixtures como se fossem a saída do experimento (2 folds)."""
    d = tmp_path / "data"
    (d / "resultados" / "am+llm").mkdir(parents=True)
    for nome in ("segmentos", "gold"):
        shutil.copy(FIX / f"{nome}.jsonl", d / f"{nome}.jsonl")
    preds = ler_jsonl(FIX / "predicoes.jsonl", Predicoes)
    for k, p in enumerate(preds):
        (d / "resultados" / "am+llm" / f"fold{k}.jsonl").write_text(p.model_dump_json() + "\n")
    return d


def _main(dados, *args):
    erros.main([*args, "--sistema", "am+llm", "--dados", str(dados), "--docs", str(dados.parent / "docs")])


def test_relatorio_lista_erros_e_resumo_sem_trechos(dados):
    _main(dados, "relatorio")
    completo = (dados / "resultados" / "am+llm" / "erros.md").read_text()
    resumo = (dados.parent / "docs" / "erros_am+llm.md").read_text()
    assert "## CE-2: Ementa vs. Dispositivo" in completo
    assert "### Falsos negativos" in completo and "“RECURSO PROVIDO”" in completo
    assert "Ementa diz provido" in completo  # justificativa da anotação
    assert "| CE-2 | 0 | 0 | 1 |" in resumo and "| CDF-1 | 1 | 0 | 0 |" in resumo
    # a CE-2 perdida não estava entre os pares avaliados; nenhum acerto com categoria trocada
    assert "| CE-2 | 1 | 0 |" in resumo and "Acertos com categoria diferente da inserida: 0 de 2." in resumo
    # nada do acórdão no arquivo versionado
    assert "RECURSO PROVIDO" not in resumo and "aluguéis" not in resumo


def test_amostra_e_consolidacao(dados):
    _main(dados, "amostra")
    planilha = dados / "revisao" / "am+llm.csv"
    with planilha.open(encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    # 2 decisões -> 10% arredondado para cima = 1 decisão sorteada; só a FICT-0001 tem contradições
    assert {r["decisao"] for r in linhas} <= {"FICT-0001", "FICT-0002"}
    assert all(r["avaliacao"] == "" for r in linhas)

    # duas revisões preenchidas à mão sobre uma planilha com 4 itens
    itens = [
        {**dict.fromkeys(erros.COLUNAS, ""), "item": str(i), "categoria": c, "decisao": d}
        for i, (c, d) in enumerate([("CDF-1", "X-9"), ("CIF-2", "X-9"), ("CE-2", "X-7"), ("CDF-1", "X-7")], 1)
    ]
    for nome, notas in [
        ("r1", ["Genuína", "genuina", "incorreta", "parcialmente valida"]),
        ("r2", ["genuína", "genuína", "incorreta", ""]),
    ]:
        erros.escrever_csv(
            dados / "revisao" / f"{nome}.csv",
            [
                {**x, "avaliacao": n, "comentario": "fora de contexto" if n == "incorreta" else ""}
                for x, n in zip(itens, notas)
            ],
        )
    erros.main(
        [
            "consolidar",
            str(dados / "revisao" / "r1.csv"),
            str(dados / "revisao" / "r2.csv"),
            "--docs",
            str(dados.parent / "docs"),
        ]
    )
    texto = (dados.parent / "docs" / "revisao_am+llm.md").read_text()
    assert "r2: 1 itens sem avaliação válida (itens 4)" in texto
    assert "| genuína | 2 | 2 |" in texto and "| incorreta | 1 | 1 |" in texto
    assert "Concordância entre os revisores: 100,0% (3 itens); Kappa de Cohen = 1,000" in texto
    assert "CDF-1: 1, CIF-2: 1" in texto
    # por decisão, numerada (sem o identificador do processo) e por categoria
    assert "2 decisões; 1 com ao menos uma contradição genuína." in texto
    assert "| 1 | 2 | 0 | 0 |" in texto and "| 2 | 0 | 1 | 1 |" in texto  # r1, com o item 4
    assert "| 2 | 0 | 0 | 1 |" in texto  # r2: item 4 sem avaliação fica fora
    assert "| CE-2 | 0 | 0 | 1 |" in texto and "X-9" not in texto
    assert "| incorreta | fora de contexto | 1 |" in texto


def test_tipos_de_erro():
    gold = {g.id: g for g in ler_jsonl(FIX / "gold.jsonl", Gold)}
    ce2 = gold["FICT-0001"].contradicoes[2]
    # FP que repete a frase alterada (b do gold), FP em outro par e FP em decisão intacta
    repete = Predicao(a=ce2.a.model_copy(update={"segmento": "fundamentacao"}), b=ce2.b, contradicao=True)
    outro = Predicao(
        a=gold["FICT-0001"].contradicoes[0].a, b=gold["FICT-0001"].contradicoes[1].a, contradicao=True
    )
    assert erros.tipo_fp(gold["FICT-0001"], repete) == erros.FP_TIPOS[1]
    assert erros.tipo_fp(gold["FICT-0001"], outro) == erros.FP_TIPOS[2]
    assert erros.tipo_fp(gold["FICT-0002"], outro) == erros.FP_TIPOS[0]
    # FN: o par certo foi avaliado (e dito sem contradição) ou nem foi avaliado
    avaliou = Predicoes(id="FICT-0001", sistema="am+llm", modelo="x", predicoes=[
        Predicao(a=ce2.a, b=ce2.b, contradicao=False)
    ])  # fmt: skip
    assert erros.tipo_fn(avaliou, ce2) == erros.FN_TIPOS[1]
    assert erros.tipo_fn(avaliou.model_copy(update={"predicoes": []}), ce2) == erros.FN_TIPOS[0]


def test_tribunal_conta_por_tipo_e_categoria(dados, tmp_path):
    (dados / "gold.jsonl").unlink()  # tribunal: sem gold por trecho
    classificacao = tmp_path / "classificacao.json"
    classificacao.write_text(json.dumps([
        {"id": "FICT-0001", "tipo": "interna", "categoria": "CDF-1", "evidencia": "x"},
        {"id": "FICT-0002", "tipo": "externa", "categoria": None, "evidencia": "y", "contradicao_afastada": True},
    ]))  # fmt: skip
    (dados / "rotulos.json").write_text(json.dumps({"FICT-0001": True, "FICT-0002": False}))
    (dados / "decisoes.jsonl").write_text(
        json.dumps({"id": "FICT-0001", "processo": "AgInt no REsp 1", "texto": ""}) + "\n"
        + json.dumps({"id": "FICT-0002", "processo": "REsp 2", "texto": ""}) + "\n"
    )  # fmt: skip
    erros.main(["tribunal", str(classificacao), "--dados", str(dados), "--docs", str(dados.parent / "docs")])
    texto = (dados.parent / "docs" / "erros_tribunal.md").read_text()
    assert "| agravo interno ou regimental | reconhecida | 1 | 1 |" in texto
    assert (
        "Em 1 das 2, o acórdão dos embargos afasta a contradição" in texto
        and "am+llm marcou 0 delas" in texto
    )
    assert "| outros | rejeitada | 1 | 0 |" in texto and "| outros | reconhecida | 0 | 0 |" in texto
    # FICT-0001 tem contradição prevista; FICT-0002, não
    assert "| interna | 1 | 1 | 0 |" in texto and "| externa | 1 | 0 | 1 |" in texto
    assert "| total | 2 | 1 | 1 |" in texto and "| CDF-1 | 1 | 1 |" in texto
    classificacao.write_text(json.dumps([{"id": "FICT-0001", "tipo": "outro"}]))
    with pytest.raises(SystemExit, match="tipo fora"):
        erros.main(
            ["tribunal", str(classificacao), "--dados", str(dados), "--docs", str(dados.parent / "docs")]
        )


def test_kappa_multiclasse():
    a = ["genuína", "genuína", "incorreta", "parcialmente válida"]
    b = ["genuína", "incorreta", "incorreta", "parcialmente válida"]
    # po = 3/4; pe = (2·1 + 1·2 + 1·1)/16 = 5/16
    assert erros.kappa(a, b) == pytest.approx((0.75 - 5 / 16) / (1 - 5 / 16))


def test_sem_predicoes_avisa(tmp_path):
    with pytest.raises(SystemExit, match="experimento.py"):
        erros.main(["relatorio", "--sistema", "am+llm", "--dados", str(tmp_path)])


def test_amostra_sem_gold_para_o_rotulo_do_tribunal(dados, capsys):
    (dados / "gold.jsonl").unlink()  # avaliação 1: só o rótulo do STJ, sem trechos gold
    _main(dados, "amostra")
    assert (dados / "revisao" / "am+llm.csv").exists() and "contradições de" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="avaliação sintética"):
        _main(dados, "relatorio")
