"""Gateway de LLM com o provedor substituído por um falso: nenhum teste toca a rede."""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from src import llm


@pytest.fixture(autouse=True)
def _sem_env_local(monkeypatch):
    for var in ("LLM_MODEL_MA", "LLM_MODEL_NLI", "LLM_TETO_USD"):  # vazias: o .env local não vaza
        monkeypatch.setenv(var, "")


@pytest.fixture
def provedor(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "modelo-teste")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    chamadas = []
    respostas = []  # fila de respostas/exceções/(texto, uso); vazia = eco do prompt

    def falso(model, system, prompt):
        chamadas.append((model, system, prompt))
        r = respostas.pop(0) if respostas else f"eco: {prompt}"
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, tuple) else (r, {"tokens_in": 10, "tokens_out": 5})

    monkeypatch.setattr(llm, "_chamar_provedor", falso)
    return chamadas, respostas


def test_cache_evita_segunda_chamada(provedor):
    chamadas, _ = provedor
    assert llm.complete("oi") == llm.complete("oi") == "eco: oi"
    assert len(chamadas) == 1
    llm.complete("oi", system="outro")
    assert len(chamadas) == 2


def test_cache_registra_modelo(provedor, tmp_path):
    llm.complete("oi")
    (entrada,) = [json.loads(f.read_text(encoding="utf-8")) for f in tmp_path.glob("*.json")]
    assert entrada["model"] == "modelo-teste"
    assert (entrada["tokens_in"], entrada["tokens_out"]) == (10, 5)


def test_complete_json_com_cerca_e_reforco(provedor):
    chamadas, respostas = provedor
    respostas += ['```json\n{"a": 1}\n```']
    assert llm.complete_json("p1") == {"a": 1}
    respostas += ["não é json", "[1, 2]"]
    assert llm.complete_json("p2") == [1, 2]
    assert "JSON válido" in chamadas[-1][2]


def test_complete_json_explicacao_antes_do_json_nas_duas_respostas(provedor):
    # caso real da rodada de 30/10: o modelo explicou antes do JSON também depois do reforço
    _, respostas = provedor
    explicada = 'O par [0] não se contradiz.\n```json\n{"resultados": [{"i": 0}, {"i": 1}]}\n```'
    respostas += ["Explicação primeiro.", explicada]
    assert llm.complete_json("p3") == {"resultados": [{"i": 0}, {"i": 1}]}  # o JSON inteiro, não o "[0]"
    respostas += ["nada", "nada de novo"]
    with pytest.raises(json.JSONDecodeError):
        llm.complete_json("p4")


def test_custo_acumulado(provedor):
    llm.complete("a")
    llm.complete("b")
    llm.complete("a")
    custo = llm.custo_acumulado()
    assert (custo["chamadas"], custo["tokens_in"], custo["tokens_out"]) == (2, 20, 10)
    assert custo["usd"] == 0  # modelo fora de PRECOS
    assert custo["por_etapa"] == {
        "sem_etapa": {"modelo-teste": {"chamadas": 2, "tokens_in": 20, "tokens_out": 10, "usd": 0}}
    }


def test_modelo_por_etapa(provedor, monkeypatch, tmp_path):
    chamadas, _ = provedor
    monkeypatch.setenv("LLM_MODEL_MA", "modelo-ma")
    monkeypatch.setenv("LLM_MODEL_NLI", "modelo-nli")
    llm.complete("a", etapa="ma")
    llm.complete("b", etapa="nli")
    llm.complete("c")  # sem etapa: LLM_MODEL
    assert [m for m, _, _ in chamadas] == ["modelo-ma", "modelo-nli", "modelo-teste"]
    monkeypatch.setenv("LLM_MODEL_NLI", "")  # não definido: cai em LLM_MODEL
    assert llm.modelo(etapa="nli") == "modelo-teste"
    assert llm.modelo("explicito", etapa="ma") == "explicito"
    with pytest.raises(ValueError):
        llm.modelo(etapa="baseline")
    por_etapa = llm.custo_acumulado()["por_etapa"]
    assert {e: list(m) for e, m in por_etapa.items()} == {
        "ma": ["modelo-ma"],
        "nli": ["modelo-nli"],
        "sem_etapa": ["modelo-teste"],
    }


def test_custo_usd_separa_cache_de_prompt():
    uso = {"tokens_in": 1_000_000, "tokens_out": 1_000_000}
    assert llm.custo_usd("claude-sonnet-5-5", uso) == pytest.approx(2 + 10)
    uso |= {"tokens_cache_escrita": 400_000, "tokens_cache_leitura": 500_000}
    assert llm.custo_usd("claude-sonnet-5-5", uso) == pytest.approx(0.1 * 2 + 0.4 * 2.5 + 0.5 * 0.2 + 10)
    assert llm.custo_usd("modelo-teste", uso) is None


def test_teto_para_antes_de_ultrapassar(provedor, monkeypatch):
    chamadas, respostas = provedor
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5-5")
    uso = {"tokens_in": 0, "tokens_out": 10_000}  # US$ 0,10 por chamada; pior caso ~US$ 0,16
    respostas += [("ok", uso)] * 10
    llm.complete("1")
    llm.complete("2")  # sem teto ainda: US$ 0,20 no cache
    monkeypatch.setenv("LLM_TETO_USD", "0.5")
    llm.complete("3")  # 0,20 (lido do cache) + 0,16 <= 0,5
    llm.complete("4")  # 0,30 + 0,16 <= 0,5
    with pytest.raises(llm.TetoDeCusto):
        llm.complete("5")  # 0,40 + 0,16 > 0,5: não chama
    assert len(chamadas) == 4
    assert llm.custo_acumulado()["usd"] == pytest.approx(0.4) and llm.custo_acumulado()["usd"] <= 0.5
    assert llm.complete("1") == "ok"  # o que está no cache não gasta, então passa


@pytest.fixture
def api(monkeypatch):
    """Cliente da Anthropic falso: guarda os parâmetros e devolve `api.resposta` (ou levanta `api.erro`)."""
    estado = SimpleNamespace(chamadas=[], erro=None, resposta=None)

    def create(**kwargs):
        estado.chamadas.append(kwargs)
        if estado.erro:
            raise estado.erro
        return estado.resposta

    monkeypatch.setattr(llm, "_cliente", lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
    estado.resposta = _resposta("ok")
    return estado


def _resposta(texto, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=texto)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=7, cache_creation_input_tokens=100, cache_read_input_tokens=0, output_tokens=3
        ),
        _request_id="req_x",
    )


def _erro_http(status):
    resposta = httpx2.Response(
        status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    return anthropic.APIStatusError(f"erro {status}", response=resposta, body=None)


def test_provedor_monta_a_chamada(api):
    uso = {"tokens_in": 107, "tokens_out": 3, "tokens_cache_escrita": 100, "tokens_cache_leitura": 0}
    assert llm._chamar_provedor("claude-x", "instruções", "prompt") == ("ok", uso)
    (kwargs,) = api.chamadas
    assert kwargs["model"] == "claude-x"
    assert kwargs["messages"] == [{"role": "user", "content": "prompt"}]
    assert kwargs["system"][0]["text"] == "instruções" and "cache_control" in kwargs["system"][0]
    assert kwargs["output_config"] == {"effort": llm.ESFORCO}
    assert "temperature" not in kwargs  # a API recusa nos modelos atuais
    llm._chamar_provedor("claude-x", "", "prompt")
    assert api.chamadas[-1]["system"] == []


def test_resposta_cortada_ou_recusada_nao_vai_para_o_cache(api, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    for motivo in ("max_tokens", "refusal"):
        api.resposta = _resposta('{"incompleto": ', stop_reason=motivo)
        with pytest.raises(llm.RespostaIncompleta):
            llm.complete("p", model="m")
    assert not list(tmp_path.glob("*.json"))
