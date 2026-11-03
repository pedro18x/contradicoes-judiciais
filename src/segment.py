"""Segmentação do acórdão em ementa, relatório, fundamentação e dispositivo.

    from src.segment import segmentar
    segs = segmentar(decisao.id, normalizar(decisao.texto))

Regras:
- Os blocos são delimitados pelos títulos do inteiro teor em linha própria (EMENTA, ACÓRDÃO, RELATÓRIO,
  VOTO, CERTIDÃO DE JULGAMENTO...), inclusive com letras espaçadas ("R E L A T Ó R I O") ou sem acento.
- Fundamentação e dispositivo saem do voto condutor: o VOTO VENCEDOR, se houver (relator vencido); quando
  o acórdão diz que outro ministro "lavrará o acórdão" e não há VOTO VENCEDOR, o VOTO-VISTA desse ministro
  (ou o primeiro voto-vista); senão o primeiro VOTO. Os demais votos (vista, vencido, vogal,
  retificação...), a certidão de julgamento e o bloco ACÓRDÃO ficam de fora.
- O dispositivo começa na última frase aberta por uma fórmula de conclusão ("Ante o exposto", "Pelo
  exposto", "Isso posto", "Forte nessas razões"...) que não esteja entre aspas no seu parágrafo. Começo de
  parágrafo conta como começo de frase, mesmo depois de aspas ou parêntese. Sem fórmula, começa na última
  frase com verbo de decisão ("nego provimento", "acolho os embargos", "indefiro"...).
- O relatório termina antes do último "É o relatório." do bloco (o que vem depois é cabeçalho de página).
- Rótulo com o nome do ministro no começo do relatório ou do voto ("MINISTRA FULANA (Relatora):") sai.
- Texto sem nenhum título (colado na demo) é tratado inteiro como voto.
- Fechos protocolares ("É o relatório.", "É como voto.") saem. Segmento não encontrado = "".

Cada segmento é um trecho contínuo do texto recebido; `fatiar` devolve esses intervalos.

    python -m src.segment data/decisoes.jsonl data/segmentos.jsonl   # normaliza e segmenta o corpus
"""

import argparse
import logging
import re
import unicodedata
from collections import Counter

from src.contratos import Decisao, Segmentos, escrever_jsonl, ler_jsonl
from src.preprocess import normalizar, sentencas

log = logging.getLogger(__name__)

_ACENTOS = {"A": "[AÁÂÃ]", "E": "[EÉÊ]", "I": "[IÍ]", "O": "[OÓÔÕ]", "U": "[UÚ]", "C": "[CÇ]"}

_TITULOS = {
    "ementa": ["EMENTA"],
    "acordao": ["ACORDAO"],
    "relatorio": ["RELATORIO"],
    "voto": ["VOTO"],
    "vencedor": ["VOTO VENCEDOR"],
    "outro": ["ESCLARECIMENTOS", "CERTIDAO DE JULGAMENTO", "CERTIDAO", "EXTRATO DE ATA"],
}
# Qualquer outro título de voto em maiúsculas: VOTO-VISTA, VOTO VENCIDO, RETIFICAÇÃO DE VOTO...
_OUTRO_VOTO = r"(?-i:VOTO[ -][A-ZÀ-Ý][A-ZÀ-Ý -]*|[A-ZÀ-Ý][A-ZÀ-Ý ]* (?:DE|AO|DO) VOTO)"


def _titulo(frase: str) -> str:
    """Regex de um título escrito sem acento: aceita acento, letras espaçadas e hífen entre palavras."""
    palavras = [" ?".join(_ACENTOS.get(c, re.escape(c)) for c in p) for p in frase.split()]
    return "[ -]+".join(palavras)


_TITULO = re.compile(
    r"^[ \t]*(?:"
    + "|".join(f"(?P<{tipo}>{'|'.join(map(_titulo, frases))})" for tipo, frases in _TITULOS.items())
    + f"|(?P<outro_voto>{_OUTRO_VOTO})"
    + r")[ \t]*[:.]?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

_FORMULA_CONCLUSAO = re.compile(
    r"\b(?:"
    r"(?:ante|diante|pelo|em face|em vista|à vista|por todo|do)\s+(?:d?o\s+|de\s+)?(?:todo\s+o\s+)?"
    r"(?:acima\s+)?exposto"
    r"|is[st]o\s+posto|posto\s+is[st]o"
    r"|(?:com|por|feitas)\s+(?:essas|estas|tais)\s+(?:considera[çc][õo]es|raz[õo]es)"
    r"|forte\s+(?:n(?:essas|estas)|em\s+(?:tais|essas|estas))\s+(?:considera[çc][õo]es|raz[õo]es)"
    r"|por\s+(?:esses|estes|tais)\s+fundamentos"
    r"|manifesto\s+(?:o\s+)?meu\s+voto"
    r")\b",
    re.IGNORECASE,
)

_VERBO_DECISAO = re.compile(
    r"\b(?:(?:dou|nego|dar|negar|d[áa]-se|nega-se)(?:-lhes?)?(?:\s+parcial)?\s+provimento"
    r"|(?:n[ãa]o\s+)?conhe[çc]o|acolho|acolhem-se|rejeito|rejeitam-se|julgo|(?:in)?defiro)\b",
    re.IGNORECASE,
)
# "Nessas condições" também abre raciocínio ("Nessas condições, o recurso não prospera"): só conta como
# fórmula de conclusão quando a mesma frase decide ("Nessas condições, NEGO PROVIMENTO ao agravo")
_FORMULA_FRACA = re.compile(r"\b(?:n(?:essas|estas)|em\s+tais)\s*condi[çc][õo]es\b", re.IGNORECASE)

# "É o relatório.", "É, no essencial, o relatório.", "É o breve relatório.", "É como voto.", "É como penso."
_FECHO = re.compile(
    r"(?:é,?\s+(?:(?:em\s+s[íi]ntese|no\s+essencial|no\s+que\s+importa),?\s+)?o\s+(?:breve\s+)?relat[óo]rio"
    r"|é\s+(?:como|o)\s+(?:meu\s+)?(?:penso(?:\s+e\s+voto)?|voto))\.?\s*$",
    re.IGNORECASE,
)
# número de item que ficou sozinho no fim da fundamentação ("2.") quando o dispositivo é o item seguinte, ou
# o subtítulo da conclusão ("VI. Dispositivo", "DISPOSITIVO", "Conclusão")
_ITEM_SOLTO = re.compile(
    r"(?:^|\n)\s*(?:(?:\d{1,3}|[IVXLC]+)\s*[.)\-–]?\s*)?(?:(?i:dispositivo|conclus[ãa]o)\s*[.:]?\s*)?$"
)


def _inicio_paragrafo(texto: str, ini: int, pos: int) -> int:
    return max(ini, texto.rfind("\n", ini, pos) + 1)


def _inicia_frase(texto: str, ini: int, pos: int) -> bool:
    """Começo de parágrafo ou depois de pontuação final. Começo de parágrafo vale mesmo quando a linha de
    cima termina em aspas ou parêntese ('...efetivada."' / '...(EDcl no AgInt...)')."""
    if not texto[_inicio_paragrafo(texto, ini, pos) : pos].strip():
        return True
    antes = texto[ini:pos].rstrip()
    return not antes or antes[-1] in ".:;!?"


def _entre_aspas(texto: str, ini: int, pos: int) -> bool:
    """Aspas abertas no próprio parágrafo. Contar desde o começo do voto falha quando uma aspa fica sem par
    (citação longa, polegada): tudo o que vem depois parece citado."""
    antes = texto[_inicio_paragrafo(texto, ini, pos) : pos]
    return antes.count("“") > antes.count("”") or antes.count('"') % 2 == 1


def _decide_na_frase(texto: str, pos: int, fim: int) -> bool:
    """A frase que começa em `pos` (até o ponto final ou a quebra de linha) tem verbo de decisão."""
    frase = re.match(r"[^\n]*?(?:\.(?=\s)|\n|$)", texto[pos : min(fim, pos + 400)])
    return bool(_VERBO_DECISAO.search(frase.group() if frase else ""))


def _inicio_dispositivo(texto: str, ini: int, fim: int) -> int:
    def valida(pos: int) -> bool:
        return _inicia_frase(texto, ini, pos) and not _entre_aspas(texto, ini, pos)

    formulas = [m.start() for m in _FORMULA_CONCLUSAO.finditer(texto, ini, fim) if valida(m.start())]
    formulas += [
        m.start()
        for m in _FORMULA_FRACA.finditer(texto, ini, fim)
        if valida(m.start()) and _decide_na_frase(texto, m.start(), fim)
    ]
    if formulas:
        return max(formulas)
    verbos = list(_VERBO_DECISAO.finditer(texto, ini, fim))
    if not verbos:
        return fim
    pos = verbos[-1].start() - ini
    inicio_frase = max((a for a, _ in sentencas(texto[ini:fim]) if a <= pos), default=0)
    return ini + inicio_frase


def _aparar(texto: str, ini: int, fim: int) -> tuple[int, int]:
    """Tira espaços das pontas e o fecho protocolar do fim. Trecho vazio vira (ini, ini)."""
    while m := _FECHO.search(texto, ini, fim):  # pode haver dois: "É como penso. É como voto."
        fim = m.start()
    if m := _ITEM_SOLTO.search(texto, ini, fim):
        fim = m.start()
    trecho = texto[ini:fim]
    if not trecho.strip():
        return ini, ini
    return ini + len(trecho) - len(trecho.lstrip()), ini + len(trecho.rstrip())


# "nos termos do voto do Sr. Ministro Fulano de Tal, que lavrará o acórdão": o relator ficou vencido
_LAVRA = re.compile(
    r"voto\s+d[oa]\s+(?:Sr[a]?\.?\s+|Exm[oa]\.?\s+)*Ministr[oa]\s+(?P<nome>[^,;]+?)\s*,?\s+que\s+lavrar[áa]"
    r"\s+o\s+ac[óo]rd[ãa]o",
    re.IGNORECASE,
)
_FIM_RELATORIO = re.compile(
    r"é,?\s+(?:(?:em\s+s[íi]ntese|no\s+essencial|no\s+que\s+importa),?\s+)?o\s+(?:breve\s+)?relat[óo]rio\b",
    re.IGNORECASE,
)
# "MINISTRA FULANA (Relatora):", "O EXMO. SR. MINISTRO FULANO:", "Relatora: MINISTRA FULANA" (linha própria)
_ROTULO = re.compile(
    r"\s*(?:Relator[a]?\s*:\s*)?(?:(?:O|A)\s+EXM[OA]\.?\s+SR[A]?\.?\s+)?MINISTR[OA]\s+[A-ZÀ-Ý][A-ZÀ-Ý .'-]*?"
    r"(?:\s*\((?:Relator|Relatora|Presidente)\))?\s*(?::|(?=\n))"
)


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()


def _voto_vista_vencedor(texto: str, titulos: list, fim_de) -> tuple[int, int] | None:
    """Relator vencido sem título VOTO VENCEDOR: o voto-vista de quem lavra o acórdão (ou o primeiro)."""
    m = _LAVRA.search(texto)
    vistas = [(t.end(), fim_de(i)) for i, t in enumerate(titulos) if "VISTA" in _sem_acento(t.group())]
    if not m or not vistas:
        return None
    nome = _sem_acento(" ".join(m["nome"].split()))
    for ini, fim in vistas:  # o rótulo com o nome abre o voto: "O EXMO. SR. MINISTRO FULANO:"
        if nome in _sem_acento(" ".join(texto[ini : min(fim, ini + 400)].split())):
            return ini, fim
    return vistas[0]


def _sem_rotulo(texto: str, ini: int, fim: int) -> int:
    m = _ROTULO.match(texto, ini, fim)
    return m.end() if m else ini


def fatiar(texto: str) -> dict[str, tuple[int, int]]:
    """Intervalos (início, fim) de cada segmento em `texto`."""
    titulos = list(_TITULO.finditer(texto))

    def fim_de(i: int) -> int:
        return titulos[i + 1].start() if i + 1 < len(titulos) else len(texto)

    def fim_do_voto(i: int) -> int:
        # "EMENTA" com texto, dentro do voto, é de precedente citado: não fecha o voto, senão a conclusão que
        # vem depois fica de fora. Um "EMENTA" vazio (separador entre votos) fecha.
        for j in range(i + 1, len(titulos)):
            if titulos[j].lastgroup != "ementa" or not texto[titulos[j].end() : fim_de(j)].strip():
                return titulos[j].start()
        return len(texto)

    blocos: dict[str, tuple[int, int]] = {}
    for i, m in enumerate(titulos):
        fim = fim_do_voto(i) if m.lastgroup in ("voto", "vencedor", "outro_voto") else fim_de(i)
        # a primeira ementa pode ser só o título, com a ementa de verdade num segundo bloco EMENTA
        if m.lastgroup == "ementa" and "ementa" in blocos and not texto[slice(*blocos["ementa"])].strip():
            del blocos["ementa"]
        blocos.setdefault(m.lastgroup, (m.end(), fim))
    if not titulos:
        blocos["voto"] = (0, len(texto))

    voto = blocos.get("vencedor") or _voto_vista_vencedor(texto, titulos, fim_do_voto) or blocos.get("voto")
    if voto is None:
        log.warning("nenhum título VOTO encontrado: fundamentação e dispositivo ficam vazios")
        voto = (0, 0)
    voto = (_sem_rotulo(texto, *voto), voto[1])
    corte = _inicio_dispositivo(texto, *voto)

    rel_ini, rel_fim = blocos.get("relatorio", (0, 0))
    if fechos := list(_FIM_RELATORIO.finditer(texto, rel_ini, rel_fim)):
        rel_fim = fechos[-1].start()  # depois do "É o relatório." vem o cabeçalho de página
    return {
        "ementa": _aparar(texto, *blocos.get("ementa", (0, 0))),
        "relatorio": _aparar(texto, _sem_rotulo(texto, rel_ini, rel_fim), rel_fim),
        "fundamentacao": _aparar(texto, voto[0], corte),
        "dispositivo": _aparar(texto, corte, voto[1]),
    }


def segmentar(id: str, texto: str) -> Segmentos:
    return Segmentos(id=id, **{nome: texto[ini:fim] for nome, (ini, fim) in fatiar(texto).items()})


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Normaliza e segmenta os acórdãos (Decisao.texto = embargado)")
    ap.add_argument("decisoes", help="decisoes.jsonl (saída de src.collect.stj)")
    ap.add_argument("saida", help="segmentos.jsonl")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    segmentos = [segmentar(d.id, normalizar(d.texto)) for d in ler_jsonl(args.decisoes, Decisao)]
    escrever_jsonl(args.saida, segmentos)
    vazios = Counter(
        nome
        for s in segmentos
        for nome in ("ementa", "relatorio", "fundamentacao", "dispositivo")
        if not getattr(s, nome)
    )
    resumo = ", ".join(f"{nome} vazio em {n}" for nome, n in vazios.items()) or "nenhum segmento vazio"
    print(f"{len(segmentos)} decisões segmentadas -> {args.saida} ({resumo})")


if __name__ == "__main__":
    main()
