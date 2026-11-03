from pathlib import Path

from scripts.estatisticas_corpus import relatorio
from src.contratos import Decisao, Gold, ler_jsonl

FIX = Path(__file__).parent / "fixtures"
GOLD = ler_jsonl(FIX / "gold.jsonl", Gold)
DECISOES = ler_jsonl(FIX / "decisoes.jsonl", Decisao)


def test_contagens_da_fixture():
    texto = relatorio(GOLD)
    assert "- Decisões: 2 (meta >= 300: faltam 298)" in texto
    assert "- Com contradição: 1 (50,0%); sem contradição: 1 (50,0%)" in texto
    assert "| CDF-1 | Conclusão Invertida | 1 | 1 | faltam 29 |" in texto
    assert "| CIL-1 | Non Sequitur | 0 | 0 | faltam 30 |" in texto
    assert "| ementa × dispositivo | 1 |" in texto
    assert "| fundamentacao × fundamentacao | 1 |" in texto


def test_confere_rotulo_da_coleta():
    texto = relatorio(GOLD, DECISOES)
    assert "Embargos acolhidos por contradição, mas sem contradição anotada: 0" in texto

    sem_anotacao = [g.model_copy(update={"contradicoes": []}) for g in GOLD]
    texto = relatorio(sem_anotacao, DECISOES[:1])
    assert "Acolhidos sem anotação: FICT-0001" in texto
    assert "Fora da coleta: FICT-0002" in texto
