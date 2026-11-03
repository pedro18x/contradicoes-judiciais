import json
import sys
from pathlib import Path

import pytest

from src import evaluate
from src.contratos import ContradicaoGold, Gold, Pares, Predicao, Predicoes, Proposicoes, Trecho, ler_jsonl

FIX = Path(__file__).parent / "fixtures"
PREDS = ler_jsonl(FIX / "predicoes.jsonl", Predicoes)
GOLD = ler_jsonl(FIX / "gold.jsonl", Gold)


def _t(ini, fim, seg="fundamentacao"):
    return Trecho(segmento=seg, inicio=ini, fim=fim)


def _preds(id, *pares, categoria="CIF-2"):
    ps = [Predicao(a=a, b=b, contradicao=True, categoria=categoria) for a, b in pares]
    return Predicoes(id=id, sistema="t", modelo="m", predicoes=ps)


def test_fixtures_criterio_da_issue():
    m = evaluate.metricas(PREDS, GOLD)
    par = m["par"]["global"]
    # CDF-1 e CIF-2 acertados (o CIF-2 previsto vem em ordem invertida); CE-2 perdida
    assert (par["vp"], par["fp"], par["fn"]) == (2, 0, 1)
    assert par["precisao"] == 1.0 and par["revocacao"] == pytest.approx(2 / 3)
    assert m["par"]["por_categoria"]["CE-2"] == {
        "vp": 0, "fp": 0, "fn": 1, "precisao": None, "revocacao": 0.0, "f1": 0.0
    }  # fmt: skip
    assert m["par"]["por_categoria"]["CDF-1"]["f1"] == 1.0
    # FICT-0001 VP, FICT-0002 VN
    d = m["decisao"]
    assert (d["vp"], d["fp"], d["fn"], d["vn"]) == (1, 0, 0, 1)


def test_ordem_nao_importa_e_casamento_um_para_um():
    g = Gold(id="x", contradicoes=[ContradicaoGold(categoria="CIF-2", a=_t(0, 10), b=_t(20, 30))])
    assert evaluate.f1_pares([_preds("x", (_t(20, 30), _t(0, 10)))], [g]) == 1.0
    # a segunda predição sobre a mesma contradição é repetição: nem VP nem FP
    m = evaluate.metricas([_preds("x", (_t(0, 10), _t(20, 30)), (_t(20, 30), _t(0, 10)))], [g])
    assert (m["par"]["global"]["vp"], m["par"]["global"]["fp"]) == (1, 0)
    assert m["par"]["vp_estrito"] == 1


# frase que ficou (a) na fundamentação, frase alterada (b) no dispositivo
CDF1 = ContradicaoGold(
    categoria="CDF-1", a=_t(0, 10), b=_t(0, 20, "dispositivo")
)  # fmt: skip


@pytest.mark.parametrize("ordem", [1, -1])
def test_frase_alterada_com_outra_frase_do_segmento_em_conflito_acerta(ordem):
    outra = _t(40, 60)  # outra frase da fundamentação, não a do gold
    par = (_t(0, 20, "dispositivo"), outra)[::ordem]
    assert evaluate.acerta(Predicao(a=par[0], b=par[1], contradicao=True), CDF1)
    assert not evaluate.acerta_estrito(Predicao(a=par[0], b=par[1], contradicao=True), CDF1)


def test_sem_a_frase_alterada_ou_fora_do_segmento_nao_acerta():
    original_e_outra = Predicao(a=_t(0, 10), b=_t(40, 60), contradicao=True)
    outro_segmento = Predicao(a=_t(0, 20, "dispositivo"), b=_t(0, 10, "relatorio"), contradicao=True)
    assert not evaluate.acerta(original_e_outra, CDF1)
    assert not evaluate.acerta(outro_segmento, CDF1)


def test_cif2_o_outro_lado_nao_pode_ser_a_propria_frase_alterada():
    g = ContradicaoGold(categoria="CIF-2", a=_t(0, 10), b=_t(20, 30))
    assert evaluate.acerta(Predicao(a=_t(20, 30), b=_t(40, 50), contradicao=True), g)
    assert not evaluate.acerta(Predicao(a=_t(20, 30), b=_t(18, 32), contradicao=True), g)


def test_varias_predicoes_na_mesma_contradicao_contam_uma_vez():
    gold = Gold(id="x", contradicoes=[CDF1])
    alterada = _t(0, 20, "dispositivo")
    preds = _preds("x", (alterada, _t(40, 60)), (_t(0, 10), alterada), (_t(70, 80), _t(90, 99)))
    m = evaluate.metricas([preds], [gold])
    # 1 VP (a primeira), a segunda é repetição, a terceira não toca a contradição: FP
    assert (m["par"]["global"]["vp"], m["par"]["global"]["fp"], m["par"]["global"]["fn"]) == (1, 1, 0)
    assert m["par"]["vp_estrito"] == 1  # a segunda predição tem os dois trechos gold


def test_cobertura_de_metade_do_trecho_gold():
    g = ContradicaoGold(categoria="CIF-2", a=_t(0, 10), b=_t(20, 30))
    metade = Predicao(a=_t(5, 40), b=_t(20, 30), contradicao=True)  # cobre 5 dos 10 caracteres de "a"
    menos = Predicao(a=_t(6, 40), b=_t(20, 30), contradicao=True)
    outro_segmento = Predicao(a=_t(0, 10, "relatorio"), b=_t(20, 30), contradicao=True)
    assert evaluate.acerta(metade, g)
    assert not evaluate.acerta(menos, g)
    assert not evaluate.acerta(outro_segmento, g)


def test_falso_positivo_conta_na_categoria_prevista():
    g = Gold(id="x", contradicoes=[])
    m = evaluate.metricas([_preds("x", (_t(0, 1), _t(2, 3)), categoria=None)], [g])
    assert m["par"]["por_categoria"] == {
        "sem categoria": {"vp": 0, "fp": 1, "fn": 0, "precisao": 0.0, "revocacao": None, "f1": 0.0}
    }
    assert m["decisao"]["fp"] == 1


def test_decisao_sem_predicoes_e_predicao_sem_gold(caplog):
    m = evaluate.metricas([PREDS[1], PREDS[0].model_copy(update={"id": "outra"})], GOLD)
    assert m["par"]["global"]["fn"] == 3  # FICT-0001 sem predições: tudo é falso negativo
    assert m["decisao"]["fn"] == 1
    assert "outra" in caplog.text
    with pytest.raises(ValueError, match="sem gold"):
        evaluate.metricas(PREDS, GOLD, ids=["nao-existe"])


def test_por_fold_media_e_desvio():
    gold = [
        Gold(id=i, contradicoes=[ContradicaoGold(categoria="CIF-2", a=_t(0, 5), b=_t(9, 12))]) for i in "abcd"
    ]
    certo = [_preds(i, (_t(0, 5), _t(9, 12))) for i in "ab"]  # c e d sem predição
    r = evaluate.por_fold(certo, gold, [["a", "b"], ["c", "d"]])
    assert [f["par"]["global"]["f1"] for f in r["folds"]] == [1.0, 0.0]
    assert r["resumo"]["par.f1"]["media"] == 0.5
    assert r["resumo"]["par.f1"]["desvio"] == pytest.approx(0.7071, abs=1e-4)
    assert r["resumo"]["par.precisao"]["folds"] == 1  # fold sem nenhuma predição não tem precisão


def test_cli(tmp_path, monkeypatch, capsys):
    splits = tmp_path / "splits.json"
    splits.write_text(json.dumps({"seed": 42, "k": 2, "folds": [["FICT-0001"], ["FICT-0002"]]}))
    saida = tmp_path / "res.json"
    argv = ["evaluate", "--pred", str(FIX / "predicoes.jsonl"), "--gold", str(FIX / "gold.jsonl")]
    monkeypatch.setattr(sys, "argv", [*argv, "--splits", str(splits), "--json", str(saida)])
    evaluate.main()
    out = capsys.readouterr().out
    assert "| **global** | 2 | 0 | 1 | 1,000 | 0,667 | 0,800 |" in out
    assert "## Nível decisão" in out and "## Por fold" in out
    assert json.loads(saida.read_text())["geral"]["par"]["global"]["vp"] == 2


def test_cobertura_da_ma():
    props = ler_jsonl(FIX / "proposicoes.jsonl", Proposicoes)
    pares = ler_jsonl(FIX / "pares.jsonl", Pares)
    c = evaluate.cobertura(pares, props, GOLD)
    # o par estrutural ementa × dispositivo (p1 × p6) cobre a CE-2: 3 de 3
    assert (c["cobertas"], c["contradicoes_gold"], c["cobertura"]) == (3, 3, 1.0)
    # FICT-0001: 5 de 15 pares possíveis; FICT-0002: 2 de 3
    assert (c["pares"], c["todos_pares"]) == (7, 18) and c["reducao"] == pytest.approx(7 / 18)
    # sem o par estrutural (fixture antiga): CDF-1 e CIF-2 cobertos, CE-2 não -> 2/3
    sem_ementa = [
        p.model_copy(update={"pares": [x for x in p.pares if x.relacao != "ementa-dispositivo"]})
        for p in pares
    ]
    sem = evaluate.cobertura(sem_ementa, props, GOLD)
    assert sem["cobertura"] == pytest.approx(2 / 3)
    # por categoria: a perda fica visível na CE-2
    assert sem["por_categoria"]["CE-2"] == {"cobertas": 0, "total": 1, "cobertura": 0.0}
    assert sem["por_categoria"]["CDF-1"]["cobertura"] == 1.0
    # decisão sem pares selecionados: nenhuma contradição coberta
    assert evaluate.cobertura([], props, GOLD)["cobertas"] == 0


def test_casar_lista_acertos_e_erros():
    acertos, fps, fns = evaluate.casar(PREDS[0], GOLD[0])
    assert [g.categoria for _, g in acertos] == ["CDF-1", "CIF-2"]
    assert fps == [] and [g.categoria for g in fns] == ["CE-2"]
    assert evaluate.casar(None, GOLD[0])[2] == GOLD[0].contradicoes
