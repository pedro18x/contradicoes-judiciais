"""Contratos de dados entre os módulos: os formatos que todas as etapas leem e gravam.

Todo arquivo intermediário é JSONL (um objeto por linha) de um destes modelos.
Offsets (`inicio`, `fim`) são índices de caractere Python DENTRO do segmento:
`getattr(segmentos, trecho.segmento)[trecho.inicio:trecho.fim]` devolve o texto do trecho.
"""

from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, model_validator

Segmento = Literal["ementa", "relatorio", "fundamentacao", "dispositivo"]

Categoria = Literal[
    "CDF-1", "CDF-2", "CIF-1", "CIF-2", "CIF-3", "CIL-1", "CIL-2", "CE-1", "CE-2"
]

# Taxonomia (Tabela 2 do TCC). Usar nos prompts de few-shot.
CATEGORIAS: dict[str, str] = {
    "CDF-1": "Conclusão Invertida: a fundamentação conclui em favor de uma das partes, "
    "mas o dispositivo decide em sentido oposto.",
    "CDF-2": "Extensão Incompatível: a fundamentação delimita o alcance da condenação "
    "(valor, período ou objeto), mas o dispositivo concede mais ou menos do que o raciocínio suporta.",
    "CIF-1": "Contradição Fático-Jurídica: os fatos estabelecidos no relatório ou na "
    "fundamentação não sustentam a subsunção jurídica aplicada pelo julgador.",
    "CIF-2": "Contradição entre Premissas: dois enunciados factuais ou jurídicos dentro da "
    "fundamentação se negam mutuamente, sem que o julgador resolva a antinomia.",
    "CIF-3": "Contradição Normativa: normas ou precedentes conflitantes são aplicados "
    "simultaneamente sem que o julgador solucione o conflito entre eles.",
    "CIL-1": "Non Sequitur: a conclusão não decorre logicamente das premissas apresentadas; "
    "há um salto argumentativo.",
    "CIL-2": "Contradição Condicional: o direito reconhecido no dispositivo está condicionado "
    "a um estado de fato que a própria fundamentação, em outro trecho, nega existir.",
    "CE-1": "Relatório vs. Fundamentação: fato narrado no relatório é negado ou alterado na "
    "fundamentação sem qualquer justificativa.",
    "CE-2": "Ementa vs. Dispositivo: a ementa enuncia tese ou resultado distinto do que consta "
    "no dispositivo do acórdão.",
}


class Decisao(BaseModel):
    """Saída da coleta (src/collect). `texto` = acórdão EMBARGADO (entrada do modelo)."""

    id: str
    processo: str
    relator: str
    data: str  # AAAA-MM-DD
    url: str
    texto: str
    texto_embargos: str | None = None  # acórdão dos embargos: fonte do rótulo
    rotulo_decisao: bool  # True = embargos acolhidos por contradição


class Segmentos(BaseModel):
    """Saída de src/segment.py. Segmento ausente = string vazia."""

    id: str
    ementa: str
    relatorio: str
    fundamentacao: str
    dispositivo: str


class Trecho(BaseModel):
    segmento: Segmento
    inicio: int
    fim: int

    @model_validator(mode="after")
    def _ordem(self):
        if not 0 <= self.inicio < self.fim:
            raise ValueError(f"offsets inválidos: {self.inicio}..{self.fim}")
        return self


class Proposicao(Trecho):
    pid: str
    texto: str


class Proposicoes(BaseModel):
    """Saída de argmining.proposicoes()."""

    id: str
    proposicoes: list[Proposicao]


class Par(BaseModel):
    par: tuple[str, str]  # pids
    relacao: str  # ex.: "premissa-conclusao", "conclusao-dispositivo", "todos"
    origem: Literal["am", "todos"]  # am = Mineração de Argumentos; todos = O(n²)


class Pares(BaseModel):
    """Saída de argmining.pares() ou de todos os pares possíveis (baseline / ablação B)."""

    id: str
    pares: list[Par]


class Predicao(BaseModel):
    a: Trecho
    b: Trecho
    contradicao: bool
    categoria: Categoria | None = None
    justificativa: str = ""


class Predicoes(BaseModel):
    """Saída de nli.py e baseline.py (mesmo formato, para comparar no evaluate)."""

    id: str
    sistema: str  # "am+llm" | "todos+llm" | "baseline" | "am+nli-local" ...
    modelo: str  # nome + versão do modelo, para reprodutibilidade
    predicoes: list[Predicao]


class ContradicaoGold(BaseModel):
    categoria: Categoria
    a: Trecho
    b: Trecho
    justificativa: str = ""


class Gold(BaseModel):
    """Anotação de referência (consenso dos anotadores). Lista vazia = sem contradição."""

    id: str
    contradicoes: list[ContradicaoGold]


M = TypeVar("M", bound=BaseModel)


def ler_jsonl(caminho: str | Path, modelo: type[M]) -> list[M]:
    linhas = Path(caminho).read_text(encoding="utf-8").splitlines()
    return [modelo.model_validate_json(linha) for linha in linhas if linha.strip()]


def escrever_jsonl(caminho: str | Path, itens: list[BaseModel]) -> None:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    Path(caminho).write_text(
        "".join(i.model_dump_json() + "\n" for i in itens), encoding="utf-8"
    )


def texto_do_trecho(segmentos: Segmentos, trecho: Trecho) -> str:
    return getattr(segmentos, trecho.segmento)[trecho.inicio : trecho.fim]
