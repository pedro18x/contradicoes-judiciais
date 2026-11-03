"""Gold da segmentação: arquivos para conferir à mão e importação para o avaliar_segmentacao.

    python scripts/gold_segmentacao.py preparar data/decisoes.jsonl data/segmentacao --n 30
    (conferir/corrigir os .txt de data/segmentacao/)
    python scripts/gold_segmentacao.py importar data/segmentacao data/segmentacao_gold.jsonl
    python scripts/avaliar_segmentacao.py data/segmentacao_gold.jsonl --saida docs/resultados/segmentacao.md

`preparar` sorteia --n decisões (seed 42) e grava um .txt por decisão com o texto NORMALIZADO e marcadores
em linhas próprias nos limites que a segmentação automática encontrou:

    [[INÍCIO EMENTA]]
    ...
    [[FIM EMENTA]]

Quem confere só move os marcadores que estiverem no lugar errado (ou apaga o par, se o segmento não existe).
Texto fora de um par INÍCIO/FIM não pertence a nenhum segmento (cabeçalho do acórdão, certidão, outros votos).
`importar` lê os .txt corrigidos e grava o gold no formato `Segmentos`.
"""

import argparse
import random
import re
import sys
from pathlib import Path

from src.contratos import Decisao, Segmentos, escrever_jsonl, ler_jsonl
from src.preprocess import normalizar
from src.segment import fatiar

NOMES = {
    "ementa": "EMENTA",
    "relatorio": "RELATÓRIO",
    "fundamentacao": "FUNDAMENTAÇÃO",
    "dispositivo": "DISPOSITIVO",
}
_MARCADOR = re.compile(
    r"^\[\[(INÍCIO|FIM) (EMENTA|RELATÓRIO|FUNDAMENTAÇÃO|DISPOSITIVO)\]\]\s*$", re.MULTILINE
)


def marcar(texto: str) -> str:
    """Texto com os marcadores [[INÍCIO X]] / [[FIM X]] nos limites da segmentação automática."""
    inserir = []
    for nome, (ini, fim) in fatiar(texto).items():
        if fim > ini:
            inserir += [(ini, 1, f"\n[[INÍCIO {NOMES[nome]}]]\n"), (fim, 0, f"\n[[FIM {NOMES[nome]}]]\n")]
    saida, pos = [], 0
    for ponto, _, marcador in sorted(inserir):
        saida += [texto[pos:ponto], marcador]
        pos = ponto
    saida.append(texto[pos:])
    return re.sub(r"\n{3,}", "\n\n", "".join(saida)).strip() + "\n"


def ler_marcado(id: str, conteudo: str) -> Segmentos:
    """Inverso de `marcar`: o texto de cada par INÍCIO/FIM. Erro claro se um par estiver incompleto."""
    abertos, segmentos = {}, dict.fromkeys(NOMES, "")
    por_titulo = {v: k for k, v in NOMES.items()}
    for m in _MARCADOR.finditer(conteudo):
        nome = por_titulo[m[2]]
        if m[1] == "INÍCIO":
            if nome in abertos:
                raise ValueError(f"{id}: [[INÍCIO {m[2]}]] aparece duas vezes")
            abertos[nome] = m.end()
        else:
            if nome not in abertos:
                raise ValueError(f"{id}: [[FIM {m[2]}]] sem o [[INÍCIO {m[2]}]] antes")
            trecho = _MARCADOR.sub("", conteudo[abertos.pop(nome) : m.start()])
            segmentos[nome] = trecho.strip()
    if abertos:
        raise ValueError(f"{id}: falta o [[FIM ...]] de {', '.join(NOMES[n] for n in abertos)}")
    return Segmentos(id=id, **segmentos)


def preparar(decisoes: list[Decisao], pasta: Path, n: int, seed: int = 42) -> list[str]:
    escolhidas = random.Random(seed).sample(sorted(decisoes, key=lambda d: d.id), min(n, len(decisoes)))
    pasta.mkdir(parents=True, exist_ok=True)
    for d in escolhidas:
        (pasta / f"{d.id}.txt").write_text(marcar(normalizar(d.texto)), encoding="utf-8")
    return [d.id for d in escolhidas]


def importar(pasta: Path) -> tuple[list[Segmentos], list[str]]:
    gold, erros = [], []
    for arquivo in sorted(pasta.glob("*.txt")):
        try:
            gold.append(ler_marcado(arquivo.stem, arquivo.read_text(encoding="utf-8")))
        except ValueError as e:
            erros.append(str(e))
    return gold, erros


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description="Gold da segmentação: preparar arquivos e importar a conferência"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preparar")
    p.add_argument("decisoes")
    p.add_argument("pasta")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p = sub.add_parser("importar")
    p.add_argument("pasta")
    p.add_argument("saida")
    args = ap.parse_args(argv)
    if args.cmd == "preparar":
        ids = preparar(ler_jsonl(args.decisoes, Decisao), Path(args.pasta), args.n, args.seed)
        print(f"{len(ids)} arquivos para conferir em {args.pasta}/")
        return
    gold, erros = importar(Path(args.pasta))
    for e in erros:
        print(f"CORRIGIR: {e}", file=sys.stderr)
    escrever_jsonl(args.saida, gold)
    print(
        f"{len(gold)} decisões no gold de segmentação -> {args.saida}"
        + (f" ({len(erros)} com erro)" if erros else "")
    )
    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()
