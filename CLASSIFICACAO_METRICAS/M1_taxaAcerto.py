import os
import json
import pandas as pd
from pathlib import Path
from tqdm import tqdm

def calcular_taxa_acerto(diretorio_transactions):
    base_path = Path(diretorio_transactions)
    # Dicionário para guardar valores únicos: {id_exercicio: {'tentou': set(), 'acertou': set()}}
    estatisticas = {}

    print(f"A ler logs em: {base_path.resolve()}")
    arquivos = list(base_path.glob("**/*.log"))

    if not arquivos:
        print("Nenhum ficheiro .log encontrado.")
        return

    for arquivo_log in tqdm(arquivos, desc="A analisar M1 - Taxa de Acerto"):
        exercicio_id = arquivo_log.stem
        
        # Extração de ID
        try:
            partes = arquivo_log.parts
            idx_trans = partes.index("transactions_exame_only")
            aluno_id = partes[idx_trans + 1]
        except (ValueError, IndexError):
            aluno_id = "desconhecido"

        if exercicio_id not in estatisticas:
            estatisticas[exercicio_id] = {'tentou': set(), 'acertou': set()}

        try:
            with open(arquivo_log, 'r', encoding='utf-8') as f:
                for linha in f:
                    linha = linha.strip()
                    if not linha: continue
                    
                    try:
                        evento = json.loads(linha)
                    except json.JSONDecodeError:
                        continue
                    
                    # 1. Verificar se o aluno submeteu a questão (Denominador)
                    if evento.get('eventType') == 'submission':
                        estatisticas[exercicio_id]['tentou'].add(aluno_id)
                        
                        detalhes = evento.get('details', {})
                        
                        # Proteção de conversão para o correctness
                        try:
                            correctness = float(detalhes.get('correctness', 0))
                        except (ValueError, TypeError):
                            correctness = 0.0

                        # 2. Verificar se o aluno obteve sucesso (Numerador)
                        if correctness == 1.0:
                            estatisticas[exercicio_id]['acertou'].add(aluno_id)
                            
        except Exception:
            continue

    # 3. Consolidar os resultados num dataframe
    resultado_final = []
    for ex_id, counts in estatisticas.items():
        total_tentou = len(counts['tentou'])
        total_acertou = len(counts['acertou'])
        
        # Significância Estatística
        if total_tentou >= 20:
            taxa = (total_acertou / total_tentou) * 100
            resultado_final.append({
                'ID_Exercicio': ex_id,
                'Qtd_Alunos_Tentaram': total_tentou,
                'Qtd_Alunos_Acertaram': total_acertou,
                'Taxa_Acerto_%_M1': round(taxa, 2)
            })

    if not resultado_final:
        print("\nNenhum exercício atingiu o critério mínimo de 5 alunos com submissões.")
        return

    df = pd.DataFrame(resultado_final)
    # Ordenar pelos exercícios mais difíceis (Menor taxa de acerto)
    df = df.sort_values(by='Taxa_Acerto_%_M1', ascending=True) 

    # Colocar o caminho para a saída
    caminho_arquivo = Path(__file__).parent.parent

    output_file = caminho_arquivo/ "ANALISE_DE_CODIGOS"/ "resultado_analise_padroes"/ "M1_resultados.csv"
    df.to_csv(output_file, index=False)
    print(f"\nRelatório M1 salvo em: {output_file}")

# Caminho (coloar seu caminho para a pasta transactions)

path_t = Path(__file__).parent
#arquivos_gerais_pibic = path_t.parent

caminho_transactions = path_t / "transactions"
calcular_taxa_acerto(caminho_transactions)