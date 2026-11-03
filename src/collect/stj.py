"""Coleta do corpus no Portal de Dados Abertos do STJ (https://dadosabertos.web.stj.jus.br).

    python -m src.collect.stj --desde 2025-06 --ate 2025-06 --max 5 --saida data/teste.jsonl   # amostra
    python -m src.collect.stj --desde 2021-01 --ate 2025-12 --saida data/decisoes.jsonl

Fontes (conjuntos de dados oficiais do STJ, sem raspagem do portal de pesquisa):
- "Íntegras de decisões terminativas e acórdãos" (2008-2020 e, de 2021 em diante, do Diário da Justiça):
  um JSON de metadados e um ZIP com os textos completos por dia de publicação. Os metadados listam todos os
  acórdãos do dia, com o resultado (`teor`) e o relator. Só os textos necessários são lidos do ZIP (HTTP
  Range), então a coleta não baixa os ZIPs inteiros.
- "Espelhos de acórdãos" da Terceira e da Quarta Turma: dizem quem relatou acórdãos de Direito Privado em
  cada mês (o filtro temático) e, quando o embargado tem espelho, a classe exata dele.

Seleção entre os acórdãos de embargos de declaração publicados no período, de todas as
Seções do STJ (com --so-direito-privado, só os relatados por ministros da Terceira e da Quarta Turma). O
rótulo é a decisão do próprio tribunal sobre a contradição alegada (avaliação 1 do TCC):
- "reconhecida": embargos ACOLHIDOS cuja ementa afirma a contradição no julgado embargado. Positivo,
  `rotulo_decisao=True`. Até `--max`, em dias sorteados (seed) de todo o período.
- "rejeitada": embargos REJEITADOS em que a parte alegou contradição. O tribunal examinou a alegação e não
  viu contradição: negativo difícil, `rotulo_decisao=False`, na proporção `--proporcao-negativos` das
  reconhecidas (padrão 1:1).
- "negativa": embargos REJEITADOS sem alegação de contradição, `rotulo_decisao=False`. Não entram na
  avaliação 1: são a base em que src/sintetico.py insere contradições controladas (avaliação 2).
  `--base-sintetico` define quantas.
O critério de cada decisão vai para <saida>.criterios.jsonl.
- `Decisao.texto` é o ACÓRDÃO EMBARGADO (a entrada do modelo) e `texto_embargos` é o acórdão dos embargos
  (fonte do rótulo). O embargado é o último acórdão do mesmo processo publicado antes dos embargos.

As reconhecidas, as rejeitadas e as negativas são procuradas em dias sorteados
(seed 42) até completar as metas, para não concentrar o corpus num período. Casos sem embargado ou sem texto ficam em <saida>.log.jsonl com o motivo. Tudo o que é baixado
fica em cache em $DATA_DIR/stj/ (fora do git: os acórdãos têm nomes das partes).
"""

import argparse
import datetime as dt
import html
import http.client
import io
import json
import logging
import os
import random
import re
import time
import unicodedata
import urllib.request
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from src.contratos import Decisao, escrever_jsonl

log = logging.getLogger(__name__)

API = "https://dadosabertos.web.stj.jus.br/api/3/action/package_show?id="
PACOTES_INTEGRAS = [
    "integras-de-decisoes-terminativas-e-acordaos-2008-2020",
    "integras-de-decisoes-terminativas-e-acordaos-do-diario-da-justica",
]
TURMAS = {"terceira": "espelhos-de-acordaos-terceira-turma", "quarta": "espelhos-de-acordaos-quarta-turma"}
URL_PROCESSO = "https://processo.stj.jus.br/processo/pesquisa/?tipoPesquisa=tipoPesquisaNumeroRegistro&termo="


# ---------------------------------------------------------------- regras (funções puras, testadas)

_ACOLHE = re.compile(
    r"\bacolh(?:er|eu|ê-los|e-los|endo|imento)\b[^.]{0,60}embargos|\bembargos[^.]{0,80}\bacolhid",
    re.IGNORECASE,
)
_REJEITA = re.compile(r"\brejeit(?:ar|ou|á-los|a-los|ados|ando)\b", re.IGNORECASE)
_NAO_CONHECE = re.compile(r"\bn[ãa]o\s+conhec", re.IGNORECASE)

# contradição apontada no próprio julgado ("contradição configurada", "incorreu em contradição")...
_CONTRADICAO_SIM = re.compile(
    r"contradi[çc][ãa]o\w*[\s.,:;-]{1,4}(?:\w+\s){0,3}?(?:configurad|verificad|caracterizad|reconhecid|existent|evidenciad"
    r"|constatad|ocorr[eê]ncia|exist[eê]ncia|presen[çt]|sanad|corrigid|eliminad)"
    r"|(?:configurad|verificad|caracterizad|reconhecid|constatad|existência d[ae]|ocorrência d[ae]|incorr\w+ em"
    r"|padece[rm]? d[ae]|eivad\w+ d[ae]|houve|há|existe|apresenta|verifica-se|constata-se|reconhece-se"
    r"|evidencia-se)\s+(?:\w+\s){0,3}?contradi[çc]"
    r"|acolhid\w*[^.;]{0,60}\b(?:sanar|corrigir|eliminar|afastar|suprimir)\s+(?:\w+\s){0,2}?contradi",
    re.IGNORECASE,
)
# ...mas não a frase-padrão que só enumera os vícios do art. 1.022 nem a contradição negada
_CONTRADICAO_NAO = re.compile(
    r"(?:n[ãa]o\s+(?:\w+\s){0,3}?|inexist[eê]ncia\s+d[ae]\s+|inexiste[m]?\s+(?:\w+\s){0,2}?|aus[eê]ncia\s+d[ae]\s+|sem\s+)contradi"
    r"|contradi[çc][ãa]o\w*[\s.,:;-]{1,4}(?:\w+\s){0,2}?(?:inexistent|n[ãa]o\s+(?:configurad|verificad|caracterizad|demonstrad))"
    r"|omiss[ãa]o,\s*contradi|obscuridade,\s*contradi|contradi[çc][ãa]o,\s*(?:omiss|obscur)|contradi[çc][ãa]o\s+ou\s+(?:omiss|obscur)",
    re.IGNORECASE,
)


def resultado_embargos(decisao: str) -> str | None:
    """'acolhidos', 'rejeitados' ou None (não conhecidos, misto ou não identificado), pela parte dispositiva."""
    if _NAO_CONHECE.search(decisao):
        return None
    acolhe, rejeita = bool(_ACOLHE.search(decisao)), bool(_REJEITA.search(decisao))
    if acolhe and not rejeita:
        return "acolhidos"
    if rejeita and not acolhe:
        return "rejeitados"
    return None


# frase-padrão sobre o cabimento dos embargos ("destinam-se a suprir omissão, afastar obscuridade, eliminar
# contradição eventualmente existentes..."): enumera vícios ou fala em tese, sem afirmar nada do caso
_VICIO = re.compile(r"omiss|obscur|erro\s+material", re.IGNORECASE)
_GENERICA = re.compile(
    r"destina|eventua|t[êe]m\s+(?:como|por)\s+objetivo|tem\s+por\s+objetivo|prestam-se|servem\s+para|cab[íi]ve|cabem",
    re.IGNORECASE,
)
# frase que só relata a alegação da parte ou a questão a decidir (ementas no formato do CNJ têm "Questão em
# discussão: saber se há omissão ou contradição..."), sem afirmar que a contradição existe
_HIPOTESE = re.compile(
    r"\bsaber\s+se\b|\bse\s+(?:h[áa]|houve|existe)\b|\balega|\bsustent|\bargument|\bsuscit|\baduz|\binsurg"
    r"|\bquest[ãa]o\s+em\s+discuss",
    re.IGNORECASE,
)
# só "contradição/contradições": "contraditório" quase sempre é o princípio (contraditório e ampla defesa)
_ALEGACAO = re.compile(
    r"\b(?:alega|aponta|sustenta|suscita|aduz|argumenta|defende|afirma)\w*\b[^.;]{0,120}contradi[çc]"
    r"|contradi[çc][^.;]{0,80}\b(?:alegad|apontad|suscitad)",
    re.IGNORECASE,
)
_CABECALHO = re.compile(
    r"contradi[çc][ãa]o(?:\s+[^\s.]+){0,5}\.\s*(?:ocorr|exist|configur|verific|caracteriz|reconhec|constat)",
    re.IGNORECASE,
)


def _generica(frase: str) -> bool:
    vicios = {m.group().lower()[:5] for m in _VICIO.finditer(frase)}
    return len(vicios) >= 2 or bool(_GENERICA.search(frase))


def aponta_contradicao(*textos: str) -> bool:
    """Alguma frase afirma que o julgado embargado tem contradição (e não só cita o art. 1.022)."""
    for texto in textos:
        texto = texto or ""
        for frase in re.split(r"(?<=[.;])\s+|\n", texto):
            if (
                "contradi" in frase.lower()
                and _CONTRADICAO_SIM.search(frase)
                and not _CONTRADICAO_NAO.search(frase)
                and not _generica(frase)
                and not _HIPOTESE.search(frase)
            ):
                return True
        # cabeçalho da ementa em maiúsculas: "APONTADA CONTRADIÇÃO NO ACÓRDÃO. OCORRÊNCIA." fica dividido em
        # duas frases; o trecho desde o ponto anterior não pode ser a enumeração dos vícios nem negar
        for m in _CABECALHO.finditer(texto):
            trecho = texto[texto.rfind(".", 0, m.start()) + 1 : m.end()]
            # "OMISSÃO. OBSCURIDADE. CONTRADIÇÃO. EXISTÊNCIA PARCIAL.": a lista de vícios não diz qual existe
            anterior = re.split(r"\.\s*", texto[: m.start()].rstrip(". "))[-1]
            enumeracao = _VICIO.fullmatch(anterior.strip()) or re.fullmatch(
                r"\s*(?:omiss|obscur)\w*\s*", anterior, re.IGNORECASE
            )
            if not (_generica(trecho) or enumeracao or _CONTRADICAO_NAO.search(trecho)):
                return True
    return False


def alega_contradicao(texto: str) -> bool:
    """A parte alega contradição no julgado embargado (procedente ou não). Não conta "o embargante não aponta
    omissões, contradições..." nem a alegação genérica de todos os vícios do art. 1.022."""
    for frase in re.split(r"(?<=[.;])\s+|\n", texto or ""):
        m = _ALEGACAO.search(frase)
        if m and not re.search(r"\bn[ãa]o\s+(?:\w+\s){0,2}$", frase[: m.start()]) and not _generica(frase):
            return True
    return False


def criterio_dos_embargos(texto: str) -> str | None:
    """Critério de seleção pelo texto do acórdão dos embargos:
    - "reconhecida": embargos acolhidos e a ementa afirma a contradição (o tribunal viu contradição);
    - "rejeitada": embargos rejeitados em que a parte alegou contradição (o tribunal não a viu);
    - "negativa": embargos rejeitados sem alegação de contradição (base das contradições sintéticas);
    - None: nenhum dos casos acima (ex.: acolhidos só por omissão, resultado misto)."""
    dispositivo, ementa = partes_do_acordao(texto)
    resultado = resultado_embargos(dispositivo)
    if resultado == "acolhidos" and aponta_contradicao(ementa):
        return "reconhecida"
    if resultado == "rejeitados":
        return "rejeitada" if alega_contradicao(texto) else "negativa"
    return None


def classe_embargada(sigla: str) -> str | None:
    """'EDcl no AgInt no AREsp' -> 'AgInt no AREsp'; None se não for embargos de declaração."""
    m = re.match(r"\s*EDcl\s+n[oa]s?\s+(.+)", sigla or "")
    return m.group(1).strip() if m else None


def data_publicacao(campo: str) -> dt.date | None:
    """'DJEN       DATA:19/08/2026' -> date(2026, 8, 19). Com várias datas, vale a primeira."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", campo or "")
    return dt.date(int(m[3]), int(m[2]), int(m[1])) if m else None


def limpar_texto(bruto: str) -> str:
    """Texto do ZIP das íntegras: quebras em <br>, entidades HTML."""
    texto = re.sub(r"<br\s*/?>", "\n", bruto, flags=re.IGNORECASE)
    texto = re.sub(r"</?(?:p|div)[^>]*>", "\n", texto, flags=re.IGNORECASE)
    return html.unescape(re.sub(r"<[^>]+>", "", texto)).strip()


@dataclass(frozen=True)
class Espelho:
    id: str
    registro: str
    classe: str  # ex.: "EDcl no AgInt no AREsp"
    processo: str  # ex.: "EDcl no AgInt no AREsp 3004382"
    relator: str
    orgao: str
    julgamento: dt.date | None
    publicacao: dt.date | None
    ementa: str
    decisao: str
    complementares: str


def espelho(bruto: dict) -> Espelho | None:
    def campo(nome):
        v = bruto.get(nome)
        return "" if v is None or str(v) == "None" else str(v)

    if not campo("numeroRegistro") or not campo("siglaClasse"):
        return None
    julgamento = campo("dataDecisao")
    return Espelho(
        id=campo("id"),
        registro=campo("numeroRegistro"),
        classe=campo("siglaClasse").strip(),
        processo=f"{campo('siglaClasse').strip()} {campo('numeroProcesso')}".strip(),
        relator=campo("ministroRelator"),
        orgao=campo("nomeOrgaoJulgador"),
        julgamento=dt.date(int(julgamento[:4]), int(julgamento[4:6]), int(julgamento[6:8]))
        if re.fullmatch(r"\d{8}", julgamento)
        else None,
        publicacao=data_publicacao(campo("dataPublicacao")),
        ementa=campo("ementa"),
        decisao=campo("decisao"),
        complementares=campo("informacoesComplementares"),
    )


def achar_embargado(ed: Espelho, por_registro: dict[str, list[Espelho]]) -> Espelho | None:
    """O último acórdão do mesmo registro, com a classe embargada, publicado antes dos embargos."""
    alvo = classe_embargada(ed.classe)
    candidatos = [
        e
        for e in por_registro.get(ed.registro, [])
        if e.classe == alvo and e.publicacao and ed.publicacao and e.publicacao < ed.publicacao
    ]
    return max(candidatos, key=lambda e: e.publicacao, default=None)


# ---------------------------------------------------------------- acesso ao portal (rede + cache)


class ArquivoRemoto:
    """Arquivo HTTP lido por intervalos (Range), para o zipfile ler só o diretório e os membros pedidos."""

    BLOCO = 256 * 1024

    def __init__(self, url: str, obter_intervalo, tamanho: int):
        self.url, self._obter, self.tamanho, self.pos = url, obter_intervalo, tamanho, 0
        self._blocos: dict[int, bytes] = {}

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, deslocamento, origem=0):
        self.pos = {0: deslocamento, 1: self.pos + deslocamento, 2: self.tamanho + deslocamento}[origem]
        return self.pos

    def read(self, n=-1):
        fim = self.tamanho if n is None or n < 0 else min(self.tamanho, self.pos + n)
        partes = []
        while self.pos < fim:
            b = self.pos // self.BLOCO
            if b not in self._blocos:
                inicio = b * self.BLOCO
                self._blocos[b] = self._obter(self.url, inicio, min(self.tamanho, inicio + self.BLOCO) - 1)
            bloco = self._blocos[b]
            ini = self.pos - b * self.BLOCO
            parte = bloco[ini : ini + (fim - self.pos)]
            if not parte:
                break
            partes.append(parte)
            self.pos += len(parte)
        return b"".join(partes)


TENTATIVAS = 8  # ~20 min de espera somada antes de desistir


class Portal:
    """Downloads com cache em disco e pausa entre requisições."""

    def __init__(self, cache: Path, pausa: float = 1.0):
        self.cache, self.pausa = cache, pausa
        self._ultima = 0.0
        self._zips: dict[str, zipfile.ZipFile] = {}

    def _requisitar(self, url: str, cabecalhos: dict | None = None, metodo: str = "GET"):
        espera = self.pausa - (time.monotonic() - self._ultima)
        if espera > 0:
            time.sleep(espera)
        self._ultima = time.monotonic()
        req = urllib.request.Request(
            url, headers={"User-Agent": "tcc-contradicoes-judiciais", **(cabecalhos or {})}, method=metodo
        )
        for tentativa in range(TENTATIVAS):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.headers, r.read()
            # OSError inclui timeout (o portal às vezes fica minutos sem responder); HTTPException cobre a
            # conexão que cai no meio da resposta (IncompleteRead), que derrubou a coleta em 29/10.
            except (OSError, http.client.HTTPException):
                if tentativa == TENTATIVAS - 1:
                    raise
                time.sleep(min(15 * 2**tentativa, 300))

    def baixar(self, url: str, nome: str) -> bytes:
        destino = self.cache / nome
        if not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            _, dados = self._requisitar(url)
            destino.write_bytes(dados)
        return destino.read_bytes()

    def recursos(self, pacote: str) -> list[dict]:
        """Lista de arquivos do conjunto de dados (renovada uma vez por dia)."""
        destino = self.cache / "pacotes" / f"{pacote}.json"
        if destino.exists() and time.time() - destino.stat().st_mtime > 86400:
            destino.unlink()
        return json.loads(self.baixar(API + pacote, f"pacotes/{pacote}.json"))["result"]["resources"]

    def _intervalo(self, url: str, inicio: int, fim: int) -> bytes:
        return self._requisitar(url, {"Range": f"bytes={inicio}-{fim}"})[1]

    def membro_zip(self, url: str, nome: str, cache: str) -> bytes | None:
        destino = self.cache / cache
        if destino.exists():
            return destino.read_bytes()
        if url not in self._zips:
            cabecalhos, _ = self._requisitar(url, metodo="HEAD")
            self._zips[url] = zipfile.ZipFile(
                ArquivoRemoto(url, self._intervalo, int(cabecalhos["Content-Length"]))
            )
        try:
            dados = self._zips[url].read(nome)
        except KeyError:
            return None
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados)
        return dados


# ---------------------------------------------------------------- coleta


def _mes(texto: str) -> dt.date:
    ano, mes = map(int, texto.split("-"))
    return dt.date(ano, mes, 1)


def _somar_meses(d: dt.date, meses: int) -> dt.date:
    total = d.year * 12 + d.month - 1 + meses
    return dt.date(total // 12, total % 12 + 1, 1)


def normalizar_nome(nome: str) -> str:
    """'Ricardo Villas Bôas Cueva (Relator)' -> 'RICARDO VILLAS BOAS CUEVA'."""
    nome = unicodedata.normalize("NFD", re.sub(r"\(.*?\)", "", nome or ""))
    return " ".join("".join(c for c in nome if not unicodedata.combining(c)).upper().split())


def carregar_espelhos(portal: Portal, turmas: list[str], de: dt.date, ate: dt.date) -> list[Espelho]:
    """Espelhos publicados em [de, ate]. Cada arquivo é uma extração (AAAAMMDD) com o que entrou na base
    desde a anterior; o ZIP mais antigo traz o histórico inteiro."""
    espelhos, vistos = [], set()
    for turma in turmas:
        for r in portal.recursos(TURMAS[turma]):
            m = re.search(r"(\d{8})\.(json|zip)$", r["url"])
            if not m:
                continue
            extracao = dt.datetime.strptime(m[1], "%Y%m%d").date()
            # uma extração anterior a `de` não tem publicações da janela; as de [de, ate] podem entrar na base
            # alguns meses depois da publicação (as que entrarem mais tarde que isso ficam de fora)
            if extracao < de or extracao > _somar_meses(ate, 4):
                continue
            dados = portal.baixar(r["url"], f"espelhos/{turma}/{m[1]}.{m[2]}")
            if m[2] == "zip":
                with zipfile.ZipFile(io.BytesIO(dados)) as z:
                    brutos = [x for n in z.namelist() if n.endswith(".json") for x in json.loads(z.read(n))]
            else:
                brutos = json.loads(dados)
            for b in brutos:
                e = espelho(b)
                if e and e.id not in vistos and e.publicacao and de <= e.publicacao <= ate:
                    vistos.add(e.id)
                    espelhos.append(e)
    return espelhos


def relatores_por_mes(espelhos: list[Espelho], minimo: int = 3) -> dict[tuple[int, int], set[str]]:
    """Quem relatou ao menos `minimo` acórdãos nas Turmas de Direito Privado em cada mês."""
    contagem: dict[tuple[int, int], Counter] = {}
    for e in espelhos:
        contagem.setdefault((e.publicacao.year, e.publicacao.month), Counter())[
            normalizar_nome(e.relator)
        ] += 1
    return {mes: {r for r, n in c.items() if n >= minimo} for mes, c in contagem.items()}


def do_direito_privado(relator: str, dia: dt.date, relatores: dict) -> bool:
    """O relator estava nas Turmas de Direito Privado no mês do julgado ou num mês vizinho."""
    nome = normalizar_nome(relator)
    vizinhos = (_somar_meses(dia.replace(day=1), k) for k in (-1, 0, 1))
    return any(nome in relatores.get((m.year, m.month), set()) for m in vizinhos)


@dataclass(frozen=True)
class Documento:
    """Uma linha dos metadados das íntegras."""

    seq: int
    registro: str
    dia: dt.date
    processo: str  # ex.: "AREsp 2630547"
    recurso: str  # ex.: "EDcl", "AgInt" ou "" (o próprio processo)
    relator: str
    teor: str
    acordao: bool

    @property
    def embargos(self) -> bool:
        # 2021 e 2024+ abreviam ("EDcl"); 2022 e 2023 escrevem por extenso ("EMBARGOS DE DECLARAÇÃO")
        return self.recurso.startswith("EDcl") or self.recurso.upper().startswith("EMBARGOS DE DECLARA")

    @property
    def nome(self) -> str:
        """Classe e número como no STJ: 'AgInt no AREsp 2630547'."""
        return f"{self.recurso} no {self.processo}" if self.recurso else self.processo


def documento(bruto: dict, dia: dt.date) -> Documento | None:
    """Uma linha dos metadados. Os nomes dos campos variam entre os anos (SeqDocumento/seqDocumento,
    NM_MINISTRO/ministro), então a busca ignora maiúsculas. Linha sem identificador vira None."""
    campos = {k.lower(): v for k, v in bruto.items()}
    seq = campos.get("seqdocumento")
    if seq in (None, ""):
        return None
    return Documento(
        seq=int(seq),
        registro=str(campos.get("numeroregistro") or ""),
        dia=dia,
        processo=(campos.get("processo") or "").strip(),
        recurso=(campos.get("recurso") or "").strip(),
        relator=campos.get("nm_ministro") or campos.get("ministro") or "",
        teor=(campos.get("teor") or "").strip(),
        # "ACÓRDÃO" na maioria dos anos, "ACORDAO" sem acento em 2021
        acordao="ACORD" in normalizar_nome(campos.get("tipodocumento") or ""),
    )


def partes_do_acordao(texto: str) -> tuple[str, str]:
    """(parte dispositiva do acórdão, ementa) do texto das íntegras: o que vem antes de EMENTA e o que vai
    de EMENTA até RELATÓRIO."""
    m = re.search(r"^\s*E\s?M\s?E\s?N\s?T\s?A\b", texto, re.MULTILINE)
    if not m:
        return texto[:1500], texto[:3000]
    fim = re.search(r"^\s*R\s?E\s?L\s?A\s?T\s?[ÓO]\s?R\s?I\s?O\b", texto[m.end() :], re.MULTILINE)
    return texto[: m.start()], texto[m.end() : m.end() + (fim.start() if fim else 4000)]


class Integras:
    def __init__(self, portal: Portal):
        self.portal = portal
        self._arquivos: dict[str, dict[str, str]] | None = None
        self._docs: dict[dt.date, list[Documento]] = {}

    def _por_dia(self) -> dict[str, dict[str, str]]:
        if self._arquivos is None:
            self._arquivos = {}
            for pacote in PACOTES_INTEGRAS:
                for r in self.portal.recursos(pacote):
                    # metadadosAAAAMMDD.json; textosAAAAMMDD.zip (ou só AAAAMMDD.zip até 2020)
                    m = re.search(r"/(metadados|textos)?(\d{8})\.(json|zip)$", r["url"])
                    if m and (m[3] == "zip" or m[1] == "metadados"):
                        tipo = "metadados" if m[3] == "json" else "textos"
                        self._arquivos.setdefault(m[2], {})[tipo] = r["url"]
        return self._arquivos

    def dias(self, de: dt.date, ate: dt.date) -> list[dt.date]:
        """Dias de publicação com metadados e textos em [de, ate]."""
        dias = (dt.datetime.strptime(d, "%Y%m%d").date() for d, a in self._por_dia().items() if len(a) == 2)
        return sorted(d for d in dias if de <= d <= ate)

    def documentos(self, dia: dt.date) -> list[Documento]:
        if dia not in self._docs:
            chave = dia.strftime("%Y%m%d")
            arquivos = self._por_dia().get(chave, {})
            brutos = (
                json.loads(self.portal.baixar(arquivos["metadados"], f"integras/metadados{chave}.json"))
                if "metadados" in arquivos
                else []
            )
            self._docs[dia] = [d for d in (documento(b, dia) for b in brutos) if d and d.acordao]
        return self._docs[dia]

    def texto(self, doc: Documento) -> str | None:
        chave = doc.dia.strftime("%Y%m%d")
        url = self._por_dia().get(chave, {}).get("textos")
        if not url:
            return None
        # os ZIPs de 2022 e 2023 guardam os textos numa subpasta com a data
        for nome in (f"{doc.seq}.txt", f"{chave}/{doc.seq}.txt"):
            bruto = self.portal.membro_zip(url, nome, f"integras/textos/{doc.seq}.txt")
            if bruto:
                return limpar_texto(bruto.decode("utf-8", "replace"))
        return None

    def anterior(self, registro: str, antes_de: dt.date, limite: dt.date) -> Documento | None:
        """O último acórdão do registro publicado antes de `antes_de` (até `limite`)."""
        for dia in reversed(self.dias(limite, antes_de - dt.timedelta(days=1))):
            achados = [d for d in self.documentos(dia) if d.registro == registro]
            if achados:
                return max(achados, key=lambda d: d.seq)
        return None


def coletar(args, portal: Portal) -> tuple[list[Decisao], list[dict]]:
    desde, ate = _mes(args.desde), _somar_meses(_mes(args.ate), 1) - dt.timedelta(days=1)
    janela = _somar_meses(desde, -args.meses_embargado)
    espelhos = carregar_espelhos(portal, args.turmas, janela, _somar_meses(ate, 1))
    relatores = relatores_por_mes(espelhos)
    espelhos_por_registro: dict[str, list[Espelho]] = {}
    for e in espelhos:
        espelhos_por_registro.setdefault(e.registro, []).append(e)
    integras = Integras(portal)
    dias = integras.dias(desde, ate)

    # metas: todas as reconhecidas do período (até --max); as rejeitadas, na proporção das reconhecidas
    # encontradas (definida depois da etapa 1); as negativas, --base-sintetico
    metas = {"reconhecida": args.max, "rejeitada": 0, "negativa": args.base_sintetico}
    decisoes: list[Decisao] = []
    criterios: dict[str, str] = {}
    falhas: list[dict] = []
    usados: set[int] = set()

    def falta(criterio: str) -> bool:
        return sum(c == criterio for c in criterios.values()) < metas[criterio]

    def embargado_de(ed: Documento) -> tuple[Documento | None, str]:
        """Pelo espelho dos embargos, quando há (classe exata); senão, o último acórdão anterior."""
        esp = next((e for e in espelhos_por_registro.get(ed.registro, []) if e.publicacao == ed.dia), None)
        if esp and (alvo := achar_embargado(esp, espelhos_por_registro)):
            doc = next((d for d in integras.documentos(alvo.publicacao) if d.registro == ed.registro), None)
            if doc:
                return doc, alvo.processo
        doc = integras.anterior(ed.registro, ed.dia, ed.dia - dt.timedelta(days=31 * args.meses_embargado))
        return doc, doc.nome if doc else ""

    def incluir(ed: Documento, texto_embargos: str, criterio: str) -> None:
        embargado, processo = embargado_de(ed)
        if embargado is None:
            falhas.append(
                {"processo": ed.nome, "registro": ed.registro, "motivo": "embargado não encontrado"}
            )
            return
        texto = integras.texto(embargado)
        if texto is None:
            motivo = f"embargado sem texto em {embargado.dia}"
            falhas.append({"processo": processo, "registro": ed.registro, "motivo": motivo})
            return
        decisao = Decisao(
            id=f"STJ-{ed.registro}-{embargado.seq}",
            processo=processo,
            relator=embargado.relator,
            data=embargado.dia.isoformat(),
            url=URL_PROCESSO + ed.registro,
            texto=texto,
            texto_embargos=texto_embargos,
            rotulo_decisao=criterio == "reconhecida",
        )
        if decisao.id not in criterios:
            decisoes.append(decisao)
            criterios[decisao.id] = criterio

    def candidatos(dia: dt.date, teores: tuple[str, ...]):
        for ed in integras.documentos(dia):
            novo = ed.embargos and ed.teor in teores and ed.seq not in usados
            if novo and (not args.so_direito_privado or do_direito_privado(ed.relator, dia, relatores)):
                yield ed

    def texto_dos_embargos(ed: Documento) -> str | None:
        texto = integras.texto(ed)
        if texto is None:
            falhas.append(
                {"processo": ed.nome, "registro": ed.registro, "motivo": f"embargos sem texto em {ed.dia}"}
            )
        return texto

    # 1) embargos acolhidos por contradição, em dias sorteados (seed): com --max, a amostra cobre o período
    # inteiro em vez de parar nos primeiros meses; sem limite, todos os dias são visitados
    if metas["reconhecida"]:
        dias_sorteados = list(dias)
        random.Random(args.seed).shuffle(dias_sorteados)
        for dia in dias_sorteados:
            if not falta("reconhecida"):
                break
            for ed in candidatos(dia, ("Admitindo Embargo",)):
                texto = texto_dos_embargos(ed)
                if texto and criterio_dos_embargos(texto) == "reconhecida" and falta("reconhecida"):
                    usados.add(ed.seq)
                    incluir(ed, texto, "reconhecida")

    # 2) rejeitadas (alegação de contradição que o tribunal não acolheu) e negativas, em dias sorteados
    metas["rejeitada"] = round(args.proporcao_negativos * sum(c == "reconhecida" for c in criterios.values()))
    sorteados = list(dias)
    random.Random(args.seed).shuffle(sorteados)
    for dia in sorteados:
        if not (falta("rejeitada") or falta("negativa")):
            break
        for ed in candidatos(dia, ("Negando",)):
            if not (falta("rejeitada") or falta("negativa")):
                break
            texto = texto_dos_embargos(ed)
            criterio = criterio_dos_embargos(texto) if texto else None
            if criterio in ("rejeitada", "negativa") and falta(criterio):
                usados.add(ed.seq)
                incluir(ed, texto, criterio)
    return decisoes, falhas, criterios


def main(argv=None) -> None:
    padrao = Path(os.environ.get("DATA_DIR", "data"))
    ap = argparse.ArgumentParser(description="Coleta acórdãos embargados no Portal de Dados Abertos do STJ")
    ap.add_argument("--saida", default=str(padrao / "decisoes.jsonl"))
    ap.add_argument("--desde", default="2021-01", help="mês inicial da publicação dos embargos (AAAA-MM)")
    ap.add_argument("--ate", default="2025-12", help="mês final da publicação dos embargos (AAAA-MM)")
    ap.add_argument("--turmas", nargs="+", choices=sorted(TURMAS), default=["terceira", "quarta"])
    ap.add_argument("--max", type=int, default=1000, help="máximo de contradições reconhecidas")
    ap.add_argument(
        "--proporcao-negativos", type=float, default=1.0, help="rejeitadas por reconhecida (padrão 1:1)"
    )
    ap.add_argument(
        "--base-sintetico", type=int, default=500, help="negativas para as contradições sintéticas"
    )
    ap.add_argument(
        "--so-direito-privado", action="store_true", help="só ministros da Terceira e da Quarta Turma"
    )
    ap.add_argument(
        "--meses-embargado", type=int, default=12, help="até quantos meses antes buscar o embargado"
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre requisições ao portal")
    ap.add_argument("--cache", default=str(padrao / "stj"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    decisoes, falhas, criterios = coletar(args, Portal(Path(args.cache), args.pausa))
    escrever_jsonl(args.saida, decisoes)
    linhas = "".join(
        json.dumps({"id": i, "criterio": c}, ensure_ascii=False) + "\n" for i, c in criterios.items()
    )
    Path(args.saida + ".criterios.jsonl").write_text(linhas, encoding="utf-8")
    Path(args.saida + ".log.jsonl").write_text(
        "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in falhas), encoding="utf-8"
    )
    contagem = Counter(criterios.values())
    tentativas = len(decisoes) + len(falhas)
    print(
        f"{len(decisoes)} decisões -> {args.saida}: {contagem['reconhecida']} com contradição reconhecida, "
        f"{contagem['rejeitada']} com contradição alegada e rejeitada, {contagem['negativa']} negativas "
        f"(critério de cada uma em {args.saida}.criterios.jsonl)\n"
        f"{len(falhas)} casos sem embargado ou sem texto -> {args.saida}.log.jsonl"
        + (f" ({len(decisoes) / tentativas:.0%} dos casos tentados com os dois textos)" if tentativas else "")
    )


if __name__ == "__main__":
    main()
