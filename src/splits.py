"""Folds da validação cruzada (k = 5). Todo experimento usa exatamente estes folds.

    python -m src.splits data/gold.jsonl --resumo docs/resultados/splits.md   # grava data/splits.json
    python -m src.splits --rotulos data/decisoes.jsonl.criterios.jsonl --saida data/tribunal/splits.json

    from src import splits
    folds = splits.carregar()                      # list[list[str]]: ids de cada fold
    treino, teste = splits.particao(folds, 0)      # fold 0 como teste, os outros como treino

Estratificação pela categoria principal de cada decisão: a mais rara no corpus entre as que ela tem,
para as categorias raras se espalharem pelos folds. Decisões sem contradição formam um estrato próprio.
Cada estrato é embaralhado com a seed e distribuído em rodízio, então dentro de um estrato os folds
diferem em no máximo uma decisão. O resultado não depende da ordem do gold.
Com o rótulo do tribunal (`gerar_rotulos`), os estratos são só "com contradição" e "sem contradição".
"""

import argparse
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

from src.contratos import CATEGORIAS, Gold, ler_jsonl
from src.evaluate import ler_rotulos

NEGATIVA = "sem contradição"


def _caminho_padrao() -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "splits.json"


def _categorias(g: Gold) -> set[str]:
    return {c.categoria for c in g.contradicoes}


def gerar(gold: list[Gold], k: int = 5, seed: int = 42) -> dict:
    ids = [g.id for g in gold]
    if len(set(ids)) != len(ids):
        raise ValueError("ids repetidos no gold")
    frequencia = Counter(c for g in gold for c in _categorias(g))

    estratos = defaultdict(list)
    for g in sorted(gold, key=lambda g: g.id):
        cats = _categorias(g)
        estratos[min(cats, key=lambda c: (frequencia[c], c)) if cats else NEGATIVA].append(g.id)
    return _distribuir(estratos, k, seed)


def gerar_rotulos(rotulos: dict[str, bool], k: int = 5, seed: int = 42) -> dict:
    """Folds estratificados pelo rótulo do tribunal (reconhecida / rejeitada)."""
    estratos = defaultdict(list)
    for id in sorted(rotulos):
        estratos["com contradição" if rotulos[id] else NEGATIVA].append(id)
    return _distribuir(estratos, k, seed)


def _distribuir(estratos: dict[str, list[str]], k: int, seed: int) -> dict:
    rng = random.Random(seed)
    folds: list[list[str]] = [[] for _ in range(k)]
    posicao = 0
    for estrato in sorted(estratos):
        rng.shuffle(estratos[estrato])
        for id in estratos[estrato]:
            folds[posicao % k].append(id)
            posicao += 1
    return {"seed": seed, "k": k, "folds": [sorted(f) for f in folds]}


def salvar(splits: dict, caminho: str | Path | None = None) -> None:
    caminho = Path(caminho or _caminho_padrao())
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(splits, ensure_ascii=False, indent=1), encoding="utf-8")


def carregar(caminho: str | Path | None = None) -> list[list[str]]:
    return json.loads(Path(caminho or _caminho_padrao()).read_text(encoding="utf-8"))["folds"]


def particao(folds: list[list[str]], teste: int) -> tuple[list[str], list[str]]:
    """(ids de treino, ids de teste) usando o fold `teste` como teste."""
    return [id for i, f in enumerate(folds) if i != teste for id in f], list(folds[teste])


def distribuicao(folds: list[list[str]], gold: list[Gold]) -> str:
    """Tabela markdown: decisões por categoria em cada fold (uma decisão conta em todas que tiver)."""
    por_id = {g.id: g for g in gold}
    colunas = [*CATEGORIAS, NEGATIVA]
    linhas = [
        "| Fold | Decisões | " + " | ".join(colunas) + " |",
        "|---" * (len(colunas) + 2) + "|",
    ]
    for i, fold in enumerate(folds):
        cont = Counter(c for id in fold for c in (_categorias(por_id[id]) or {NEGATIVA}))
        linhas.append(f"| {i} | {len(fold)} | " + " | ".join(str(cont[c]) for c in colunas) + " |")
    return "\n".join(linhas)


def main() -> None:
    ap = argparse.ArgumentParser(description="Gera os folds estratificados da validação cruzada")
    ap.add_argument("gold", nargs="?", help="gold.jsonl (avaliação por trecho)")
    ap.add_argument("--rotulos", help="<decisoes>.criterios.jsonl: folds pelo rótulo do tribunal")
    ap.add_argument("--saida", help=f"padrão: {_caminho_padrao()}")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resumo", help="grava a distribuição em markdown (ex.: docs/resultados/splits.md)")
    args = ap.parse_args()

    if bool(args.gold) == bool(args.rotulos):
        ap.error("passe o gold ou --rotulos (um dos dois)")
    if args.rotulos:
        rotulos = ler_rotulos(args.rotulos)
        splits = gerar_rotulos(rotulos, k=args.k, seed=args.seed)
        # a distribuição usa um gold só com o rótulo: positiva = uma contradição qualquer
        gold = [Gold(id=id, contradicoes=[]) for id in rotulos]
        tabela = "\n".join(
            f"- fold {i}: {len(f)} decisões, {sum(rotulos[id] for id in f)} com contradição reconhecida"
            for i, f in enumerate(splits["folds"])
        )
    else:
        gold = ler_jsonl(args.gold, Gold)
        splits = gerar(gold, k=args.k, seed=args.seed)
        tabela = distribuicao(splits["folds"], gold)
    salvar(splits, args.saida)
    print(f"{len(gold)} decisões em {args.k} folds (seed {args.seed})\n\n{tabela}")
    if args.resumo:
        Path(args.resumo).parent.mkdir(parents=True, exist_ok=True)
        cabecalho = (
            f"# Folds da validação cruzada\n\nk = {args.k}, seed = {args.seed}, {len(gold)} decisões.\n\n"
        )
        Path(args.resumo).write_text(cabecalho + tabela + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
