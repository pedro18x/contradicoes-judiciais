import random
from collections import Counter

from src import splits
from src.contratos import ContradicaoGold, Gold, Trecho

T = Trecho(segmento="fundamentacao", inicio=0, fim=1)


def _gold(id, *categorias):
    return Gold(id=id, contradicoes=[ContradicaoGold(categoria=c, a=T, b=T) for c in categorias])


# 40 negativas, 30 CDF-1, 20 CIF-2 e 10 decisões com CDF-1 + CE-2 (CE-2 é a mais rara: vira o estrato)
GOLD = (
    [_gold(f"n{i:02}") for i in range(40)]
    + [_gold(f"a{i:02}", "CDF-1") for i in range(30)]
    + [_gold(f"b{i:02}", "CIF-2") for i in range(20)]
    + [_gold(f"c{i:02}", "CDF-1", "CE-2") for i in range(10)]
)


def test_cada_decisao_em_exatamente_um_fold():
    folds = splits.gerar(GOLD)["folds"]
    todos = [id for f in folds for id in f]
    assert sorted(todos) == sorted(g.id for g in GOLD)
    assert {len(f) for f in folds} == {20}


def test_mesma_seed_mesmos_folds_independente_da_ordem():
    embaralhado = random.Random(0).sample(GOLD, len(GOLD))
    assert splits.gerar(GOLD) == splits.gerar(embaralhado)
    assert splits.gerar(GOLD, seed=7) != splits.gerar(GOLD)


def test_estratos_divididos_por_igual():
    folds = splits.gerar(GOLD)["folds"]
    for prefixo, total in [("n", 40), ("a", 30), ("b", 20), ("c", 10)]:
        por_fold = [sum(id.startswith(prefixo) for id in f) for f in folds]
        assert por_fold == [total // 5] * 5, prefixo


def test_estrato_de_categoria_rara_nao_concentra():
    gold = [_gold(f"x{i}", "CDF-1") for i in range(12)] + [_gold(f"y{i}", "CDF-1", "CIL-2") for i in range(3)]
    folds = splits.gerar(gold, k=3)["folds"]
    assert Counter(sum(id.startswith("y") for id in f) for f in folds) == Counter({1: 3})


def test_salvar_carregar_e_particao(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = splits.gerar(GOLD)
    splits.salvar(s)
    assert (tmp_path / "splits.json").exists()
    folds = splits.carregar()
    assert folds == s["folds"]
    treino, teste = splits.particao(folds, 2)
    assert teste == folds[2] and len(treino) == 80 and not set(treino) & set(teste)
