from pathlib import Path

from scripts import gold_segmentacao as gs
from scripts.avaliar_segmentacao import medir
from src.contratos import Decisao, Segmentos, ler_jsonl
from src.preprocess import normalizar
from src.segment import segmentar

FIX = Path(__file__).parent / "fixtures"
INTEIRO_TEOR = normalizar((FIX / "inteiro_teor_stj.txt").read_text(encoding="utf-8"))


def test_marcar_e_ler_devolvem_a_segmentacao_automatica():
    marcado = gs.marcar(INTEIRO_TEOR)
    assert (
        "[[INÍCIO DISPOSITIVO]]\nAnte o exposto, dou provimento ao recurso especial.\n[[FIM DISPOSITIVO]]"
        in marcado
    )
    assert gs.ler_marcado("X", marcado) == segmentar("X", INTEIRO_TEOR)


def test_correcao_manual_muda_o_gold_e_a_avaliacao():
    marcado = gs.marcar(INTEIRO_TEOR)
    # quem confere decide que a última frase da fundamentação também é dispositivo: move o marcador
    corrigido = (
        marcado.replace(
            "deve ser reformado.\n[[FIM FUNDAMENTAÇÃO]]\n\n[[INÍCIO DISPOSITIVO]]\n",
            "\n[[FIM FUNDAMENTAÇÃO]]\n[[INÍCIO DISPOSITIVO]]\ndeve ser reformado.\n",  # marcador em linha própria
        )
        if "deve ser reformado.\n[[FIM FUNDAMENTAÇÃO]]\n\n[[INÍCIO DISPOSITIVO]]\n" in marcado
        else None
    )
    assert corrigido, marcado
    gold = gs.ler_marcado("X", corrigido)
    assert gold.dispositivo.startswith("deve ser reformado.")
    m = medir(INTEIRO_TEOR, gold)
    comum, previsto, esperado = m["dispositivo"]
    assert comum == previsto < esperado  # a automática acertou só parte do dispositivo: revocação < 1


def test_segmento_apagado_fica_vazio_e_preparar_importar(tmp_path, capsys):
    decisoes = ler_jsonl(FIX / "decisoes.jsonl", Decisao)
    ids = gs.preparar(decisoes, tmp_path, n=5)
    assert sorted(ids) == sorted(d.id for d in decisoes)  # pede 5, há 2
    arquivo = tmp_path / f"{ids[0]}.txt"
    texto = arquivo.read_text(encoding="utf-8")
    inicio, fim = texto.index("[[INÍCIO EMENTA]]"), texto.index("[[FIM EMENTA]]") + len("[[FIM EMENTA]]")
    arquivo.write_text(texto[:inicio] + texto[fim:], encoding="utf-8")  # a conferência apagou a ementa
    saida = tmp_path / "gold.jsonl"
    gs.main(["importar", str(tmp_path), str(saida)])
    gold = {g.id: g for g in ler_jsonl(saida, Segmentos)}
    assert gold[ids[0]].ementa == "" and gold[ids[0]].fundamentacao
    assert "2 decisões no gold" in capsys.readouterr().out


def test_relatorio_antes_da_ementa():
    """Alguns acórdãos do STJ trazem o relatório antes da ementa: a avaliação acha os segmentos mesmo assim."""
    texto = (
        "RELATÓRIO\nTrata-se de recurso especial.\nEMENTA\nCIVIL. RECURSO PROVIDO.\n"
        "VOTO\nHá prova do pagamento.\nAnte o exposto, dou provimento ao recurso."
    )
    gold = Segmentos(
        id="X",
        ementa="CIVIL. RECURSO PROVIDO.",
        relatorio="Trata-se de recurso especial.",
        fundamentacao="Há prova do pagamento.",
        dispositivo="Ante o exposto, dou provimento ao recurso.",
    )
    m = medir(texto, gold)
    assert {nome: m[nome][2] for nome in m} == {
        nome: len(getattr(gold, nome)) for nome in ("ementa", "relatorio", "fundamentacao", "dispositivo")
    }
