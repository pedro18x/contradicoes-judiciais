"""Análise de erros por categoria e revisão humana de 10% (TCC seção 2.5).

    python scripts/erros.py relatorio --sistema am+llm --dados data/sintetico
    python scripts/erros.py amostra --sistema am+llm --dados data/tribunal
    python scripts/erros.py consolidar data/tribunal/revisao/am+llm_especialista.csv

Lê as predições que scripts/experimento.py gravou em <dados>/resultados/<sistema>/fold*.jsonl, além de
<dados>/segmentos.jsonl e, se existir, <dados>/gold.jsonl (padrão $DATA_DIR ou data/). O relatório precisa
do gold (avaliação sintética); a amostra não (serve também para a avaliação pelo rótulo do tribunal).

- relatorio: falsos positivos e falsos negativos por categoria, com os trechos e a justificativa do modelo,
  em <dados>/resultados/<sistema>/erros.md. Esse arquivo cita os acórdãos (nomes das partes, LGPD) e fica
  fora do git. Em docs/resultados/erros_<sistema>.md vão só as contagens.
- amostra: sorteia 10% das decisões de teste (seed 42, pelo menos 1) e gera uma planilha CSV (";", abre no
  Excel) com cada contradição apontada pelo sistema, para a revisão por especialista em Direito. Quem
  revisa preenche a coluna `avaliacao` com: genuína, parcialmente válida ou incorreta.
- tribunal: com a classificação, feita lendo o acórdão dos embargos, de onde estava cada contradição
  reconhecida (JSON fora do git: tem os identificadores), conta por tipo quantas o sistema marcou. Grava
  docs/resultados/erros_tribunal.md.
- consolidar: junta as planilhas preenchidas (uma por revisor), conta as avaliações e, com 2 revisores,
  calcula a concordância (Kappa de Cohen). Grava em docs/resultados/revisao_<sistema>.md.

Os padrões de falha (por que o modelo erra) são descritos por quem lê o relatório; o script só organiza.
"""

import argparse
import csv
import json
import math
import os
import random
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from src import evaluate
from src.contratos import CATEGORIAS, Gold, Predicoes, Segmentos, ler_jsonl, texto_do_trecho

AVALIACOES = ["genuína", "parcialmente válida", "incorreta"]
COLUNAS = [
    "item", "decisao", "categoria", "segmento_a", "trecho_a", "segmento_b", "trecho_b",
    "justificativa", "avaliacao", "comentario",
]  # fmt: skip
FRACAO = 0.10


def carregar(dados: Path, sistema: str) -> tuple[dict[str, Segmentos], dict[str, Gold], list[Predicoes]]:
    arquivos = sorted((dados / "resultados" / sistema).glob("fold*.jsonl"))
    if not arquivos:
        sys.exit(f"sem predições em {dados / 'resultados' / sistema}: rode scripts/experimento.py antes")
    predicoes = [p for a in arquivos for p in ler_jsonl(a, Predicoes)]
    segs = {s.id: s for s in ler_jsonl(dados / "segmentos.jsonl", Segmentos)}
    caminho_gold = dados / "gold.jsonl"
    gold = {g.id: g for g in ler_jsonl(caminho_gold, Gold)} if caminho_gold.exists() else {}
    return segs, gold, predicoes


def _citar(segs: Segmentos, trecho) -> str:
    return f"[{trecho.segmento}] “{texto_do_trecho(segs, trecho)}”"


FN_TIPOS = ["par não avaliado", "par avaliado sem contradição"]
FP_TIPOS = [
    "decisão intacta",
    "mesma contradição, outro par (toca a frase alterada)",
    "outro par da decisão com contradição",
]


def tipo_fn(pred: Predicoes, g) -> str:
    """O sistema avaliou algum par que acertaria a contradição (e disse que não), ou nenhum par a alcançava?"""
    avaliados = (p.model_copy(update={"contradicao": True}) for p in pred.predicoes)
    return FN_TIPOS[1] if any(evaluate.acerta(p, g) for p in avaliados) else FN_TIPOS[0]


def _sobrepoe(p, g) -> bool:
    return p.segmento == g.segmento and min(p.fim, g.fim) > max(p.inicio, g.inicio)


def tipo_fp(gold: Gold, p) -> str:
    """Falso positivo em decisão intacta, repetindo a contradição inserida (frase alterada) ou em outro par."""
    if not gold.contradicoes:
        return FP_TIPOS[0]
    # basta tocar a frase alterada: a proposição costuma ser só um pedaço dela ("dou provimento ao agravo")
    if any(_sobrepoe(t, g.b) for g in gold.contradicoes for t in (p.a, p.b)):
        return FP_TIPOS[1]
    return FP_TIPOS[2]


def relatorio(segs: dict, gold: dict, predicoes: list[Predicoes], sistema: str) -> tuple[str, str]:
    """(relatório com os trechos, resumo só com contagens)."""
    acertos, fps, fns = Counter(), {}, {}
    por_tipo_fn, por_tipo_fp, categoria_errada = Counter(), Counter(), 0
    for pred in predicoes:
        a, fp, fn = evaluate.casar(pred, gold[pred.id])
        acertos.update(g.categoria for _, g in a)
        categoria_errada += sum(p.categoria != g.categoria for p, g in a)
        for p in fp:
            fps.setdefault(p.categoria or evaluate.SEM_CATEGORIA, []).append((pred.id, p))
            por_tipo_fp[tipo_fp(gold[pred.id], p)] += 1
        for g in fn:
            fns.setdefault(g.categoria, []).append((pred.id, g))
            por_tipo_fn[(g.categoria, tipo_fn(pred, g))] += 1

    categorias = [c for c in [*CATEGORIAS, evaluate.SEM_CATEGORIA] if acertos[c] or c in fps or c in fns]
    resumo = [
        f"# Erros por categoria: {sistema}",
        "",
        f"{len(predicoes)} decisões de teste. Trechos: `data/resultados/{sistema}/erros.md` (fora do git).",
        "",
        "| Categoria | Acertos | Falsos positivos | Falsos negativos |",
        "|---|---|---|---|",
    ]
    resumo += [f"| {c} | {acertos[c]} | {len(fps.get(c, []))} | {len(fns.get(c, []))} |" for c in categorias]
    com_fn = [c for c in categorias if c in fns]
    resumo += [
        "",
        "## Falsos negativos por tipo",
        "",
        "Par não avaliado: nenhum par que o sistema avaliou acertaria a contradição (a seleção de pares a perdeu).",
        "Par avaliado sem contradição: o sistema avaliou um par que acertaria e disse que não há contradição.",
        "",
        "| Categoria | " + " | ".join(FN_TIPOS) + " |",
        "|---" * (len(FN_TIPOS) + 1) + "|",
        *(f"| {c} | " + " | ".join(str(por_tipo_fn[(c, x)]) for x in FN_TIPOS) + " |" for c in com_fn),
        "| total | " + " | ".join(str(sum(por_tipo_fn[(c, x)] for c in com_fn)) for x in FN_TIPOS) + " |",
        "",
        "## Falsos positivos por tipo",
        "",
        "| Tipo | Pares |",
        "|---|---|",
        *(f"| {x} | {por_tipo_fp[x]} |" for x in FP_TIPOS),
        "",
        f"Acertos com categoria diferente da inserida: {categoria_errada} de {sum(acertos.values())}.",
    ]

    linhas = [f"# Erros por categoria: {sistema}", ""]
    for c in categorias:
        nome = CATEGORIAS[c].split(":")[0] if c in CATEGORIAS else c
        linhas += [
            f"## {c}: {nome}",
            "",
            f"{acertos[c]} acertos, {len(fps.get(c, []))} FP, {len(fns.get(c, []))} FN",
        ]
        if c in fps:
            linhas += ["", "### Falsos positivos (o sistema apontou, o gold não tem)", ""]
            for id, p in fps[c]:
                linhas += [
                    f"- **{id}**",
                    f"  - A: {_citar(segs[id], p.a)}",
                    f"  - B: {_citar(segs[id], p.b)}",
                ]
                linhas.append(f"  - Tipo: {tipo_fp(gold[id], p)}")
                linhas.append(f"  - Modelo: {p.justificativa or '(sem justificativa)'}")
        if c in fns:
            linhas += ["", "### Falsos negativos (o gold tem, o sistema não achou)", ""]
            for id, g in fns[c]:
                linhas += [
                    f"- **{id}**",
                    f"  - A: {_citar(segs[id], g.a)}",
                    f"  - B: {_citar(segs[id], g.b)}",
                ]
                linhas.append(f"  - Anotação: {g.justificativa or '(sem justificativa)'}")
        linhas.append("")
    return "\n".join(linhas) + "\n", "\n".join(resumo) + "\n"


def amostra(segs: dict, predicoes: list[Predicoes], seed: int = 42) -> list[dict]:
    """Linhas da planilha: cada contradição apontada nas decisões sorteadas (10%, pelo menos 1)."""
    ids = sorted(p.id for p in predicoes)
    sorteadas = set(random.Random(seed).sample(ids, max(1, math.ceil(FRACAO * len(ids))))) if ids else set()
    linhas = []
    for pred in sorted(predicoes, key=lambda p: p.id):
        if pred.id not in sorteadas:
            continue
        for p in (x for x in pred.predicoes if x.contradicao):
            linhas.append(
                {
                    "item": len(linhas) + 1,
                    "decisao": pred.id,
                    "categoria": p.categoria or "",
                    "segmento_a": p.a.segmento,
                    "trecho_a": texto_do_trecho(segs[pred.id], p.a),
                    "segmento_b": p.b.segmento,
                    "trecho_b": texto_do_trecho(segs[pred.id], p.b),
                    "justificativa": p.justificativa,
                    "avaliacao": "",
                    "comentario": "",
                }
            )
    return linhas


def escrever_csv(caminho: Path, linhas: list[dict]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8-sig", newline="") as f:  # BOM: o Excel reconhece os acentos
        w = csv.DictWriter(f, fieldnames=COLUNAS, delimiter=";")
        w.writeheader()
        w.writerows(linhas)


def _normalizar(avaliacao: str) -> str | None:
    def sem_acento(t: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFD", t.strip().lower()) if not unicodedata.combining(c)
        )

    return next((a for a in AVALIACOES if sem_acento(a) == sem_acento(avaliacao)), None)


def ler_revisao(caminho: Path) -> dict[str, tuple[str, str | None, str, str]]:
    """item -> (categoria, avaliação normalizada ou None se vazia/inválida, decisão, comentário)."""
    with caminho.open(encoding="utf-8-sig", newline="") as f:
        return {
            r["item"]: (
                r["categoria"],
                _normalizar(r["avaliacao"] or ""),
                r.get("decisao") or "",
                (r.get("comentario") or "").strip(),
            )
            for r in csv.DictReader(f, delimiter=";")
        }


def _tabela_por(revisao: dict, grupo: dict[str, str], rotulo: str) -> list[str]:
    """Contagem das avaliações de um revisor por grupo (item -> grupo), na ordem em que aparecem."""
    grupos: dict[str, Counter] = {}
    for i, g in grupo.items():
        grupos.setdefault(g, Counter())[revisao[i][1]] += 1
    linhas = [f"| {rotulo} | " + " | ".join(AVALIACOES) + " |", "|---" * (len(AVALIACOES) + 1) + "|"]
    linhas += [f"| {g} | " + " | ".join(str(c[a]) for a in AVALIACOES) + " |" for g, c in grupos.items()]
    return linhas


def kappa(a: list[str], b: list[str]) -> float:
    """Kappa de Cohen para rótulos categóricos (as 3 avaliações)."""
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[r] * cb[r] for r in AVALIACOES) / n**2
    return float("nan") if pe == 1 else (po - pe) / (1 - pe)


def consolidar(revisoes: dict[str, dict], sistema: str) -> str:
    nomes = list(revisoes)
    itens = sorted(set.intersection(*(set(r) for r in revisoes.values())), key=int)
    pendentes = {n: [i for i in itens if revisoes[n][i][1] is None] for n in nomes}
    linhas = [
        f"# Revisão humana: {sistema}",
        "",
        f"{len(itens)} contradições apontadas na amostra de 10%.",
        "",
    ]
    for n, faltam in pendentes.items():
        if faltam:
            linhas.append(f"- {n}: {len(faltam)} itens sem avaliação válida (itens {', '.join(faltam[:10])})")
    completos = [i for i in itens if all(revisoes[n][i][1] for n in nomes)]
    linhas += [
        "",
        "| Avaliação | " + " | ".join(nomes) + " |",
        "|---" * (len(nomes) + 1) + "|",
    ]
    for a in AVALIACOES:
        linhas.append(
            f"| {a} | "
            + " | ".join(str(sum(revisoes[n][i][1] == a for i in completos)) for n in nomes)
            + " |"
        )
    for n in nomes:
        validos = [i for i in itens if revisoes[n][i][1]]
        # decisões numeradas na ordem da planilha: o identificador leva ao processo (LGPD)
        numero = {d: str(k) for k, d in enumerate(dict.fromkeys(revisoes[n][i][2] for i in validos), 1)}
        com_genuina = {revisoes[n][i][2] for i in validos if revisoes[n][i][1] == "genuína"}
        linhas += [
            "",
            f"## {n}: por decisão",
            "",
            f"{len(numero)} decisões; {len(com_genuina)} com ao menos uma contradição genuína.",
            "",
            *_tabela_por(revisoes[n], {i: numero[revisoes[n][i][2]] for i in validos}, "Decisão"),
            "",
            f"## {n}: por categoria",
            "",
            *_tabela_por(
                revisoes[n], {i: revisoes[n][i][0] or evaluate.SEM_CATEGORIA for i in validos}, "Categoria"
            ),
        ]
        # o comentário é de quem revisa (não copia trecho do acórdão, como pede o guia)
        comentarios = Counter((revisoes[n][i][1], revisoes[n][i][3]) for i in validos if revisoes[n][i][3])
        if comentarios:
            linhas += ["", f"## {n}: comentários", "", "| Avaliação | Comentário | Itens |", "|---|---|---|"]
            linhas += [f"| {a} | {c} | {k} |" for (a, c), k in comentarios.most_common()]
    if len(nomes) == 2 and completos:
        a, b = ([revisoes[n][i][1] for i in completos] for n in nomes)
        concordancia = sum(x == y for x, y in zip(a, b)) / len(completos)
        linhas += [
            "",
            (
                f"Concordância entre os revisores: {concordancia:.1%} ({len(completos)} itens); "
                f"Kappa de Cohen = {kappa(a, b):.3f}"
            ).replace(".", ","),
        ]
        genuinas = Counter(
            revisoes[nomes[0]][i][0] or evaluate.SEM_CATEGORIA
            for i, x, y in zip(completos, a, b)
            if x == y == "genuína"
        )
        if genuinas:
            por_categoria = ", ".join(f"{c}: {n}" for c, n in sorted(genuinas.items()))
            linhas += ["", f"Genuínas para os dois revisores, por categoria: {por_categoria}"]
    return "\n".join(linhas) + "\n"


TIPOS_TRIBUNAL = ["interna", "externa", "erro_material", "fundamentacao", "indeterminado"]


_AGRAVO = re.compile(r"AGRAVO (INTERNO|REGIMENTAL)|\bAgInt\b|\bAgRg\b", re.IGNORECASE)


def e_agravo(decisao: dict) -> bool:
    """Agravo interno ou regimental: o voto costuma transcrever a decisão agravada."""
    return bool(_AGRAVO.search(f"{decisao.get('processo') or ''} {(decisao.get('texto') or '')[:600]}"))


def por_recurso(
    decisoes: list[dict], rotulos: dict[str, bool], predicoes: list[Predicoes], sistema: str
) -> list[str]:
    """Todas as decisões do tribunal: agravo interno/regimental ou não x rótulo x o sistema marcou."""
    marcou = {p.id: any(x.contradicao for x in p.predicoes) for p in predicoes}
    cont = Counter(
        (e_agravo(d), rotulos[d["id"]], marcou.get(d["id"], False)) for d in decisoes if d["id"] in rotulos
    )
    linhas = [
        "",
        "## Todas as decisões, por tipo de recurso",
        "",
        f"| Recurso | Rótulo do tribunal | Decisões | {sistema} marcou |",
        "|---|---|---|---|",
    ]
    for agravo, nome in ((True, "agravo interno ou regimental"), (False, "outros")):
        for rotulo, r in ((True, "reconhecida"), (False, "rejeitada")):
            n = cont[(agravo, rotulo, True)] + cont[(agravo, rotulo, False)]
            linhas.append(f"| {nome} | {r} | {n} | {cont[(agravo, rotulo, True)]} |")
    return linhas


def tribunal(classificacao: list[dict], predicoes: list[Predicoes], sistema: str) -> str:
    """Contradições reconhecidas pelo STJ por onde estavam (lidas no acórdão dos embargos) x o sistema marcou."""
    marcou = {p.id: any(x.contradicao for x in p.predicoes) for p in predicoes}
    sem_predicao = [c["id"] for c in classificacao if c["id"] not in marcou]
    if sem_predicao:
        sys.exit(f"decisões classificadas sem predição de {sistema}: {', '.join(sem_predicao[:5])}")
    invalidos = [c["id"] for c in classificacao if c["tipo"] not in TIPOS_TRIBUNAL]
    if invalidos:
        sys.exit(f"tipo fora de {TIPOS_TRIBUNAL}: {', '.join(invalidos[:5])}")
    por_tipo = Counter((c["tipo"], marcou[c["id"]]) for c in classificacao)
    internas = Counter(
        (c.get("categoria") or "sem categoria", marcou[c["id"]])
        for c in classificacao
        if c["tipo"] == "interna"
    )
    linhas = [
        f"# Contradições reconhecidas pelo tribunal: onde estavam e o que {sistema} marcou",
        "",
        f"{len(classificacao)} acórdãos embargados com a contradição reconhecida. Para cada um, o acórdão dos",
        "embargos foi lido e a contradição reconhecida, classificada por onde estava (regras em",
        "`scripts/erros.py`, `TIPOS_TRIBUNAL`): `interna`, entre dois trechos do próprio acórdão, que é o que o",
        "sistema procura; `externa`, entre o acórdão e algo fora dele (autos, provas, decisão recorrida, outro",
        "julgado, pedido da parte); `erro_material`; `fundamentacao`, falha de fundamentação ou omissão chamada",
        "de contradição; `indeterminado`.",
        "",
        f"| Onde estava | Decisões | {sistema} marcou | {sistema} não marcou |",
        "|---|---|---|---|",
    ]
    for t in TIPOS_TRIBUNAL:
        s, n = por_tipo[(t, True)], por_tipo[(t, False)]
        if s or n:
            linhas.append(f"| {t} | {s + n} | {s} | {n} |")
    total = sum(por_tipo.values())
    linhas.append(
        f"| total | {total} | {sum(v for (_, m), v in por_tipo.items() if m)} | "
        f"{sum(v for (_, m), v in por_tipo.items() if not m)} |"
    )
    afastadas = [c for c in classificacao if c.get("contradicao_afastada")]
    linhas += [
        "",
        (
            f"Em {len(afastadas)} das {len(classificacao)}, o acórdão dos embargos afasta a contradição alegada e"
            " acolhe os embargos por outro vício (omissão ou erro material): positivos que a regra de seleção do"
            f" corpus tomou por contradição reconhecida. {sistema} marcou {sum(marcou[c['id']] for c in afastadas)}"
            " delas."
        ),
    ]
    if internas:
        linhas += [
            "",
            "## Internas, por categoria",
            "",
            f"| Categoria | Decisões | {sistema} marcou |",
            "|---|---|---|",
        ]
        for c in sorted({c for c, _ in internas}):
            linhas.append(f"| {c} | {internas[(c, True)] + internas[(c, False)]} | {internas[(c, True)]} |")
    return "\n".join(linhas) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Análise de erros e revisão humana de 10%")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("relatorio", "amostra"):
        p = sub.add_parser(nome)
        p.add_argument("--sistema", required=True)
        p.add_argument("--dados", default=os.environ.get("DATA_DIR", "data"))
        p.add_argument("--docs", default="docs/resultados")
        p.add_argument("--seed", type=int, default=42)
    p = sub.add_parser("tribunal", help="contradições reconhecidas classificadas por onde estavam")
    p.add_argument(
        "classificacao",
        type=Path,
        help="JSON: [{id, tipo, categoria, evidencia, contradicao_afastada}] (fora do git)",
    )
    p.add_argument("--sistema", default="am+llm")
    p.add_argument("--dados", default=os.environ.get("DATA_DIR", "data/tribunal"))
    p.add_argument("--docs", default="docs/resultados")
    p = sub.add_parser("consolidar", help="planilhas preenchidas (uma por revisor)")
    p.add_argument("planilhas", nargs="+", type=Path)
    p.add_argument("--sistema", default="am+llm")
    p.add_argument("--docs", default="docs/resultados")
    args = ap.parse_args(argv)

    docs = Path(args.docs)
    if args.cmd == "consolidar":
        texto = consolidar({p.stem: ler_revisao(p) for p in args.planilhas}, args.sistema)
        docs.mkdir(parents=True, exist_ok=True)
        (docs / f"revisao_{args.sistema}.md").write_text(texto, encoding="utf-8")
        print(texto)
        return
    dados = Path(args.dados)
    segs, gold, predicoes = carregar(dados, args.sistema)
    if args.cmd == "tribunal":
        texto = tribunal(json.loads(args.classificacao.read_text(encoding="utf-8")), predicoes, args.sistema)
        decisoes = [
            json.loads(linha) for linha in (dados / "decisoes.jsonl").open(encoding="utf-8") if linha.strip()
        ]
        rotulos = json.loads((dados / "rotulos.json").read_text(encoding="utf-8"))
        texto += "\n".join(por_recurso(decisoes, rotulos, predicoes, args.sistema)) + "\n"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "erros_tribunal.md").write_text(texto, encoding="utf-8")
        print(texto)
        return
    if args.cmd == "relatorio":
        if not gold:
            sys.exit(f"sem {dados / 'gold.jsonl'}: o relatório por trecho é da avaliação sintética")
        completo, resumo = relatorio(segs, gold, predicoes, args.sistema)
        (dados / "resultados" / args.sistema / "erros.md").write_text(completo, encoding="utf-8")
        docs.mkdir(parents=True, exist_ok=True)
        (docs / f"erros_{args.sistema}.md").write_text(resumo, encoding="utf-8")
        print(resumo)
    else:
        linhas = amostra(segs, predicoes, args.seed)
        destino = dados / "revisao" / f"{args.sistema}.csv"
        escrever_csv(destino, linhas)
        print(f"{len(linhas)} contradições de {len({x['decisao'] for x in linhas})} decisões -> {destino}")
        print("Copie o arquivo para cada revisor (ex.: am+llm_carolina.csv) e peça a coluna 'avaliacao'.")


if __name__ == "__main__":
    main()
