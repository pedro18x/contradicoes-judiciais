"""Anotação por planilha: o que os especialistas preenchem de verdade (copiar e colar, Excel, Google)."""

import csv
from pathlib import Path

from src import annotation
from src.contratos import Gold, Segmentos, ler_jsonl, texto_do_trecho

FIX = Path(__file__).parent / "fixtures"
SEGS = ler_jsonl(FIX / "segmentos.jsonl", Segmentos)
GOLD = {g.id: g for g in ler_jsonl(FIX / "gold.jsonl", Gold)}


def _preencher(caminho, linhas, encoding="utf-8-sig", delimitador=";"):
    with open(caminho, "w", encoding=encoding, newline="") as f:
        w = csv.DictWriter(f, fieldnames=annotation.COLUNAS_PLANILHA, delimiter=delimitador)
        w.writeheader()
        for linha in linhas:
            w.writerow({**dict.fromkeys(annotation.COLUNAS_PLANILHA, ""), **linha})


def test_exportar_gera_html_legivel_e_csv_pre_preenchido(tmp_path):
    caminho_html, caminho_csv = annotation.exportar_planilha(SEGS, tmp_path, "piloto")
    pagina = caminho_html.read_text(encoding="utf-8")
    assert "<h2>Decisão 1</h2>" in pagina and "<h3>FUNDAMENTAÇÃO</h3>" in pagina
    assert "Assim, é devida a cobrança dos aluguéis em atraso." in pagina and "{{" not in pagina
    linhas = annotation._ler_csv(caminho_csv)
    assert [(linha["decisao"], linha["numero"]) for linha in linhas] == [
        ("FICT-0001", "1"),
        ("FICT-0002", "2"),
    ]


def test_importar_o_que_o_anotador_cola(tmp_path):
    planilha = tmp_path / "ana.csv"
    _preencher(planilha, [
        # copiado do HTML com aspas curvas, espaço duplo e quebra de linha; categoria sem hífen
        {"decisao": "FICT-0001", "contradicao": "Sim", "categoria": "cdf1",
         "trecho_a": "“Assim, é devida  a cobrança\ndos aluguéis em atraso.”", "trecho_b": "nego provimento ao recurso especial",
         "justificativa": "Fundamentação favorável, dispositivo nega."},
        {"decisao": "FICT-0001", "contradicao": "sim", "categoria": "CE-2",
         "trecho_a": "RECURSO PROVIDO", "trecho_b": "nego provimento ao recurso especial"},
        {"decisao": "FICT-0002", "contradicao": "não"},
    ])  # fmt: skip
    golds, problemas = annotation.importar_planilha(planilha, SEGS)
    assert problemas == []
    g = {x.id: x for x in golds}
    assert g["FICT-0002"].contradicoes == []
    cdf, ce2 = g["FICT-0001"].contradicoes
    assert (
        cdf.categoria == "CDF-1" and cdf.a == GOLD["FICT-0001"].contradicoes[0].a
    )  # offsets idênticos ao gold
    assert texto_do_trecho(SEGS[0], cdf.b) == "nego provimento ao recurso especial"
    assert ce2.categoria == "CE-2" and ce2.a.segmento == "ementa"
    assert cdf.justificativa == "Fundamentação favorável, dispositivo nega."


def test_problemas_explicados_por_linha(tmp_path):
    planilha = tmp_path / "bruno.csv"
    _preencher(planilha, [
        {"decisao": "FICT-0001", "contradicao": "sim", "categoria": "XYZ", "trecho_a": "a", "trecho_b": "b"},
        {"decisao": "FICT-0001", "contradicao": "sim", "categoria": "CIF-2",
         "trecho_a": "trecho que não existe", "trecho_b": "O contrato de locação estava vigente"},
        # "nego provimento ao recurso especial" está nas duas decisões, mas dentro de cada uma é único
        {"decisao": "FICT-0001", "contradicao": "sim", "categoria": "CIF-2", "trecho_a": "o contrato de locação",
         "trecho_b": "nego provimento ao recurso especial"},
        {"decisao": "FICT-9999", "contradicao": "não"},
        {"decisao": "FICT-0002", "contradicao": "talvez"},
    ])  # fmt: skip
    golds, problemas = annotation.importar_planilha(planilha, SEGS)
    assert any("linha 2" in p and "categoria" in p for p in problemas)
    assert any("linha 3" in p and "trecho_a não foi encontrado" in p for p in problemas)
    assert any("linha 4" in p and "trecho_a aparece em mais de um lugar" in p for p in problemas)
    assert any("FICT-9999" in p for p in problemas) and any("'talvez'" in p for p in problemas)
    assert [g.id for g in golds] == ["FICT-0001", "FICT-0002"]  # anotadas, mesmo com problemas


def test_google_planilhas_com_virgula_e_excel_windows(tmp_path):
    for nome, encoding, delimitador in (("google.csv", "utf-8", ","), ("excel.csv", "cp1252", ";")):
        planilha = tmp_path / nome
        _preencher(planilha, [{"decisao": "FICT-0002", "contradicao": "Não"}], encoding, delimitador)
        golds, problemas = annotation.importar_planilha(planilha, SEGS)
        assert (golds, problemas) == ([Gold(id="FICT-0002", contradicoes=[])], [])


def test_ida_e_volta_kappa_desempate_e_consenso(tmp_path):
    ana, bruno = tmp_path / "ana.csv", tmp_path / "bruno.csv"
    cdf = {"decisao": "FICT-0001", "contradicao": "sim", "categoria": "CDF-1",
           "trecho_a": "Assim, é devida a cobrança dos aluguéis em atraso.", "trecho_b": "nego provimento ao recurso especial"}  # fmt: skip
    cif = {"decisao": "FICT-0001", "contradicao": "sim", "categoria": "CIF-2",
           "trecho_a": "O contrato de locação estava vigente entre janeiro e junho de 2020",
           "trecho_b": "o contrato de locação foi rescindido em dezembro de 2019"}  # fmt: skip
    _preencher(ana, [cdf, cif, {"decisao": "FICT-0002", "contradicao": "não"}])
    _preencher(bruno, [cdf, {"decisao": "FICT-0002", "contradicao": "não"}])
    gold_a, _ = annotation.importar_planilha(ana, SEGS)
    gold_b, _ = annotation.importar_planilha(bruno, SEGS)
    assert annotation.divergencias(gold_a, gold_b) == [("FICT-0001", "CIF-2")]
    assert 0 < annotation.kappa(gold_a, gold_b) < 1
    notas = annotation.notas_de_desempate(gold_a, gold_b)
    assert notas == {"FICT-0001": "Divergência em: CIF-2"}
    _, csv_desempate = annotation.exportar_planilha([SEGS[0]], tmp_path, "desempate", notas)
    assert annotation._ler_csv(csv_desempate)[0]["observacao"] == "Divergência em: CIF-2"
    # o desempatador confirma a CIF-2
    _preencher(tmp_path / "carla.csv", [cif])
    desempate, _ = annotation.importar_planilha(tmp_path / "carla.csv", SEGS)
    final = {g.id: g for g in annotation.consenso(gold_a, gold_b, desempate)}
    assert [c.categoria for c in final["FICT-0001"].contradicoes] == ["CDF-1", "CIF-2"]
    assert final["FICT-0002"].contradicoes == []
