"""Mineração de Argumentos (MA): proposições e pares candidatos, via LLM (src/llm.py).

    from src import argmining
    props = argmining.proposicoes(segs)      # Segmentos -> Proposicoes
    pares = argmining.pares(segs, props)     # -> Pares (origem "am")
    todos = argmining.todos_pares(props)     # -> Pares (origem "todos", ablação B)

Os prompts ficam versionados em src/prompts/ e listam só as `CATEGORIAS_ALVO`. O LLM só copia o texto das proposições; os offsets são
calculados aqui (`segmento.find`), então `texto_do_trecho` sempre devolve o texto da proposição. Texto que
não aparece literalmente no segmento é descartado com aviso no log.

Pares da MA = os que o LLM aponta (premissa -> conclusão, premissas sobre o mesmo ponto, relatório ×
fundamentação sobre o mesmo fato) + os estruturais que a taxonomia exige, montados aqui: conclusões da
fundamentação × dispositivo (CDF) e ementa × dispositivo (CE-2).
"""

import logging
from itertools import combinations
from pathlib import Path

from src import llm
from src.contratos import CATEGORIAS, Par, Pares, Proposicao, Proposicoes, Segmentos

log = logging.getLogger(__name__)

PROMPTS = Path(__file__).parent / "prompts"
SEGMENTOS = ("ementa", "relatorio", "fundamentacao", "dispositivo")
RELACOES_LLM = {"premissa-conclusao", "premissa-premissa", "relatorio-fundamentacao"}
# Alvo do sistema: dois enunciados incompatíveis no mesmo julgado. CIF-1 e CIL-1 são falhas de
# fundamentação (art. 489, § 1º, do CPC), não contradição entre dois trechos: ficam na taxonomia
# (CATEGORIAS), mas o sistema não as procura.
FORA_DO_ALVO = ("CIF-1", "CIL-1")
CATEGORIAS_ALVO = {c: d for c, d in CATEGORIAS.items() if c not in FORA_DO_ALVO}


def carregar_prompt(nome: str) -> str:
    """Prompt de src/prompts/<nome>.md com as categorias-alvo no lugar de {{categorias}}."""
    texto = (PROMPTS / f"{nome}.md").read_text(encoding="utf-8")
    return texto.replace("{{categorias}}", "\n".join(f"- {c}: {d}" for c, d in CATEGORIAS_ALVO.items()))


def lista_json(resposta, chave: str, id: str) -> list:
    """`resposta[chave]` se for uma lista; senão avisa e devolve []."""
    valor = resposta.get(chave) if isinstance(resposta, dict) else None
    if not isinstance(valor, list):
        log.warning("%s: resposta do LLM sem a lista '%s': %r", id, chave, str(resposta)[:200])
        return []
    return valor


def proposicoes(segs: Segmentos) -> Proposicoes:
    """Uma chamada por segmento não vazio; pids sequenciais p1..pn na ordem dos segmentos."""
    system = carregar_prompt("proposicoes")
    itens: list[Proposicao] = []
    vistos = set()
    for nome in SEGMENTOS:
        segmento = getattr(segs, nome)
        if not segmento.strip():
            continue
        resposta = llm.complete_json(f"Segmento: {nome}\nTexto:\n{segmento}", system=system, etapa="ma")
        desde = 0
        for texto in lista_json(resposta, "proposicoes", segs.id):
            texto = texto.strip() if isinstance(texto, str) else ""
            # procura a partir da proposição anterior (textos repetidos); se não achar, no segmento todo
            inicio = segmento.find(texto, desde) if texto else -1
            if inicio < 0 and texto:
                inicio = segmento.find(texto)
            if inicio < 0:
                log.warning("%s/%s: proposição fora do texto descartada: %r", segs.id, nome, texto[:80])
                continue
            fim = inicio + len(texto)
            if (nome, inicio, fim) in vistos:
                continue
            vistos.add((nome, inicio, fim))
            desde = max(desde, fim)
            pid = f"p{len(itens) + 1}"
            itens.append(Proposicao(segmento=nome, inicio=inicio, fim=fim, pid=pid, texto=texto))
    return Proposicoes(id=segs.id, proposicoes=itens)


def pares(segs: Segmentos, props: Proposicoes) -> Pares:
    """Pares apontados pelo LLM + estruturais (conclusões × dispositivo, ementa × dispositivo)."""
    ps = props.proposicoes
    por_pid = {p.pid: p for p in ps}
    saida: list[Par] = []
    vistos = set()

    def incluir(a: str, b: str, relacao: str) -> None:
        if a != b and frozenset((a, b)) not in vistos:
            vistos.add(frozenset((a, b)))
            saida.append(Par(par=(a, b), relacao=relacao, origem="am"))

    if len(ps) < 2:
        return Pares(id=props.id, pares=[])
    lista = "\n".join(f"{p.pid} [{p.segmento}] {p.texto}" for p in ps)
    resposta = llm.complete_json(f"Proposições:\n{lista}", system=carregar_prompt("pares"), etapa="ma")

    for item in lista_json(resposta, "pares", props.id):
        a, b, relacao = (
            (item.get(k) for k in ("a", "b", "relacao")) if isinstance(item, dict) else (None,) * 3
        )
        if a not in por_pid or b not in por_pid or relacao not in RELACOES_LLM:
            log.warning("%s: par inválido do LLM descartado: %r", props.id, item)
            continue
        incluir(a, b, relacao)

    conclusoes = []
    for pid in lista_json(resposta, "conclusoes", props.id):
        if pid in por_pid and por_pid[pid].segmento == "fundamentacao":
            conclusoes.append(pid)
        else:
            log.warning("%s: conclusão inválida do LLM descartada: %r", props.id, pid)
    dispositivo = [p.pid for p in ps if p.segmento == "dispositivo"]
    for c in conclusoes:
        for d in dispositivo:
            incluir(c, d, "conclusao-dispositivo")
    for e in (p.pid for p in ps if p.segmento == "ementa"):
        for d in dispositivo:
            incluir(e, d, "ementa-dispositivo")
    return Pares(id=props.id, pares=saida)


def todos_pares(props: Proposicoes) -> Pares:
    """Todos os n·(n−1)/2 pares, sem MA (ablação B)."""
    return Pares(
        id=props.id,
        pares=[
            Par(par=(a.pid, b.pid), relacao="todos", origem="todos")
            for a, b in combinations(props.proposicoes, 2)
        ],
    )
