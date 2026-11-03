from pathlib import Path

import pytest

from scripts.avaliar_segmentacao import localizar, medir
from src.contratos import Decisao, Segmentos, ler_jsonl
from src.preprocess import normalizar
from src.segment import fatiar, segmentar

FIX = Path(__file__).parent / "fixtures"
DECISOES = ler_jsonl(FIX / "decisoes.jsonl", Decisao)
ESPERADO = {s.id: s for s in ler_jsonl(FIX / "segmentos.jsonl", Segmentos)}
INTEIRO_TEOR = (FIX / "inteiro_teor_stj.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("d", DECISOES, ids=lambda d: d.id)
def test_reproduz_fixture(d):
    assert segmentar(d.id, d.texto) == ESPERADO[d.id]
    assert segmentar(d.id, normalizar(d.texto)) == ESPERADO[d.id]


def test_inteiro_teor_do_stj():
    segs = segmentar("X", normalizar(INTEIRO_TEOR))
    assert segs.ementa == (
        "CIVIL. CONTRATO DE LOCAÇÃO. COBRANÇA DE ALUGUÉIS. RECURSO PROVIDO.\n"
        "1. Os aluguéis vencidos durante a vigência do contrato são devidos.\n"
        "2. Recurso especial provido."
    )
    assert segs.relatorio == (
        "Trata-se de recurso especial interposto por João Fictício, com fundamento no art. 105, III, a, "
        "da CF, contra acórdão que julgou improcedente a ação de cobrança."
    )
    # O rodapé no meio da frase some e a frase volta a ficar inteira; "diante do exposto pelo
    # perito" no meio da frase não é o dispositivo.
    assert segs.fundamentacao == (
        "O contrato de locação estava vigente no período cobrado, conforme os documentos de fls. 10-12. "
        "Os aluguéis desse período não foram\npagos pelo recorrido, e o acórdão recorrido, diante do "
        "exposto pelo perito, deve ser reformado."
    )
    assert segs.dispositivo == "Ante o exposto, dou provimento ao recurso especial."


def test_normalizar_remove_paginacao_e_metadados():
    texto = normalizar(INTEIRO_TEOR)
    for lixo in ["Página", "Superior Tribunal de Justiça\n", "PB999999", "PB888888", "RELATOR :", "EXMO."]:
        assert lixo not in texto
    assert "art. 105, III" in texto  # abreviações ficam
    assert normalizar(texto) == texto


def test_normalizar_espacos_e_unicode():
    decomposto = "Ação"  # "Acção" com acentos combinantes
    assert normalizar(f"  {decomposto}  de\tcobrança  \r\n\r\n\r\nfim­ ") == "Ação de cobrança\n\nfim"


def test_sem_ementa():
    segs = segmentar(
        "X",
        "RELATÓRIO\nTrata-se de recurso.\n\nVOTO\nO recurso não merece prosperar.\n\n"
        "Pelo exposto, nego provimento.",
    )
    assert segs.ementa == ""
    assert segs.relatorio == "Trata-se de recurso."
    assert segs.fundamentacao == "O recurso não merece prosperar."
    assert segs.dispositivo == "Pelo exposto, nego provimento."


def test_texto_sem_titulos_vira_voto():
    segs = segmentar("X", "Os aluguéis são devidos. Isso posto, dou provimento ao recurso.")
    assert (segs.ementa, segs.relatorio) == ("", "")
    assert segs.fundamentacao == "Os aluguéis são devidos."
    assert segs.dispositivo == "Isso posto, dou provimento ao recurso."


def test_dispositivo_sem_formula_usa_verbo_de_decisao():
    segs = segmentar("X", "VOTO\nO dano não foi provado. Nessas condições, nego provimento ao recurso.")
    assert segs.fundamentacao == "O dano não foi provado."
    assert segs.dispositivo == "Nessas condições, nego provimento ao recurso."


def test_voto_vista_e_certidao_ficam_fora():
    texto = (
        "VOTO\nFundamento.\nAnte o exposto, acolho os embargos.\nVOTO-VISTA\nDivirjo.\nCERTIDÃO\nCertifico."
    )
    segs = segmentar("X", texto)
    assert segs.dispositivo == "Ante o exposto, acolho os embargos."
    assert "Divirjo" not in segs.fundamentacao + segs.dispositivo


def test_fatiar_devolve_intervalos_do_texto():
    texto = normalizar(INTEIRO_TEOR)
    segs = segmentar("X", texto)
    for nome, (ini, fim) in fatiar(texto).items():
        assert texto[ini:fim] == getattr(segs, nome)


def test_avaliacao_por_caractere():
    texto = normalizar(INTEIRO_TEOR)
    gold = segmentar("X", texto).model_copy(update={"dispositivo": ""})  # gold sem dispositivo
    gold.fundamentacao = gold.fundamentacao.replace("\n", " ")  # quebra de linha diferente: tolerada
    m = medir(texto, gold)
    assert m["ementa"][0] == m["ementa"][1] == m["ementa"][2]  # P = R = 1
    assert m["fundamentacao"][0] == m["fundamentacao"][1]
    assert m["dispositivo"] == (0, len("Ante o exposto, dou provimento ao recurso especial."), 0)
    assert localizar(texto, "trecho que não existe") is None


def test_relator_vencido_usa_voto_vencedor():
    texto = (
        "EMENTA\nRECURSO PROVIDO.\n\nRELATÓRIO\nTrata-se de recurso.\n\nVOTO\nNão há prova.\n"
        "Ante o exposto, nego provimento.\n\nVOTO VENCEDOR\nHá prova do pagamento.\n"
        "Ante o exposto, dou provimento ao recurso.\n\nCERTIDÃO DE JULGAMENTO\nCertifico."
    )
    segs = segmentar("X", texto)
    assert segs.fundamentacao == "Há prova do pagamento."
    assert segs.dispositivo == "Ante o exposto, dou provimento ao recurso."


def test_titulo_de_voto_fora_da_lista_fecha_o_bloco():
    texto = "VOTO\nFundamento.\nAnte o exposto, dou provimento.\n\nRETIFICAÇÃO DE VOTO\nRevejo a posição."
    assert segmentar("X", texto).dispositivo == "Ante o exposto, dou provimento."


def test_sem_voto_do_relator_avisa(caplog):
    segs = segmentar("X", "RELATÓRIO\nTrata-se de recurso.\n\nVOTO VENCIDO\nDivirjo.\nNego provimento.")
    assert (segs.fundamentacao, segs.dispositivo) == ("", "")
    assert "nenhum título VOTO" in caplog.text


def test_fallback_respeita_abreviacao_e_aceita_pronome():
    segs = segmentar(
        "X", "VOTO\nO dano não foi provado. Assim, com base no art. 932 do CPC, nego-lhe provimento."
    )
    assert segs.fundamentacao == "O dano não foi provado."
    assert segs.dispositivo == "Assim, com base no art. 932 do CPC, nego-lhe provimento."


def test_formula_entre_aspas_nao_e_dispositivo():
    texto = (
        "VOTO\nO acórdão recorrido concluiu: “Ante o exposto, julgo improcedente o pedido.”\n"
        "Contudo, o contrato estava vigente. Ante o exposto, dou provimento ao recurso."
    )
    assert segmentar("X", texto).dispositivo == "Ante o exposto, dou provimento ao recurso."


def test_cli_segmenta_o_corpus(tmp_path, capsys):
    from src import segment

    saida = tmp_path / "segmentos.jsonl"
    segment.main([str(FIX / "decisoes.jsonl"), str(saida)])
    assert {s.id: s for s in ler_jsonl(saida, Segmentos)} == ESPERADO
    assert "2 decisões segmentadas" in capsys.readouterr().out


def test_fechos_e_numero_de_item_solto():
    texto = (
        "RELATÓRIO\nTrata-se de agravo.\nÉ, no essencial, o relatório.\n\nVOTO\n1. O recurso não merece prosperar."
        "\n2.\nAnte o exposto, nego provimento ao agravo interno.\nÉ como penso. É como voto."
    )
    segs = segmentar("X", texto)
    assert segs.relatorio == "Trata-se de agravo."
    assert segs.fundamentacao == "1. O recurso não merece prosperar."
    assert segs.dispositivo == "Ante o exposto, nego provimento ao agravo interno."
    assert segmentar("X", "RELATÓRIO\nFatos.\nÉ o breve relatório.").relatorio == "Fatos."


# Regras ajustadas com os erros achados na conferência de 30 decisões. Textos fictícios.


def test_formula_no_comeco_do_paragrafo_depois_de_aspas_ou_parentese():
    for fim_da_linha in ['efetivada."', "(AgInt no REsp 1/SP, DJe 1º/1/2020)"]:
        texto = f"VOTO\nO acórdão de origem concluiu assim, {fim_da_linha}\nAnte o exposto, nego provimento ao agravo."
        assert segmentar("X", texto).dispositivo == "Ante o exposto, nego provimento ao agravo."


def test_aspa_sem_par_nao_esconde_a_conclusao():
    texto = (
        'VOTO\nA tela tem 12" de largura, conforme o laudo.\n'
        "Diante do exposto, o Tribunal de origem negou provimento à apelação e manteve a sentença, em decisão\n"
        "que se transcreve sem aspas no voto.\n"
        "Ante o exposto, nego provimento ao agravo regimental."
    )
    segs = segmentar("X", texto)
    assert segs.dispositivo == "Ante o exposto, nego provimento ao agravo regimental."
    assert segs.fundamentacao.startswith("A tela")


def test_formula_citada_no_proprio_paragrafo_continua_ignorada():
    texto = 'VOTO\nO acórdão disse: "Ante o exposto, julgo improcedente."\nNego provimento ao recurso.'
    assert segmentar("X", texto).dispositivo == "Nego provimento ao recurso."


def test_formulas_novas_e_subtitulo_do_dispositivo():
    texto = "VOTO\nNão houve omissão.\nDISPOSITIVO\nForte nessas razões, REJEITO os embargos de declaração."
    segs = segmentar("X", texto)
    assert segs.fundamentacao == "Não houve omissão."  # o subtítulo fica fora das partes
    assert segs.dispositivo == "Forte nessas razões, REJEITO os embargos de declaração."
    texto = "VOTO\nO laudo é claro.\nManifesto meu voto, portanto, pelo não provimento do recurso."
    assert segmentar("X", texto).dispositivo.startswith("Manifesto meu voto")


def test_nessas_condicoes_so_conta_quando_decide():
    texto = (
        "VOTO\nNessas condições, o recurso não prospera quanto ao mérito.\n"
        "Nessas condições, NEGO PROVIMENTO ao agravo interno.\n"
        "Em razão disso, JULGO PREJUDICADO o pedido de efeito suspensivo."
    )
    segs = segmentar("X", texto)
    assert segs.fundamentacao == "Nessas condições, o recurso não prospera quanto ao mérito."
    assert segs.dispositivo.startswith("Nessas condições, NEGO PROVIMENTO")


def test_relatorio_termina_no_e_o_relatorio_e_rotulo_do_ministro_sai():
    texto = (
        "RELATÓRIO\nMINISTRA FULANA DE TAL: Trata-se de agravo interno.\nÉ o relatório.\n"
        "RELATORA : MINISTRA FULANA DE TAL\nAGRAVANTE : EMPRESA FICTÍCIA LTDA\n\n"
        "VOTO\nMINISTRA FULANA DE TAL (Relatora): O agravo não merece provimento.\n"
        "Ante o exposto, nego provimento ao agravo interno."
    )
    segs = segmentar("X", texto)
    assert segs.relatorio == "Trata-se de agravo interno."
    assert segs.fundamentacao == "O agravo não merece provimento."


def test_relator_vencido_sem_voto_vencedor_usa_o_voto_vista_de_quem_lavra():
    texto = (
        "ACÓRDÃO\nA Turma, por maioria, concedeu a ordem, nos termos do voto do Sr. Ministro Beltrano Fictício, "
        "que lavrará o acórdão. Vencido o Sr. Ministro Relator.\n\n"
        "VOTO\nNão há ilegalidade.\nAnte o exposto, não conheço do habeas corpus.\n\n"
        "VOTO-VISTA\nO EXMO. SR. MINISTRO SICRANO FICTÍCIO: Acompanho o relator.\nAnte o exposto, não conheço.\n\n"
        "VOTO-VISTA\nO EXMO. SR. MINISTRO BELTRANO FICTÍCIO: Houve prescrição.\n"
        "Pelo exposto, concedo a ordem de ofício."
    )
    segs = segmentar("X", texto)
    assert segs.fundamentacao == "Houve prescrição."
    assert segs.dispositivo == "Pelo exposto, concedo a ordem de ofício."


def test_ementa_de_precedente_dentro_do_voto_nao_fecha_o_voto_e_ementa_vazia_e_pulada():
    texto = (
        "ACÓRDÃO\nA Turma negou provimento.\nEMENTA\n\nRELATÓRIO\nTrata-se de agravo.\n\n"
        "EMENTA\nAGRAVO. MULTA. AGRAVO NÃO PROVIDO.\n\nVOTO\nO precedente é claro:\nEMENTA\n"
        "TRIBUTÁRIO. TEMA REPETITIVO. RECURSO PROVIDO.\nAplica-se o tema ao caso.\n"
        "Ante o exposto, nego provimento ao agravo."
    )
    segs = segmentar("X", texto)
    assert segs.ementa == "AGRAVO. MULTA. AGRAVO NÃO PROVIDO."
    assert segs.dispositivo == "Ante o exposto, nego provimento ao agravo."
    assert "Aplica-se o tema" in segs.fundamentacao
