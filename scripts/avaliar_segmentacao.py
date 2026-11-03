"""Precisão e revocação da segmentação contra uma amostra segmentada à mão (meta: P e R >= 0,85).

    python scripts/avaliar_segmentacao.py data/segmentacao_gold.jsonl
    python scripts/avaliar_segmentacao.py data/segmentacao_gold.jsonl --saida docs/resultados/segmentacao.md

O gold tem um `Segmentos` por decisão, montado à mão copiando cada segmento do texto NORMALIZADO
(`normalizar(decisao.texto)`). Os textos vêm de `--decisoes` (padrão: $DATA_DIR/decisoes.jsonl).

A comparação é por caractere: cada segmento (previsto e gold) vira um intervalo do texto normalizado, e
P = |previsto ∩ gold| / |previsto|, R = |previsto ∩ gold| / |gold|, somando todas as decisões (micro).
Diferenças só de espaço ou quebra de linha entre o gold e o texto são toleradas.
"""

import argparse
import os
import re
import sys
from pathlib import Path

from src.contratos import Decisao, Segmentos, ler_jsonl
from src.preprocess import normalizar
from src.segment import fatiar

NOMES = ["ementa", "relatorio", "fundamentacao", "dispositivo"]
META = 0.85


def localizar(texto: str, trecho: str, desde: int = 0) -> tuple[int, int] | None:
    """Intervalo de `trecho` em `texto` a partir de `desde`, ignorando diferenças de espaço."""
    if not trecho.strip():
        return (desde, desde)
    padrao = r"\s+".join(re.escape(t) for t in trecho.split())
    m = re.compile(padrao).search(texto, desde)
    return (m.start(), m.end()) if m else None


def _intersecao(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def medir(texto: str, gold: Segmentos) -> dict[str, tuple[int, int, int]]:
    """Por segmento: (caracteres em comum, tamanho previsto, tamanho gold)."""
    previsto = fatiar(texto)
    contagem, desde = {}, 0
    for nome in NOMES:
        # procura depois do segmento anterior (um dispositivo curto também pode aparecer citado no relatório);
        # se não achar, procura desde o começo: alguns acórdãos trazem o relatório antes da ementa
        trecho = getattr(gold, nome)
        intervalo = localizar(texto, trecho, desde) or localizar(texto, trecho, 0)
        if intervalo is None:
            raise ValueError(f"{gold.id}: o segmento '{nome}' do gold não aparece no texto normalizado")
        desde = max(desde, intervalo[1])
        p = previsto[nome]
        contagem[nome] = (_intersecao(p, intervalo), p[1] - p[0], intervalo[1] - intervalo[0])
    return contagem


def _razao(a: int, b: int) -> float | None:
    return a / b if b else None


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}".replace(".", ",")


def tabela(medidas: dict[str, dict[str, tuple[int, int, int]]]) -> str:
    linhas = ["| Segmento | P | R | F1 |", "|---|---|---|---|"]
    for nome in NOMES:
        comum = sum(m[nome][0] for m in medidas.values())
        p = _razao(comum, sum(m[nome][1] for m in medidas.values()))
        r = _razao(comum, sum(m[nome][2] for m in medidas.values()))
        f1 = None if p is None or r is None else (2 * p * r / (p + r) if p + r else 0.0)
        linhas.append(f"| {nome} | {_fmt(p)} | {_fmt(r)} | {_fmt(f1)} |")
    return "\n".join(linhas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gold")
    ap.add_argument("--decisoes", default=Path(os.environ.get("DATA_DIR", "data")) / "decisoes.jsonl")
    ap.add_argument("--saida", help="grava a tabela em markdown (ex.: docs/resultados/segmentacao.md)")
    args = ap.parse_args()

    textos = {d.id: normalizar(d.texto) for d in ler_jsonl(args.decisoes, Decisao)}
    gold = ler_jsonl(args.gold, Segmentos)
    faltando = [g.id for g in gold if g.id not in textos]
    if faltando:
        sys.exit(f"decisões do gold ausentes em {args.decisoes}: {', '.join(faltando)}")

    medidas, erros = {}, []
    for g in gold:
        try:
            medidas[g.id] = medir(textos[g.id], g)
        except ValueError as e:
            erros.append(str(e))
    for e in erros:
        print(f"IGNORADA: {e}", file=sys.stderr)

    resultado = f"{len(medidas)} decisões avaliadas (meta: P e R >= {_fmt(META)})\n\n{tabela(medidas)}\n"
    print(resultado)
    abaixo = [
        f"{id} ({nome}: P={_fmt(_razao(c, p))}, R={_fmt(_razao(c, g))})"
        for id, m in medidas.items()
        for nome, (c, p, g) in m.items()
        if min(_razao(c, p) or 0, _razao(c, g) or 0) < META and (p or g)
    ]
    if abaixo:
        print("Abaixo da meta:\n  " + "\n  ".join(abaixo))
    if args.saida:
        Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
        Path(args.saida).write_text(f"# Segmentação\n\n{resultado}", encoding="utf-8")


if __name__ == "__main__":
    main()
