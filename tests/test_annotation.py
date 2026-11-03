import json
import math
import zipfile
from pathlib import Path

import pytest

from src import annotation
from src.contratos import ContradicaoGold, Gold, Segmentos, Trecho, ler_jsonl, texto_do_trecho

FIX = Path(__file__).parent / "fixtures"
SEGS = ler_jsonl(FIX / "segmentos.jsonl", Segmentos)
GOLD = ler_jsonl(FIX / "gold.jsonl", Gold)


def _sem_justificativa(golds):
    return [
        g.model_copy(
            update={"contradicoes": [c.model_copy(update={"justificativa": ""}) for c in g.contradicoes]}
        )
        for g in golds
    ]


def test_ida_e_volta_labelstudio(tmp_path):
    caminho = tmp_path / "tarefas.json"
    annotation.exportar_labelstudio(SEGS, caminho, gold=GOLD)
    assert annotation.importar(caminho) == GOLD


def test_ida_e_volta_doccano(tmp_path):
    caminho = tmp_path / "tarefas.jsonl"
    annotation.exportar_doccano(SEGS, caminho, gold=GOLD)
    assert annotation.importar(caminho) == _sem_justificativa(GOLD)  # Doccano não guarda justificativa


def test_doccano_zip_por_usuario(tmp_path):
    jsonl = tmp_path / "x.jsonl"
    annotation.exportar_doccano(SEGS, jsonl, gold=GOLD)
    with zipfile.ZipFile(tmp_path / "export.zip", "w") as z:
        z.writestr("ana.jsonl", jsonl.read_text(encoding="utf-8"))
        z.writestr("bruno.jsonl", "")
    assert annotation.importar(tmp_path / "export.zip", anotador="ana") == _sem_justificativa(GOLD)
    assert annotation.importar(tmp_path / "export.zip", anotador="bruno") == []
    with pytest.raises(ValueError, match="anotador"):
        annotation.importar(tmp_path / "export.zip")


def _tarefa_labelstudio(anotacoes):
    return {
        "data": {"decisao": SEGS[0].id, "texto": annotation.montar_texto(SEGS[0])},
        "annotations": anotacoes,
    }


def test_labelstudio_offsets_e_espacos(tmp_path):
    texto = annotation.montar_texto(SEGS[0])
    ini_a = texto.index("Assim, é devida")
    ini_b = texto.index("nego provimento")
    resultado = [
        # o anotador pegou o espaço antes e a quebra de linha depois: as pontas são aparadas
        {"id": "x", "type": "labels", "value": {"start": ini_a - 1, "end": ini_a + 50 + 1}},
        {"id": "y", "type": "labels", "value": {"start": ini_b, "end": ini_b + 35}},
        {"id": "x", "type": "textarea", "value": {"text": ["Fundamentação favorável; dispositivo nega."]}},
        {"type": "relation", "from_id": "x", "to_id": "y", "labels": ["CDF-1"]},
    ]
    caminho = tmp_path / "export.json"
    caminho.write_text(json.dumps([_tarefa_labelstudio([{"completed_by": 7, "result": resultado}])]))
    (gold,) = annotation.importar(caminho, anotador="7")
    (c,) = gold.contradicoes
    assert c.a == Trecho(segmento="fundamentacao", inicio=166, fim=216)
    assert texto_do_trecho(SEGS[0], c.b) == "nego provimento ao recurso especial"
    assert c.justificativa == "Fundamentação favorável; dispositivo nega."


def test_labelstudio_filtra_anotador_e_ignora_invalidos(tmp_path, caplog):
    texto = annotation.montar_texto(SEGS[0])
    fora = texto.index("RELATÓRIO") - 5  # cruza a fronteira entre ementa e relatório
    invalida = [
        {"id": "x", "type": "labels", "value": {"start": fora, "end": fora + 20}},
        {"id": "y", "type": "labels", "value": {"start": 0, "end": 3}},  # só o título
        {"type": "relation", "from_id": "x", "to_id": "y", "labels": ["CE-2"]},
        {"type": "relation", "from_id": "x", "to_id": "x", "labels": ["XYZ"]},
    ]
    anotacoes = [
        {"completed_by": {"id": 1, "email": "ana@exemplo.invalid"}, "result": invalida},
        {"completed_by": {"id": 2, "email": "bruno@exemplo.invalid"}, "result": [], "was_cancelled": True},
    ]
    caminho = tmp_path / "export.json"
    caminho.write_text(json.dumps([_tarefa_labelstudio(anotacoes)]))
    assert annotation.importar(caminho, anotador="ana@exemplo.invalid") == [Gold(id="FICT-0001", contradicoes=[])]
    assert "fora de um único segmento" in caplog.text and "XYZ" in caplog.text
    assert annotation.importar(caminho, anotador="bruno@exemplo.invalid") == []  # pulou a tarefa: não conta
    caminho.write_text(json.dumps([_tarefa_labelstudio([anotacoes[0], {**anotacoes[0], "completed_by": 3}])]))
    with pytest.raises(ValueError, match="anotador"):
        annotation.importar(caminho)


def test_cohen_valor_conhecido():
    # 50 itens: 20 sim/sim, 5 sim/não, 10 não/sim, 15 não/não -> po = 0,7, pe = 0,5, kappa = 0,4
    a = [True] * 25 + [False] * 25
    b = [True] * 20 + [False] * 5 + [True] * 10 + [False] * 15
    assert annotation._cohen(a, b) == pytest.approx(0.4)
    assert math.isnan(annotation._cohen([False] * 3, [False] * 3))


def _gold(id, *categorias):
    t = Trecho(segmento="fundamentacao", inicio=0, fim=1)
    return Gold(id=id, contradicoes=[ContradicaoGold(categoria=c, a=t, b=t) for c in categorias])


def test_kappa_por_decisao_e_categoria():
    a = [_gold("d1", "CDF-1"), _gold("d2"), _gold("so-a", "CE-1")]
    b = [_gold("d1", "CDF-1", "CIF-2"), _gold("d2")]
    # 18 unidades (2 decisões × 9 categorias): A marca 1, B marca 2, concordam em 17
    po, pa, pb = 17 / 18, 1 / 18, 2 / 18
    pe = pa * pb + (1 - pa) * (1 - pb)
    assert annotation.kappa(a, b) == pytest.approx((po - pe) / (1 - pe))
    assert annotation.kappa(a, a) == 1.0
    assert annotation.divergencias(a, b) == [("d1", "CIF-2")]


def test_consenso_usa_desempate_so_nas_divergencias():
    a = [_gold("d1", "CDF-1", "CE-2"), _gold("d2")]
    b = [_gold("d1", "CDF-1"), _gold("d2", "CIL-1")]
    desempate = [_gold("d1", "CE-2"), _gold("d2")]  # mantém CE-2 em d1, descarta CIL-1 em d2
    final = annotation.consenso(a, b, desempate)
    assert [(g.id, [c.categoria for c in g.contradicoes]) for g in final] == [
        ("d1", ["CDF-1", "CE-2"]),
        ("d2", []),
    ]
    with pytest.raises(ValueError, match="d2"):
        annotation.consenso(a, b, desempate[:1])


def test_doccano_relacao_orfa_e_sem_id(tmp_path, caplog):
    texto = annotation.montar_texto(SEGS[0])
    ini = texto.index("nego provimento")
    ex = {
        "decisao": SEGS[0].id,
        "text": texto,
        "entities": [{"id": 1, "label": "TRECHO", "start_offset": ini, "end_offset": ini + 15}],
        "relations": [{"id": 1, "from_id": 1, "to_id": 2, "type": "CE-2"}],
    }
    caminho = tmp_path / "x.jsonl"
    caminho.write_text(json.dumps(ex) + "\n")
    assert annotation.importar(caminho) == [Gold(id=SEGS[0].id, contradicoes=[])]
    assert "trecho apagado" in caplog.text
    caminho.write_text(json.dumps({**ex, "decisao": None}) + "\n")
    with pytest.raises(ValueError, match="decisao"):
        annotation.importar(caminho)
