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
│   ├── resultado_analise_padroes/
│   │   └── features_ast_padroes_completos.csv      # saída do pipeline (uma linha por exercício)
│   └── classifcacaoDePadroes.py           # script de extração (versão v15 desta documentação)
├── DataSet/
│   ├── exerciciosSolucao/                # soluções dos exercícios
│   ├── exerciciosSolucao_-_Assessments/         # (conteúdo não detalhado)
│   └── transactions/                     # (conteúdo não detalhado)
└── .gitignore
```

---

## 2. Padrões de programação (documento de padrões)

Os padrões estão organizados em 6 módulos, por complexidade crescente. Cada padrão tem um código de referência (M*x.y*) e um critério de reconhecimento via AST.

| Módulo | Padrão | Critério AST (resumo) | Categoria no classificador |
|---|---|---|---|
| **M1** Sequencial | M1.1–M1.4 (médias, conversões, fórmulas, saída formatada) | Sem `if` e sem laço | `Input/output sequencial` |
| **M2** Condicionais | M2.1 Composto (`if/else`) | `If` com `orelse` que não é outro `If` | `Condicional composto` |
| | M2.2 Simples (`if` isolado) | `If` sem `orelse` | `Condicional simples` |
| **M3** Encadeado/aninhado | M3.1 Encadeado (`if/elif/else`) | `If` cujo `orelse` é um único `If` (cadeia inteira conta como 1) | `Condicional encadeado` |
| | M3.2 Aninhado | `If` dentro do corpo de outro `If` (um `elif` **não** conta como aninhamento) | `Condicional aninhado` |
| **M4** `while` | M4.1 Validação de entrada | `while` sem `if` interno, sem acúmulo aritmético, cuja condição usa variável reatribuída no corpo (ex.: `input()`) | `Repetição - validação de entrada` |
| | M4.2 Menu | `while True` com `if/elif` interno e sem acúmulo aritmético | `Repetição - controle por menu` |
| | M4.3 Acumuladores | Incremento/acúmulo dentro do `while`, **sem** `if` envolvendo a operação | `Repetição - incremento/acúmulo de variável` |
| | M4.4 Condição interna + incremento | Incremento (`+1`/`-1`) dentro de um `if` no `while` | `Repetição com condição - incremento de variável` |
| | M4.5 Condição interna + acúmulo | Acúmulo dentro de um `if` no `while` | `Repetição com condição - acúmulo de variável` |
| **M5** Vetores e strings | M5.1 Maior/Menor, M5.2 Soma, M5.3 Contagem de frequência | `for` sobre `range(...)` (iteração por **índice**) ou direto sobre a coleção (iteração por **valor**) | `Estrutura linear (lista/string) - iteração por índice/valor` |
| **M6** `for` por contagem | M6.1 Somatórios, M6.2 Séries numéricas (fatorial, Fibonacci) | `for` com acúmulo aditivo ou multiplicativo | `Estrutura linear …` (ver limitações) |

### Hierarquia de dominância

Quando um arquivo ativa vários padrões, apenas o **mais complexo** é mantido como padrão dominante (`padroes_str`). Ordem, do mais complexo ao mais simples:

1. Estrutura linear - iteração por índice
2. Estrutura linear - iteração por valor
3. Repetição com condição - acúmulo de variável
4. Repetição com condição - incremento de variável
5. Repetição - acúmulo de variável
6. Repetição - incremento de variável
7. Repetição - controle por menu
8. Repetição - validação de entrada
9. Condicional aninhado
10. Condicional encadeado
11. Condicional composto
12. Condicional simples
13. Input/output sequencial

As posições 7 e 8 (menu e validação) foram definidas nesta documentação por critério pedagógico: são laços, portanto acima de qualquer condicional isolado, mas sem acúmulo numérico, portanto abaixo de M4.3–M4.5. Vale validar essa ordem com o orientador.

### Incremento × acúmulo

- **Incremento:** passo unitário (`+= 1`, `-= 1`, `x = x + 1`).
- **Acúmulo:** qualquer outra atualização da própria variável (`+= valor`, `*= i`, `x = x * i`, `/`, `//`).

---

## 3. Sub-padrões posicionais

Além do padrão principal, o pipeline registra **onde estão as operações em relação à estrutura de controle**: antes, depois, ambas ou nenhuma. Essa dimensão já aparecia nos comentários do documento de padrões (`# operações antes do condicional`), mas nunca era extraída.

### 3.1 Cruzamento tipo × posição (condicionais, M2 e M3)

Para cada `if` individual, o classificador combina o tipo (simples, composto, encadeado, aninhado) com a posição daquele mesmo nó. Cada ocorrência cai em **exatamente uma** de 4 categorias mutuamente exclusivas:

| Variação | Operação antes? | Operação depois? | Coluna |
|---|---|---|---|
| Isolado | Não | Não | `Sub_<Tipo>_Isolado` |
| Só antes | Sim | Não | `Sub_<Tipo>_Antes` |
| Só depois | Não | Sim | `Sub_<Tipo>_Depois` |
| Ambos | Sim | Sim | `Sub_<Tipo>_Dupla` |

`<Tipo>` ∈ {`Simples`, `Composto`, `Encadeado`, `Aninhado`}, o que gera **16 colunas**.

**Por que categorias exclusivas?** Com dois contadores independentes (`Com_Antes`, `Com_Depois`), um arquivo com 1 `if` que tem operação antes **e** depois produz o mesmo resultado que um arquivo com 2 `if`s separados (um só com antes, outro só com depois). Com categorias exclusivas, os dois casos são distinguíveis e a soma das 4 colunas de um tipo é igual ao total de ocorrências daquele tipo.

**Observação:** um `if` aninhado também tem seu próprio formato de branch (por exemplo, composto). Ele contribui ao mesmo tempo para `Sub_Aninhado_*` e `Sub_Composto_*`, com a mesma posição. Isso é esperado, pois são dois fatos verdadeiros sobre o mesmo nó.

### 3.2 Sub-padrões globais (laços e condicionais, agregados por arquivo)

Contagens independentes do padrão dominante, não mutuamente exclusivas:

| Coluna | Significado |
|---|---|
| `Sub_If_Operacao_Antes` / `Sub_If_Operacao_Apos` | `if`s com instrução antes / depois no mesmo bloco |
| `Sub_Laco_Operacao_Antes` / `Sub_Laco_Operacao_Apos` | laços (`for`/`while`) com instrução antes / depois |
| `Sub_Laco_Var_Inicializada_Atualizada` | variável atribuída logo antes do laço e reatribuída dentro dele (acumuladores, contadores, valor-base de comparação, estado de menu) |

---

## 4. Features extraídas (colunas do CSV)

Uma linha por exercício. O script usa o arquivo com `sample_solution` no nome; se não houver, usa o maior `.py` da pasta.

**Identificação**

| Coluna | Descrição |
|---|---|
| `id_exercicio` | nome da pasta do exercício |
| `padroes_str` | padrão dominante (ou `Sem Padrão Mapeado`) |

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

`Freq_<padrão>`: uma coluna por categoria de padrão, com a contagem após aplicar a hierarquia de dominância (apenas a categoria dominante fica diferente de zero). Ex.: `Freq_Repetição_-_controle_por_menu`.

**Sub-padrões**

`Sub_*` conforme a seção 3.

---