"""Ida e volta com a anotação (planilha, Label Studio ou Doccano), Kappa de Cohen e consenso.

Planilha (o caminho mais simples, sem instalar nada):

    python -m src.annotation exportar-planilha data/segmentos.jsonl data/anotacao --lote piloto --n 50
    (cada anotador lê piloto_textos.html e preenche uma cópia de piloto_anotacao.csv)
    python -m src.annotation importar-planilha data/anotacao/piloto_ana.csv data/segmentos.jsonl \
        --saida data/gold_ana.jsonl
    python -m src.annotation desempate-planilha data/gold_ana.jsonl data/gold_bruno.jsonl \
        data/segmentos.jsonl data/anotacao --lote piloto_desempate

Ferramentas de anotação:

    python -m src.annotation exportar data/segmentos.jsonl data/anotacao/lote1.json   # .jsonl = Doccano
    python -m src.annotation config > labelstudio.xml                                  # interface do LS
    python -m src.annotation importar export.json --anotador 3 --saida data/gold_ana.jsonl
    python -m src.annotation kappa data/gold_ana.jsonl data/gold_bruno.jsonl
    python -m src.annotation divergencias data/gold_ana.jsonl data/gold_bruno.jsonl
    python -m src.annotation consenso data/gold_ana.jsonl data/gold_bruno.jsonl data/gold_carla.jsonl \
        --saida data/gold.jsonl

Cada decisão vira um texto único com os quatro segmentos, cada um abaixo de um título ("### EMENTA ###").
O anotador marca os dois trechos contraditórios e liga os dois com uma relação cujo rótulo é a categoria
(CDF-1, CIF-2...). Decisão anotada sem nenhuma relação = sem contradição. `importar` converte as posições
no texto único de volta para offsets dentro de cada segmento (`Trecho`).

- Label Studio: a justificativa vai no campo de texto do trecho A (perRegion). Só entram as tarefas que o
  anotador enviou; tarefas puladas ou não feitas ficam de fora. `anotador` é o id do usuário no Label
  Studio (é o que o export JSON traz em `completed_by`); o e-mail funciona quando o export traz o usuário.
- Doccano (projeto de sequence labeling com relações): não tem campo de justificativa, e todo exemplo
  exportado conta como anotado. Exporte marcando "only approved documents". O export de vários usuários
  vem num .zip com um <usuario>.jsonl por anotador; `anotador` escolhe o arquivo.

Kappa: unidade = decisão × categoria (presente/ausente), sobre as decisões que os dois anotaram.
Consenso: onde A e B concordam vale a anotação de A; nas divergências (decisão × categoria) vale a do
desempatador, que só precisa olhar a lista de `divergencias`.
"""

import argparse
import csv
import html
import io
import json
import logging
import random
import re
import unicodedata
import zipfile
from pathlib import Path

from src.contratos import CATEGORIAS, ContradicaoGold, Gold, Segmentos, Trecho, escrever_jsonl, ler_jsonl

log = logging.getLogger(__name__)

TITULOS = {
    "ementa": "EMENTA",
    "relatorio": "RELATÓRIO",
    "fundamentacao": "FUNDAMENTAÇÃO",
    "dispositivo": "DISPOSITIVO",
}
_TITULO = re.compile(r"^### (" + "|".join(TITULOS.values()) + r") ###\n", re.MULTILINE)
_SEGMENTO = {titulo: nome for nome, titulo in TITULOS.items()}

CONFIG_LABELSTUDIO = (
    "<View>\n  <Relations>\n"
    + "".join(f'    <Relation value="{c}"/>\n' for c in CATEGORIAS)
    + "  </Relations>\n"
    '  <Labels name="trecho" toName="texto">\n    <Label value="Trecho"/>\n  </Labels>\n'
    '  <Text name="texto" value="$texto"/>\n'
    '  <TextArea name="justificativa" toName="texto" perRegion="true" editable="true"\n'
    '            placeholder="Justificativa (preencha no trecho A)"/>\n'
    "</View>\n"
)


def montar_texto(segs: Segmentos) -> str:
    return "".join(f"### {titulo} ###\n{getattr(segs, nome)}\n\n" for nome, titulo in TITULOS.items())


def _intervalos(texto: str) -> dict[str, tuple[int, int]]:
    """Onde cada segmento está no texto único (inverso de `montar_texto`)."""
    titulos = list(_TITULO.finditer(texto))
    fins = [m.start() for m in titulos[1:]] + [len(texto)]
    return {
        _SEGMENTO[m.group(1)]: (m.end(), m.end() + len(texto[m.end() : fim].rstrip("\n")))
        for m, fim in zip(titulos, fins)
    }


def _trecho(texto: str, inicio: int, fim: int) -> Trecho:
    """Posição no texto único -> `Trecho` com offset dentro do segmento (sem espaços nas pontas)."""
    while inicio < fim and texto[inicio].isspace():
        inicio += 1
    while fim > inicio and texto[fim - 1].isspace():
        fim -= 1
    for nome, (ini_seg, fim_seg) in _intervalos(texto).items():
        if ini_seg <= inicio < fim <= fim_seg:
            return Trecho(segmento=nome, inicio=inicio - ini_seg, fim=fim - ini_seg)
    raise ValueError(f"trecho {inicio}..{fim} vazio ou fora de um único segmento")


def _contradicao(id, texto, categoria, a, b, justificativa=""):
    """Monta a contradição; se o rótulo ou os trechos forem inválidos, avisa e devolve None."""
    if categoria not in CATEGORIAS:
        log.warning("%s: relação com rótulo desconhecido %r ignorada", id, categoria)
        return None
    try:
        return ContradicaoGold(
            categoria=categoria, a=_trecho(texto, *a), b=_trecho(texto, *b), justificativa=justificativa
        )
    except ValueError as e:
        log.warning("%s: relação %s ignorada: %s", id, categoria, e)
        return None


def _deslocar(segs: Segmentos, trecho: Trecho) -> tuple[int, int]:
    base = _intervalos(montar_texto(segs))[trecho.segmento][0]
    return base + trecho.inicio, base + trecho.fim


def exportar_labelstudio(segmentos: list[Segmentos], caminho: str | Path, gold: list[Gold] = ()) -> None:
    """Tarefas para importar no Label Studio. `gold` (opcional) entra como anotação já feita."""
    gold_por_id = {g.id: g for g in gold}
    tarefas = []
    for segs in segmentos:
        tarefa = {"data": {"decisao": segs.id, "texto": montar_texto(segs)}}
        if segs.id in gold_por_id:
            tarefa["annotations"] = [{"result": _resultado_labelstudio(segs, gold_por_id[segs.id])}]
        tarefas.append(tarefa)
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    Path(caminho).write_text(json.dumps(tarefas, ensure_ascii=False, indent=1), encoding="utf-8")


def _resultado_labelstudio(segs: Segmentos, gold: Gold) -> list[dict]:
    texto, resultado = montar_texto(segs), []
    for i, c in enumerate(gold.contradicoes):
        ids = []
        for lado, trecho in (("a", c.a), ("b", c.b)):
            ini, fim = _deslocar(segs, trecho)
            ids.append(f"c{i}{lado}")
            valor = {"start": ini, "end": fim, "text": texto[ini:fim]}
            regiao = {"id": ids[-1], "to_name": "texto"}
            resultado.append(
                {**regiao, "from_name": "trecho", "type": "labels", "value": {**valor, "labels": ["Trecho"]}}
            )
            if lado == "a" and c.justificativa:
                resultado.append(
                    {
                        **regiao,
                        "from_name": "justificativa",
                        "type": "textarea",
                        "value": {**valor, "text": [c.justificativa]},
                    }
                )
        resultado.append({"type": "relation", "from_id": ids[0], "to_id": ids[1], "labels": [c.categoria]})
    return resultado


def _do_anotador(anotacao: dict, anotador: str) -> bool:
    autor = anotacao.get("completed_by")
    if isinstance(autor, dict):
        return anotador in (str(autor.get("id")), autor.get("email"))
    return anotador == str(autor)


def _importar_labelstudio(tarefas: list[dict], anotador: str | None) -> list[Gold]:
    golds = []
    for tarefa in tarefas:
        id, texto = tarefa["data"]["decisao"], tarefa["data"]["texto"]
        anotacoes = [a for a in tarefa.get("annotations", []) if not a.get("was_cancelled")]
        if anotador is not None:
            anotacoes = [a for a in anotacoes if _do_anotador(a, anotador)]
        if not anotacoes:
            continue
        if len(anotacoes) > 1:
            raise ValueError(f"{id}: {len(anotacoes)} anotações; informe `anotador`")
        regioes, justificativas, contradicoes = {}, {}, []
        for r in anotacoes[0]["result"]:
            if r["type"] == "labels":
                regioes[r["id"]] = (r["value"]["start"], r["value"]["end"])
            elif r["type"] == "textarea":
                justificativas[r["id"]] = " ".join(r["value"]["text"]).strip()
        for r in anotacoes[0]["result"]:
            if r["type"] == "relation":
                if not {r["from_id"], r["to_id"]} <= regioes.keys():
                    log.warning("%s: relação ligada a um trecho apagado ignorada", id)
                    continue
                for rotulo in r.get("labels") or [None]:
                    a, b = regioes[r["from_id"]], regioes[r["to_id"]]
                    j = justificativas.get(r["from_id"]) or justificativas.get(r["to_id"], "")
                    contradicoes.append(_contradicao(id, texto, rotulo, a, b, j))
        golds.append(Gold(id=id, contradicoes=[c for c in contradicoes if c]))
    return golds


def exportar_doccano(segmentos: list[Segmentos], caminho: str | Path, gold: list[Gold] = ()) -> None:
    """JSONL para um projeto de sequence labeling com relações. `gold` (opcional) vem pré-anotado."""
    gold_por_id = {g.id: g for g in gold}
    linhas = []
    for segs in segmentos:
        entidades, relacoes = [], []
        for c in gold_por_id.get(segs.id, Gold(id=segs.id, contradicoes=[])).contradicoes:
            for trecho in (c.a, c.b):
                ini, fim = _deslocar(segs, trecho)
                entidades.append(
                    {"id": len(entidades), "label": "TRECHO", "start_offset": ini, "end_offset": fim}
                )
            relacoes.append(
                {
                    "id": len(relacoes),
                    "from_id": len(entidades) - 2,
                    "to_id": len(entidades) - 1,
                    "type": c.categoria,
                }
            )
        linha = {"decisao": segs.id, "text": montar_texto(segs), "entities": entidades, "relations": relacoes}
        linhas.append(json.dumps(linha, ensure_ascii=False) + "\n")
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    Path(caminho).write_text("".join(linhas), encoding="utf-8")


def _importar_doccano(linhas: list[str]) -> list[Gold]:
    golds = []
    for linha in filter(str.strip, linhas):
        ex = json.loads(linha)
        id = ex.get("decisao") or ex.get("meta", {}).get("decisao")
        if not id:
            raise ValueError("exemplo do Doccano sem o campo 'decisao' (exporte com os metadados)")
        entidades = {e["id"]: (e["start_offset"], e["end_offset"]) for e in ex.get("entities", [])}
        contradicoes = []
        for r in ex.get("relations", []):
            if not {r["from_id"], r["to_id"]} <= entidades.keys():
                log.warning("%s: relação ligada a um trecho apagado ignorada", id)
                continue
            contradicoes.append(
                _contradicao(id, ex["text"], r["type"], entidades[r["from_id"]], entidades[r["to_id"]])
            )
        golds.append(Gold(id=id, contradicoes=[c for c in contradicoes if c]))
    return golds


def importar(caminho_export: str | Path, anotador: str | None = None) -> list[Gold]:
    """Export do Label Studio (.json) ou do Doccano (.jsonl, ou .zip com um arquivo por usuário)."""
    caminho = Path(caminho_export)
    if caminho.suffix == ".zip":
        with zipfile.ZipFile(caminho) as z:
            arquivos = [n for n in z.namelist() if n.endswith(".jsonl")]
            if not anotador and len(arquivos) > 1:
                raise ValueError(f"export com {len(arquivos)} anotadores; informe `anotador`")
            nome = f"{anotador}.jsonl" if anotador else arquivos[0]
            return _importar_doccano(z.read(nome).decode("utf-8").splitlines())
    if caminho.suffix == ".jsonl":
        return _importar_doccano(caminho.read_text(encoding="utf-8").splitlines())
    return _importar_labelstudio(json.loads(caminho.read_text(encoding="utf-8")), anotador)


def _cohen(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return float("nan") if pe == 1 else (po - pe) / (1 - pe)


def _categorias(golds: list[Gold]) -> dict[str, set[str]]:
    return {g.id: {c.categoria for c in g.contradicoes} for g in golds}


def _comuns(gold_a: list[Gold], gold_b: list[Gold]) -> list[str]:
    ids_b = {g.id for g in gold_b}
    comuns = [g.id for g in gold_a if g.id in ids_b]
    if not comuns:
        raise ValueError("nenhuma decisão anotada pelos dois")
    return comuns


def kappa(gold_a: list[Gold], gold_b: list[Gold]) -> float:
    """Kappa de Cohen sobre decisão × categoria (presente/ausente), nas decisões que os dois anotaram."""
    cats_a, cats_b = _categorias(gold_a), _categorias(gold_b)
    unidades = [(id, c) for id in _comuns(gold_a, gold_b) for c in CATEGORIAS]
    return _cohen([c in cats_a[id] for id, c in unidades], [c in cats_b[id] for id, c in unidades])


def divergencias(gold_a: list[Gold], gold_b: list[Gold]) -> list[tuple[str, str]]:
    """(decisão, categoria) em que só um dos dois marcou contradição: o que o desempatador revisa."""
    cats_a, cats_b = _categorias(gold_a), _categorias(gold_b)
    return [
        (id, c)
        for id in _comuns(gold_a, gold_b)
        for c in CATEGORIAS
        if (c in cats_a[id]) != (c in cats_b[id])
    ]


def consenso(gold_a: list[Gold], gold_b: list[Gold], desempate: list[Gold]) -> list[Gold]:
    divergentes = set(divergencias(gold_a, gold_b))
    de_a, de_c = {g.id: g for g in gold_a}, {g.id: g for g in desempate}
    pendentes = sorted({id for id, _ in divergentes} - de_c.keys())
    if pendentes:
        raise ValueError(f"divergências sem desempate: {', '.join(pendentes)}")
    final = []
    for id in _comuns(gold_a, gold_b):
        contradicoes = []
        for cat in CATEGORIAS:
            fonte = de_c[id] if (id, cat) in divergentes else de_a[id]
            contradicoes += [c for c in fonte.contradicoes if c.categoria == cat]
        final.append(Gold(id=id, contradicoes=contradicoes))
    return final


# ---------------------------------------------------------------- planilha

_ESTILO = (
    "body{font:16px/1.6 Georgia,serif;max-width:46rem;margin:2rem auto;padding:0 1rem}"
    "h2{border-top:2px solid #444;padding-top:1rem}"
    "h3{color:#555;font-size:1rem;text-transform:uppercase;letter-spacing:.05em}"
    ".id{font:13px monospace;color:#777}"
)
_INSTRUCAO = (
    "Para cada decisão, preencha a planilha seguindo o guia de anotação: copie daqui os dois trechos "
    "contraditórios (texto exato), escolha a categoria e justifique. Decisão sem contradição: escreva "
    "<b>não</b> na coluna <i>contradicao</i>. Material confidencial (LGPD): não compartilhe."
)
COLUNAS_PLANILHA = [
    "decisao",
    "numero",
    "contradicao",
    "categoria",
    "trecho_a",
    "trecho_b",
    "justificativa",
    "observacao",
]
_ASPAS = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", " ": " ", "–": "-", "—": "-"})
_ORDEM = ("ementa", "relatorio", "fundamentacao", "dispositivo")


def _sem_acento(texto: str) -> str:
    return (
        "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c))
        .strip()
        .lower()
    )


def exportar_planilha(
    segmentos: list[Segmentos], pasta: str | Path, lote: str, notas: dict[str, str] | None = None
) -> tuple[Path, Path]:
    """`<lote>_textos.html` (as decisões para ler) e `<lote>_anotacao.csv` (uma linha por decisão para
    preencher; uma contradição por linha). `notas` vai para a coluna "observacao" (ex.: o que desempatar)."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    partes = [
        (
            f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>Anotação: lote {html.escape(lote)}"
            f"</title><style>{_ESTILO}</style></head><body>"
        ),
        f"<h1>Lote {html.escape(lote)}: {len(segmentos)} decisões</h1>",
        f"<p>{_INSTRUCAO}</p>",
    ]
    for i, segs in enumerate(segmentos, 1):
        partes.append(f"<section id='d{i}'><h2>Decisão {i}</h2><p class='id'>{html.escape(segs.id)}</p>")
        for nome in _ORDEM:
            texto = getattr(segs, nome) or "(segmento não encontrado)"
            paragrafos = "".join(f"<p>{html.escape(p)}</p>" for p in texto.split("\n") if p.strip())
            partes.append(f"<h3>{TITULOS[nome]}</h3>{paragrafos}")
        partes.append("</section>")
    partes.append("</body></html>")
    caminho_html = pasta / f"{lote}_textos.html"
    caminho_html.write_text("".join(partes), encoding="utf-8")
    caminho_csv = pasta / f"{lote}_anotacao.csv"
    with caminho_csv.open("w", encoding="utf-8-sig", newline="") as f:  # BOM: o Excel reconhece os acentos
        w = csv.DictWriter(f, fieldnames=COLUNAS_PLANILHA, delimiter=";")
        w.writeheader()
        for i, segs in enumerate(segmentos, 1):
            w.writerow({**dict.fromkeys(COLUNAS_PLANILHA, ""), "decisao": segs.id, "numero": i,
                        "observacao": (notas or {}).get(segs.id, "")})  # fmt: skip
    return caminho_html, caminho_csv


def _ler_csv(caminho: Path) -> list[dict]:
    """Aceita o CSV como o Excel ou o Google Planilhas salvarem: ; ou , e UTF-8 ou Windows-1252."""
    bruto = caminho.read_bytes()
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = bruto.decode("cp1252")
    cabecalho = texto.split("\n", 1)[0]
    delimitador = ";" if cabecalho.count(";") >= cabecalho.count(",") else ","
    # StringIO, não splitlines: uma célula pode ter quebras de linha (trecho colado com mais de um parágrafo)
    linhas = list(csv.DictReader(io.StringIO(texto, newline=""), delimiter=delimitador))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in linha.items()} for linha in linhas]


def _categoria(valor: str) -> str | None:
    m = re.fullmatch(r"(CDF|CIF|CIL|CE)\s*-?\s*(\d)", valor.strip().upper())
    categoria = f"{m[1]}-{m[2]}" if m else None
    return categoria if categoria in CATEGORIAS else None


def localizar_trecho(segs: Segmentos, citado: str) -> Trecho | None | str:
    """Trecho onde o texto copiado aparece (espaços, aspas e travessões podem diferir). Devolve "ambíguo" se
    aparecer em mais de um lugar e None se não aparecer."""
    citado = citado.translate(_ASPAS).strip().strip('"').strip()
    palavras = citado.split()
    if not palavras:
        return None
    padrao = re.compile(r"\s+".join(re.escape(p) for p in palavras))
    achados = []
    for nome in _ORDEM:
        alvo = getattr(segs, nome).translate(
            _ASPAS
        )  # mesma quantidade de caracteres: offsets valem no original
        achados += [(nome, m.start(), m.end()) for m in padrao.finditer(alvo)]
    if len(achados) > 1:
        return "ambíguo"
    return Trecho(segmento=achados[0][0], inicio=achados[0][1], fim=achados[0][2]) if achados else None


def importar_planilha(caminho: str | Path, segmentos: list[Segmentos]) -> tuple[list[Gold], list[str]]:
    """Gold de um anotador e a lista de problemas a corrigir (linha da planilha + o que fazer). Decisão
    sem nenhuma linha preenchida fica de fora (não anotada)."""
    por_id = {s.id: s for s in segmentos}
    problemas: list[str] = []
    contradicoes: dict[str, list[ContradicaoGold]] = {}
    anotadas: list[str] = []
    for n, linha in enumerate(_ler_csv(Path(caminho)), 2):  # linha 1 = cabeçalho
        id, resposta = linha.get("decisao", ""), _sem_acento(linha.get("contradicao", ""))
        if not id or not resposta:
            continue
        if id not in por_id:
            problemas.append(f"linha {n}: decisão {id} não está no lote")
            continue
        if id not in anotadas:
            anotadas.append(id)
        if resposta in ("nao", "n", "sem contradicao"):
            continue
        if resposta not in ("sim", "s"):
            problemas.append(
                f"linha {n} ({id}): coluna contradicao deve ser 'sim' ou 'não', não {resposta!r}"
            )
            continue
        categoria = _categoria(linha.get("categoria", ""))
        if categoria is None:
            problemas.append(f"linha {n} ({id}): categoria {linha.get('categoria')!r} não é da taxonomia")
            continue
        trechos = []
        for lado in ("trecho_a", "trecho_b"):
            achado = localizar_trecho(por_id[id], linha.get(lado, ""))
            if achado is None:
                problemas.append(
                    f"linha {n} ({id}): {lado} não foi encontrado no texto; copie o trecho exato"
                )
            elif achado == "ambíguo":
                problemas.append(
                    f"linha {n} ({id}): {lado} aparece em mais de um lugar; copie um trecho maior"
                )
            else:
                trechos.append(achado)
        if len(trechos) == 2:
            contradicoes.setdefault(id, []).append(
                ContradicaoGold(
                    categoria=categoria,
                    a=trechos[0],
                    b=trechos[1],
                    justificativa=linha.get("justificativa", ""),
                )
            )
    return [Gold(id=id, contradicoes=contradicoes.get(id, [])) for id in anotadas], problemas


def notas_de_desempate(gold_a: list[Gold], gold_b: list[Gold]) -> dict[str, str]:
    """Por decisão, as categorias em que os dois anotadores divergiram (para orientar o desempatador)."""
    notas: dict[str, list[str]] = {}
    for id, categoria in divergencias(gold_a, gold_b):
        notas.setdefault(id, []).append(categoria)
    return {id: "Divergência em: " + ", ".join(cats) for id, cats in notas.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description="Anotação: exportar, importar, Kappa e consenso")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("exportar", help="segmentos -> tarefas (.json Label Studio, .jsonl Doccano)")
    p.add_argument("segmentos")
    p.add_argument("saida")
    sub.add_parser("config", help="imprime a interface de anotação do Label Studio")
    p = sub.add_parser("importar", help="export da ferramenta -> gold de um anotador")
    p.add_argument("export")
    p.add_argument("--anotador")
    p.add_argument("--saida", required=True)
    for nome in ("kappa", "divergencias"):
        p = sub.add_parser(nome)
        p.add_argument("gold_a")
        p.add_argument("gold_b")
    p = sub.add_parser("consenso")
    p.add_argument("gold_a")
    p.add_argument("gold_b")
    p.add_argument("desempate")
    p.add_argument("--saida", required=True)
    p = sub.add_parser("exportar-planilha", help="segmentos -> HTML para ler + CSV para preencher")
    p.add_argument("segmentos")
    p.add_argument("pasta")
    p.add_argument("--lote", required=True)
    p.add_argument("--n", type=int, help="sorteia n decisões (seed 42); sem --n, exporta todas")
    p.add_argument(
        "--excluir", nargs="*", default=[], help="gold(s) já anotados: essas decisões ficam de fora"
    )
    p = sub.add_parser("importar-planilha", help="CSV preenchido -> gold de um anotador")
    p.add_argument("planilha")
    p.add_argument("segmentos")
    p.add_argument("--saida", required=True)
    p = sub.add_parser("desempate-planilha", help="HTML + CSV só com as decisões em que A e B divergiram")
    p.add_argument("gold_a")
    p.add_argument("gold_b")
    p.add_argument("segmentos")
    p.add_argument("pasta")
    p.add_argument("--lote", required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    if args.cmd == "exportar":
        segs = ler_jsonl(args.segmentos, Segmentos)
        (exportar_doccano if args.saida.endswith(".jsonl") else exportar_labelstudio)(segs, args.saida)
        print(f"{len(segs)} decisões exportadas para {args.saida}")
    elif args.cmd == "exportar-planilha":
        segs = ler_jsonl(args.segmentos, Segmentos)
        feitos = {g.id for caminho in args.excluir for g in ler_jsonl(caminho, Gold)}
        segs = sorted((s for s in segs if s.id not in feitos), key=lambda s: s.id)
        if args.n:
            segs = random.Random(42).sample(segs, min(args.n, len(segs)))
        caminho_html, caminho_csv = exportar_planilha(segs, args.pasta, args.lote)
        print(f"{len(segs)} decisões -> {caminho_html} (ler) e {caminho_csv} (preencher)")
    elif args.cmd == "importar-planilha":
        golds, problemas = importar_planilha(args.planilha, ler_jsonl(args.segmentos, Segmentos))
        for problema in problemas:
            print(f"CORRIGIR {problema}")
        escrever_jsonl(args.saida, golds)
        total = sum(len(g.contradicoes) for g in golds)
        print(
            f"{len(golds)} decisões anotadas, {total} contradições -> {args.saida}; {len(problemas)} a corrigir"
        )
    elif args.cmd == "desempate-planilha":
        a, b = ler_jsonl(args.gold_a, Gold), ler_jsonl(args.gold_b, Gold)
        notas = notas_de_desempate(a, b)
        segs = [s for s in ler_jsonl(args.segmentos, Segmentos) if s.id in notas]
        caminho_html, caminho_csv = exportar_planilha(segs, args.pasta, args.lote, notas)
        print(f"{len(segs)} decisões com divergência -> {caminho_html} e {caminho_csv}")
    elif args.cmd == "config":
        print(CONFIG_LABELSTUDIO, end="")
    elif args.cmd == "importar":
        golds = importar(args.export, args.anotador)
        escrever_jsonl(args.saida, golds)
        print(f"{len(golds)} decisões anotadas, {sum(len(g.contradicoes) for g in golds)} contradições")
    else:
        a = ler_jsonl(args.gold_a, Gold)
        b = ler_jsonl(args.gold_b, Gold)
        if args.cmd == "kappa":
            print(f"Kappa = {kappa(a, b):.3f} ({len(_comuns(a, b))} decisões × {len(CATEGORIAS)} categorias)")
        elif args.cmd == "divergencias":
            for id, cat in divergencias(a, b):
                print(f"{id}\t{cat}")
        else:
            final = consenso(a, b, ler_jsonl(args.desempate, Gold))
            escrever_jsonl(args.saida, final)
            print(f"{len(final)} decisões no gold de consenso")


if __name__ == "__main__":
    main()
