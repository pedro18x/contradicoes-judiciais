"""Gateway único de LLM: toda chamada a LLM do projeto passa por aqui.

    from src import llm
    texto = llm.complete("Resuma o trecho: ...", system="Você é um assistente jurídico.")
    dados = llm.complete_json("Liste as proposições em JSON: ...", etapa="ma")

- Provedor: API da Anthropic (Claude). Chave em `LLM_API_KEY` (ou `ANTHROPIC_API_KEY`); se a chave não
  for de um workspace específico, informe o workspace em `LLM_WORKSPACE_ID` (wrkspc_...).
- Cache em disco (`LLM_CACHE_DIR`, padrão `.cache/llm`): chamada idêntica (modelo + esforço + system +
  prompt) não vai à rede. Rerodar experimentos não gasta tokens, e a demo funciona offline com o cache cheio.
- Modelo por etapa: `LLM_MODEL_MA` (proposições e pares) e `LLM_MODEL_NLI`, caindo em `LLM_MODEL` quando
  não definidos (ou o parâmetro `model`). Modelo e etapa ficam gravados em cada entrada do cache.
- Teto de gasto `LLM_TETO_USD`: antes de cada chamada à rede, se o gasto registrado no cache + o pior caso
  da chamada (`PRECOS`) passar do teto, levanta `TetoDeCusto` sem chamar.
- Erros transitórios (429/5xx/conexão) são repetidos até 3 vezes, com espera crescente.
- Variáveis podem vir do ambiente ou do arquivo `.env` na raiz.

Reprodutibilidade: os modelos atuais do Claude não aceitam `temperature` (a API recusa o parâmetro), e
mesmo temperatura 0 não garante a mesma resposta duas vezes. O que garante é o ID fixo do modelo + o cache:
os números do TCC saem das respostas gravadas em `.cache/llm`.
"""

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import anthropic

TENTATIVAS = 3
ESFORCO = "medium"  # output_config.effort; entra na chave do cache
MAX_TOKENS = 16000  # inclui o raciocínio do modelo
ETAPAS = ("ma", "nli")

# US$ por milhão de tokens: (entrada, saída, leitura do cache de prompt); escrita no cache = 1,25 × entrada.
# Haiku: preço para prompts de até 100K tokens (os nossos ficam bem abaixo). Leitura do Haiku: 0,1 × entrada.
PRECOS = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
}


class ErroTransitorio(Exception):
    """Levantado por `_chamar_provedor` em erros que valem nova tentativa (429, 5xx)."""


class RespostaIncompleta(Exception):
    """Resposta cortada (max_tokens) ou recusada: não vai para o cache."""


class TetoDeCusto(Exception):
    """A próxima chamada poderia passar de `LLM_TETO_USD`: a execução para antes de gastar."""


def _cliente() -> anthropic.Anthropic:
    # Chave de usuário (não presa a um workspace) exige o workspace em cada chamada: LLM_WORKSPACE_ID
    workspace = os.environ.get("LLM_WORKSPACE_ID")
    # max_retries=0: quem repete é `complete`, para haver uma única política de retry
    return anthropic.Anthropic(
        api_key=os.environ.get("LLM_API_KEY") or None,
        max_retries=0,
        default_headers={"anthropic-workspace-id": workspace} if workspace else None,
    )


def _chamar_provedor(model: str, system: str, prompt: str) -> tuple[str, dict]:
    """ÚNICA função que conhece o provedor. Trocar de provedor = reescrever só esta função.

    Devolve `(texto, uso)`, com `uso` = tokens_in (total), tokens_out e quantos dos tokens de entrada foram
    escrita e leitura do cache de prompt. Erros 429/5xx -> `ErroTransitorio`.
    """
    # o system (instruções + few-shot) se repete entre decisões: fica no cache de prompt da API
    blocos_system = (
        [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if system else []
    )
    try:
        r = _cliente().messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=blocos_system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": ESFORCO},
        )
    except anthropic.APIStatusError as e:
        if e.status_code == 429 or e.status_code >= 500:
            raise ErroTransitorio(f"{e.status_code}: {e.message}") from e
        raise
    except anthropic.APIConnectionError as e:
        raise ErroTransitorio(str(e)) from e
    if r.stop_reason in ("max_tokens", "refusal"):
        raise RespostaIncompleta(f"{model}: stop_reason={r.stop_reason} (request-id {r._request_id})")
    texto = "".join(b.text for b in r.content if b.type == "text")
    u = r.usage
    escrita, leitura = u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0
    return texto, {
        "tokens_in": u.input_tokens + escrita + leitura,
        "tokens_out": u.output_tokens,
        "tokens_cache_escrita": escrita,
        "tokens_cache_leitura": leitura,
    }


def _carregar_env() -> None:
    env = Path(".env")
    if not env.exists():
        return
    for linha in env.read_text(encoding="utf-8").splitlines():
        chave, sep, valor = linha.partition("=")
        if sep and not linha.lstrip().startswith("#"):
            os.environ.setdefault(chave.strip(), valor.strip())


def _dir_cache() -> Path:
    return Path(os.environ.get("LLM_CACHE_DIR", ".cache/llm"))


def modelo(model: str | None = None, etapa: str | None = None) -> str:
    """Modelo efetivo (`model`, senão `LLM_MODEL_<ETAPA>`, senão `LLM_MODEL`), para `Predicoes.modelo`."""
    _carregar_env()
    if etapa is not None and etapa not in ETAPAS:
        raise ValueError(f"etapa desconhecida {etapa!r}; use uma de {ETAPAS}")
    model = model or (etapa and os.environ.get(f"LLM_MODEL_{etapa.upper()}")) or os.environ.get("LLM_MODEL")
    if not model:
        raise ValueError("Defina LLM_MODEL no .env ou passe model=...")
    return model


def custo_usd(model: str, uso: dict) -> float | None:
    """Custo em US$ de uma chamada pelo `uso` gravado no cache; None se o modelo não está em `PRECOS`."""
    if model not in PRECOS:
        return None
    entrada, saida, leitura = PRECOS[model]
    escrita_tok, leitura_tok = uso.get("tokens_cache_escrita", 0), uso.get("tokens_cache_leitura", 0)
    sem_cache = uso["tokens_in"] - escrita_tok - leitura_tok
    usd = (
        sem_cache * entrada + escrita_tok * 1.25 * entrada + leitura_tok * leitura + uso["tokens_out"] * saida
    )
    return usd / 1e6


_gasto: dict[Path, float] = {}  # gasto do cache por pasta: lido do disco uma vez, somado a cada chamada


def _checar_teto(model: str, system: str, prompt: str) -> None:
    teto = os.environ.get("LLM_TETO_USD")
    if not teto:
        return
    if model not in PRECOS:
        raise ValueError(f"{model} não está em PRECOS: não dá para respeitar LLM_TETO_USD")
    pasta = _dir_cache().resolve()
    if pasta not in _gasto:
        _gasto[pasta] = custo_acumulado()["usd"]
    # pior caso: ~1 token a cada 2 caracteres, system inteiro escrito no cache e MAX_TOKENS de saída
    n_system = len(system) // 2 + 1
    uso = {"tokens_in": n_system + len(prompt) // 2 + 1, "tokens_out": MAX_TOKENS}
    pior = custo_usd(model, uso | {"tokens_cache_escrita": n_system})
    if _gasto[pasta] + pior > float(teto):
        raise TetoDeCusto(
            f"gasto US$ {_gasto[pasta]:.4f} + pior caso da próxima chamada US$ {pior:.4f} "
            f"passaria do teto LLM_TETO_USD = US$ {teto}"
        )


def complete(prompt: str, *, system: str = "", model: str | None = None, etapa: str | None = None) -> str:
    model = modelo(model, etapa)

    chave = hashlib.sha256(json.dumps([model, ESFORCO, system, prompt]).encode()).hexdigest()
    arquivo = _dir_cache() / f"{chave}.json"
    if arquivo.exists():
        return json.loads(arquivo.read_text(encoding="utf-8"))["resposta"]

    _checar_teto(model, system, prompt)
    for tentativa in range(TENTATIVAS):
        try:
            texto, uso = _chamar_provedor(model, system, prompt)
            break
        except ErroTransitorio:
            if tentativa == TENTATIVAS - 1:
                raise
            time.sleep(2**tentativa)

    pasta = _dir_cache().resolve()
    if pasta in _gasto:
        _gasto[pasta] += custo_usd(model, uso) or 0.0
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    entrada = {
        "model": model,
        "etapa": etapa,
        "esforco": ESFORCO,
        "system": system,
        "prompt": prompt,
        "resposta": texto,
        **uso,
        "ts": datetime.now(UTC).isoformat(),
    }
    arquivo.write_text(json.dumps(entrada, ensure_ascii=False), encoding="utf-8")
    return texto


def _parse_json(texto: str):
    texto = texto.strip()
    if texto.startswith("```"):  # LLMs costumam cercar o JSON com ```json ... ```
        texto = texto.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(texto)


def _maior_json(texto: str):
    """O maior trecho JSON válido dentro do texto. O modelo às vezes explica antes do JSON (e cita "[0]" na
    explicação), por isso fica o trecho mais longo, não o primeiro. Sem nenhum trecho, o erro sobe."""
    decoder = json.JSONDecoder()
    achados = []
    for i, c in enumerate(texto):
        if c in "{[":
            try:
                obj, fim = decoder.raw_decode(texto, i)
            except json.JSONDecodeError:
                continue
            achados.append((fim - i, obj))
    if not achados:
        raise json.JSONDecodeError("nenhum JSON na resposta", texto, 0)
    return max(achados, key=lambda a: a[0])[1]


def complete_json(prompt: str, *, system: str = "", model: str | None = None, etapa: str | None = None):
    """Como `complete`, mas devolve o JSON já convertido. Se vier inválido, pede de novo uma vez; se a
    segunda resposta também vier com texto em volta do JSON, usa o maior trecho JSON dela. Esse último passo
    só roda quando as duas falham, então respostas que já eram lidas continuam com o mesmo resultado."""
    try:
        return _parse_json(complete(prompt, system=system, model=model, etapa=etapa))
    except json.JSONDecodeError:
        reforco = prompt + "\n\nResponda apenas com JSON válido, sem nenhum texto extra."
        texto = complete(reforco, system=system, model=model, etapa=etapa)
    try:
        return _parse_json(texto)
    except json.JSONDecodeError:
        return _maior_json(texto)


def custo_acumulado() -> dict:
    """Soma chamadas, tokens e US$ de tudo que está no cache (para reportar o custo no TCC), no total e em
    `por_etapa[etapa][modelo]`. Entradas antigas, sem etapa, ficam em "sem_etapa"; modelos fora de
    `PRECOS` contam US$ 0."""

    def zerado():
        return {"chamadas": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0}

    total = zerado() | {"por_etapa": {}}
    for f in _dir_cache().glob("*.json"):
        e = json.loads(f.read_text(encoding="utf-8"))
        etapa = total["por_etapa"].setdefault(e.get("etapa") or "sem_etapa", {})
        for soma in (total, etapa.setdefault(e["model"], zerado())):
            soma["chamadas"] += 1
            soma["tokens_in"] += e["tokens_in"]
            soma["tokens_out"] += e["tokens_out"]
            soma["usd"] += custo_usd(e["model"], e) or 0.0
    return total
