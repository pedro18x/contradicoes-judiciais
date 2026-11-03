"""Baseline sem Mineração de Argumentos: todos os pares de sentenças, similaridade semântica e regras.

    pip install -e ".[baseline]"
    python -m src.baseline data/segmentos.jsonl --gold data/gold.jsonl --folds data/splits.json \\
        --saida data/predicoes_baseline.jsonl      # limiar ajustado nos folds de treino (experimento)
    python -m src.baseline data/segmentos.jsonl --limiar 0.7 --saida data/predicoes_avulsas.jsonl

1. Proposições = sentenças dos quatro segmentos com pelo menos 2 palavras. A verbetação da ementa (o
   trecho em maiúsculas: "CIVIL. LOCAÇÃO. RECURSO PROVIDO.") conta como uma sentença só.
2. Todos os pares, O(n²).
3. Embeddings de sentença (sentence-transformers multilíngue) e cosseno. Só os pares com cosseno >= limiar
   são comparados; eles entram nas predições, com `contradicao` True ou False.
4. Um par comparado é contradição se só uma das sentenças tem negação ("não", "nunca", "nenhum", "nego",
   "improvido"...) ou se uma tem uma palavra e a outra o antônimo dela (src/antonimos.txt). As duas coisas
   juntas se anulam: "não é cabível" × "é incabível" dizem o mesmo.
5. A categoria vem do par de segmentos: ementa × dispositivo = CE-2, relatório × fundamentação = CE-1,
   fundamentação × dispositivo = CDF-1, fundamentação × fundamentação = CIF-2; os demais ficam sem categoria.

O limiar é o que dá o maior F1 no nível do par nas decisões de TREINO de cada fold (empate: o maior
limiar). Critério de acerto da Metodologia do TCC: os dois trechos gold, ou a frase alterada com outro
trecho do segmento em conflito (cobertura de pelo menos 50% dos caracteres, em qualquer ordem). Cada par
gold casa com no máximo uma predição; repetições não contam e as demais predições são falso positivo. O
critério é o de src/evaluate.py (`f1_pares`), o mesmo da avaliação final.
"""

import argparse
import json
import re
from functools import cache
from pathlib import Path

import numpy as np

from src.contratos import (
    Gold,
    Predicao,
    Predicoes,
    Segmentos,
    Trecho,
    escrever_jsonl,
    ler_jsonl,
)
from src.evaluate import f1_decisao, f1_pares
from src.preprocess import sentencas

MODELO_PADRAO = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
LIMIARES = [round(0.5 + 0.05 * i, 2) for i in range(10)]  # 0,50 ... 0,95
LIMIAR_PADRAO = 0.7  # só para uso avulso; no experimento o limiar vem de ajustar_limiar

NEGACOES = {
    "não", "nao", "nunca", "jamais", "nem", "nenhum", "nenhuma", "nada", "ninguém", "tampouco", "sequer",
    "nego", "nega", "negar", "negou", "negam", "negaram", "negado", "negada", "negados", "negadas",
    "improvido", "improvida", "desprovido", "desprovida", "improvimento", "desprovimento",
}  # fmt: skip

CATEGORIAS_POR_SEGMENTO = {
    ("ementa", "dispositivo"): "CE-2",
    ("relatorio", "fundamentacao"): "CE-1",
    ("fundamentacao", "dispositivo"): "CDF-1",
    ("fundamentacao", "fundamentacao"): "CIF-2",
}


def _variacoes(palavra: str) -> set[str]:
    formas = {palavra, palavra + "s"}
    if palavra.endswith("o"):
        formas |= {palavra[:-1] + "a", palavra[:-1] + "as"}
    if palavra.endswith("l"):
        formas.add(palavra[:-1] + "is")
    return formas


def _ler_antonimos(caminho: Path) -> list[tuple[str, str, set[str], set[str]]]:
    pares = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip() and not linha.lstrip().startswith("#"):
            a, b = linha.split()
            pares.append((a, b, _variacoes(a), _variacoes(b)))
    return pares


ANTONIMOS = _ler_antonimos(Path(__file__).parent / "antonimos.txt")


def _palavras(texto: str) -> set[str]:
    return set(re.findall(r"\w+(?:-\w+)*", texto.lower()))


def _conflito(a: set[str], b: set[str]) -> str | None:
    """Motivo pelo qual duas sentenças (conjuntos de palavras) se contradizem, ou None."""
    oposta = bool(a & NEGACOES) != bool(b & NEGACOES)
    antonimos = next(
        (
            f"antônimos: {p1} × {p2}"
            for p1, p2, v1, v2 in ANTONIMOS
            if (a & v1 and b & v2) or (a & v2 and b & v1)
        ),
        None,
    )
    if oposta and antonimos:
        return None
    return "polaridade oposta" if oposta else antonimos


@cache
def carregar_encoder(modelo: str = MODELO_PADRAO):
    from sentence_transformers import SentenceTransformer

    st = SentenceTransformer(modelo)
    return lambda frases: st.encode(frases, convert_to_numpy=True, show_progress_bar=False)


def comparar(segs: Segmentos, encoder) -> tuple[list[Trecho], list[tuple[int, int, float, str | None]]]:
    """Sentenças da decisão e os pares (i, j, cosseno, motivo) com cosseno >= o menor limiar da grade."""
    trechos = [
        Trecho(segmento=nome, inicio=ini, fim=fim)
        for nome in ("ementa", "relatorio", "fundamentacao", "dispositivo")
        for ini, fim in sentencas(getattr(segs, nome))
        if len(re.findall(r"[^\W\d_]+", getattr(segs, nome)[ini:fim])) >= 2
    ]
    if len(trechos) < 2:
        return trechos, []
    textos = [getattr(segs, t.segmento)[t.inicio : t.fim] for t in trechos]
    vetores = np.asarray(encoder(textos), dtype=float)
    vetores /= np.clip(np.linalg.norm(vetores, axis=1, keepdims=True), 1e-12, None)
    cosseno = vetores @ vetores.T
    palavras = [_palavras(t) for t in textos]
    ii, jj = np.triu_indices(len(trechos), k=1)
    manter = cosseno[ii, jj] >= LIMIARES[0] - 1e-9
    pares = [
        (int(i), int(j), float(cosseno[i, j]), _conflito(palavras[i], palavras[j]))
        for i, j in zip(ii[manter], jj[manter])
    ]
    return trechos, pares


def _predicoes(id: str, comparacao, limiar: float, modelo: str) -> Predicoes:
    trechos, pares = comparacao
    predicoes = []
    for i, j, cos, motivo in pares:
        if cos < limiar - 1e-9:
            continue
        a, b = trechos[i], trechos[j]
        predicoes.append(
            Predicao(
                a=a,
                b=b,
                contradicao=motivo is not None,
                categoria=CATEGORIAS_POR_SEGMENTO.get((a.segmento, b.segmento)) if motivo else None,
                justificativa=f"cosseno {cos:.2f}" + (f"; {motivo}" if motivo else ""),
            )
        )
    return Predicoes(id=id, sistema="baseline", modelo=f"{modelo}; limiar={limiar}", predicoes=predicoes)


def prever(
    segs: Segmentos, limiar: float = LIMIAR_PADRAO, encoder=None, modelo: str = MODELO_PADRAO
) -> Predicoes:
    return _predicoes(segs.id, comparar(segs, encoder or carregar_encoder(modelo)), limiar, modelo)


def ajustar_limiar(
    comparacoes: dict,
    gold: dict[str, Gold],
    modelo: str = MODELO_PADRAO,
    rotulos: dict[str, bool] | None = None,
) -> float:
    """Limiar da grade com maior F1 nas decisões de `comparacoes` (passe só as de treino): F1 por par contra
    o gold ou, com `rotulos` (rótulo do tribunal), F1 por decisão."""
    # o F1 só olha os pares marcados como contradição; os outros não precisam virar Predicao
    so_contradicoes = {id: (t, [p for p in pares if p[3]]) for id, (t, pares) in comparacoes.items()}

    def f1(limiar):
        preds = [_predicoes(id, c, limiar, modelo) for id, c in so_contradicoes.items()]
        if rotulos is not None:
            return f1_decisao(preds, rotulos)
        return f1_pares(preds, [gold[id] for id in comparacoes])

    return max(LIMIARES, key=lambda limiar: (f1(limiar), limiar))


def validacao_cruzada(
    segmentos: list[Segmentos],
    gold: list[Gold],
    folds: list[list[str]],
    encoder=None,
    modelo: str = MODELO_PADRAO,
    rotulos: dict[str, bool] | None = None,
) -> tuple[list[Predicoes], list[float]]:
    """Predições de cada decisão no fold em que ela é teste, com o limiar ajustado nos outros folds (contra
    o gold ou, com `rotulos`, contra o rótulo do tribunal)."""
    encoder = encoder or carregar_encoder(modelo)
    comparacoes = {s.id: comparar(s, encoder) for s in segmentos}
    gold_por_id = {g.id: g for g in gold}
    referencia = rotulos.keys() if rotulos is not None else gold_por_id.keys()
    faltando = {id for f in folds for id in f} - (comparacoes.keys() & referencia)
    if faltando:
        raise ValueError(f"decisões dos folds sem segmentos ou gold: {', '.join(sorted(faltando))}")
    predicoes, limiares = [], []
    for i, teste in enumerate(folds):
        treino = {id: comparacoes[id] for j, f in enumerate(folds) if j != i for id in f}
        limiar = ajustar_limiar(treino, gold_por_id, modelo, rotulos)
        limiares.append(limiar)
        predicoes += [_predicoes(id, comparacoes[id], limiar, modelo) for id in teste]
    return predicoes, limiares


def main() -> None:
    ap = argparse.ArgumentParser(description="Baseline: similaridade + regras sobre todos os pares")
    ap.add_argument("segmentos")
    ap.add_argument("--saida", required=True)
    ap.add_argument("--gold", help="com --folds: ajusta o limiar no treino de cada fold")
    ap.add_argument("--folds", help="data/splits.json")
    ap.add_argument("--limiar", type=float, default=LIMIAR_PADRAO, help="usado sem --gold/--folds")
    ap.add_argument("--modelo", default=MODELO_PADRAO)
    args = ap.parse_args()

    segmentos = ler_jsonl(args.segmentos, Segmentos)
    if bool(args.gold) != bool(args.folds):
        ap.error("--gold e --folds vão juntos")
    if args.folds:
        folds = json.loads(Path(args.folds).read_text(encoding="utf-8"))["folds"]
        predicoes, limiares = validacao_cruzada(
            segmentos, ler_jsonl(args.gold, Gold), folds, modelo=args.modelo
        )
        print("limiar por fold: " + ", ".join(f"{i}: {limiar}" for i, limiar in enumerate(limiares)))
    else:
        predicoes = [prever(s, args.limiar, modelo=args.modelo) for s in segmentos]
    escrever_jsonl(args.saida, predicoes)
    n = sum(p.contradicao for d in predicoes for p in d.predicoes)
    print(f"{len(predicoes)} decisões, {n} pares marcados como contradição -> {args.saida}")


if __name__ == "__main__":
    main()
