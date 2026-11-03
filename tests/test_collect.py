"""Coleta do STJ com um portal falso em memória (dados fictícios): nenhum teste acessa a rede."""

import datetime as dt
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from src.collect import stj
from src.contratos import Decisao, ler_jsonl

BASE = "https://portal.test/"


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Constata-se a contradição no acórdão embargado.", True),
        ("Embargos de declaração acolhidos para sanar contradição.", True),
        ("O acórdão incorreu em contradição ao afirmar que o contrato estava vigente.", True),
        ("EXISTÊNCIA DE CONTRADIÇÃO ENTRE A FUNDAMENTAÇÃO E O DISPOSITIVO.", True),
        ("CONTRADIÇÃO CONFIGURADA.", True),
        ("OMISSÃO, CONTRADIÇÃO, OBSCURIDADE OU ERRO MATERIAL. INEXISTÊNCIA.", False),
        ("CONTRADIÇÃO. AUSÊNCIA. OMISSÃO. AUSÊNCIA.", False),
        ("Não há contradição no julgado.", False),
        ("ERRO MATERIAL. EXISTÊNCIA.", False),
        ("APONTADA CONTRADIÇÃO NO ACÓRDÃO EMBARGADO. OCORRÊNCIA. CONTRADIÇÃO SANADA.", True),
        (
            (
                "Os embargos de declaração têm como objetivo sanar eventual existência de obscuridade, contradição, "
                "omissão ou erro material (CPC/2015, art. 1.022). Na espécie, contradição reconhecida e sanada."
            ),
            True,
        ),
        # frase-padrão dos embargos (casos reais de acolhimento por omissão e por erro material)
        (
            (
                "Os embargos de declaração constituem recurso de estritos limites processuais e destinam-se a suprir "
                "omissão, afastar obscuridade, eliminar contradição eventualmente existentes no julgado combatido, bem "
                "como corrigir erro material. 2. Omissão existente em relação ao sobrestamento do feito."
            ),
            False,
        ),
        ("OMISSÃO, CONTRADIÇÃO OU OBSCURIDADE. EXISTÊNCIA.", False),
        # ementas no formato do CNJ (casos reais acolhidos por outros motivos)
        (
            "A questão em discussão consiste em saber se há omissão ou contradição no acórdão embargado.",
            False,
        ),
        ("A embargante alega omissão/contradição no acórdão embargado quanto aos honorários.", False),
        ("Não há omissão ou contradição a ser sanada, pois a decisão embargada expôs as razões.", False),
    ],
)
def test_aponta_contradicao(texto, esperado):
    assert stj.aponta_contradicao(texto) is esperado


@pytest.mark.parametrize(
    "decisao, esperado",
    [
        ("por unanimidade, acolher os embargos de declaração, com efeitos modificativos", "acolhidos"),
        ("acolher parcialmente os embargos de declaração", "acolhidos"),
        ("por maioria, rejeitar os embargos. Votaram vencidos os que os acolhiam.", "rejeitados"),
        ("não conhecer dos embargos de declaração", None),
        ("acolher os embargos de A e rejeitar os de B", None),
    ],
)
def test_resultado_embargos(decisao, esperado):
    assert stj.resultado_embargos(decisao) == esperado


def test_classe_data_e_texto():
    assert stj.classe_embargada("EDcl no AgInt no AREsp") == "AgInt no AREsp"
    assert stj.classe_embargada("EDcl nos EDcl no REsp") == "EDcl no REsp"
    assert stj.classe_embargada("AgInt no REsp") is None
    assert stj.data_publicacao("DJEN       DATA:19/08/2025") == dt.date(2025, 8, 19)
    assert stj.data_publicacao("None") is None
    assert stj.limpar_texto("EMENTA<br>Linha &amp; outra<BR/>fim ") == "EMENTA\nLinha & outra\nfim"


# ------------------------------------------------------------------ portal falso


def _espelho(id, registro, classe, numero, publicacao, relator="MINISTRA FICTÍCIA"):
    return {
        "id": id, "numeroRegistro": registro, "siglaClasse": classe, "numeroProcesso": numero,
        "ministroRelator": relator, "nomeOrgaoJulgador": "TERCEIRA TURMA", "dataDecisao": publicacao.replace("-", ""),
        "dataPublicacao": "DJEN DATA:" + "/".join(reversed(publicacao.split("-"))), "ementa": "",
        "decisao": "", "informacoesComplementares": None,
    }  # fmt: skip


def _meta(seq, registro, processo, recurso, teor, relator="Ministra Fictícia", tipo="ACÓRDÃO"):
    return {
        "SeqDocumento": seq, "numeroRegistro": registro, "processo": processo, "recurso": recurso,
        "teor": teor, "NM_MINISTRO": relator, "tipoDocumento": tipo,
    }  # fmt: skip


VOTO = "EMENTA\nCIVIL. RECURSO PROVIDO.\nRELATÓRIO\nTrata-se de agravo.\nVOTO\nO contrato estava vigente.\nAnte o exposto, nego provimento."


def _embargos(resultado, ementa, relatorio="Opostos embargos."):
    return (
        f"ACÓRDÃO\nacordam os Ministros, por unanimidade, {resultado} os embargos de declaração.\nEMENTA\n{ementa}"
        f"\nRELATÓRIO\n{relatorio}\nVOTO\nÉ o voto."
    )


class PortalFalso(stj.Portal):
    """Espelhos, metadados e ZIPs fictícios em memória; registra as requisições."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path / "cache", pausa=0)
        self.requisicoes = []
        espelhos = [
            # a relatora fictícia está na Terceira Turma em março e junho (pelo menos 3 acórdãos por mês)
            *(_espelho(f"x{i}", f"X{i}", "REsp", str(i), "2025-03-1" + str(i)) for i in range(3)),
            *(_espelho(f"y{i}", f"Y{i}", "REsp", str(i), "2025-06-1" + str(i)) for i in range(3)),
            # R1 tem espelho dos embargos e do embargado: a classe vem de lá
            _espelho("1", "R1", "AgInt no AREsp", "100", "2025-03-10"),
            _espelho("2", "R1", "EDcl no AgInt no AREsp", "100", "2025-06-02"),
        ]
        meta = {
            "20250310": [
                _meta(11, "R1", "AREsp 100", "AgInt", "Negando"),
                _meta(31, "R3", "AREsp 300", None, "Não Conhecendo"),
                _meta(51, "R5", "REsp 500", None, "Negando"),
            ],
            "20250602": [
                _meta(12, "R1", "AREsp 100", "EDcl  ", "Admitindo Embargo"),  # positivo (espelho)
                _meta(22, "R2", "REsp 200", "EDcl", "Admitindo Embargo"),  # acolhidos por omissão: sai
                _meta(32, "R3", "AREsp 300", "EDcl", "Negando"),  # negativo (embargado pelos metadados)
                _meta(42, "R4", "REsp 400", "EDcl", "Negando"),  # sem acórdão anterior
                _meta(52, "R5", "REsp 500", "EDcl", "Negando"),  # alegou contradição, rejeitada
                _meta(
                    62, "R6", "HC 600", "EDcl", "Admitindo Embargo", relator="Ministro Penal"
                ),  # outra Seção, sem acórdão anterior
                _meta(99, "R1", "AREsp 100", None, "Negando", tipo="DECISÃO"),
            ],
        }
        textos = {
            "20250310": {11: VOTO, 31: VOTO, 51: VOTO},
            "20250602": {
                12: _embargos("acolher", "CIVIL. EMBARGOS DE DECLARAÇÃO. CONTRADIÇÃO. OCORRÊNCIA."),
                22: _embargos("acolher", "CIVIL. EMBARGOS DE DECLARAÇÃO. OMISSÃO. OCORRÊNCIA."),
                32: _embargos("rejeitar", "VÍCIOS. INEXISTÊNCIA."),
                42: _embargos("rejeitar", "VÍCIOS. INEXISTÊNCIA."),
                52: _embargos(
                    "rejeitar",
                    "VÍCIOS. INEXISTÊNCIA.",
                    "A embargante alega contradição entre a fundamentação e o dispositivo.",
                ),
                62: _embargos("acolher", "PENAL. CONTRADIÇÃO. OCORRÊNCIA."),
            },
        }
        self.arquivos = {
            BASE + "t3/20250630.json": json.dumps(espelhos).encode(),
            BASE + "t3/20240131.json": b"[]",  # extração anterior à janela: não deve ser baixada
        }
        recursos_integras = []
        for dia, docs in textos.items():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for seq, t in docs.items():
                    z.writestr(f"{seq}.txt", t.replace("\n", "<br>"))
            self.arquivos[BASE + f"i/textos{dia}.zip"] = buf.getvalue()
            self.arquivos[BASE + f"i/metadados{dia}.json"] = json.dumps(meta[dia]).encode()
            recursos_integras += [
                {"url": BASE + f"i/textos{dia}.zip"},
                {"url": BASE + f"i/metadados{dia}.json"},
            ]
        self.pacotes = {
            stj.TURMAS["terceira"]: [{"url": BASE + "t3/20240131.json"}, {"url": BASE + "t3/20250630.json"}],
            stj.PACOTES_INTEGRAS[1]: recursos_integras,
            stj.PACOTES_INTEGRAS[0]: [],
        }

    def recursos(self, pacote):
        return self.pacotes[pacote]

    def _requisitar(self, url, cabecalhos=None, metodo="GET"):
        self.requisicoes.append((metodo, url, (cabecalhos or {}).get("Range")))
        dados = self.arquivos[url]
        if metodo == "HEAD":
            return {"Content-Length": str(len(dados))}, b""
        if cabecalhos and "Range" in cabecalhos:
            ini, fim = map(int, cabecalhos["Range"].removeprefix("bytes=").split("-"))
            return {}, dados[ini : fim + 1]
        return {}, dados


def _args(**extra):
    base = {
        "desde": "2025-06", "ate": "2025-06", "turmas": ["terceira"], "max": 2, "proporcao_negativos": 1.0,
        "base_sintetico": 2, "so_direito_privado": False, "meses_embargado": 6, "seed": 42,
    }  # fmt: skip
    return SimpleNamespace(**{**base, **extra})


def test_partes_do_acordao_e_nome():
    dispositivo, ementa = stj.partes_do_acordao(_embargos("acolher", "CONTRADIÇÃO. OCORRÊNCIA."))
    assert "acolher os embargos" in dispositivo and ementa.strip() == "CONTRADIÇÃO. OCORRÊNCIA."
    doc = stj.documento(_meta(1, "R", "AREsp 9", "AgInt", "Negando"), dt.date(2025, 1, 2))
    assert doc.nome == "AgInt no AREsp 9" and not doc.embargos and doc.acordao
    assert stj.normalizar_nome("Ricardo Villas Bôas Cueva (Relator)") == "RICARDO VILLAS BOAS CUEVA"
    # esquema de 2022: seqDocumento e ministro; linha sem identificador é ignorada
    antigo = {"seqDocumento": 7, "numeroRegistro": "R", "processo": "REsp 1", "recurso": "EDcl", "ministro": "X",
              "teor": "Negando", "tipoDocumento": "ACÓRDÃO"}  # fmt: skip
    doc = stj.documento(antigo, dt.date(2022, 5, 3))
    assert (doc.seq, doc.relator, doc.embargos) == (7, "X", True)
    assert stj.documento({"processo": "REsp 1"}, dt.date(2022, 5, 3)) is None


def test_grafias_reais_dos_metadados_por_ano():
    """Valores vistos no portal: 2021 escreve ACORDAO sem acento; 2022 e 2023 escrevem o recurso por extenso."""
    de_2021 = stj.documento(_meta(1, "R", "REsp 1", "EDcl  ", "Negando", tipo="ACORDAO"), dt.date(2021, 3, 4))
    assert de_2021.acordao and de_2021.embargos
    por_extenso = _meta(2, "R", "HC 731169     ", "EMBARGOS DE DECLARAÇÃO", "Negando")
    de_2022 = stj.documento(por_extenso, dt.date(2022, 6, 13))
    assert de_2022.embargos and de_2022.processo == "HC 731169"
    agravo = stj.documento(_meta(3, "R", "HC 1", "AGRAVO REGIMENTAL", "Negando"), dt.date(2022, 6, 13))
    assert not agravo.embargos
    assert not stj.documento(
        _meta(4, "R", "HC 1", "", "Negando", tipo="DECISAO"), dt.date(2021, 3, 4)
    ).acordao


def test_texto_em_subpasta_do_zip():
    """Em 2022 e 2023 os ZIPs guardam os textos em <AAAAMMDD>/<seq>.txt."""

    class Portal:
        def recursos(self, pacote):
            return [{"url": "u/20220613.zip"}, {"url": "u/metadados20220613.json"}]

        def membro_zip(self, url, nome, cache):
            return b"EMENTA<br>texto" if nome == "20220613/7.txt" else None

    integras = stj.Integras(Portal())
    doc = stj.Documento(7, "R", dt.date(2022, 6, 13), "REsp 1", "", "X", "Negando", True)
    assert integras.texto(doc) == "EMENTA\ntexto"


def test_criterio_dos_embargos():
    assert stj.criterio_dos_embargos(_embargos("acolher", "CONTRADIÇÃO. OCORRÊNCIA.")) == "reconhecida"
    assert stj.criterio_dos_embargos(_embargos("acolher", "OMISSÃO. OCORRÊNCIA.")) is None
    alega = "A embargante aponta contradição no acórdão embargado."
    assert stj.criterio_dos_embargos(_embargos("acolher", "OMISSÃO. OCORRÊNCIA.", alega)) is None
    assert stj.criterio_dos_embargos(_embargos("rejeitar", "VÍCIOS. INEXISTÊNCIA.", alega)) == "rejeitada"
    assert stj.criterio_dos_embargos(_embargos("rejeitar", "VÍCIOS. INEXISTÊNCIA.")) == "negativa"
    assert stj.aponta_contradicao("Inexiste contradição no acórdão embargado.") is False
    # cabeçalho que enumera os vícios e diz "existência parcial" não afirma qual deles existe
    assert not stj.aponta_contradicao(
        "EMBARGOS DE DECLARAÇÃO. OMISSÃO. OBSCURIDADE. CONTRADIÇÃO. EXISTÊNCIA PARCIAL."
    )
    assert stj.aponta_contradicao("AGRAVO INTERNO. OMISSÃO E CONTRADIÇÃO. EXISTÊNCIA. EFEITOS INFRINGENTES.")
    assert stj.aponta_contradicao(
        "Embargos de declaração acolhidos para sanar a contradição sem efeitos infringentes."
    )
    # casos reais: alegação negada ou genérica não conta; alegação específica conta
    assert not stj.alega_contradicao(
        "O embargante não aponta omissões, contradições ou obscuridades no acórdão."
    )
    assert not stj.alega_contradicao(
        "A parte alega omissão, contradição, obscuridade e erro material no julgado."
    )
    assert stj.alega_contradicao(
        "A parte embargante alega contradição na decisão ao não reconhecer a gratuidade."
    )
    # o princípio do contraditório e fatos "contraditórios" não são alegação de contradição no julgado
    assert not stj.alega_contradicao(
        "O embargante sustenta a existência de omissão quanto à violação do contraditório e da ampla defesa."
    )
    assert not stj.alega_contradicao("Afirma que houve introdução de fatos novos, inclusive contraditórios.")
    assert not stj.aponta_contradicao("Houve contraditório regular no processo.")


def test_coleta_pelo_rotulo_do_tribunal(tmp_path):
    portal = PortalFalso(tmp_path)
    decisoes, falhas, criterios = stj.coletar(_args(), portal)
    por_id = {d.id: d for d in decisoes}
    # 1 reconhecida (R1; R6 não tem embargado), 1 rejeitada para ela (R5, 1:1) e as negativas para o
    # sintético: 2 pedidas, mas só R3 serve (R4 não tem embargado)
    assert criterios == {"STJ-R1-11": "reconhecida", "STJ-R5-51": "rejeitada", "STJ-R3-31": "negativa"}
    positivo = por_id["STJ-R1-11"]
    assert positivo.rotulo_decisao is True
    assert positivo.processo == "AgInt no AREsp 100" and positivo.data == "2025-03-10"
    assert positivo.relator == "Ministra Fictícia" and positivo.url.endswith("R1")
    assert positivo.texto.startswith("EMENTA\nCIVIL. RECURSO PROVIDO.")  # o embargado, com as quebras
    assert "CONTRADIÇÃO. OCORRÊNCIA." in positivo.texto_embargos
    assert por_id["STJ-R5-51"].rotulo_decisao is False  # o tribunal rejeitou a contradição alegada
    assert por_id["STJ-R3-31"].rotulo_decisao is False and por_id["STJ-R3-31"].processo == "AREsp 300"
    # R2 (omissão) é descartado e a DECISÃO monocrática não conta; R6 e R4 não têm embargado
    assert falhas == [
        {"processo": "EDcl no HC 600", "registro": "R6", "motivo": "embargado não encontrado"},
        {"processo": "EDcl no REsp 400", "registro": "R4", "motivo": "embargado não encontrado"},
    ]
    baixados = {u for _, u, _ in portal.requisicoes}
    assert BASE + "t3/20240131.json" not in baixados
    assert all(
        r for m, u, r in portal.requisicoes if u.endswith(".zip") and m == "GET"
    )  # ZIP só por intervalos


def test_metas_filtro_de_secao_e_saida(tmp_path, monkeypatch, capsys):
    assert stj.coletar(_args(max=0, base_sintetico=0), PortalFalso(tmp_path))[0] == []
    # sem reconhecidas não há rejeitadas (1:1); só a base do sintético
    decisoes, _, criterios = stj.coletar(_args(max=0, base_sintetico=1), PortalFalso(tmp_path))
    assert [d.rotulo_decisao for d in decisoes] == [False] and list(criterios.values()) == ["negativa"]
    # só Direito Privado: R6 (outra Seção) nem é tentado
    _, falhas, _ = stj.coletar(_args(so_direito_privado=True), PortalFalso(tmp_path))
    assert [f["registro"] for f in falhas] == ["R4"]
    monkeypatch.setattr(stj, "Portal", lambda cache, pausa: PortalFalso(tmp_path))
    saida = tmp_path / "decisoes.jsonl"
    argv = [
        "--desde",
        "2025-06",
        "--ate",
        "2025-06",
        "--turmas",
        "terceira",
        "--meses-embargado",
        "6",
        "--max",
        "2",
    ]
    stj.main([*argv, "--saida", str(saida)])
    assert sorted(d.rotulo_decisao for d in ler_jsonl(saida, Decisao)) == [False, False, True]
    assert "embargado não encontrado" in (tmp_path / "decisoes.jsonl.log.jsonl").read_text()
    assert '"criterio": "rejeitada"' in (tmp_path / "decisoes.jsonl.criterios.jsonl").read_text()
    saida_texto = capsys.readouterr().out
    assert "1 com contradição reconhecida, 1 com contradição alegada e rejeitada, 1 negativas" in saida_texto
