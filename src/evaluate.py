"""Avaliação: predições × gold, no nível do par e no nível da decisão.

    python -m src.evaluate --pred data/predicoes.jsonl --gold data/gold.jsonl
    python -m src.evaluate --pred data/predicoes.jsonl --gold data/gold.jsonl --splits data/splits.json \\
        --json docs/resultados/am_llm.json

Casamento (Metodologia do TCC): uma predição com contradicao=True acerta uma contradição gold se, em
qualquer ordem,
1. (estrito) cada trecho previsto cobre pelo menos 50% dos caracteres do trecho gold correspondente (mesmo
   segmento), ou
2. um lado cobre pelo menos 50% da frase alterada (`g.b`, ver src/sintetico.py) e o outro lado está no
   segmento de `g.a`, sem ser a própria frase alterada: a contradição inserida foi achada, pareada com outra
   frase do segmento em conflito.
Cada gold casa com no máximo uma predição. Uma segunda predição que acerta uma contradição já casada é
repetição e não conta (nem acerto nem falso positivo); as demais predições extras são falso positivo.
`metricas` também conta, em `par.vp_estrito`, quantas contradições tiveram um par pelo critério 1.

- Nível par: P/R/F1 global e por categoria. Acerto e falso negativo contam na categoria gold; falso positivo,
  na categoria prevista ("sem categoria" se não houver).
- Nível decisão: positiva prevista = pelo menos uma predição de contradição; positiva gold =
  `Gold.contradicoes` não vazio.
- Com --splits: as mesmas métricas no fold de teste de cada partição, e média ± desvio padrão entre folds.
- `cobertura(pares, props, gold)`: cobertura da MA, isto é, quantas contradições gold ainda podem ser
  achadas depois da seleção de pares, e quanto a seleção reduz o O(n²).

Só entram as decisões do gold; predição de decisão fora do gold é ignorada com aviso. Decisão do gold sem
predições conta como prevista negativa. P, R ou F1 sem denominador (nada previsto, nada no gold) = None.

Avaliação pelo rótulo do tribunal (avaliação 1 do TCC): não há trechos gold, só se o STJ reconheceu a
contradição (`rotulos`: id -> bool, de `ler_rotulos`). `metricas_decisao` mede só o nível decisão, com a
mesma regra de positiva prevista; `f1_decisao` é o critério de ajuste de limiar nesse caso.
"""

import argparse
import json
import logging
import statistics
from collections import Counter
from pathlib import Path

from src.contratos import (
    CATEGORIAS,
    ContradicaoGold,
    Gold,
    Pares,
    Predicao,
    Predicoes,
    Proposicoes,
    Trecho,
    ler_jsonl,
)

log = logging.getLogger(__name__)

SEM_CATEGORIA = "sem categoria"


def cobre(p: Trecho, g: Trecho) -> bool:
    """O trecho previsto cobre pelo menos metade dos caracteres do trecho gold."""
    comum = min(p.fim, g.fim) - max(p.inicio, g.inicio)
    return p.segmento == g.segmento and comum >= 0.5 * (g.fim - g.inicio)


def acerta_estrito(p: Predicao, g: ContradicaoGold) -> bool:
    """Critério 1: os dois trechos gold, em qualquer ordem."""
    return (cobre(p.a, g.a) and cobre(p.b, g.b)) or (cobre(p.a, g.b) and cobre(p.b, g.a))


def acerta(p: Predicao, g: ContradicaoGold) -> bool:
    """Critério 1, ou 2: a frase alterada (`g.b`) com outro trecho do segmento de `g.a`."""
    if acerta_estrito(p, g):
        return True
    return any(
        cobre(alterada, g.b) and outro.segmento == g.a.segmento and not cobre(outro, g.b)
        for alterada, outro in ((p.a, p.b), (p.b, p.a))
    )


def _prf(vp: int, fp: int, fn: int) -> dict:
    p = vp / (vp + fp) if vp + fp else None
    r = vp / (vp + fn) if vp + fn else None
    if p is None and r is None:
        f1 = None
    elif not vp:
        f1 = 0.0
    else:
        f1 = 2 * p * r / (p + r)
    return {"vp": vp, "fp": fp, "fn": fn, "precisao": p, "revocacao": r, "f1": f1}


def casar(pred: Predicoes | None, gold: Gold) -> tuple[list, list, list]:
    """Casamento de uma decisão: (acertos [(predição, gold)], falsos positivos, falsos negativos).
    Repetições (predição que só acerta contradições já casadas) não entram em nenhuma das listas."""
    livres = list(gold.contradicoes)
    acertos, fps = [], []
    for p in (x for x in (pred.predicoes if pred else []) if x.contradicao):
        if (g := next((g for g in livres if acerta(p, g)), None)) is not None:
            livres.remove(g)
            acertos.append((p, g))
        elif not any(acerta(p, g) for _, g in acertos):
            fps.append(p)
    return acertos, fps, livres


def metricas(predicoes: list[Predicoes], gold: list[Gold], ids: list[str] | None = None) -> dict:
    """Métricas de par e de decisão sobre as decisões `ids` (padrão: todas do gold)."""
    gold_por_id = {g.id: g for g in gold}
    pred_por_id = {p.id: p for p in predicoes}
    fora = sorted(pred_por_id.keys() - gold_por_id.keys())
    if fora:
        log.warning("predições sem gold ignoradas: %s", ", ".join(fora))
    ids = list(gold_por_id) if ids is None else ids
    sem_gold = [id for id in ids if id not in gold_por_id]
    if sem_gold:
        raise ValueError(f"decisões sem gold: {', '.join(sem_gold)}")

    vp, fp, fn = Counter(), Counter(), Counter()
    decisao = Counter()
    vp_estrito = 0
    for id in ids:
        pred = pred_por_id.get(id)
        acertos, fps, fns = casar(pred, gold_por_id[id])
        previstas = [p for p in (pred.predicoes if pred else []) if p.contradicao]
        vp_estrito += sum(any(acerta_estrito(p, g) for p in previstas) for g in gold_por_id[id].contradicoes)
        vp.update(g.categoria for _, g in acertos)
        fp.update(p.categoria or SEM_CATEGORIA for p in fps)
        fn.update(g.categoria for g in fns)
        decisao[(bool(acertos or fps), bool(gold_por_id[id].contradicoes))] += 1

    categorias = [c for c in [*CATEGORIAS, SEM_CATEGORIA] if vp[c] or fp[c] or fn[c]]
    return {
        "decisoes": len(ids),
        "par": {
            "global": _prf(sum(vp.values()), sum(fp.values()), sum(fn.values())),
            "por_categoria": {c: _prf(vp[c], fp[c], fn[c]) for c in categorias},
            "vp_estrito": vp_estrito,
        },
        "decisao": {
            **_prf(decisao[(True, True)], decisao[(True, False)], decisao[(False, True)]),
            "vn": decisao[(False, False)],
        },
    }


def ler_rotulos(caminho: str | Path) -> dict[str, bool]:
    """Rótulo do tribunal a partir de <decisoes>.criterios.jsonl (ou de um rotulos.json {id: bool}):
    "reconhecida" -> True, "rejeitada" -> False. As "negativa" ficam de fora (são a base do sintético)."""
    texto = Path(caminho).read_text(encoding="utf-8")
    if Path(caminho).suffix == ".json":
        return json.loads(texto)
    criterios = (json.loads(linha) for linha in texto.splitlines() if linha.strip())
    return {
        c["id"]: c["criterio"] == "reconhecida"
        for c in criterios
        if c["criterio"] in ("reconhecida", "rejeitada")
    }


def metricas_decisao(
    predicoes: list[Predicoes], rotulos: dict[str, bool], ids: list[str] | None = None
) -> dict:
    """P/R/F1 no nível decisão contra o rótulo do tribunal, mais VN e acurácia."""
    pred_por_id = {p.id: p for p in predicoes}
    ids = list(rotulos) if ids is None else ids
    sem_rotulo = [id for id in ids if id not in rotulos]
    if sem_rotulo:
        raise ValueError(f"decisões sem rótulo: {', '.join(sem_rotulo)}")
    cont = Counter()
    for id in ids:
        previsto = id in pred_por_id and any(p.contradicao for p in pred_por_id[id].predicoes)
        cont[(previsto, rotulos[id])] += 1
    acertos = cont[(True, True)] + cont[(False, False)]
    return {
        "decisoes": len(ids),
        "decisao": {
            **_prf(cont[(True, True)], cont[(True, False)], cont[(False, True)]),
            "vn": cont[(False, False)],
            "acuracia": acertos / len(ids) if ids else None,
        },
    }


def f1_decisao(predicoes: list[Predicoes], rotulos: dict[str, bool]) -> float:
    """F1 no nível decisão (0 quando indefinido) sobre as decisões de `predicoes`, para ajustar limiares."""
    return metricas_decisao(predicoes, rotulos, ids=[p.id for p in predicoes])["decisao"]["f1"] or 0.0


def por_fold_decisao(predicoes: list[Predicoes], rotulos: dict[str, bool], folds: list[list[str]]) -> dict:
    resultados = [metricas_decisao(predicoes, rotulos, ids=fold) for fold in folds]
    resumo = {}
    for metrica in ("precisao", "revocacao", "f1", "acuracia"):
        valores = [m["decisao"][metrica] for m in resultados if m["decisao"][metrica] is not None]
        resumo[f"decisao.{metrica}"] = {
            "media": statistics.mean(valores) if valores else None,
            "desvio": statistics.stdev(valores) if len(valores) > 1 else None,
            "folds": len(valores),
        }
    return {"folds": resultados, "resumo": resumo}


def cobertura(pares: list[Pares], props: list[Proposicoes], gold: list[Gold]) -> dict:
    """Cobertura da MA: fração das contradições gold para as quais algum par selecionado
    acerta a contradição (critério de `acerta`, qualquer ordem), e a redução de pares
    len(pares) / len(todos os pares), somando todas as decisões de `gold`. `por_categoria` mostra em quais
    categorias a seleção perde contradições."""
    pares_por_id, props_por_id = {p.id: p for p in pares}, {p.id: p for p in props}
    cobertas = total = selecionados = possiveis = 0
    por_categoria: dict[str, dict] = {}
    for g in gold:
        if g.id not in props_por_id:
            raise ValueError(f"{g.id}: sem proposições")
        por_pid = {p.pid: p for p in props_por_id[g.id].proposicoes}
        candidatos = [
            Predicao(a=por_pid[a], b=por_pid[b], contradicao=True)
            for a, b in (p.par for p in (pares_por_id[g.id].pares if g.id in pares_por_id else []))
        ]
        for x in g.contradicoes:
            coberta = any(acerta(c, x) for c in candidatos)
            cat = por_categoria.setdefault(x.categoria, {"cobertas": 0, "total": 0})
            cat["cobertas"] += coberta
            cat["total"] += 1
            cobertas += coberta
            total += 1
        n = len(por_pid)
        selecionados += len(candidatos)
        possiveis += n * (n - 1) // 2
    return {
        "cobertura": cobertas / total if total else None,
        "cobertas": cobertas,
        "contradicoes_gold": total,
        "reducao": selecionados / possiveis if possiveis else None,
        "pares": selecionados,
        "todos_pares": possiveis,
        "por_categoria": {
            c: {**v, "cobertura": v["cobertas"] / v["total"]} for c, v in sorted(por_categoria.items())
        },
    }


def f1_pares(predicoes: list[Predicoes], gold: list[Gold]) -> float:
    """F1 global no nível do par (0 quando indefinido), para ajustar hiperparâmetros no treino."""
    return metricas(predicoes, gold)["par"]["global"]["f1"] or 0.0


def por_fold(predicoes: list[Predicoes], gold: list[Gold], folds: list[list[str]]) -> dict:
    """Métricas de cada fold de teste e média ± desvio de P/R/F1 (par global e decisão)."""
    resultados = [metricas(predicoes, gold, ids=fold) for fold in folds]
    resumo = {}
    for nivel, chave in (("par", lambda m: m["par"]["global"]), ("decisao", lambda m: m["decisao"])):
        for metrica in ("precisao", "revocacao", "f1"):
            valores = [chave(m)[metrica] for m in resultados if chave(m)[metrica] is not None]
            resumo[f"{nivel}.{metrica}"] = {
                "media": statistics.mean(valores) if valores else None,
                "desvio": statistics.stdev(valores) if len(valores) > 1 else None,
                "folds": len(valores),
            }
    return {"folds": resultados, "resumo": resumo}


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}".replace(".", ",")


def tabelas(m: dict, folds: dict | None = None) -> str:
    linhas = [
        f"{m['decisoes']} decisões",
        "",
        "## Nível par",
        "",
        "| Categoria | VP | FP | FN | P | R | F1 |",
        "|---|---|---|---|---|---|---|",
    ]
    for nome, x in [("**global**", m["par"]["global"]), *m["par"]["por_categoria"].items()]:
        linhas.append(
            f"| {nome} | {x['vp']} | {x['fp']} | {x['fn']} | "
            f"{_fmt(x['precisao'])} | {_fmt(x['revocacao'])} | {_fmt(x['f1'])} |"
        )
    total = sum(x["vp"] + x["fn"] for x in m["par"]["por_categoria"].values())
    linhas += [
        "",
        f"Pelo critério estrito (os dois trechos gold): {m['par']['vp_estrito']} de {total} contradições.",
    ]
    d = m["decisao"]
    linhas += [
        "",
        "## Nível decisão",
        "",
        "| VP | FP | FN | VN | P | R | F1 |",
        "|---|---|---|---|---|---|---|",
        (
            f"| {d['vp']} | {d['fp']} | {d['fn']} | {d['vn']} | "
            f"{_fmt(d['precisao'])} | {_fmt(d['revocacao'])} | {_fmt(d['f1'])} |"
        ),
    ]
    if folds:
        linhas += [
            "",
            "## Por fold (média ± desvio)",
            "",
            "| Métrica | Média | Desvio | Folds |",
            "|---|---|---|---|",
        ]
        for nome, r in folds["resumo"].items():
            linhas.append(f"| {nome} | {_fmt(r['media'])} | {_fmt(r['desvio'])} | {r['folds']} |")
    return "\n".join(linhas) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Avalia predições contra o gold (nível par e decisão)")
    ap.add_argument("--pred", required=True, help="predicoes.jsonl (Predicoes)")
    ap.add_argument("--gold", required=True, help="gold.jsonl (Gold)")
    ap.add_argument("--splits", help="data/splits.json: métricas por fold")
    ap.add_argument("--json", help="grava as métricas em JSON (ex.: docs/resultados/am_llm.json)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    predicoes, gold = ler_jsonl(args.pred, Predicoes), ler_jsonl(args.gold, Gold)
    m = metricas(predicoes, gold)
    folds = None
    if args.splits:
        folds = por_fold(predicoes, gold, json.loads(Path(args.splits).read_text(encoding="utf-8"))["folds"])
    print(tabelas(m, folds), end="")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        saida = {"geral": m, **({"por_fold": folds} if folds else {})}
        Path(args.json).write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
