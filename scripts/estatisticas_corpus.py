"""Estatísticas do corpus anotado (metas do TCC: >= 300 decisões e >= 30 exemplos por subcategoria).

    python scripts/estatisticas_corpus.py data/gold.jsonl
    python scripts/estatisticas_corpus.py data/gold.jsonl --decisoes data/decisoes.jsonl \\
        --saida docs/resultados/corpus.md

Com `--decisoes`, confere o gold com o rótulo da coleta: decisão com embargos acolhidos por contradição
(`rotulo_decisao=True`) sem nenhuma contradição anotada, ou o contrário, aparece listada para revisão.
"""

import argparse
from collections import Counter
from pathlib import Path

from src.contratos import CATEGORIAS, Decisao, Gold, ler_jsonl

META_DECISOES = 300
META_POR_CATEGORIA = 30
ORDEM = ["ementa", "relatorio", "fundamentacao", "dispositivo"]


def _pct(parte: int, total: int) -> str:
    return f"{100 * parte / total:.1f}%".replace(".", ",") if total else "—"


def relatorio(gold: list[Gold], decisoes: list[Decisao] | None = None) -> str:
    n = len(gold)
    positivas = sum(bool(g.contradicoes) for g in gold)
    exemplos = Counter(c.categoria for g in gold for c in g.contradicoes)
    por_decisao = Counter(cat for g in gold for cat in {c.categoria for c in g.contradicoes})
    segmentos = Counter(
        " × ".join(sorted((c.a.segmento, c.b.segmento), key=ORDEM.index))
        for g in gold
        for c in g.contradicoes
    )

    meta = "ok" if n >= META_DECISOES else f"faltam {META_DECISOES - n}"
    negativas = n - positivas
    linhas = [
        "# Corpus anotado",
        "",
        f"- Decisões: {n} (meta >= {META_DECISOES}: {meta})",
        f"- Com contradição: {positivas} ({_pct(positivas, n)}); sem contradição: {negativas} ({_pct(negativas, n)})",
        f"- Contradições anotadas: {sum(exemplos.values())}",
        "",
        "## Por categoria",
        "",
        "| Categoria | Nome | Exemplos | Decisões | Meta (>= 30 exemplos) |",
        "|---|---|---|---|---|",
    ]
    for cat, descricao in CATEGORIAS.items():
        falta = META_POR_CATEGORIA - exemplos[cat]
        situacao = "ok" if falta <= 0 else f"faltam {falta}"
        linhas.append(
            f"| {cat} | {descricao.split(':')[0]} | {exemplos[cat]} | {por_decisao[cat]} | {situacao} |"
        )

    linhas += ["", "## Por par de segmentos", "", "| Segmentos | Exemplos |", "|---|---|"]
    linhas += [f"| {par} | {qtd} |" for par, qtd in segmentos.most_common()]

    if decisoes is not None:
        rotulo = {d.id: d.rotulo_decisao for d in decisoes}
        sem_rotulo = [g.id for g in gold if g.id not in rotulo]
        rotulo_sem_gold = [g.id for g in gold if rotulo.get(g.id) and not g.contradicoes]
        gold_sem_rotulo = [g.id for g in gold if rotulo.get(g.id) is False and g.contradicoes]
        linhas += [
            "",
            "## Conferência com a coleta",
            "",
            f"- Embargos acolhidos por contradição, mas sem contradição anotada: {len(rotulo_sem_gold)}",
            f"- Sem embargos acolhidos, mas com contradição anotada: {len(gold_sem_rotulo)}",
            f"- No gold, mas fora de decisoes.jsonl: {len(sem_rotulo)}",
        ]
        for titulo, ids in [
            ("Acolhidos sem anotação", rotulo_sem_gold),
            ("Anotados sem embargos acolhidos", gold_sem_rotulo),
            ("Fora da coleta", sem_rotulo),
        ]:
            if ids:
                linhas += ["", f"{titulo}: {', '.join(ids)}"]
    return "\n".join(linhas) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gold")
    ap.add_argument("--decisoes", help="data/decisoes.jsonl, para conferir o rótulo da coleta")
    ap.add_argument("--saida", help="grava o relatório em markdown (ex.: docs/resultados/corpus.md)")
    args = ap.parse_args()

    texto = relatorio(
        ler_jsonl(args.gold, Gold), ler_jsonl(args.decisoes, Decisao) if args.decisoes else None
    )
    print(texto)
    if args.saida:
        Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
        Path(args.saida).write_text(texto, encoding="utf-8")


if __name__ == "__main__":
    main()
