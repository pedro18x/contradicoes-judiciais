"""Normalização do texto do acórdão e divisão em sentenças.

    from src.preprocess import normalizar, sentencas
    texto = normalizar(decisao.texto)
    for ini, fim in sentencas(segs.fundamentacao): ...

`normalizar`:
- Unicode em NFC, espaços colapsados, quebras de linha padronizadas.
- Remove a paginação do inteiro teor do STJ (cabeçalho "Superior Tribunal de Justiça", rodapé
  "Documento: ... Página X de Y", assinatura eletrônica, carimbo e-STJ) e os metadados do processo
  (número/registro, partes, advogados, "O EXMO. SR. MINISTRO ... (Relator):").
- Abreviações jurídicas (art., fls., Min., REsp) ficam como estão.

Os offsets do gold e das predições são calculados sobre o texto normalizado: mudar uma regra aqui
muda os segmentos do corpus inteiro. Rode scripts/avaliar_segmentacao.py depois de qualquer ajuste.

`sentencas` não corta em abreviação ("art. 1.022"), em enumeração ("1.", "IV.") nem dentro da
verbetação da ementa ("CIVIL. LOCAÇÃO. RECURSO PROVIDO." é uma sentença só).
"""

import re
import unicodedata

_PARTES = (
    r"RELATORA?(?: PARA (?:O )?AC[ÓO]RD[ÃA]O)?|AGRAVANTES?|AGRAVAD[OA]S?|RECORRENTES?|RECORRID[OA]S?"
    r"|EMBARGANTES?|EMBARGAD[OA]S?|ADVOGAD[OA]S?|PROCURADOR(?:ES|AS?)?|INTERES\.|INTERESSAD[OA]S?"
    r"|REQUERENTES?|REQUERID[OA]S?|IMPETRANTES?|IMPETRAD[OA]S?|SUSCITANTES?|SUSCITAD[OA]S?"
    r"|AUTOR(?:ES|AS?)?|R[ÉE]US?|REPR\. POR|SOC\. DE ADV\.|SOCIEDADES? DE ADVOGADOS|ASSISTENTES?"
    r"|DEFENSOR(?:ES|AS?)?(?: P[ÚU]BLIC[OA]S?)?|AMICUS CURIAE"
)

# Linhas inteiras que são paginação ou metadados, não conteúdo da decisão. Os padrões são estreitos de
# propósito: uma linha de conteúdo que case com eles some do texto.
_DESCARTAR = [
    r"(?i:superior tribunal de justi[çc]a)",
    r"(?i:documento: ?\d+ - .*)",  # Documento: 123 - Inteiro Teor do Acórdão - ... Página 1 de 5
    r"(?i:p[áa]gina \d+ de \d+)",
    r"(?i:documento eletr[ôo]nico \S+ assinado eletronicamente .*)",
    r"(?i:signat[áa]rio(?:\(a\))?: .*|assinado em: .*|c[óo]digo de controle do documento: .*)",
    r"(?i:publica[çc][ãa]o no djen/cnj .*)",
    r"(?i:\(?e-stj,? fl\.? ?\d+\)?)",  # carimbo de folha
    # REsp Nº 1.234.567 - SP (2019/0123456-7)
    r".{0,80}\b[Nn][º°o]\.? ?[\d.]+(?:/[A-Z]{2})? ?- ?[A-Z]{2} ?\(\d{4}/\d{7}-\d\)",
    rf"(?:{_PARTES})\s*:\s.*",  # RELATOR : MINISTRO ...
    r"[A-ZÀ-Ý][A-ZÀ-Ý .'()/-]{2,120} - [A-Z]{2}\d{3,6}[A-Z]?",  # FULANO E OUTRO(S) - SP123456 (advogados)
]
_LINHA_DESCARTADA = re.compile("^(?:" + "|".join(_DESCARTAR) + ")$")

# "O EXMO. SR. MINISTRO X (Relator):" sozinho na linha ou abrindo o primeiro parágrafo
_ORADOR = re.compile(
    r"^(?:[OA] )?(?:EXM[OA]\.? SRA?\.?|SENHORA?) MINISTR[OA] [A-ZÀ-Ý][A-ZÀ-Ý .'-]*(?:\([^)\n]*\))?\s*:\s*"
)

_INVISIVEIS = re.compile("[\u00ad\u200b-\u200d\u2060\ufeff]")
_ESPACOS = re.compile(r"[ \t\u00a0\u2000-\u200a\u202f\u205f\u3000]+")

ABREVIACOES = {
    "art", "arts", "inc", "incs", "al", "fl", "fls", "n", "nº", "min", "rel", "des", "dr", "dra", "drs",
    "sr", "sra", "srs", "exmo", "exma", "p", "pp", "pág", "págs", "cf", "ex", "v", "vs", "proc", "resp",
    "aresp", "agrg", "agint", "edcl", "res", "dec", "par", "cap", "vol", "ed", "obs", "aprox", "op", "cit",
    "id", "ibid", "v.g", "i.e", "e.g",
}  # fmt: skip
_FIM = re.compile(r"[.!?]+[\"”’')]*(?=\s)|\n\s*\n")


def _fecha_frase(linha: str) -> bool:
    return linha.rstrip("\"”’')").endswith((".", ":", ";", "!", "?"))


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFC", texto)
    texto = re.sub(r"\r\n?|[\f\v]", "\n", texto)
    texto = _ESPACOS.sub(" ", _INVISIVEIS.sub("", texto))

    # Reconstrói o texto linha a linha. Quando uma linha descartada (rodapé, cabeçalho) cai no meio
    # de uma frase, as duas metades voltam a ficar juntas em vez de virar dois parágrafos.
    partes: list[str] = []
    vazio = descartou = False
    for linha in (_ORADOR.sub("", lin.strip()) for lin in texto.split("\n")):
        if not linha:
            vazio = True
        elif _LINHA_DESCARTADA.match(linha):
            descartou = True
        else:
            if partes:
                if descartou and not _fecha_frase(partes[-1]):
                    partes.append("\n")
                else:
                    partes.append("\n\n" if vazio or descartou else "\n")
            partes.append(linha)
            vazio = descartou = False
    return "".join(partes)


def _fecha_sentenca(texto: str, ini: int, m: re.Match) -> bool:
    antes = texto[ini : m.start()]
    palavra = re.search(r"[\w.ºª]*$", antes).group()
    resto = texto[m.end() :]
    seguinte = re.match(r"\S*", resto.lstrip()).group()
    if palavra.lower().strip(".") in ABREVIACOES or (len(palavra) == 1 and palavra.isalpha()):
        return False
    if seguinte[:1].islower():
        return False
    linha = antes[antes.rfind("\n") + 1 :]
    if linha.strip() == palavra and re.fullmatch(r"\d{1,3}|[IVXLC]+|[a-z]", palavra):  # "1." / "IV."
        return False
    # verbetação da ementa: linha toda em maiúsculas e o termo seguinte na mesma linha
    mesma_linha = "\n" not in resto[: len(resto) - len(resto.lstrip())]
    return not (linha.isupper() and mesma_linha and len(seguinte) > 1 and seguinte.isupper())


def sentencas(texto: str) -> list[tuple[int, int]]:
    """Intervalos (início, fim) das sentenças de `texto`, sem espaços nas pontas."""
    cortes, ini = [], 0
    for m in _FIM.finditer(texto):
        if m.group().startswith("\n") or _fecha_sentenca(texto, ini, m):
            cortes.append((ini, m.end()))
            ini = m.end()
    cortes.append((ini, len(texto)))
    saida = []
    for a, b in cortes:
        trecho = texto[a:b]
        if trecho.strip():
            saida.append((a + len(trecho) - len(trecho.lstrip()), a + len(trecho.rstrip())))
    return saida
