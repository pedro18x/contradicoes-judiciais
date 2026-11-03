"""Análise complementar: C com o prompt v2 do NLI (decisão transcrita e agravo interno), numa amostra.

    python -m scripts.nli_v2 --avaliacao tribunal --dados data/tribunal --exemplos data/sintetico \
        --revisao data/tribunal/revisao/am+llm_especialista.csv --estimar
    python -m scripts.nli_v2 --avaliacao tribunal --dados data/tribunal --exemplos data/sintetico \
        --revisao data/tribunal/revisao/am+llm_especialista.csv
    python -m scripts.nli_v2 --avaliacao sintetica --dados data/sintetico --n 40

Na revisão da especialista, as contradições incorretas vieram de acórdãos de agravo interno em que o voto
transcreve a decisão agravada e o dispositivo nega provimento ao agravo, o que mantém aquela decisão. O
`src/prompts/nli_v2.md` acrescenta duas regras gerais sobre isso. Como a regra nasceu de erros vistos em
decisões de teste, este script NÃO substitui a ablação (scripts/experimento.py, prompt v1): o resultado é
uma análise à parte, e as decisões revisadas pela especialista são contadas separadamente.

Os pares são os mesmos que C (v1) classificou, remontados de <dados>/resultados/am+llm/fold*.jsonl: a
Mineração de Argumentos não roda de novo. Os exemplos few-shot são os mesmos da ablação (tribunal: do corpus
sintético inteiro, --exemplos; sintético: do treino do fold de cada decisão). Só o prompt muda.

- tribunal: reclassifica as decisões que C (v1) marcou como contraditórias (só elas podem deixar de ser
  marcadas por uma regra que retira contradições) e projeta P/R/F1 nas 200 supondo que as não marcadas
  continuam não marcadas. Com --revisao, mostra o que o v2 faz com cada contradição revisada.
- sintética: sorteia --n decisões (seed 42), metade com contradição inserida e metade intacta, e compara v1
  e v2 nelas, por par e por decisão.

Saídas: <dados>/resultados/am+llm-v2/<avaliacao>.jsonl (predições, fora do git) e
<docs>/nli_v2_<avaliacao>.md (só contagens). Toda chamada passa pelo cache de src/llm.py.
"""

import argparse
import csv
import json
import math
import os
import random
from collections import Counter
from pathlib import Path

from scripts.experimento import carregar, carregar_tribunal, exemplos_do_treino
from src import evaluate, llm, nli
from src.contratos import (
    Gold,
    Par,
    Pares,
    Predicoes,
    Proposicao,
    Proposicoes,
    Segmentos,
    escrever_jsonl,
    ler_jsonl,
    texto_do_trecho,
)

PROMPT = "nli_v2"


def ler_v1(dados: Path) -> dict[str, Predicoes]:
    pasta = dados / "resultados" / "am+llm"
    arquivos = sorted(pasta.glob("fold*.jsonl"))
    if not arquivos:
        raise SystemExit(f"sem {pasta}/fold*.jsonl: rode antes scripts/experimento.py com am+llm")
    return {p.id: p for a in arquivos for p in ler_jsonl(a, Predicoes)}


def remontar(segs: Segmentos, pred: Predicoes) -> tuple[Proposicoes, Pares]:
    """Proposições e pares exatamente como C (v1) os classificou, na mesma ordem (mesmos lotes)."""
    pids: dict[tuple, str] = {}
    props, pares = [], []
    for p in pred.predicoes:
        lado = []
        for t in (p.a, p.b):
            chave = (t.segmento, t.inicio, t.fim)
            if chave not in pids:
                pids[chave] = f"p{len(pids) + 1}"
                props.append(Proposicao(**t.model_dump(), pid=pids[chave], texto=texto_do_trecho(segs, t)))
            lado.append(pids[chave])
        pares.append(Par(par=tuple(lado), relacao="am", origem="am"))
    return Proposicoes(id=segs.id, proposicoes=props), Pares(id=segs.id, pares=pares)


def chamadas(preds: list[Predicoes]) -> int:
    return sum(math.ceil(len(p.predicoes) / nli.LOTE) for p in preds)


def custo_por_chamada(docs: Path) -> float:
    """US$ médio por chamada do NLI na ablação (docs/resultados/ablacao_tribunal.json)."""
    nli_ = json.loads((docs / "ablacao_tribunal.json").read_text(encoding="utf-8"))["custo_llm"]["por_etapa"][
        "nli"
    ]
    return sum(m["usd"] for m in nli_.values()) / sum(m["chamadas"] for m in nli_.values())


def marcada(p: Predicoes) -> bool:
    return any(x.contradicao for x in p.predicoes)


def _pares_texto(segs: Segmentos, pred: Predicoes) -> dict[tuple, bool]:
    """(segmento, texto) de A e de B, sem ordem -> contradição."""
    return {
        frozenset({(x.a.segmento, texto_do_trecho(segs, x.a)), (x.b.segmento, texto_do_trecho(segs, x.b))}): (
            x.contradicao
        )
        for x in pred.predicoes
    }


def cruzar_revisao(caminho: Path, segs: dict[str, Segmentos], v2: dict[str, Predicoes]) -> Counter:
    """(avaliação da especialista, o v2 mantém?) -> itens. Item sem par correspondente: 'sem par'."""
    cont = Counter()
    with caminho.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            avaliacao = (r.get("avaliacao") or "").strip().lower()
            pred = v2.get(r["decisao"])
            chave = frozenset({(r["segmento_a"], r["trecho_a"]), (r["segmento_b"], r["trecho_b"])})
            mantem = _pares_texto(segs[r["decisao"]], pred).get(chave) if pred else None
            cont[(avaliacao, "sem par" if mantem is None else "mantém" if mantem else "retira")] += 1
    return cont


def _prf(m: dict) -> str:
    return " | ".join(f"{m[k]:.3f}" if m[k] is not None else "—" for k in ("precisao", "revocacao", "f1"))


def tribunal(args, docs: Path) -> str:
    dados = Path(args.dados)
    segmentos, rotulos, _ = carregar_tribunal(dados)
    por_id = {s.id: s for s in segmentos}
    v1 = ler_v1(dados)
    alvo = [v1[s.id] for s in segmentos if s.id in v1 and marcada(v1[s.id])]
    revisadas = set()
    if args.revisao:
        with Path(args.revisao).open(encoding="utf-8-sig", newline="") as f:
            revisadas = {r["decisao"] for r in csv.DictReader(f, delimiter=";")}
    n = chamadas(alvo)
    previsto = f"{n} chamadas ao NLI, cerca de US$ {n * custo_por_chamada(docs):.2f}"
    if args.estimar:
        return f"{len(alvo)} decisões marcadas por C (v1): {previsto}"
    exemplos = []
    if args.exemplos:
        pasta = Path(args.exemplos)
        exemplos = exemplos_do_treino(
            ler_jsonl(pasta / "segmentos.jsonl", Segmentos),
            ler_jsonl(pasta / "gold.jsonl", Gold),
            args.exemplos_por_categoria,
            args.seed,
        )
    antes = llm.custo_acumulado()
    v2 = {}
    for p in alvo:
        props, pares = remontar(por_id[p.id], p)
        v2[p.id] = nli.classificar(por_id[p.id], props, pares, exemplos, sistema="am+llm", prompt=PROMPT)
    depois = llm.custo_acumulado()
    escrever_jsonl(dados / "resultados" / "am+llm-v2" / "tribunal.jsonl", list(v2.values()))

    ids = [s.id for s in segmentos]
    # v2 projetado: as decisões que C (v1) não marcou continuam sem contradição
    projetado = [v2.get(id) or v1[id] for id in ids if id in v1]
    m1 = evaluate.metricas_decisao(list(v1.values()), rotulos, ids)["decisao"]
    m2 = evaluate.metricas_decisao(projetado, rotulos, ids)["decisao"]

    def contagem(grupo: list[str]) -> list[str]:
        linhas = []
        for rotulo, nome in ((True, "reconhecida"), (False, "rejeitada")):
            g = [id for id in grupo if rotulos[id] is rotulo]
            linhas.append(f"| {nome} | {len(g)} | {sum(marcada(v2[id]) for id in g)} |")
        return linhas

    fora = [id for id in v2 if id not in revisadas]
    linhas = [
        "# C com o prompt v2 do NLI: tribunal (análise complementar)",
        "",
        "A regra do v2 (decisão transcrita e agravo interno) foi escrita depois da revisão da especialista, que",
        "viu decisões de teste. Por isso, isto não substitui a ablação. Mesmos pares e mesmos exemplos de C (v1);",
        "só o prompt do NLI muda.",
        "",
        f"Reclassificadas: as {len(alvo)} decisões que C (v1) marcou (estimativa prévia: {previsto}).",
        "",
        "## Decisões marcadas por C (v1) que o v2 continua marcando",
        "",
        "| Rótulo do tribunal | Marcadas pelo v1 | Continuam marcadas no v2 |",
        "|---|---|---|",
        *contagem(list(v2)),
        "",
        f"Sem as {len(set(v2) & revisadas)} decisões revisadas pela especialista (de onde veio a regra):",
        "",
        "| Rótulo do tribunal | Marcadas pelo v1 | Continuam marcadas no v2 |",
        "|---|---|---|",
        *contagem(fora),
        "",
        f"## Projeção nas {len(ids)} decisões (as não marcadas pelo v1 continuam não marcadas)",
        "",
        "| Prompt | P | R | F1 | Acurácia | VP | FP | FN | VN |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for nome, m in (("v1", m1), ("v2", m2)):
        linhas.append(
            f"| {nome} | {_prf(m)} | {m['acuracia']:.3f} | {m['vp']} | {m['fp']} | {m['fn']} | {m['vn']} |".replace(
                ".", ","
            )
        )
    if args.revisao:
        cont = cruzar_revisao(Path(args.revisao), por_id, v2)
        linhas += [
            "",
            "## Contradições revisadas pela especialista",
            "",
            "| Avaliação | Itens | O v2 mantém | O v2 retira | Sem par correspondente |",
            "|---|---|---|---|---|",
        ]
        for a in ("genuína", "parcialmente válida", "incorreta"):
            k = [cont[(a, x)] for x in ("mantém", "retira", "sem par")]
            linhas.append(f"| {a} | {sum(k)} | {k[0]} | {k[1]} | {k[2]} |")
    linhas += _custo(antes, depois)
    return "\n".join(linhas) + "\n"


def sintetica(args, docs: Path) -> str:
    dados = Path(args.dados)
    segmentos, gold, folds = carregar(dados)
    por_id = {s.id: s for s in segmentos}
    v1 = ler_v1(dados)
    rng = random.Random(args.seed)
    com = sorted(id for id in por_id if gold[id].contradicoes and id in v1)
    sem = sorted(id for id in por_id if not gold[id].contradicoes and id in v1)
    ids = sorted(
        rng.sample(com, min(args.n // 2, len(com))) + rng.sample(sem, min(args.n - args.n // 2, len(sem)))
    )
    n = chamadas([v1[id] for id in ids])
    estimativa = f"{len(ids)} decisões, {n} chamadas ao NLI, cerca de US$ {n * custo_por_chamada(docs):.2f}"
    if args.estimar:
        return estimativa
    fold_de = {id: k for k, f in enumerate(folds) for id in f}
    exemplos = {}
    antes = llm.custo_acumulado()
    v2 = []
    for id in ids:
        k = fold_de[id]
        if k not in exemplos:
            treino = [x for j, f in enumerate(folds) if j != k for x in f]
            exemplos[k] = exemplos_do_treino(
                [por_id[x] for x in treino], [gold[x] for x in treino], args.exemplos_por_categoria, args.seed
            )
        props, pares = remontar(por_id[id], v1[id])
        v2.append(nli.classificar(por_id[id], props, pares, exemplos[k], sistema="am+llm", prompt=PROMPT))
    depois = llm.custo_acumulado()
    escrever_jsonl(dados / "resultados" / "am+llm-v2" / "sintetica.jsonl", v2)

    lista_gold = [gold[id] for id in ids]
    linhas = [
        "# C com o prompt v2 do NLI: conjunto sintético (análise complementar)",
        "",
        f"Amostra (seed {args.seed}): {sum(bool(gold[i].contradicoes) for i in ids)} decisões com contradição"
        + f" inserida e {sum(not gold[i].contradicoes for i in ids)} intactas.",
        "Mesmos pares e mesmos exemplos de C (v1); só o prompt do NLI muda.",
        "",
        "| Prompt | Par P | Par R | Par F1 | VP | FP | FN | Decisão P | Decisão R | Decisão F1 | Intactas marcadas |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for nome, preds in (("v1", [v1[id] for id in ids]), ("v2", v2)):
        m = evaluate.metricas(preds, lista_gold, ids)
        par, dec = m["par"]["global"], m["decisao"]
        linhas.append(
            f"| {nome} | {_prf(par)} | {par['vp']} | {par['fp']} | {par['fn']} | {_prf(dec)} | {dec['fp']} |".replace(
                ".", ","
            )
        )
    linhas += _custo(antes, depois)
    return "\n".join(linhas) + "\n"


def _custo(antes: dict, depois: dict) -> list[str]:
    return [
        "",
        f"Custo desta execução: {depois['chamadas'] - antes['chamadas']} chamadas, "
        f"US$ {depois['usd'] - antes['usd']:.2f}".replace(".", ","),
    ]


def main(argv=None) -> str:
    ap = argparse.ArgumentParser(description="C com o prompt v2 do NLI, numa amostra (análise complementar)")
    ap.add_argument("--avaliacao", choices=["sintetica", "tribunal"], required=True)
    ap.add_argument("--dados", default=os.environ.get("DATA_DIR", "data"))
    ap.add_argument("--docs", default="docs/resultados")
    ap.add_argument("--exemplos", help="tribunal: pasta do corpus sintético para os exemplos few-shot")
    ap.add_argument("--exemplos-por-categoria", type=int, default=2)
    ap.add_argument("--revisao", help="tribunal: planilha da especialista, para cruzar item a item")
    ap.add_argument("--n", type=int, default=40, help="sintética: tamanho da amostra")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--estimar", action="store_true", help="só estima as chamadas ao LLM")
    args = ap.parse_args(argv)
    docs = Path(args.docs)
    texto = (tribunal if args.avaliacao == "tribunal" else sintetica)(args, docs)
    if not args.estimar:
        docs.mkdir(parents=True, exist_ok=True)
        (docs / f"nli_v2_{args.avaliacao}.md").write_text(texto, encoding="utf-8")
    print(texto)
    return texto


if __name__ == "__main__":
    main()
