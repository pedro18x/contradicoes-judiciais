"""Monta as duas avaliações a partir da coleta, sem anotação manual.

    python scripts/preparar_avaliacoes.py data/segmentos.jsonl data/decisoes.jsonl.criterios.jsonl \
        --saida data --resumo docs/resultados/corpus.md

(data/segmentos.jsonl vem de `python -m src.segment data/decisoes.jsonl data/segmentos.jsonl`.)

- Avaliação 1, rótulo do tribunal -> <saida>/tribunal/: segmentos.jsonl, rotulos.json e splits.json com as
  decisões "reconhecida" (True) e "rejeitada" (False). Folds estratificados pelo rótulo.
- Avaliação 2, contradições sintéticas -> <saida>/sintetico/: segmentos.jsonl, gold.jsonl e splits.json,
  gerados por src/sintetico.py a partir das decisões "negativa". Folds estratificados pela categoria.

As duas usam decisões diferentes: nenhuma decisão do tribunal está no sintético, então os exemplos
few-shot da avaliação 1 podem vir do sintético inteiro sem vazamento.

Tamanho final: --max-tribunal N fica com até N decisões do tribunal, metade reconhecidas e metade
rejeitadas; --max-sintetico N fica com até N bases do sintético. Os dois cortes são sorteados com --seed e o
corpus.md registra quantas foram coletadas e quantas entraram.
"""

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

import numpy as np

from src import sintetico, splits
from src.contratos import Segmentos, escrever_jsonl, ler_jsonl
from src.evaluate import ler_rotulos
from src.preprocess import sentencas

SEGMENTOS = ("ementa", "relatorio", "fundamentacao", "dispositivo")


def tamanhos(conjuntos: dict[str, list[Segmentos]]) -> list[str]:
    """Tabela com o tamanho das decisões de cada conjunto (sentenças e caracteres nos quatro segmentos)."""
    linhas = [
        "## Tamanho das decisões",
        "",
        "Sentenças e caracteres somados nos quatro segmentos (ementa, relatório, fundamentação, dispositivo).",
        "",
        "| Conjunto | Decisões | Sentenças (mediana) | Sentenças (1º–3º quartil) | Caracteres (mediana) |",
        "|---|---|---|---|---|",
    ]
    for nome, segs in conjuntos.items():
        if not segs:
            linhas.append(f"| {nome} | 0 | — | — | — |")
            continue
        n = [sum(len(sentencas(getattr(s, c))) for c in SEGMENTOS) for s in segs]
        chars = [sum(len(getattr(s, c)) for c in SEGMENTOS) for s in segs]
        q1, med, q3 = np.percentile(n, [25, 50, 75])
        linhas.append(f"| {nome} | {len(segs)} | {med:.0f} | {q1:.0f}–{q3:.0f} | {np.median(chars):.0f} |")
    return linhas


def descartados(log: Path) -> list[str]:
    """Casos que a coleta registrou sem embargado ou sem texto, por motivo (a data do motivo é omitida)."""
    falhas = [json.loads(linha) for linha in log.read_text(encoding="utf-8").splitlines() if linha.strip()]
    motivos = Counter(re.sub(r"\s+em\s+\d{4}-\d{2}-\d{2}$", "", f["motivo"]) for f in falhas)
    return [
        "## Casos descartados na coleta",
        "",
        f"{len(falhas)} casos descartados por não terem os dois textos (registrados em `{log.name}`).",
        "",
        "| Motivo | Casos |",
        "|---|---|",
        *(f"| {m} | {c} |" for m, c in motivos.most_common()),
    ]


def amostra_tribunal(rotulos: dict[str, bool], n: int | None, seed: int) -> dict[str, bool]:
    """Até `n` decisões do tribunal, metade reconhecidas (True) e metade rejeitadas (False), sorteadas com
    `seed` (mesma entrada e mesma seed, mesma amostra). Sem `n`, devolve todas.

    A proporção fica sempre 1:1: se um rótulo tiver menos de n/2 decisões, os dois ficam com o tamanho do
    menor e o total fica abaixo de `n`. Com as classes iguais, o F1 por decisão continua comparável entre
    os folds (estratificados pelo rótulo) e entre as configurações."""
    if n is None:
        return rotulos
    rng = random.Random(seed)
    por_rotulo = {r: sorted(id for id, v in rotulos.items() if v is r) for r in (True, False)}
    k = min(n // 2, *map(len, por_rotulo.values()))
    escolhidas = [id for r in (True, False) for id in rng.sample(por_rotulo[r], k)]
    return {id: rotulos[id] for id in sorted(escolhidas)}


def amostra_sintetico(negativas: set[str], n: int | None, seed: int) -> set[str]:
    """Até `n` bases do sintético, sorteadas com `seed`. Sem `n`, devolve todas."""
    if n is None or n >= len(negativas):
        return negativas
    return set(random.Random(seed).sample(sorted(negativas), n))


def preparar(
    segmentos: list[Segmentos],
    criterios: Path,
    saida: Path,
    k: int = 5,
    seed: int = 42,
    log: Path | None = None,
    max_tribunal: int | None = None,
    max_sintetico: int | None = None,
) -> str:
    rotulos = ler_rotulos(criterios)
    linhas = criterios.read_text(encoding="utf-8").splitlines()
    negativas = {c["id"] for c in map(json.loads, filter(str.strip, linhas)) if c["criterio"] == "negativa"}
    por_id = {s.id: s for s in segmentos}
    sem_texto = sorted((rotulos.keys() | negativas) - por_id.keys())
    if sem_texto:
        raise ValueError(f"decisões sem segmentos: {', '.join(sem_texto)}")
    coletadas = {"tribunal": len(rotulos), "sintetico": len(negativas)}
    rotulos = amostra_tribunal(rotulos, max_tribunal, seed)
    negativas = amostra_sintetico(negativas, max_sintetico, seed)

    tribunal = saida / "tribunal"
    escrever_jsonl(tribunal / "segmentos.jsonl", [por_id[id] for id in sorted(rotulos)])
    (tribunal / "rotulos.json").write_text(
        json.dumps(rotulos, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    folds_t = splits.gerar_rotulos(rotulos, k, seed)
    splits.salvar(folds_t, tribunal / "splits.json")

    pasta = saida / "sintetico"
    segs_s, gold_s = sintetico.gerar([por_id[id] for id in sorted(negativas)], seed)
    escrever_jsonl(pasta / "segmentos.jsonl", segs_s)
    escrever_jsonl(pasta / "gold.jsonl", gold_s)
    folds_s = splits.gerar(gold_s, k, seed)
    splits.salvar(folds_s, pasta / "splits.json")

    positivos = sum(rotulos.values())
    corte = []
    if (len(rotulos), len(negativas)) != (coletadas["tribunal"], coletadas["sintetico"]):
        corte = [
            (
                f"Coletadas: {coletadas['tribunal']} decisões do tribunal e {coletadas['sintetico']} bases do "
                f"sintético. Entraram {len(rotulos)} e {len(negativas)}, sorteadas com seed {seed}."
            ),
            "",
        ]
    secoes = [
        "# Corpus das avaliações",
        "",
        *corte,
        "## Avaliação 1: rótulo do tribunal",
        "",
        (
            f"{len(rotulos)} acórdãos embargados: {positivos} com a contradição reconhecida pelo STJ nos embargos "
            f"de declaração e {len(rotulos) - positivos} com a contradição alegada e rejeitada. k = {k}, seed {seed}."
        ),
        "",
        "| Fold | Decisões | Reconhecidas | Rejeitadas |",
        "|---|---|---|---|",
        *(
            f"| {i} | {len(f)} | {sum(rotulos[id] for id in f)} | {sum(not rotulos[id] for id in f)} |"
            for i, f in enumerate(folds_t["folds"])
        ),
        "",
        sintetico.resumo(gold_s).replace(
            "# Contradições sintéticas", "## Avaliação 2: contradições sintéticas"
        ),
        "### Distribuição nos folds",
        "",
        splits.distribuicao(folds_s["folds"], gold_s),
        "",
        *tamanhos(
            {
                "Tribunal: contradição reconhecida": [por_id[id] for id in sorted(rotulos) if rotulos[id]],
                "Tribunal: contradição alegada e rejeitada": [
                    por_id[id] for id in sorted(rotulos) if not rotulos[id]
                ],
                "Base do sintético": [por_id[id] for id in sorted(negativas)],
            }
        ),
    ]
    if log is not None:
        secoes += ["", *descartados(log)]
    vazios = Counter(n for s in segmentos for n in ("ementa", "dispositivo") if not getattr(s, n))
    if vazios:
        secoes += [
            "",
            "Segmentos vazios no corpus inteiro: " + ", ".join(f"{n}: {c}" for n, c in vazios.items()),
        ]
    return "\n".join(secoes) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Monta data/tribunal e data/sintetico a partir da coleta")
    ap.add_argument("segmentos", help="segmentos.jsonl de todas as decisões coletadas")
    ap.add_argument("criterios", help="<decisoes>.criterios.jsonl da coleta")
    ap.add_argument("--saida", default="data")
    ap.add_argument("--resumo", help="grava o resumo em markdown (ex.: docs/resultados/corpus.md)")
    ap.add_argument("--log", help="<decisoes>.log.jsonl da coleta: conta os casos descartados")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-tribunal", type=int, help="até N decisões do tribunal, metade de cada rótulo")
    ap.add_argument("--max-sintetico", type=int, help="até N bases do sintético")
    args = ap.parse_args(argv)
    texto = preparar(
        ler_jsonl(args.segmentos, Segmentos),
        Path(args.criterios),
        Path(args.saida),
        args.k,
        args.seed,
        Path(args.log) if args.log else None,
        args.max_tribunal,
        args.max_sintetico,
    )
    if args.resumo:
        Path(args.resumo).parent.mkdir(parents=True, exist_ok=True)
        Path(args.resumo).write_text(texto, encoding="utf-8")
    print(texto, end="")


if __name__ == "__main__":
    main()
