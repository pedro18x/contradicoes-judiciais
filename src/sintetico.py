"""Contradições sintéticas controladas (avaliação 2 do TCC): gold com trecho e categoria exatos, sem anotação.

    segmentos, gold = sintetico.gerar(bases)   # chamado por scripts/preparar_avaliacoes.py

Base: as decisões de critério "negativa" (embargos rejeitados sem alegação de contradição, ver
src/collect/stj.py). Metade delas (seed 42) recebe UMA contradição inserida por regra fixa, sem LLM; a outra
metade fica intacta e é o negativo. Cada regra troca uma expressão real do texto por outra incompatível e
grava os dois trechos como gold: `a` = a frase que ficou, `b` = SEMPRE a frase alterada (o critério de
acerto de src/evaluate.py depende disso):

- CDF-1: inverte o resultado do dispositivo ("nego provimento" -> "dou provimento"). Se a ementa também
  enuncia o resultado, ela é invertida junto, para só a fundamentação ficar em sentido oposto.
  Trecho a: a frase de conclusão da fundamentação.
- CDF-2: muda no dispositivo um valor (R$ ou %) que a fundamentação fixou.
- CE-1: muda na fundamentação um fato narrado no relatório (procedência da sentença, valor).
- CE-2: inverte o resultado enunciado na ementa; o dispositivo fica como está. Trecho a: o dispositivo.
- CIF-2: muda, na fundamentação, a segunda menção a um valor ou data que ela já tinha afirmado.
- CIF-3: muda, na fundamentação, a segunda menção a um prazo legal ("prazo prescricional de 3 anos").

CIF-1, CIL-1 e CIL-2 dependem de sentido jurídico e não têm regra segura: aparecem só na avaliação
pelo rótulo do tribunal. Só entram frases do próprio julgador com até MAX_FRASE caracteres: as que citam
precedentes ("julgado em", "DJe", "Rel.") ou narram a tese da parte ("alega", "sustenta") ficam de fora. Cada decisão aparece uma vez só (alterada ou intacta), então não há a
mesma decisão nos dois lados de um fold.

`resumo(gold)` conta quantas contradições de cada categoria foram inseridas.
"""

import math
import random
import re
from collections import Counter

from src.contratos import ContradicaoGold, Gold, Segmentos, Trecho
from src.preprocess import sentencas

CATEGORIAS_SINTETICAS = ["CDF-1", "CDF-2", "CE-1", "CE-2", "CIF-2", "CIF-3"]

_CITACAO = re.compile(
    r"julgad[oa] em|\bDJe?\b|\bRel\.|\brelator|\(\s*(?:Ag|REsp|AREsp|EDcl|RE\b)", re.IGNORECASE
)
# tese da parte narrada pelo julgador: não é afirmação do próprio julgado (GUIA_ANOTACAO, seção 3)
_ALEGACAO = re.compile(
    r"\b(?:aleg|sustent|assever|aduz|argument|insurg|defend|pugn|requer|pretend|suscit)\w*|\bafirma\w* (?:a|o)"
    r" (?:parte|recorrente|agravante|embargante|autor|r[ée]u)",
    re.IGNORECASE,
)
MAX_FRASE = 500  # frase longa (em geral, ementa de outro julgado transcrita) não vira trecho gold
_VALOR = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?(?:\s*\([^)]*\))?")
_PORCENTO = re.compile(r"\b\d{1,2}(?:,\d+)?\s?%(?:\s*\([^)]*\))?")
_DATA = re.compile(r"\b\d{1,2}/\d{1,2}/(\d{4})\b|\b\d{1,2}º? de [a-zç]+ de (\d{4})\b", re.IGNORECASE)
_PRAZO = re.compile(
    r"\bprazo\w*(?:\s+(?:prescricional|decadencial|de prescri[çc][ãa]o|de decad[êe]ncia))?\s+(?:é\s+)?de\s+"
    r"(\d+)\s*(?:\([^)]*\)\s*)?(?:anos|meses|dias)\b",
    re.IGNORECASE,
)
_PROCEDENCIA = re.compile(r"\bjulg(?:ou|ada|ado|ando)\s+(?:parcialmente\s+)?(im)?procedente", re.IGNORECASE)
# resultado no dispositivo: (padrão, troca)
_DISPOSITIVO = [
    (r"\bnego provimento\b", "dou provimento"),
    (r"\bnego-lhe provimento\b", "dou-lhe provimento"),
    (r"\bdou (?:parcial )?provimento\b", "nego provimento"),
    (r"\bdou-lhe (?:parcial )?provimento\b", "nego-lhe provimento"),
    (r"\brejeito os embargos\b", "acolho os embargos"),
    (r"\bacolho os embargos\b", "rejeito os embargos"),
    (r"\bn[ãa]o conheço\b", "conheço"),
]
# resultado na ementa ("3. Agravo interno desprovido.")
_EMENTA = [
    (r"\b(?:desprovid[oa]s?|improvid[oa]s?|n[ãa]o provid[oa]s?)\b", "provido"),
    (r"\ba que se nega provimento\b", "a que se dá provimento"),
    (r"\bparcialmente provid[oa]s?\b", "não provido"),
    (r"(?<!n[ãa]o )\bprovid[oa]s?\b", "não provido"),
    (r"\bn[ãa]o conhecid[oa]s?\b", "conhecido e provido"),
    (r"\brejeitados\b", "acolhidos"),
    (r"\bacolhidos\b", "rejeitados"),
]
_FRASE_RESULTADO = re.compile(r"^\s*(?:\d+\.\s*)?(?:Agravos?|Recursos?|Embargos|Pedido)\b", re.IGNORECASE)
_CONCLUSAO = re.compile(
    r"deve(?: ela)? ser mantid|manuten[çc][ãa]o d[ae]|merece(?: ser)? (?:mantid|reformad|prosperar|acolhid|"
    r"provimento|reparo)|n[ãa]o merece|n[ãa]o prospera|n[ãa]o h[áa] como|raz[ãa]o assiste|sem raz[ãa]o|"
    r"[ée] o caso de|imp[õo]e-se|invi[áa]vel|[óo]bice|inexiste|n[ãa]o se conhece|deve ser provid|"
    r"deve ser reformad|n[ãa]o h[áa] (?:falar|que se falar)",
    re.IGNORECASE,
)

JUSTIFICATIVAS = {
    "CDF-1": "A fundamentação conclui num sentido e o dispositivo decide no sentido oposto.",
    "CDF-2": "O dispositivo fixa um valor diferente do que a fundamentação estabeleceu.",
    "CE-1": "A fundamentação altera um fato narrado no relatório, sem justificativa.",
    "CE-2": "A ementa enuncia um resultado diferente do que consta no dispositivo.",
    "CIF-2": "A fundamentação afirma o mesmo fato com valores incompatíveis.",
    "CIF-3": "A fundamentação aplica ao mesmo pedido dois prazos legais diferentes.",
}


def _caixa(original: str, novo: str) -> str:
    if original.isupper():
        return novo.upper()
    return novo[0].upper() + novo[1:] if original[:1].isupper() else novo


def _frase(texto: str, pos: int) -> tuple[int, int] | None:
    return next(((a, b) for a, b in sentencas(texto) if a <= pos < b), None)


def _frases_uteis(texto: str) -> list[tuple[int, int]]:
    """Frases do próprio julgador, curtas, que não citam precedente nem narram a tese da parte."""
    return [
        (a, b)
        for a, b in sentencas(texto)
        if b - a <= MAX_FRASE and not _CITACAO.search(texto[a:b]) and not _ALEGACAO.search(texto[a:b])
    ]


def _trocar(texto: str, ini: int, fim: int, novo: str) -> str:
    return texto[:ini] + novo + texto[fim:]


def _alterar_valor(achado: str) -> str | None:
    """Outro valor para o mesmo fato: R$ e % em dobro (metade se passar de 50%), data com o ano seguinte."""
    if m := re.match(r"R\$\s?(\d{1,3}(?:\.\d{3})*)(,\d{2})?", achado):
        inteiro = int(m[1].replace(".", "")) * 2
        return "R$ " + f"{inteiro:,}".replace(",", ".") + (m[2] or "")
    if m := re.match(r"(\d{1,2})(,\d+)?\s?%", achado):
        n = int(m[1])
        return f"{n * 2 if n * 2 <= 50 else max(n // 2, 1)}%"
    if m := _DATA.fullmatch(achado):
        ano = m[1] or m[2]
        return achado[: achado.rindex(ano)] + str(int(ano) + 1)
    if m := _PRAZO.fullmatch(achado):  # outro prazo legal plausível para o mesmo pedido
        n = int(m[1])
        novo = {1: 5, 2: 5, 3: 10, 5: 3, 10: 3, 20: 10}.get(n, n * 2)
        return achado[: m.start(1)] + str(novo) + re.sub(r"^\s*\([^)]*\)", "", achado[m.end(1) :])
    if m := _PROCEDENCIA.fullmatch(achado):  # procedente <-> improcedente, na mesma caixa
        if m[1]:
            return achado[: m.start(1)] + achado[m.end(1) :]
        fim = achado.lower().rindex("procedente")
        return achado[:fim] + _caixa(achado[fim:], "im") + achado[fim:]
    return None


def _fatos(texto: str, frases: list[tuple[int, int]], padroes) -> list[tuple[int, int, str]]:
    """(início, fim, texto) de cada valor, data ou procedência nas frases dadas."""
    achados = []
    for a, b in frases:
        for padrao in padroes:
            achados += [(a + m.start(), a + m.end(), m.group()) for m in padrao.finditer(texto[a:b])]
    return achados


def _chave(achado: str) -> str:
    """O fato sem o valor por extenso entre parênteses ("R$ 10.000,00 (dez mil reais)" == "R$ 10.000,00")."""
    return " ".join(re.sub(r"\([^)]*\)", " ", achado).split()).lower()


def _resultado(texto: str, regras, frases) -> tuple[int, int, str] | None:
    """A primeira expressão de resultado que tem troca, dentro das frases dadas: (início, fim, troca)."""
    for a, b in frases:
        for padrao, troca in regras:
            if m := re.search(padrao, texto[a:b], re.IGNORECASE):
                return a + m.start(), a + m.end(), _caixa(m.group(), troca)
    return None


def _resultado_da_ementa(ementa: str):
    finais = [(a, b) for a, b in sentencas(ementa)[-3:] if _FRASE_RESULTADO.match(ementa[a:b])]
    return _resultado(ementa, _EMENTA, finais)


def _gold(categoria: str, seg_a: str, a: tuple[int, int], seg_b: str, b: tuple[int, int]) -> ContradicaoGold:
    return ContradicaoGold(
        categoria=categoria,
        a=Trecho(segmento=seg_a, inicio=a[0], fim=a[1]),
        b=Trecho(segmento=seg_b, inicio=b[0], fim=b[1]),
        justificativa=JUSTIFICATIVAS[categoria],
    )


def _mudar(s: Segmentos, campo: str, ini: int, fim: int, novo: str) -> tuple[Segmentos, tuple[int, int]]:
    """Troca texto[ini:fim] do segmento e devolve o segmento novo e a frase alterada."""
    texto = _trocar(getattr(s, campo), ini, fim, novo)
    return s.model_copy(update={campo: texto}), _frase(texto, ini)


def cdf1(s: Segmentos):
    conclusoes = [
        (a, b) for a, b in _frases_uteis(s.fundamentacao) if _CONCLUSAO.search(s.fundamentacao[a:b])
    ]
    alvo = _resultado(s.dispositivo, _DISPOSITIVO, sentencas(s.dispositivo))
    if not (conclusoes and alvo):
        return None
    novo, b = _mudar(s, "dispositivo", *alvo)
    if ementa := _resultado_da_ementa(s.ementa):  # a ementa acompanha o dispositivo
        novo = novo.model_copy(update={"ementa": _trocar(s.ementa, *ementa)})
    return novo, _gold("CDF-1", "fundamentacao", conclusoes[-1], "dispositivo", b)


def ce2(s: Segmentos):
    ementa = _resultado_da_ementa(s.ementa)
    disp = _resultado(s.dispositivo, _DISPOSITIVO, sentencas(s.dispositivo))
    if not (ementa and disp):
        return None
    novo, b = _mudar(s, "ementa", *ementa)
    return novo, _gold("CE-2", "dispositivo", _frase(s.dispositivo, disp[0]), "ementa", b)


def _entre(s: Segmentos, categoria: str, origem: str, destino: str, padroes):
    """Um fato que aparece em `origem` e de novo em `destino` muda em `destino` (mesmo segmento: a segunda
    menção, numa frase diferente da primeira)."""
    em_origem = _fatos(getattr(s, origem), _frases_uteis(getattr(s, origem)), padroes)
    frases_destino = _frases_uteis(getattr(s, destino))
    if origem == destino:
        for i, (ini, _, achado) in enumerate(em_origem):
            for ini2, fim2, achado2 in em_origem[i + 1 :]:
                mesma_frase = _frase(s.fundamentacao, ini) == _frase(s.fundamentacao, ini2)
                if (
                    _chave(achado2) == _chave(achado)
                    and not mesma_frase
                    and (novo_valor := _alterar_valor(achado2))
                ):
                    novo, b = _mudar(s, destino, ini2, fim2, novo_valor)
                    return novo, _gold(categoria, origem, _frase(s.fundamentacao, ini), destino, b)
        return None
    no_destino = _fatos(getattr(s, destino), frases_destino, padroes)
    for ini, _, achado in em_origem:
        for ini2, fim2, achado2 in no_destino:
            if _chave(achado2) == _chave(achado) and (novo_valor := _alterar_valor(achado2)):
                novo, b = _mudar(s, destino, ini2, fim2, novo_valor)
                return novo, _gold(categoria, origem, _frase(getattr(s, origem), ini), destino, b)
    return None


def cdf2(s: Segmentos):
    return _entre(s, "CDF-2", "fundamentacao", "dispositivo", [_VALOR, _PORCENTO])


def ce1(s: Segmentos):
    # sem datas: a mesma data no relatório e na fundamentação muitas vezes é de fatos diferentes
    return _entre(s, "CE-1", "relatorio", "fundamentacao", [_PROCEDENCIA, _VALOR])


def cif2(s: Segmentos):
    return _entre(s, "CIF-2", "fundamentacao", "fundamentacao", [_VALOR, _DATA])


def cif3(s: Segmentos):
    return _entre(s, "CIF-3", "fundamentacao", "fundamentacao", [_PRAZO])


REGRAS = {"CDF-1": cdf1, "CDF-2": cdf2, "CE-1": ce1, "CE-2": ce2, "CIF-2": cif2, "CIF-3": cif3}


def gerar(
    bases: list[Segmentos], seed: int = 42, positivos: float = 0.5
) -> tuple[list[Segmentos], list[Gold]]:
    """Insere uma contradição em `positivos` das bases (a categoria aplicável menos usada até ali) e deixa
    o resto intacto. Base em que nenhuma regra se aplica fica como negativo."""
    ordem = sorted(bases, key=lambda s: s.id)
    random.Random(seed).shuffle(ordem)
    meta = math.ceil(positivos * len(ordem))
    usados: Counter = Counter()
    segmentos, gold = [], []
    for s in ordem:
        resultado = None
        if sum(usados.values()) < meta:
            aplicaveis = {c: r for c in CATEGORIAS_SINTETICAS if (r := REGRAS[c](s))}
            if aplicaveis:
                categoria = min(aplicaveis, key=lambda c: (usados[c], CATEGORIAS_SINTETICAS.index(c)))
                resultado = aplicaveis[categoria]
                usados[categoria] += 1
        if resultado:
            segmentos.append(resultado[0])
            gold.append(Gold(id=s.id, contradicoes=[resultado[1]]))
        else:
            segmentos.append(s)
            gold.append(Gold(id=s.id, contradicoes=[]))
    return segmentos, gold


def resumo(gold: list[Gold]) -> str:
    cont = Counter(c.categoria for g in gold for c in g.contradicoes)
    negativos = sum(not g.contradicoes for g in gold)
    linhas = [
        "# Contradições sintéticas",
        "",
        f"{len(gold)} decisões: {len(gold) - negativos} com uma contradição inserida, {negativos} intactas.",
        "",
        "| Categoria | Inseridas |",
        "|---|---|",
        *(f"| {c} | {cont[c]} |" for c in CATEGORIAS_SINTETICAS),
    ]
    return "\n".join(linhas) + "\n"
