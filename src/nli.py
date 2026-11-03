"""NLI via LLM: classifica cada par como contradição ou não, com a categoria e a justificativa.

    from src import nli
    preds = nli.classificar(segs, props, pares)                          # demo / pipeline
    preds = nli.classificar(segs, props, pares, exemplos=ex, sistema=s)  # experimento

- Prompt few-shot versionado em src/prompts/nli.md, com as `CATEGORIAS_ALVO` da taxonomia. O `prompt="nli_v2"`
  acrescenta as regras de decisão transcrita e agravo interno; só a análise complementar o usa.
- Em lote: até `LOTE` pares por chamada; resposta JSON {"resultados": [{i, contradicao, categoria,
  justificativa}]}. Funciona com `Pares` de origem "am" e "todos".
- `exemplos` (few-shot extra) vem SÓ das decisões do fold de treino: `exemplos_do_gold(segs_treino,
  gold_treino)`. Usar decisões de teste aqui é vazamento.
- Categoria fora das `CATEGORIAS_ALVO` (inclusive CIF-1 e CIL-1) vira None (com aviso); par sem resposta
  vira "sem contradição" (com aviso).
- `Predicoes.modelo` registra o modelo de cada etapa (MA e NLI) e o esforço, para reprodutibilidade.

NLI local, sem LLM (`sistema="am+nli-local"`): `classificar_local` usa um modelo NLI multilíngue de 3
classes (`MODELO_LOCAL`, revisão fixa). O ASSIN 2 não serve aqui porque não tem a classe contradição.
Contradição = P(contradição) >= limiar, com o limiar ajustado só no treino
(`ajustar_limiar_local`). NLI é direcional, então a nota do par é o maior valor entre (a, b) e (b, a). O
modelo não conhece a taxonomia: a categoria vem do par de segmentos, como no baseline, e
`conclusao-dispositivo` vira CDF-1.

    pip install -e ".[local]"
"""

import json
import logging
from functools import cache

from src import llm
from src.argmining import CATEGORIAS_ALVO, SEGMENTOS, carregar_prompt, lista_json
from src.baseline import CATEGORIAS_POR_SEGMENTO
from src.contratos import (
    Gold,
    Pares,
    Predicao,
    Predicoes,
    Proposicao,
    Proposicoes,
    Segmentos,
    Trecho,
    texto_do_trecho,
)
from src.evaluate import f1_decisao, f1_pares

log = logging.getLogger(__name__)

LOTE = 10

MODELO_LOCAL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
REVISAO_LOCAL = "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"  # commit no Hugging Face (reprodutibilidade)
LIMIARES_LOCAL = [round(0.05 * i, 2) for i in range(1, 20)]  # 0,05 ... 0,95


def exemplos_do_gold(segmentos: list[Segmentos], gold: list[Gold]) -> list[dict]:
    """Contradições anotadas no formato de exemplo do prompt. Passe só o gold do fold de TREINO."""
    por_id = {s.id: s for s in segmentos}
    return [
        {
            "a": (c.a.segmento, texto_do_trecho(por_id[g.id], c.a)),
            "b": (c.b.segmento, texto_do_trecho(por_id[g.id], c.b)),
            "categoria": c.categoria,
            "justificativa": c.justificativa,
        }
        for g in gold
        if g.id in por_id
        for c in g.contradicoes
    ]


def _lado(rotulo: str, segmento: str, texto: str) -> str:
    return f"{rotulo} ({segmento}): {json.dumps(texto, ensure_ascii=False)}"


def _system(exemplos: list[dict], prompt: str = "nli") -> str:
    system = carregar_prompt(prompt)
    if not exemplos:
        return system.replace("{{exemplos}}", "").rstrip() + "\n"
    linhas = ["## Exemplos de contradições", ""]
    for e in exemplos:
        linhas += [
            _lado("A", *e["a"]),
            "    " + _lado("B", *e["b"]),
            f"    -> {e['categoria']}: {e['justificativa']}",
            "",
        ]
    return system.replace("{{exemplos}}", "\n".join(linhas).rstrip()) + "\n"


def classificar(
    segs: Segmentos,
    props: Proposicoes,
    pares: Pares,
    exemplos: list[dict] = (),
    sistema: str = "am+llm",
    prompt: str = "nli",
) -> Predicoes:
    por_pid = {p.pid: p for p in props.proposicoes}
    validos = []
    for par in pares.pares:
        if all(pid in por_pid for pid in par.par):
            validos.append(par)
        else:
            log.warning("%s: par com pid inexistente ignorado: %s", segs.id, par.par)

    system = _system(list(exemplos), prompt)
    predicoes = []
    for inicio in range(0, len(validos), LOTE):
        lote = validos[inicio : inicio + LOTE]
        linhas = []
        for i, par in enumerate(lote):
            a, b = por_pid[par.par[0]], por_pid[par.par[1]]
            linhas += [f"[{i}] " + _lado("A", a.segmento, a.texto), "    " + _lado("B", b.segmento, b.texto)]
        resposta = llm.complete_json("Pares:\n" + "\n".join(linhas), system=system, etapa="nli")
        resultados = {}
        for r in lista_json(resposta, "resultados", segs.id):
            if isinstance(r, dict) and isinstance(r.get("i"), int) and 0 <= r["i"] < len(lote):
                resultados.setdefault(r["i"], r)
            else:
                log.warning("%s: resultado inválido do LLM ignorado: %r", segs.id, r)
        for i, par in enumerate(lote):
            r = resultados.get(i)
            if r is None:
                log.warning("%s: LLM não respondeu o par %s; fica sem contradição", segs.id, par.par)
                r = {}
            contradicao = r.get("contradicao") is True
            categoria = r.get("categoria") if contradicao else None
            if categoria is not None and categoria not in CATEGORIAS_ALVO:
                log.warning("%s: categoria fora do alvo %r no par %s", segs.id, categoria, par.par)
                categoria = None
            a, b = por_pid[par.par[0]], por_pid[par.par[1]]
            predicoes.append(
                Predicao(
                    a=Trecho(segmento=a.segmento, inicio=a.inicio, fim=a.fim),
                    b=Trecho(segmento=b.segmento, inicio=b.inicio, fim=b.fim),
                    contradicao=contradicao,
                    categoria=categoria,
                    justificativa=str(r.get("justificativa") or ""),
                )
            )
    return Predicoes(
        id=segs.id,
        sistema=sistema,
        modelo=f"ma={llm.modelo(etapa='ma')}; nli={llm.modelo(etapa='nli')}; esforco={llm.ESFORCO}"
        + ("" if prompt == "nli" else f"; prompt={prompt}"),
        predicoes=predicoes,
    )


@cache
def carregar_nli_local(modelo: str = MODELO_LOCAL, revisao: str = REVISAO_LOCAL):
    """Função [(premissa, hipótese)] -> [P(contradição)] com o modelo do Hugging Face (baixado uma vez)."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(modelo, revision=revisao)
    rede = AutoModelForSequenceClassification.from_pretrained(modelo, revision=revisao).eval()
    indice = {rotulo.lower(): i for i, rotulo in rede.config.id2label.items()}["contradiction"]

    def prob_contradicao(pares: list[tuple[str, str]]) -> list[float]:
        saida = []
        for inicio in range(0, len(pares), 16):
            lote = pares[inicio : inicio + 16]
            entrada = tokenizer(
                [a for a, _ in lote], [b for _, b in lote], truncation=True, padding=True, return_tensors="pt"
            )
            with torch.no_grad():
                saida += torch.softmax(rede(**entrada).logits, dim=-1)[:, indice].tolist()
        return saida

    return prob_contradicao


def _trecho(p: Proposicao) -> Trecho:
    return Trecho(segmento=p.segmento, inicio=p.inicio, fim=p.fim)


def _categoria_local(a: Proposicao, b: Proposicao, relacao: str) -> str | None:
    if relacao == "conclusao-dispositivo":
        return "CDF-1"
    return CATEGORIAS_POR_SEGMENTO.get(tuple(sorted((a.segmento, b.segmento), key=SEGMENTOS.index)))


def pontuar_local(
    segs: Segmentos, props: Proposicoes, pares: Pares, prob_contradicao=None
) -> list[tuple[Predicao, float]]:
    """(predição sem rótulo, P(contradição)) de cada par. Rode uma vez e aplique vários limiares."""
    por_pid = {p.pid: p for p in props.proposicoes}
    validos = []
    for par in pares.pares:
        if all(pid in por_pid for pid in par.par):
            validos.append((por_pid[par.par[0]], por_pid[par.par[1]], par.relacao))
        else:
            log.warning("%s: par com pid inexistente ignorado: %s", segs.id, par.par)
    if not validos:
        return []
    prob = prob_contradicao or carregar_nli_local()
    ida = prob([(a.texto, b.texto) for a, b, _ in validos])
    volta = prob([(b.texto, a.texto) for a, b, _ in validos])
    return [
        (
            Predicao(
                a=_trecho(a), b=_trecho(b), contradicao=False, categoria=_categoria_local(a, b, relacao)
            ),
            max(p1, p2),
        )
        for (a, b, relacao), p1, p2 in zip(validos, ida, volta)
    ]


def aplicar_limiar(
    id: str, pontuados: list[tuple[Predicao, float]], limiar: float, sistema: str = "am+nli-local"
) -> Predicoes:
    predicoes = [
        p.model_copy(
            update={
                "contradicao": nota >= limiar,
                "categoria": p.categoria if nota >= limiar else None,
                "justificativa": f"P(contradição) = {nota:.2f}",
            }
        )
        for p, nota in pontuados
    ]
    modelo = f"{MODELO_LOCAL}@{REVISAO_LOCAL[:7]}; limiar={limiar}"
    return Predicoes(id=id, sistema=sistema, modelo=modelo, predicoes=predicoes)


def ajustar_limiar_local(
    pontuados: dict[str, list], gold: dict[str, Gold], rotulos: dict[str, bool] | None = None
) -> float:
    """Limiar da grade com maior F1 nas decisões de `pontuados` (passe só as de TREINO): por par contra o
    gold ou, com `rotulos` (rótulo do tribunal), por decisão. Empate: o maior limiar."""

    def f1(limiar):
        preds = [aplicar_limiar(id, pts, limiar) for id, pts in pontuados.items()]
        if rotulos is not None:
            return f1_decisao(preds, rotulos)
        return f1_pares(preds, [gold[id] for id in pontuados])

    return max(LIMIARES_LOCAL, key=lambda limiar: (f1(limiar), limiar))


def classificar_local(
    segs: Segmentos, props: Proposicoes, pares: Pares, limiar: float = 0.5, prob_contradicao=None
) -> Predicoes:
    return aplicar_limiar(segs.id, pontuar_local(segs, props, pares, prob_contradicao), limiar)
