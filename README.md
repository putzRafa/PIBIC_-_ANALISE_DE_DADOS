# Classificação de Padrões de Programação via AST

Pipeline que lê as soluções de exercícios de programação em Python, identifica **padrões estruturais de código** a partir da árvore sintática (AST) e gera um CSV de *features* por exercício.

O catálogo de padrões serve a dois objetivos:

1. **Montar novas listas de exercícios balanceadas**, cobrindo de forma deliberada cada padrão e cada variação.
2. **Auditar o balanceamento das atividades já aplicadas**, identificando quais padrões foram pouco ou muito exercitados.

---

## 1. Estrutura do repositório

```
ARQUIVOS_GERAIS_PIBIC/
├── ANALISE_DE_CODIGOS/
│   ├── classifcacaoDePadroesNovo.py            # extrator de padrões (versão v17 desta documentação)
│   └── resultado_analise_padroes/
│       ├── features_ast_padroes_completos.csv  # saída do extrator (uma linha por exercício)
│       ├── M1_resultados.csv                   # saída das métricas (ver abaixo)
│       ├── ...
├── CLASSIFICACAO_METRICAS/
│   ├── transactions/                           # (conteúdo não detalhado)
│   ├── M1_taxaAcerto.py
│   ├── ...
├── DataSet/
│   └── exerciciosSolucao/                      # soluções dos exercícios (uma subpasta por exercício)
```

**Extrator de padrões (`ANALISE_DE_CODIGOS`).** Lê as soluções em `DataSet/exerciciosSolucao`, classifica cada uma e grava `features_ast_padroes_completos.csv`. O restante deste README descreve esse extrator.

**Métricas (`CLASSIFICACAO_METRICAS`).** Os nomes dos três scripts sugerem métricas de desempenho por exercício: taxa de acerto, submissões e taxa de aceitação. **Confirmar e descrever aqui** o que cada uma calcula e quais colunas gera. Atenção ao nome: `M1`, `M2` e `M3` nessa pasta são **métricas**, e não os módulos de padrões (M1 a M6) do documento de padrões.

O script resolve os caminhos a partir da própria localização:

```python
caminho_do_script     = Path(__file__).parent          # ANALISE_DE_CODIGOS/
arquivos_gerais_pibic = caminho_do_script.parent       # raiz do repositório
caminho_exercises     = arquivos_gerais_pibic / "DataSet" / "exerciciosSolucao"
output_file           = caminho_do_script / "resultado_analise_padroes" / "features_ast_padroes_completos.csv"
```

A pasta de saída é criada automaticamente se não existir.

### Versionamento

Os dados dos exercícios e as transações não precisam ir para o GitHub. Sugestão de `.gitignore`:

```gitignore
DataSet/exerciciosSolucao/
DataSet/exerciciosSolucao_-_Ass*/
CLASSIFICACAO_METRICAS/transactions/
*.code-workspace
```

---

## 2. Padrões de programação (documento de padrões, 6 módulos)

Os padrões estão organizados em **6 módulos**. Cada um começa com uma definição conceitual no documento e traz padrões com código de referência (M*x.y*) e critério de reconhecimento via AST.

| Módulo | Padrão | Critério AST (resumo) | Categoria no extrator |
|---|---|---|---|
| **M1** Estruturas sequenciais | M1.1–M1.4 (médias, conversões, fórmulas, saída formatada) | Sem `if` e sem laço | `Input/output sequencial` |
| **M2** Condicional simples e composto | M2.1 Simples (`if` isolado) | `If` sem `orelse` | `Condicional simples` |
| | M2.2 Composto (`if/else`) | `If` com `orelse` que não é outro `If` | `Condicional composto` |
| **M3** Encadeado e aninhado | M3.1 Encadeado (`if/elif/else`) | `If` cujo `orelse` é um único `If` (a cadeia inteira conta como 1) | `Condicional encadeado` |
| | M3.2 Aninhado | `if` dentro de outro `if` (um `elif` **não** conta como aninhamento) | `Condicional aninhado` |
| **M4** Repetição por condição (`while`) | M4.1 Validação de entrada | `while` sem `if` interno, sem acúmulo aritmético, cuja condição usa variável reatribuída no corpo (ex.: `input()`) | `Repetição - validação de entrada` |
| | M4.2 Menu | `while True` com `if/elif` interno e sem acúmulo aritmético | `Repetição - controle por menu` |
| | M4.3 Contadores | Incremento unitário (`+1`/`-1`) no `while`, **sem** `if` dentro do laço envolvendo a operação | `Repetição - incremento de variável` |
| | M4.4 Condição interna + incremento | Incremento unitário dentro de um `if` do `while` | `Repetição com condição - incremento de variável` |
| | M4.5 Condição interna + acúmulo | Acúmulo dentro de um `if` do `while` | `Repetição com condição - acúmulo de variável` |
| **M5** Vetores e strings (Estrutura Linear) | M5.1 Maior/Menor, M5.2 Soma de Vetor, M5.3 Contagem de Frequência | `for` que percorre uma **coleção**: por índice ou por valor (ver abaixo) | `Estrutura linear (lista/string) - iteração por índice` / `… por valor` |
| **M6** Repetição por contagem (`for`) | M6.1 Somatórios (acúmulo aditivo), M6.2 Séries numéricas (acúmulo multiplicativo) | `for` sobre `range()` **numérico**, sem `len()` e sem indexar coleção, com acumulador | `Repetição por contagem - incremento/acúmulo de variável` |

O extrator também reconhece a categoria `Repetição - acúmulo de variável` (`while` sem `if` interno, com passo não unitário, por exemplo `total = total + x`). **O documento atual não tem padrão correspondente**, porque o antigo "Acumuladores" foi renomeado para "Contadores" (M4.3) e passou a descrever só o `+1`. Ver pendências.

### Como o M5 se distingue do M6

Os dois usam `for`, mas percorrem coisas diferentes. A distinção é feita pelo AST, e não pelo nome do módulo:

| Situação no código | Classificação |
|---|---|
| `for i in range(len(lista))` | M5, iteração por índice |
| `for i in range(n)` com `lista[i]` no corpo (a variável do laço indexa uma coleção) | M5, iteração por índice |
| `for x in lista` | M5, iteração por valor |
| `for i in range(1, n + 1)` sem `len()` e sem indexar coleção | **M6** |

A variável do laço é **índice** no M5 e **contador usado na conta** no M6 (`somatorio + i`, `fatorial * i`). Por isso M5.2 (Soma de Vetor por índice) e M6.1 (Somatórios) são padrões diferentes, apesar de ambos somarem.

Dentro do M6, a **família da operação** do acumulador separa M6.1 de M6.2:

| Coluna | Significado |
|---|---|
| `Sub_Contagem_Aditivo` | acumulador atualizado com `+` ou `-` (M6.1) |
| `Sub_Contagem_Multiplicativo` | acumulador atualizado com `*`, `/` ou `//` (M6.2) |

### Incremento × acúmulo

- **Incremento:** passo unitário (`+= 1`, `-= 1`, `x = x + 1`).
- **Acúmulo:** qualquer outra atualização da própria variável (`+= valor`, `*= i`, `x = x * i`, `/`, `//`).

### Hierarquia de dominância

Quando um arquivo ativa vários padrões, apenas o **mais complexo** é mantido como padrão dominante (`padroes_str`). Ordem, do mais complexo ao mais simples:

| # | Padrão | Módulo | Nível |
|---|---|---|---|
| 1 | Estrutura linear - iteração por índice | M5 | Coleção |
| 2 | Estrutura linear - iteração por valor | M5 | Coleção |
| 3 | Repetição com condição - acúmulo de variável | M4 | Laço com decisão |
| 4 | Repetição com condição - incremento de variável | M4 | Laço com decisão |
| 5 | Repetição - controle por menu | M4 | Laço com decisão |
| 6 | Repetição - acúmulo de variável (`while`) | M4 | Repetição básica |
| 7 | Repetição - incremento de variável (`while`) | M4 | Repetição básica |
| 8 | Repetição - validação de entrada | M4 | Repetição básica |
| 9 | Repetição por contagem - acúmulo de variável | M6 | Repetição básica |
| 10 | Repetição por contagem - incremento de variável | M6 | Repetição básica |
| 11 | Condicional aninhado | M3 | Decisão |
| 12 | Condicional encadeado | M3 | Decisão |
| 13 | Condicional composto | M2 | Decisão |
| 14 | Condicional simples | M2 | Decisão |
| 15 | Input/output sequencial | M1 | Sequencial |

A ordem segue quatro critérios, do mais ao menos determinante:

1. **Estruturas combinadas:** decisão < laço < laço com decisão < laço sobre coleção.
2. **Número de repetições:** conhecido (`for` de contagem, M6) < desconhecido (`while`, M4).
3. **Tipo de atualização:** incremento (passo fixo) < acúmulo (expressão).
4. **Acesso à coleção:** iteração por valor < iteração por índice.

Consequências práticas:

- **A numeração dos módulos não é a ordem de complexidade.** O M6 tem número maior que M4 e M5, mas é classificado como mais simples que todos os `while`.
- O `for` de contagem (M6) fica abaixo de todos os `while`, mas acima de qualquer condicional. Um exercício que combine, por exemplo, um aninhado com um somatório de 1 até N é classificado como M6.
- Dentro de um mesmo nível, o acúmulo domina o incremento.
- O controle por menu (posição 5) fica acima do `while` com acúmulo simples, porque combina laço indefinido com despacho `if/elif`. Fica abaixo de M4.4 e M4.5, cujos exemplos já indexam uma coleção.
- A posição de menu, validação e das categorias de contagem foi definida por critério pedagógico. Vale validar essa ordem com o orientador.

### Qual laço rotula o acumulador

O incremento/acúmulo é rotulado de acordo com o laço **mais interno** que o contém:

- `while` sem `if` aberto dentro do laço: M4.3 (incremento) ou `Repetição - acúmulo de variável` (sem padrão no documento).
- `while` com a operação dentro de um `if` do laço: M4.4/M4.5. Um `if` que apenas envolve o laço **não** torna o acúmulo condicional.
- `for` de contagem numérica: M6.
- `for` sobre coleção: sem rótulo próprio, pois a operação já faz parte do padrão M5.

---

## 3. Sub-padrões posicionais

Além do padrão principal, o pipeline registra **onde estão as operações em relação à estrutura de controle**: antes, depois, ambas ou nenhuma. Essa dimensão aparece no documento como "Variação" (isolado, só antes, só depois, ambos) nos módulos M2 e M3.

### 3.1 Cruzamento tipo × posição (condicionais, M2 e M3)

Cada ocorrência cai em **exatamente uma** de 4 categorias mutuamente exclusivas:

| Variação | Operação antes? | Operação depois? | Coluna |
|---|---|---|---|
| Isolado | Não | Não | `Sub_<Tipo>_Isolado` |
| Só antes | Sim | Não | `Sub_<Tipo>_Antes` |
| Só depois | Não | Sim | `Sub_<Tipo>_Depois` |
| Ambos | Sim | Sim | `Sub_<Tipo>_Dupla` |

`<Tipo>` ∈ {`Simples`, `Composto`, `Encadeado`, `Aninhado`}, o que gera **16 colunas**.

**Por que categorias exclusivas?** Com dois contadores independentes (`Com_Antes`, `Com_Depois`), um arquivo com 1 `if` que tem operação antes **e** depois produz o mesmo resultado que um arquivo com 2 `if`s separados (um só com antes, outro só com depois). Com categorias exclusivas, os dois casos são distinguíveis e a soma das 4 colunas de um tipo é igual ao total de ocorrências daquele tipo.

**Regra especial para o Aninhado (M3.2).** A posição é medida ao redor do **`if` mais externo da estrutura** (a raiz), e cada estrutura aninhada conta **uma vez**, mesmo com vários `if`s internos. Exemplo do documento:

```python
valor1 = input()          # operação antes
if condicao1:             # <- if mais externo
    if condicao2:
        pass
    else:
        pass
else:
    pass
print(valor1)             # operação depois
```

Resultado: `Sub_Aninhado_Dupla = 1`.

Os `if`s também recebem o rótulo do próprio formato (simples, composto ou encadeado), com a posição do próprio nó. No exemplo acima, o `if` externo soma em `Sub_Composto_Dupla` e o interno soma em `Sub_Composto_Isolado`. São dois fatos distintos, e não uma inconsistência. Por isso `Freq_Condicional_aninhado` conta **estruturas** aninhadas, e não `if`s internos.

### 3.2 Sub-padrões globais (laços e condicionais, agregados por arquivo)

Contagens independentes do padrão dominante, não mutuamente exclusivas:

| Coluna | Significado |
|---|---|
| `Sub_If_Operacao_Antes` / `Sub_If_Operacao_Apos` | `if`s com instrução antes / depois no mesmo bloco |
| `Sub_Laco_Operacao_Antes` / `Sub_Laco_Operacao_Apos` | laços (`for`/`while`) com instrução antes / depois |
| `Sub_Laco_Var_Inicializada_Atualizada` | variável atribuída logo antes do laço e reatribuída dentro dele (contadores, acumuladores, valor-base de comparação, estado de menu) |

---

## 4. Features extraídas (colunas do CSV)

Uma linha por exercício. O script usa o arquivo com `sample_solution` no nome; se não houver, usa o maior `.py` da pasta.

**Identificação**

| Coluna | Descrição |
|---|---|
| `id_exercicio` | nome da pasta do exercício |
| `padroes_str` | padrão dominante (ou `Sem Padrão Mapeado`) |
| `Modulo_Dominante` | módulo do padrão dominante (`M1` a `M6`, ou `Sem módulo`) |

**Tamanho**

| Coluna | Descrição |
|---|---|
| `LOC` | linhas físicas não vazias e que não começam com `#` |
| `LLOC` | linhas **lógicas** de código, calculadas com `radon.raw.analyze`. Se o `radon` falhar para um arquivo, fica `None` |

**Métricas estruturais (AST)**

| Coluna | Descrição |
|---|---|
| `AST_Profundidade_Fluxo` | profundidade máxima de aninhamento de `if`/`for`/`while`/comprehensions |
| `AST_Complexidade_Ciclomatica` | McCabe aproximada: começa em 1; +1 por `if`/laço/comprehension; +(N−1) por `and`/`or` |
| `AST_Qtd_Loops` | `for`, `while` e comprehensions |
| `AST_Qtd_Ifs` | nós `If` (cada `elif` conta como um) |
| `AST_Qtd_Variaveis` | nomes distintos atribuídos |
| `AST_Qtd_Funcoes` | quantidade de `def` |
| `AST_Tem_Recursao` | 1 se alguma função chama a si mesma diretamente |

**Normalizações** (densidade por linha)

`Norm_Complexidade_Por_LOC`, `Norm_Ifs_Por_LOC`, `Norm_Loops_Por_LOC` e as equivalentes `…_Por_LLOC`.

**Frequência por padrão**

`Freq_<padrão>`: uma coluna por categoria de padrão (15 no total), com a contagem após aplicar a hierarquia de dominância. Apenas a categoria dominante fica diferente de zero. Ex.: `Freq_Repetição_por_contagem_-_acúmulo_de_variável`.

**Sub-padrões**

`Sub_*` conforme a seção 3 (posicionais, cruzados e `Sub_Contagem_*`).

---

## 5. Como executar

**Dependências**

```bash
pip install pandas tqdm radon
```

Teste rápido do `radon`:

```python
from radon.raw import analyze
print(analyze("x = 1\ny = 2\n").lloc)   # deve imprimir 2
```

**Execução**

```bash
python ANALISE_DE_CODIGOS/classifcacaoDePadroesNovo.py
```

O script percorre as subpastas de `DataSet/exerciciosSolucao`, analisa um arquivo por pasta e grava o CSV em `ANALISE_DE_CODIGOS/resultado_analise_padroes/`.

---

## 6. Histórico de alterações em relação ao script original (v11)

**v12: correção de bugs**
- `if/elif/else` deixou de ser contado também como "Condicional aninhado".
- O rótulo "Repetição com condição" passou a exigir um `if` interno ao `while`. Antes, o contador sem `if` era rotulado como "com condição".
- Multiplicação, divisão e divisão inteira passaram a ser reconhecidas como acúmulo (antes só `+`/`-`), o que torna a série multiplicativa (fatorial) detectável.
- `x *= 1` deixou de ser tratado como "incremento".
- `ast.Str` (depreciado) foi substituído por `ast.Constant`.
- Comprehensions (list, dict, set, generator) passaram a ser classificadas e contadas na profundidade.
- `for` sobre `enumerate()`, `zip()`, `dict.items()` e strings literais passou a ser reconhecido.

**v13**
- Adicionado `LLOC` via `radon` e normalizações por LLOC.
- Adicionados os sub-padrões posicionais globais (seção 3.2).

**v14**
- Cruzamento tipo × posição para condicionais (seção 3.1), inicialmente com dois contadores independentes e depois com 4 categorias mutuamente exclusivas.

**v15**
- Colunas renomeadas para `Antes`/`Depois`, alinhadas ao documento de padrões.
- Critérios AST para validação de entrada e menu, com duas novas categorias na hierarquia. Antes, a validação caía em `Sem Padrão Mapeado` e o menu em `Condicional encadeado`.

**v16**
- **M5 × M6 (numeração da época: M6 × M7):** o `for` sobre `range()` deixou de ser sempre "iteração por índice". `range(len(x))` ou variável que indexa coleção continua estrutura linear; `range` numérico sem `len()` e sem indexar coleção passou a ser repetição por contagem, com categorias próprias e colunas `Sub_Contagem_Aditivo`/`Sub_Contagem_Multiplicativo`.
- **Aninhado:** a posição passou a ser medida ao redor do `if` mais externo da estrutura, com uma ocorrência por estrutura.
- O incremento/acúmulo passou a ser rotulado pelo laço mais interno, e um `if` que só envolve o laço não torna o acúmulo condicional.
- Nova coluna `Modulo_Dominante`.
- **Hierarquia de dominância reordenada**: o `for` de contagem passou a ficar abaixo de todos os `while`, e o controle por menu acima do `while` com acúmulo simples. Arquivos que misturam padrões podem ter mudado de classificação em relação ao CSV anterior.
- Os caminhos do script passaram a refletir a estrutura do repositório, e a pasta de saída é criada automaticamente.

**v17**
- Numeração dos módulos alinhada ao novo documento de padrões, que passou de 7 para **6 módulos** (condicional simples e composto agora formam o M2, e todos os módulos seguintes foram renumerados). Mudaram apenas `MODULO_POR_PADRAO` e os comentários: a classificação dos padrões é a mesma da v16.

---

## 7. Limitações e pendências conhecidas

**No código**
- **Um padrão dominante por arquivo.** Arquivos que combinam padrões distintos perdem informação na coluna principal. Os `Sub_*` e o `Modulo_Dominante` mitigam isso, mas não substituem.
- **Acúmulo não unitário no `while`** sem `if` (`total = total + x`) é classificado como `Repetição - acúmulo de variável`, que não tem padrão correspondente no documento atual.
- **`for` numérico sem acumulador** (`for i in range(5): print(i)`) e comprehensions com `range` numérico não correspondem a nenhum padrão documentado e resultam em `Sem Padrão Mapeado`.
- **Fibonacci** escrito com variável auxiliar (`prox = a + b`) ou troca de tuplas não é reconhecido como M6: o acumulador só é detectado quando a variável se atualiza usando a si mesma.
- **`while True` sem `if`** não corresponde a nenhum padrão documentado e resulta em `Sem Padrão Mapeado`.
- **Cruzamento posição × tipo só para condicionais.** Estendê-lo aos laços exige passar o nó do laço para a classificação de incremento/acúmulo.
- **Recursão:** só detecta recursão direta, por nome simples.
- **`radon`:** a integração foi escrita conforme a API documentada, mas não foi executada de ponta a ponta no ambiente onde o código foi desenvolvido (sem acesso à rede). Rode o teste da seção 5 antes do pipeline completo.

**No documento de padrões**
- **Nome antigo em dois pontos.** O M4.3 foi renomeado para "Contadores", mas a observação do M4.4 ("diferindo do padrão de Acumuladores acima") e a introdução do Módulo 4 ("acumuladores") ainda usam o nome antigo.
- **Acúmulo não unitário no `while`** ficou sem padrão (ver acima). Há duas saídas: acrescentar um padrão ao M4 ou aceitar a categoria como não documentada.
- **Indentação de código.** Pela extração do layout do PDF, o `while` do M4.5 e o `for` do M5.3.1 estão mais recuados que as linhas vizinhas, o que faz o código copiado não executar. Nos M4.3 e M5.1.1, o comentário quebra de linha e a continuação vai para a margem esquerda, fora do bloco.
- **Texto repetido no M6.** A frase "Laço for cujo limite vem de um valor numérico…" aparece logo depois da introdução do módulo, que já diz o mesmo.
- **Título do Módulo 2.** "Condicional Simples e Composto- Estrutura condicional isolada" tem o hífen colado e o subtítulo descreve só o simples.
- **Exemplo Padrão** existe apenas em M1 e M6.
- **"Isolada" × "Isolado".** O subtítulo do Módulo 2 e a variante "Isolado" das tabelas usam a mesma palavra com sentidos diferentes.