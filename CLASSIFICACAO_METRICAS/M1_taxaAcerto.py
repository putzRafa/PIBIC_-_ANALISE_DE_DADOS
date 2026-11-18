import json
import pandas as pd
from pathlib import Path
from tqdm import tqdm


def calcular_taxa_acerto(diretorio_transactions):
    base_path = Path(diretorio_transactions)

    # {id_exercicio: {
    #     'tentou': set(),                  # alunos que submeteram ao menos uma vez
    #     'n_submissoes': {aluno: int},     # contador de submissões até o 1º acerto
    #     'primeiro_acerto': {aluno: int}   # nº da submissão em que acertou pela 1ª vez
    # }}
    estatisticas = {}

    print(f"A ler logs em: {base_path.resolve()}")
    arquivos = list(base_path.glob("**/*.log"))

    if not arquivos:
        print("Nenhum ficheiro .log encontrado.")
        return

    for arquivo_log in tqdm(arquivos, desc="A analisar M1 - Taxa de Acerto"):
        exercicio_id = arquivo_log.stem

        # Extração de ID do aluno
        try:
            partes = arquivo_log.parts
            idx_trans = partes.index("transactions_exame_only")
            aluno_id = partes[idx_trans + 1]
        except (ValueError, IndexError):
            aluno_id = "desconhecido"

        if exercicio_id not in estatisticas:
            estatisticas[exercicio_id] = {
                'tentou': set(),
                'n_submissoes': {},
                'primeiro_acerto': {}
            }

        est = estatisticas[exercicio_id]

        try:
            with open(arquivo_log, 'r', encoding='utf-8') as f:
                for linha in f:
                    linha = linha.strip()
                    if not linha:
                        continue

                    try:
                        evento = json.loads(linha)
                    except json.JSONDecodeError:
                        continue

                    if evento.get('eventType') != 'submission':
                        continue

                    # Denominador: aluno tentou
                    est['tentou'].add(aluno_id)

                    # Conta submissões do aluno nesse exercício
                    est['n_submissoes'][aluno_id] = est['n_submissoes'].get(aluno_id, 0) + 1

                    detalhes = evento.get('details', {})
                    try:
                        correctness = float(detalhes.get('correctness', 0))
                    except (ValueError, TypeError):
                        correctness = 0.0

                    # Numerador: só registra o PRIMEIRO acerto do aluno
                    if correctness == 1.0 and aluno_id not in est['primeiro_acerto']:
                        est['primeiro_acerto'][aluno_id] = est['n_submissoes'][aluno_id]

        except Exception:
            continue

    # Consolidar resultados
    resultado_final = []
    for ex_id, est in estatisticas.items():
        total_tentou = len(est['tentou'])
        total_acertou = len(est['primeiro_acerto'])

        # Significância estatística
        if total_tentou >= 16:
            taxa = (total_acertou / total_tentou) * 100

            tentativas_acerto = list(est['primeiro_acerto'].values())
            acertou_1 = sum(1 for n in tentativas_acerto if n == 1)
            acertou_2 = sum(1 for n in tentativas_acerto if n == 2)
            acertou_3 = sum(1 for n in tentativas_acerto if n == 3)
            acertou_4_mais = sum(1 for n in tentativas_acerto if n >= 4)

            def pct(x):
                return round(x / total_acertou * 100, 2) if total_acertou else 0.0

            resultado_final.append({
                'ID_Exercicio': ex_id,
                'Qtd_Alunos_Tentaram': total_tentou,
                'Qtd_Alunos_Acertaram': total_acertou,
                'Taxa_Acerto_%_M1': round(taxa, 2),
                # Quantidade de alunos por nº da submissão do 1º acerto
                'Acertou_1a_Submissao': acertou_1,
                'Acertou_2a_Submissao': acertou_2,
                'Acertou_3a_Submissao': acertou_3,
                'Acertou_4+_Submissoes': acertou_4_mais,
                # Proporção em relação a quem acertou
                '%_Acertou_1a': pct(acertou_1),
                '%_Acertou_2a': pct(acertou_2),
                '%_Acertou_3a': pct(acertou_3),
                '%_Acertou_4+': pct(acertou_4_mais),
            })

    if not resultado_final:
        print("\nNenhum exercício atingiu o critério mínimo de 16 alunos com submissões.")
        return

    df = pd.DataFrame(resultado_final)
    df = df.sort_values(by='Taxa_Acerto_%_M1', ascending=True)

    caminho_arquivo = Path(__file__).parent.parent
    output_dir = caminho_arquivo / "ANALISE_DE_CODIGOS" / "resultado_analise_padroes"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "M1_resultados.csv"
    df.to_csv(output_file, index=False)
    print(f"\nRelatório M1 salvo em: {output_file}")


path_t = Path(__file__).parent
caminho_transactions = path_t / "transactions"
calcular_taxa_acerto(caminho_transactions)