"""Ablação A/B/C/D: o resultado central do TCC, nas duas avaliações.

    python scripts/preparar_avaliacoes.py                           # data/tribunal e data/sintetico
    python scripts/experimento.py --dados data/sintetico --estimar  # só conta chamadas, não usa o LLM
    python scripts/experimento.py --dados data/sintetico --sistemas baseline todos+llm am+llm am+nli-local
    python scripts/experimento.py --avaliacao tribunal --dados data/tribunal --exemplos data/sintetico \
        --sistemas baseline todos+llm am+llm am+nli-local

Avaliação 2, contradições sintéticas (padrão): --dados tem segmentos.jsonl, gold.jsonl e splits.json, e as
métricas são por par, por categoria e por decisão. Avaliação 1, rótulo do tribunal (--avaliacao tribunal):
--dados tem segmentos.jsonl, rotulos.json ({id: bool}) e splits.json; só há métrica por decisão (o STJ diz
se há contradição, não onde), os limiares são ajustados pelo F1 por decisão no treino e os exemplos
few-shot vêm do corpus sintético inteiro (--exemplos), que não tem nenhuma decisão do corpus do tribunal.
Em cada fold k de splits.json, as decisões do fold são teste e as demais são treino:
- baseline      A: src/baseline.py, limiar de similaridade ajustado no treino
- todos+llm     B: todos os pares (argmining.todos_pares) + nli.classificar
- am+llm        C: pares da Mineração de Argumentos (argmining.pares) + nli.classificar
- am+nli-local  D: pares da MA + nli.classificar_local, limiar ajustado no treino
Few-shot do NLI: até --exemplos-por-categoria contradições de cada categoria, sorteadas (seed 42) SÓ do
gold de treino do fold. As proposições não dependem do fold e são extraídas uma vez por decisão.

B pode ficar caro (n·(n−1)/2 pares por decisão). Com --max-pares-todos K, B usa só os K pares de maior
similaridade de embeddings (o encoder do baseline); com --max-pares-todos am, K é, em cada decisão, o número
de pares que a MA selecionou (mesmo orçamento que C). Os resultados do artigo usam --max-pares-todos am.

Saídas:
- <dados>/resultados/<sistema>/fold<k>.jsonl: predições (têm trechos dos acórdãos: ficam fora do git)
- <docs>/ablacao_<avaliacao>.md e .json: P/R/F1 média ± desvio entre folds, por categoria, limiares, custo
- <docs>/ma.md: cobertura da MA e redução de pares, por categoria, comparadas com todos os pares das
  mesmas proposições (teto) e com os pares mais similares no mesmo número (sem LLM); só na avaliação sintética

Toda chamada ao LLM passa pelo cache de src/llm.py: rerodar não gasta tokens.
"""

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

import numpy as np

from src import argmining, baseline, evaluate, llm, nli
from src.contratos import CATEGORIAS, Gold, Pares, Predicoes, Segmentos, escrever_jsonl, ler_jsonl
from src.preprocess import sentencas

SISTEMAS = ["baseline", "todos+llm", "am+llm", "am+nli-local"]


def carregar(dados: Path) -> tuple[list[Segmentos], dict[str, Gold], list[list[str]]]:
    segmentos = ler_jsonl(dados / "segmentos.jsonl", Segmentos)
    gold = {g.id: g for g in ler_jsonl(dados / "gold.jsonl", Gold)}
    folds = json.loads((dados / "splits.json").read_text(encoding="utf-8"))["folds"]
    ids = [id for f in folds for id in f]
    faltando = sorted(set(ids) - ({s.id for s in segmentos} & gold.keys()))
    if faltando:
        sys.exit(f"decisões dos folds sem segmentos ou gold: {', '.join(faltando)}")
    por_id = {s.id: s for s in segmentos}
    return [por_id[id] for id in ids], gold, folds


def carregar_tribunal(dados: Path) -> tuple[list[Segmentos], dict[str, bool], list[list[str]]]:
    segmentos = ler_jsonl(dados / "segmentos.jsonl", Segmentos)
    rotulos = evaluate.ler_rotulos(dados / "rotulos.json")
    folds = json.loads((dados / "splits.json").read_text(encoding="utf-8"))["folds"]
    ids = [id for f in folds for id in f]
    faltando = sorted(set(ids) - ({s.id for s in segmentos} & rotulos.keys()))
    if faltando:
        sys.exit(f"decisões dos folds sem segmentos ou rótulo: {', '.join(faltando)}")
    por_id = {s.id: s for s in segmentos}
    return [por_id[id] for id in ids], rotulos, folds


def exemplos_do_treino(segs: list[Segmentos], gold: list[Gold], por_categoria: int, seed: int) -> list[dict]:
    """Até `por_categoria` exemplos de cada categoria, sorteados do gold de TREINO."""
    rng = random.Random(seed)
    todos = nli.exemplos_do_gold(segs, gold)
    escolhidos = []
    for categoria in CATEGORIAS:
        da_categoria = [e for e in todos if e["categoria"] == categoria]
        escolhidos += rng.sample(da_categoria, min(por_categoria, len(da_categoria)))
    return escolhidos


def _top_k(segs: Segmentos, props, pares: Pares, k: int) -> Pares:
    """Os k pares de maior cosseno entre as proposições (encoder do baseline)."""
    if len(pares.pares) <= k:
        return pares
    vetores = np.asarray(baseline.carregar_encoder()([p.texto for p in props.proposicoes]), dtype=float)
    vetores /= np.clip(np.linalg.norm(vetores, axis=1, keepdims=True), 1e-12, None)
    indice = {p.pid: i for i, p in enumerate(props.proposicoes)}
    nota = [float(vetores[indice[a]] @ vetores[indice[b]]) for a, b in (p.par for p in pares.pares)]
    melhores = sorted(range(len(pares.pares)), key=lambda i: -nota[i])[:k]
    return pares.model_copy(update={"pares": [pares.pares[i] for i in sorted(melhores)]})


def estimar(segmentos: list[Segmentos], sistemas: list[str]) -> str:
    """Ordem de grandeza das chamadas ao LLM, sem chamar o LLM: usa as sentenças como aproximação das
    proposições. Chamadas que já estão no cache não gastam tokens."""
    n_segmentos = sum(bool(getattr(s, c).strip()) for s in segmentos for c in argmining.SEGMENTOS)
    n = [sum(len(sentencas(getattr(s, c))) for c in argmining.SEGMENTOS) for s in segmentos]
    todos = sum(x * (x - 1) // 2 for x in n)
    linhas = [
        f"{len(segmentos)} decisões, ~{sum(n)} proposições (sentenças), {todos} pares possíveis",
        f"proposições: {n_segmentos} chamadas (uma por segmento)",
    ]
    if {"am+llm", "am+nli-local"} & set(sistemas):
        linhas.append(f"pares da MA: {len(segmentos)} chamadas (uma por decisão)")
    if "am+llm" in sistemas:
        linhas.append("NLI am+llm: ~1 chamada por 10 pares selecionados (a MA costuma reduzir bem o O(n²))")
    if "todos+llm" in sistemas:
        linhas.append(f"NLI todos+llm: ~{sum(math.ceil(x * (x - 1) / 2 / nli.LOTE) for x in n)} chamadas")
    return "\n".join(linhas)


def rodar(args) -> dict:
    dados, docs = Path(args.dados), Path(args.docs)
    tribunal = args.avaliacao == "tribunal"
    rotulos = None
    if tribunal:
        segmentos, rotulos, folds = carregar_tribunal(dados)
        gold = {}
        exemplos_fixos = []
        if args.exemplos:  # few-shot do corpus sintético inteiro: decisões diferentes das do tribunal
            pasta = Path(args.exemplos)
            exemplos_fixos = exemplos_do_treino(
                ler_jsonl(pasta / "segmentos.jsonl", Segmentos),
                ler_jsonl(pasta / "gold.jsonl", Gold),
                args.exemplos_por_categoria,
                args.seed,
            )
    else:
        segmentos, gold, folds = carregar(dados)
    if args.estimar:
        print(estimar(segmentos, args.sistemas))
        return {}
    por_id = {s.id: s for s in segmentos}
    llm_ou_ma = {"todos+llm", "am+llm", "am+nli-local"} & set(args.sistemas)
    b_como_ma = "todos+llm" in args.sistemas and args.max_pares_todos == "am"
    props = {s.id: argmining.proposicoes(s) for s in segmentos} if llm_ou_ma else {}
    pares_am = (
        {s.id: argmining.pares(s, props[s.id]) for s in segmentos}
        if {"am+llm", "am+nli-local"} & set(args.sistemas) or b_como_ma
        else {}
    )

    def pares_de_b(id: str) -> Pares:
        pares = argmining.todos_pares(props[id])
        if not args.max_pares_todos:
            return pares
        k = len(pares_am[id].pares) if b_como_ma else int(args.max_pares_todos)
        return _top_k(por_id[id], props[id], pares, k)

    predicoes: dict[str, dict[int, list[Predicoes]]] = {}
    limiares: dict[str, list[float]] = {}
    # pares enviados ao classificador por sistema: o espaço de busca efetivo (o baseline filtra por limiar)
    pares_classificados: dict[str, int] = {}
    for sistema in args.sistemas:
        por_fold: dict[int, list[Predicoes]] = {}
        if sistema == "baseline":
            todas, limiares[sistema] = baseline.validacao_cruzada(
                segmentos, list(gold.values()), folds, rotulos=rotulos
            )
            por_decisao = {p.id: p for p in todas}
            por_fold = {k: [por_decisao[id] for id in teste] for k, teste in enumerate(folds)}
        elif sistema == "am+nli-local":
            pares_classificados[sistema] = sum(len(pares_am[id].pares) for id in por_id)
            pontuados = {id: nli.pontuar_local(por_id[id], props[id], pares_am[id]) for id in por_id}
            limiares[sistema] = []
            for k, teste in enumerate(folds):
                treino = [id for j, f in enumerate(folds) if j != k for id in f]
                limiar = nli.ajustar_limiar_local({id: pontuados[id] for id in treino}, gold, rotulos)
                limiares[sistema].append(limiar)
                por_fold[k] = [nli.aplicar_limiar(id, pontuados[id], limiar) for id in teste]
        else:
            pares_classificados[sistema] = 0
            for k, teste in enumerate(folds):
                treino = [id for j, f in enumerate(folds) if j != k for id in f]
                exemplos = (
                    exemplos_fixos
                    if tribunal
                    else exemplos_do_treino(
                        [por_id[id] for id in treino],
                        [gold[id] for id in treino],
                        args.exemplos_por_categoria,
                        args.seed,
                    )
                )
                por_fold[k] = []
                for id in teste:
                    pares = pares_am[id] if sistema == "am+llm" else pares_de_b(id)
                    pares_classificados[sistema] += len(pares.pares)
                    por_fold[k].append(
                        nli.classificar(por_id[id], props[id], pares, exemplos, sistema=sistema)
                    )
        for k, preds in por_fold.items():
            escrever_jsonl(dados / "resultados" / sistema / f"fold{k}.jsonl", preds)
        predicoes[sistema] = por_fold

    resultado = {
        "avaliacao": args.avaliacao,
        "decisoes": len(segmentos),
        "k": len(folds),
        "sistemas": {},
        "limiares": limiares,
        "pares_classificados": pares_classificados,
    }
    ids = [s.id for s in segmentos]
    lista_gold = [gold[id] for id in ids] if not tribunal else []
    for sistema, por_fold in predicoes.items():
        todas = [p for preds in por_fold.values() for p in preds]
        if tribunal:
            resultado["sistemas"][sistema] = {
                "geral": evaluate.metricas_decisao(todas, rotulos, ids),
                "por_fold": evaluate.por_fold_decisao(todas, rotulos, folds),
            }
        else:
            resultado["sistemas"][sistema] = {
                "geral": evaluate.metricas(todas, lista_gold),
                "por_fold": evaluate.por_fold(todas, lista_gold, folds),
            }
    if tribunal:
        resultado["positivos"] = sum(rotulos[id] for id in ids)
    elif pares_am:
        lista_props = list(props.values())
        resultado["ma"] = evaluate.cobertura(list(pares_am.values()), lista_props, lista_gold)
        # referências sem LLM, com as mesmas proposições: o teto (todos os pares) e a seleção barata por
        # similaridade com o mesmo número de pares da MA em cada decisão
        todos = {id: argmining.todos_pares(props[id]) for id in ids}
        similares = [_top_k(por_id[id], props[id], todos[id], len(pares_am[id].pares)) for id in ids]
        resultado["ma_referencias"] = {
            "todos": evaluate.cobertura(list(todos.values()), lista_props, lista_gold),
            "similaridade": evaluate.cobertura(similares, lista_props, lista_gold),
        }
    if llm_ou_ma:
        resultado["custo_llm"] = llm.custo_acumulado()

    docs.mkdir(parents=True, exist_ok=True)
    nome = f"ablacao_{args.avaliacao}"
    (docs / f"{nome}.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    (docs / f"{nome}.md").write_text(
        tabela_tribunal(resultado, args) if tribunal else tabela(resultado, args), encoding="utf-8"
    )
    if "ma" in resultado:
        (docs / "ma.md").write_text(tabela_ma(resultado["ma"], resultado["ma_referencias"]), encoding="utf-8")
    print((docs / f"{nome}.md").read_text(encoding="utf-8"))
    return resultado


def _media(r: dict) -> str:
    if r["media"] is None:
        return "—"
    desvio = "" if r["desvio"] is None else f" ± {r['desvio']:.3f}"
    return f"{r['media']:.3f}{desvio}".replace(".", ",")


def _fmt(x) -> str:
    return "—" if x is None else f"{x:.3f}".replace(".", ",")


def _usd(x: float) -> str:
    return f"{x:.4f}".replace(".", ",")


def _nota_b(args) -> str:
    if args.max_pares_todos == "am":
        return " B limitado, em cada decisão, ao mesmo número de pares que a MA (os mais similares)."
    return f" B limitado aos {args.max_pares_todos} pares mais similares." if args.max_pares_todos else ""


def _rodape(r: dict) -> list[str]:
    linhas = []
    if r.get("pares_classificados"):
        linhas += [
            "",
            "## Pares classificados por sistema (espaço de busca)",
            "",
            "| Sistema | Pares | Por decisão |",
            "|---|---|---|",
        ]
        linhas += [f"| {s} | {n} | {_fmt(n / r['decisoes'])} |" for s, n in r["pares_classificados"].items()]
    if r["limiares"]:
        linhas += ["", "## Limiares escolhidos no treino de cada fold", ""]
        linhas += [f"- {s}: " + ", ".join(_fmt(x) for x in v) for s, v in r["limiares"].items()]
    if "custo_llm" in r:
        c = r["custo_llm"]
        linhas += [
            "",
            "## Custo do LLM (tudo o que está no cache)",
            "",
            (
                f"{c['chamadas']} chamadas, {c['tokens_in']} tokens de entrada, {c['tokens_out']} de saída, "
                f"US$ {_usd(c['usd'])}. Modelo da MA: {llm.modelo(etapa='ma')}; do NLI: "
                f"{llm.modelo(etapa='nli')}; esforço {llm.ESFORCO}."
            ),
            "",
            "| Etapa | Modelo | Chamadas | Tokens de entrada | Tokens de saída | US$ |",
            "|---|---|---|---|---|---|",
        ]
        linhas += [
            f"| {etapa} | {m} | {s['chamadas']} | {s['tokens_in']} | {s['tokens_out']} | {_usd(s['usd'])} |"
            for etapa, modelos in c["por_etapa"].items()
            for m, s in modelos.items()
        ]
    return linhas


def tabela_tribunal(r: dict, args) -> str:
    linhas = [
        "# Ablação A/B/C pelo rótulo do tribunal",
        "",
        f"{r['decisoes']} decisões ({r['positivos']} com contradição reconhecida pelo STJ, "
        f"{r['decisoes'] - r['positivos']} com a contradição alegada e rejeitada), k = {r['k']}. "
        + (
            f"Few-shot: até {args.exemplos_por_categoria} exemplos por categoria do corpus sintético."
            if args.exemplos
            else "Sem exemplos few-shot."
        )
        + _nota_b(args),
        "",
        "## Média ± desvio entre folds (nível decisão)",
        "",
        "| Sistema | P | R | F1 | Acurácia |",
        "|---|---|---|---|---|",
    ]
    for sistema, m in r["sistemas"].items():
        resumo = m["por_fold"]["resumo"]
        celulas = [_media(resumo[f"decisao.{x}"]) for x in ("precisao", "revocacao", "f1", "acuracia")]
        linhas.append(f"| {sistema} | " + " | ".join(celulas) + " |")
    linhas += [
        "",
        "## Todas as decisões de teste juntas",
        "",
        "| Sistema | VP | FP | FN | VN |",
        "|---|---|---|---|---|",
    ]
    for sistema, m in r["sistemas"].items():
        d = m["geral"]["decisao"]
        linhas.append(f"| {sistema} | {d['vp']} | {d['fp']} | {d['fn']} | {d['vn']} |")
    return "\n".join(linhas + _rodape(r)) + "\n"


def tabela(r: dict, args) -> str:
    linhas = [
        "# Ablação A/B/C nas contradições sintéticas",
        "",
        f"{r['decisoes']} decisões, k = {r['k']} (splits.json), few-shot: até {args.exemplos_por_categoria} "
        f"exemplos por categoria do treino de cada fold (seed {args.seed})." + _nota_b(args),
        "",
        "## Média ± desvio entre folds",
        "",
        "| Sistema | P (par) | R (par) | F1 (par) | P (decisão) | R (decisão) | F1 (decisão) |",
        "|---|---|---|---|---|---|---|",
    ]
    for sistema, m in r["sistemas"].items():
        resumo = m["por_fold"]["resumo"]
        celulas = [
            _media(resumo[f"{nivel}.{x}"])
            for nivel in ("par", "decisao")
            for x in ("precisao", "revocacao", "f1")
        ]
        linhas.append(f"| {sistema} | " + " | ".join(celulas) + " |")

    sistemas = list(r["sistemas"])
    linhas += [
        "",
        "## F1 por categoria (todas as decisões de teste juntas)",
        "",
        "| Categoria | " + " | ".join(sistemas) + " |",
        "|---" * (len(sistemas) + 1) + "|",
    ]
    for categoria in [*CATEGORIAS, evaluate.SEM_CATEGORIA]:
        valores = [r["sistemas"][s]["geral"]["par"]["por_categoria"].get(categoria) for s in sistemas]
        if any(valores):
            linhas.append(
                f"| {categoria} | " + " | ".join(_fmt(v["f1"]) if v else "—" for v in valores) + " |"
            )

    return "\n".join(linhas + _rodape(r)) + "\n"


def tabela_ma(c: dict, refs: dict) -> str:
    """Cobertura (contradições gold com um par selecionado que casa com os dois trechos) e tamanho do espaço
    de busca de cada seleção, com as mesmas proposições."""
    selecoes = {
        "Mineração de Argumentos": c,
        "Todos os pares": refs["todos"],
        "Mais similares (mesmo número da MA)": refs["similaridade"],
    }
    linhas = [
        "# Cobertura da Mineração de Argumentos",
        "",
        f"{c['contradicoes_gold']} contradições inseridas; {c['todos_pares']} pares possíveis entre as proposições.",
        "",
        "| Seleção | Pares | Fração de todos os pares | Cobertura |",
        "|---|---|---|---|",
    ]
    for nome, s in selecoes.items():
        linhas.append(
            f"| {nome} | {s['pares']} | {_fmt(s['reducao'])} | "
            f"{_fmt(s['cobertura'])} ({s['cobertas']} de {s['contradicoes_gold']}) |"
        )
    linhas += ["", "## Cobertura por categoria", "", "| Categoria | " + " | ".join(selecoes) + " |"]
    linhas.append("|---" * (len(selecoes) + 1) + "|")
    for categoria, v in c["por_categoria"].items():
        celulas = [_fmt(s["por_categoria"].get(categoria, {}).get("cobertura")) for s in selecoes.values()]
        linhas.append(f"| {categoria} ({v['total']}) | " + " | ".join(celulas) + " |")
    return "\n".join(linhas) + "\n"


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="Ablação A/B/C com validação cruzada")
    ap.add_argument("--avaliacao", choices=["sintetica", "tribunal"], default="sintetica")
    ap.add_argument("--exemplos", help="tribunal: pasta do corpus sintético para os exemplos few-shot")
    ap.add_argument("--sistemas", nargs="+", choices=SISTEMAS, default=["baseline", "todos+llm", "am+llm"])
    ap.add_argument("--dados", default=os.environ.get("DATA_DIR", "data"))
    ap.add_argument("--docs", default="docs/resultados")
    ap.add_argument("--exemplos-por-categoria", type=int, default=2)
    ap.add_argument(
        "--max-pares-todos",
        type=lambda v: v if v == "am" else str(int(v)),
        help="B só com os K pares mais similares por decisão; 'am' = o número de pares da MA na decisão",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--estimar", action="store_true", help="só estima as chamadas ao LLM")
    return rodar(ap.parse_args(argv))


if __name__ == "__main__":
    main()
