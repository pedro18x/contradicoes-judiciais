from src.preprocess import normalizar, sentencas


def _frases(texto):
    return [texto[a:b] for a, b in sentencas(texto)]


def test_normalizar_nao_apaga_conteudo_parecido_com_rodape():
    texto = (
        "O recorrente juntou aos autos o\n"
        "documento eletrônico de fls. 20, que comprova o pagamento.\n"
        "A procuração cita o advogado Fulano de Tal - SP123456\n"
        "e o precedente REsp 1.234.567 (2019/0123456-7)"
    )
    assert normalizar(texto) == texto


def test_normalizar_tira_orador_na_mesma_linha():
    texto = "RELATÓRIO\nO EXMO. SR. MINISTRO FICTÍCIO DA SILVA (Relator): Trata-se de recurso especial."
    assert normalizar(texto) == "RELATÓRIO\nTrata-se de recurso especial."
    assert normalizar("O Exmo. Sr. Ministro Fulano, em voto-vista, afirmou: há omissão.").startswith(
        "O Exmo."
    )


def test_sentencas_abreviacoes_enumeracao_e_verbetacao():
    texto = (
        "CIVIL. LOCAÇÃO. RECURSO PROVIDO.\n1. Nos termos do art. 1.022 do CPC, cabem embargos. "
        "O Min. Fulano, à fl. 3, votou. O valor é de R$ 10,00. Fim"
    )
    assert _frases(texto) == [
        "CIVIL. LOCAÇÃO. RECURSO PROVIDO.",
        "1. Nos termos do art. 1.022 do CPC, cabem embargos.",
        "O Min. Fulano, à fl. 3, votou.",
        "O valor é de R$ 10,00.",
        "Fim",
    ]


def test_sentencas_empresa_sigla_e_ementa_nova():
    assert len(_frases("Ação contra Empresa Fictícia Ltda. O juízo julgou improcedente.")) == 2
    assert len(_frases("Nos termos do CPC. NÃO há omissão.")) == 2
    ementa = "DIREITO CIVIL. RECURSO PROVIDO.\nI. CASO EM EXAME\n1. Recurso especial contra acórdão."
    assert _frases(ementa)[0] == "DIREITO CIVIL. RECURSO PROVIDO."
