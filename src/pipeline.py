"""Pipeline completo: texto do acórdão -> (Segmentos, Predicoes).

    python -m src.pipeline arquivo.txt

Se um módulo (preprocess, segment, argmining, nli) não existir em src/, a etapa usa um stub que
devolve a decisão fictícia FICT-0001 de tests/fixtures/.
"""

import importlib
import importlib.util
import logging
import sys
from pathlib import Path

from src.contratos import (
    CATEGORIAS,
    Pares,
    Predicoes,
    Proposicoes,
    Segmentos,
    ler_jsonl,
    texto_do_trecho,
)

log = logging.getLogger(__name__)
FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


def _fixture(nome, modelo, id):
    return ler_jsonl(FIXTURES / f"{nome}.jsonl", modelo)[0].model_copy(update={"id": id})


# Stubs com as fixtures, usados só quando o módulo correspondente não existe.
_STUBS = {
    ("preprocess", "normalizar"): lambda texto: texto,
    ("segment", "segmentar"): lambda id, texto: _fixture("segmentos", Segmentos, id),
    ("argmining", "proposicoes"): lambda segs: _fixture("proposicoes", Proposicoes, segs.id),
    ("argmining", "pares"): lambda segs, props: _fixture("pares", Pares, segs.id),
    ("nli", "classificar"): lambda segs, props, pares: _fixture("predicoes", Predicoes, segs.id),
}


def _etapa(modulo: str, funcao: str):
    if importlib.util.find_spec(f"src.{modulo}") is None:
        log.warning("src/%s.py ainda não existe: usando stub com a fixture FICT-0001", modulo)
        return _STUBS[(modulo, funcao)]
    return getattr(importlib.import_module(f"src.{modulo}"), funcao)


def run(texto: str, id: str = "entrada") -> tuple[Segmentos, Predicoes]:
    texto = _etapa("preprocess", "normalizar")(texto)
    segs = _etapa("segment", "segmentar")(id, texto)
    props = _etapa("argmining", "proposicoes")(segs)
    pares = _etapa("argmining", "pares")(segs, props)
    return segs, _etapa("nli", "classificar")(segs, props, pares)


def main(caminho: str) -> None:
    segs, preds = run(Path(caminho).read_text(encoding="utf-8"))
    achadas = [p for p in preds.predicoes if p.contradicao]
    print(f"{len(achadas)} contradição(ões) encontrada(s)\n")
    for p in achadas:
        nome = CATEGORIAS[p.categoria].split(":")[0] if p.categoria else "sem categoria"
        print(f"[{p.categoria}] {nome}")
        print(f"  {p.a.segmento}: {texto_do_trecho(segs, p.a)}")
        print(f"  {p.b.segmento}: {texto_do_trecho(segs, p.b)}")
        print(f"  Justificativa: {p.justificativa}\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    if len(sys.argv) != 2:
        sys.exit("uso: python -m src.pipeline arquivo.txt")
    main(sys.argv[1])
