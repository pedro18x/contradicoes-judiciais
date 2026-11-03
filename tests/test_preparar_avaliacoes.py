import json
from pathlib import Path

from scripts import preparar_avaliacoes
from src.contratos import Gold, Segmentos, ler_jsonl
from tests.test_sintetico import BASE

FIX = Path(__file__).parent / "fixtures"


def test_tribunal_e_sintetico_com_decisoes_separadas(tmp_path, capsys):
    tribunal = ler_jsonl(FIX / "segmentos.jsonl", Segmentos)  # FICT-0001 reconhecida, FICT-0002 rejeitada
    bases = [BASE.model_copy(update={"id": f"FICT-S{i}"}) for i in range(4)]
    (tmp_path / "segmentos.jsonl").write_text("".join(s.model_dump_json() + "\n" for s in tribunal + bases))
    criterios = [
        {"id": "FICT-0001", "criterio": "reconhecida"},
        {"id": "FICT-0002", "criterio": "rejeitada"},
        *({"id": b.id, "criterio": "negativa"} for b in bases),
    ]
    (tmp_path / "c.jsonl").write_text("".join(json.dumps(c) + "\n" for c in criterios))
    resumo = tmp_path / "corpus.md"
    log = tmp_path / "c.log.jsonl"
    log.write_text(
        '{"processo": "A", "motivo": "embargado não encontrado"}\n'
        '{"processo": "B", "motivo": "embargado sem texto em 2024-03-01"}\n'
        '{"processo": "C", "motivo": "embargado não encontrado"}\n'
    )
    preparar_avaliacoes.main(
        [str(tmp_path / "segmentos.jsonl"), str(tmp_path / "c.jsonl"), "--saida", str(tmp_path),
         "--k", "2", "--resumo", str(resumo), "--log", str(log)]
    )  # fmt: skip
    assert json.loads((tmp_path / "tribunal/rotulos.json").read_text()) == {
        "FICT-0001": True,
        "FICT-0002": False,
    }
    folds_t = json.loads((tmp_path / "tribunal/splits.json").read_text())["folds"]
    assert sorted(id for f in folds_t for id in f) == ["FICT-0001", "FICT-0002"]
    assert [s.id for s in ler_jsonl(tmp_path / "tribunal/segmentos.jsonl", Segmentos)] == [
        "FICT-0001",
        "FICT-0002",
    ]
    gold = ler_jsonl(tmp_path / "sintetico/gold.jsonl", Gold)
    assert sorted(g.id for g in gold) == [b.id for b in bases]  # só as negativas viram base
    assert sum(bool(g.contradicoes) for g in gold) == 2
    folds_s = json.loads((tmp_path / "sintetico/splits.json").read_text())["folds"]
    assert sorted(id for f in folds_s for id in f) == [b.id for b in bases]
    texto = resumo.read_text()
    assert "1 com a contradição reconhecida pelo STJ" in texto and "2 com uma contradição inserida" in texto
    # tamanho de cada conjunto, para a descrição do corpus
    assert "| Tribunal: contradição reconhecida | 1 |" in texto and "| Base do sintético | 4 |" in texto
    # casos que a coleta não conseguiu montar, agrupados pelo motivo (sem a data)
    assert "3 casos descartados" in texto and "| embargado não encontrado | 2 |" in texto
    assert "| embargado sem texto | 1 |" in texto
    assert texto == capsys.readouterr().out


def test_amostra_tribunal_metade_de_cada_rotulo():
    rotulos = {f"R{i}": True for i in range(10)} | {f"N{i}": False for i in range(30)}
    amostra = preparar_avaliacoes.amostra_tribunal(rotulos, 8, seed=42)
    assert amostra.items() <= rotulos.items()  # só decisões coletadas, com o rótulo original
    assert sum(amostra.values()) == 4 and sum(not v for v in amostra.values()) == 4
    assert amostra == preparar_avaliacoes.amostra_tribunal(rotulos, 8, seed=42)  # reprodutível
    assert preparar_avaliacoes.amostra_tribunal(rotulos, None, seed=42) == rotulos
    # a mesma entrada em outra ordem dá a mesma amostra (o sorteio não depende da ordem do dict)
    invertido = dict(reversed(list(rotulos.items())))
    assert preparar_avaliacoes.amostra_tribunal(invertido, 8, seed=42) == amostra


def test_amostra_sintetico_sorteia_ate_n():
    negativas = {f"S{i}" for i in range(10)}
    amostra = preparar_avaliacoes.amostra_sintetico(negativas, 4, seed=42)
    assert len(amostra) == 4 and amostra <= negativas
    assert amostra == preparar_avaliacoes.amostra_sintetico(negativas, 4, seed=42)
    assert preparar_avaliacoes.amostra_sintetico(negativas, 50, seed=42) == negativas


def test_corte_registrado_no_resumo(tmp_path):
    tribunal = ler_jsonl(FIX / "segmentos.jsonl", Segmentos)
    bases = [BASE.model_copy(update={"id": f"FICT-S{i}"}) for i in range(4)]
    (tmp_path / "segmentos.jsonl").write_text("".join(s.model_dump_json() + "\n" for s in tribunal + bases))
    criterios = [
        {"id": "FICT-0001", "criterio": "reconhecida"},
        {"id": "FICT-0002", "criterio": "rejeitada"},
        *({"id": b.id, "criterio": "negativa"} for b in bases),
    ]
    (tmp_path / "c.jsonl").write_text("".join(json.dumps(c) + "\n" for c in criterios))
    texto = preparar_avaliacoes.preparar(
        ler_jsonl(tmp_path / "segmentos.jsonl", Segmentos), tmp_path / "c.jsonl", tmp_path, k=2,
        max_tribunal=2, max_sintetico=2,
    )  # fmt: skip
    assert "Coletadas: 2 decisões do tribunal e 4 bases do sintético. Entraram 2 e 2" in texto
    assert len(ler_jsonl(tmp_path / "sintetico/gold.jsonl", Gold)) == 2
