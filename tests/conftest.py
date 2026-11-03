"""Nenhum teste chama a API do LLM.

- `_sem_rede` (automático): cache do LLM numa pasta temporária e provedor real trocado por um erro, para
  um teste que esqueça o mock falhar em vez de gastar créditos (test_llm.py cuida do provedor sozinho).
- `llm_fixtures`: LLM falso que responde a partir das fixtures (FICT-0001/0002), para rodar o pipeline
  inteiro com os prompts reais.
- `provedor_fixtures`: as mesmas respostas, mas no lugar do provedor: o gateway (modelo por etapa, cache)
  roda de verdade.
"""

import json
import re
from pathlib import Path

import pytest

from src import llm
from src.contratos import Pares, Predicoes, Proposicoes, Segmentos, ler_jsonl, texto_do_trecho

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _sem_rede(request, monkeypatch, tmp_path):
    if request.module.__name__.endswith("test_llm"):
        return
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache-llm"))
    monkeypatch.setenv("LLM_MODEL", "modelo-teste")
    for var in ("LLM_MODEL_MA", "LLM_MODEL_NLI", "LLM_TETO_USD"):  # vazias: o .env local não vaza
        monkeypatch.setenv(var, "")

    def proibido(*args, **kwargs):
        raise AssertionError("teste tentou chamar a API do LLM: use um mock (ex.: llm_fixtures)")

    monkeypatch.setattr(llm, "_chamar_provedor", proibido)


class LLMFixtures:
    """Responde como o LLM responderia nas fixtures, identificando o prompt pelo título do system."""

    def __init__(self):
        self.segs = ler_jsonl(FIX / "segmentos.jsonl", Segmentos)
        self.props = ler_jsonl(FIX / "proposicoes.jsonl", Proposicoes)
        self.pares = {p.id: p for p in ler_jsonl(FIX / "pares.jsonl", Pares)}
        self.preds = {p.id: p for p in ler_jsonl(FIX / "predicoes.jsonl", Predicoes)}
        self.chamadas: list[tuple[str, str]] = []

    def __call__(self, prompt: str, *, system: str = "", model=None, etapa=None):
        self.chamadas.append((system.splitlines()[0] if system else "", prompt))
        if system.startswith("# Proposições"):
            return self._proposicoes(prompt)
        if system.startswith("# Pares"):
            return self._pares(prompt)
        if system.startswith("# NLI"):
            return self._nli(prompt)
        raise AssertionError(f"prompt desconhecido: {system[:40]!r}")

    def _proposicoes(self, prompt):
        nome, texto = re.match(r"Segmento: (\w+)\nTexto:\n(.*)", prompt, re.DOTALL).groups()
        for segs, props in zip(self.segs, self.props):
            if getattr(segs, nome) == texto:
                return {"proposicoes": [p.texto for p in props.proposicoes if p.segmento == nome]}
        return {"proposicoes": []}

    def _decisao(self, textos: set[str]) -> Proposicoes:
        return next(p for p in self.props if {x.texto for x in p.proposicoes} == textos)

    def _pares(self, prompt):
        linhas = re.findall(r"^(p\d+) \[\w+\] (.*)$", prompt, re.MULTILINE)
        props = self._decisao({t for _, t in linhas})
        # pids do prompt = pids da fixture (mesma ordem de extração)
        pares = self.pares[props.id].pares
        estruturais = {"conclusao-dispositivo", "ementa-dispositivo"}  # montados pelo argmining
        return {
            "conclusoes": [p.par[0] for p in pares if p.relacao == "conclusao-dispositivo"],
            "pares": [
                {"a": p.par[0], "b": p.par[1], "relacao": p.relacao}
                for p in pares
                if p.relacao not in estruturais
            ],
        }

    def _nli(self, prompt):
        itens = re.findall(r'^\[(\d+)\] A \(\w+\): (".*")\n {4}B \(\w+\): (".*")$', prompt, re.MULTILINE)
        resultados = []
        for i, a, b in itens:
            a, b = json.loads(a), json.loads(b)
            achada = None
            for segs in self.segs:
                for p in self.preds[segs.id].predicoes:
                    textos = {texto_do_trecho(segs, p.a), texto_do_trecho(segs, p.b)}
                    if p.contradicao and textos == {a, b}:
                        achada = p
            resultados.append(
                {
                    "i": int(i),
                    "contradicao": achada is not None,
                    "categoria": achada.categoria if achada else None,
                    "justificativa": achada.justificativa if achada else "",
                }
            )
        return {"resultados": resultados}


@pytest.fixture
def llm_fixtures(monkeypatch):
    falso = LLMFixtures()
    monkeypatch.setattr(llm, "complete_json", falso)
    return falso


@pytest.fixture
def provedor_fixtures(monkeypatch):
    """Devolve a lista (título do prompt, modelo) de cada chamada que chegou ao provedor."""
    falso, chamadas = LLMFixtures(), []

    def provedor(model, system, prompt):
        chamadas.append((system.splitlines()[0], model))
        return json.dumps(falso(prompt, system=system)), {"tokens_in": 100, "tokens_out": 10}

    monkeypatch.setattr(llm, "_chamar_provedor", provedor)
    return chamadas
