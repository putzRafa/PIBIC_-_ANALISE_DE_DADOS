import ast
from pathlib import Path
import pandas as pd
from tqdm import tqdm
from collections import Counter

try:
    from radon.raw import analyze as radon_analyze
except ImportError as exc:
    raise ImportError(
        "A biblioteca 'radon' é necessária para calcular LLOC. "
        "Instale com: pip install radon"
    ) from exc


class ASTMetricsExtractor(ast.NodeVisitor):
    def __init__(self):
        self.metrics = {
            'max_depth': 0,
            'num_loops': 0,
            'num_ifs': 0,
            'variaveis_unicas': set(),
            'complexidade_ciclomatica': 1,
            'num_funcoes': 0,
            'tem_recursao': 0
        }
        self.current_depth = 0

    def _enter_control_flow(self, node):
        self.current_depth += 1
        self.metrics['max_depth'] = max(self.metrics['max_depth'], self.current_depth)
        self.generic_visit(node)
        self.current_depth -= 1

    def visit_FunctionDef(self, node):
        self.metrics['num_funcoes'] += 1
        for sub_node in ast.walk(node):
            if isinstance(sub_node, ast.Call) and getattr(sub_node.func, 'id', None) == node.name:
                self.metrics['tem_recursao'] = 1
        self.generic_visit(node)

    def visit_If(self, node):
        self.metrics['num_ifs'] += 1
        self.metrics['complexidade_ciclomatica'] += 1
        self._enter_control_flow(node)

    def visit_For(self, node):
        self.metrics['num_loops'] += 1
        self.metrics['complexidade_ciclomatica'] += 1
        self._enter_control_flow(node)

    def visit_While(self, node):
        self.metrics['num_loops'] += 1
        self.metrics['complexidade_ciclomatica'] += 1
        self._enter_control_flow(node)

    def visit_ListComp(self, node):
        self.metrics['num_loops'] += 1
        self.metrics['complexidade_ciclomatica'] += 1
        # FIX (métricas): antes usava generic_visit puro e não contava a
        # comprehension na profundidade de aninhamento (max_depth), tratando-a
        # de forma diferente de for/while/if embora ela também seja um laço.
        self._enter_control_flow(node)

    def visit_DictComp(self, node):
        self.metrics['num_loops'] += 1
        self.metrics['complexidade_ciclomatica'] += 1
        self._enter_control_flow(node)

    def visit_SetComp(self, node):
        # FIX (métricas): set comprehensions não eram contabilizadas.
        self.metrics['num_loops'] += 1
        self.metrics['complexidade_ciclomatica'] += 1
        self._enter_control_flow(node)

    def visit_GeneratorExp(self, node):
        # FIX (métricas): geradores (ex.: sum(x for x in lista)) não eram
        # contabilizados como laço.
        self.metrics['num_loops'] += 1
        self.metrics['complexidade_ciclomatica'] += 1
        self._enter_control_flow(node)

    def visit_BoolOp(self, node):
        self.metrics['complexidade_ciclomatica'] += len(node.values) - 1
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.metrics['variaveis_unicas'].add(node.id)
        self.generic_visit(node)


class ASTPlanDetector(ast.NodeVisitor):
    """
    Classifica o código-fonte de acordo com os padrões descritos em
    "Padrões de Programação" (Módulos 1 a 6).
    """

    def __init__(self, global_metrics, posicoes=None):
        self.global_metrics = global_metrics
        self.pattern_counts = Counter()

        # {id(node): (tem_antes, tem_apos)} pré-calculado por
        # _mapa_posicoes_estruturas -- permite cruzar a posição com o TIPO
        # específico deste mesmo nó (Condicional simples/composto/
        # encadeado/aninhado), em vez de um agregado global desconectado.
        self.posicoes = posicoes or {}

        self.in_if = 0
        self.in_for = 0
        self.in_while = 0

    # ------------------------------------------------------------------ #
    # Condicionais (Módulos 2 e 3)
    # ------------------------------------------------------------------ #
    def visit_If(self, node):
        is_elif = getattr(node, 'is_elif', False)

        # Rótulos atribuídos especificamente a ESTE nó (um If pode receber
        # mais de um: ex. um if aninhado que também é, em si, um condicional
        # composto -- "aninhado" descreve a posição; "composto" descreve o
        # formato das próprias branches. Os dois são fatos simultâneos sobre
        # o mesmo nó, por isso são coletados numa lista, não um único rótulo).
        tipos_deste_no = []

        # FIX (bug crítico): a versão anterior marcava "Condicional aninhado"
        # sempre que in_if > 0, sem checar se o `if` atual era, na verdade, a
        # continuação de uma cadeia elif (que fica estruturalmente dentro do
        # `orelse` do `if` anterior, e por isso também "parecia" aninhado para
        # o AST). Isso fazia com que TODO if/elif/.../else fosse contado, de
        # forma incorreta, também como "Condicional aninhado" (M3.2), além de
        # "Condicional encadeado" (M3.1). Agora só conta como aninhado quando
        # o `if` não é um elo de uma cadeia elif.
        if self.in_if > 0 and not is_elif:
            self.pattern_counts["Condicional aninhado"] += 1
            tipos_deste_no.append("Condicional aninhado")

        if is_elif:
            # Já foi classificado pelo `if` raiz da cadeia; apenas segue a árvore.
            pass
        else:
            # M2.2 - Condicional simples (sem else)
            if len(node.orelse) == 0:
                self.pattern_counts["Condicional simples"] += 1
                tipos_deste_no.append("Condicional simples")

            # M3.1 - Condicional encadeado (if/elif/.../else)
            elif len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                self.pattern_counts["Condicional encadeado"] += 1
                tipos_deste_no.append("Condicional encadeado")

                # Marca toda a cadeia de elifs para não contá-la de novo nem
                # como um novo "if" nem como "aninhado".
                curr = node
                while len(curr.orelse) == 1 and isinstance(curr.orelse[0], ast.If):
                    curr = curr.orelse[0]
                    curr.is_elif = True

            # M2.1 - Condicional composto (if/else)
            else:
                self.pattern_counts["Condicional composto"] += 1
                tipos_deste_no.append("Condicional composto")

        # Cruzamento tipo x posição (ver _mapa_posicoes_estruturas): usa a
        # posição REAL deste nó específico, não uma contagem global agregada.
        #
        # FIX: a versão anterior incrementava "com operação antes" e "com
        # operação após" de forma INDEPENDENTE. Isso criava uma ambiguidade
        # real: um arquivo com 1 if que tem antes E depois ao mesmo tempo
        # gerava exatamente os mesmos números (Com_Antes=1, Com_Apos=1) que
        # um arquivo com 2 ifs SEPARADOS -- um só com antes, outro só com
        # depois -- tornando os dois cenários indistinguíveis no CSV.
        #
        # Agora cada ocorrência cai em exatamente 1 de 4 categorias
        # mutuamente exclusivas, então a soma das 4 colunas de um tipo
        # sempre bate com o total de ocorrências daquele tipo, e "dupla
        # operação" (antes e depois no mesmo nó) vira uma categoria própria,
        # distinta de "só antes" + "só depois" em nós diferentes.
        tem_antes, tem_apos = self.posicoes.get(id(node), (False, False))
        if tem_antes and tem_apos:
            categoria_posicao = "dupla operação (antes e após)"
        elif tem_antes:
            categoria_posicao = "só operação antes"
        elif tem_apos:
            categoria_posicao = "só operação após"
        else:
            categoria_posicao = "isolado (sem antes/depois)"

        for tipo in tipos_deste_no:
            # Prefixo "SUBPOS::" identifica rótulos de sub-padrão cruzado,
            # para serem filtrados de fora de `padroes_str` em analisar_arquivo.
            self.pattern_counts[f"SUBPOS::{tipo}::{categoria_posicao}"] += 1

        self.in_if += 1
        self.generic_visit(node)
        self.in_if -= 1

    # ------------------------------------------------------------------ #
    # Laços (Módulos 4, 5 e 6)
    # ------------------------------------------------------------------ #
    def visit_For(self, node):
        self.in_for += 1

        if isinstance(node.iter, ast.Call) and getattr(node.iter.func, 'id', None) == 'range':
            # M5.1 / M5.2 / M5.3 / M6.1 / M6.2 - iteração por índice
            self.pattern_counts["Estrutura linear (lista/string) - iteração por índice"] += 1
        elif isinstance(node.iter, (ast.Name, ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Call, ast.Constant)):
            # FIX: a versão anterior só reconhecia Name/List/Tuple/Str (e
            # `ast.Str` está depreciado desde o Python 3.8 e será removido no
            # 3.14). Um `for` sobre uma chamada como `enumerate(lista)`,
            # `dicionario.items()`, `zip(a, b)` ou sobre uma string literal
            # (ex.: `for c in "abc":`) não era classificado em NENHUM padrão.
            # Agora usamos `ast.Constant` (API atual) e também cobrimos
            # `ast.Call`, `ast.Set` e `ast.Dict`.
            self.pattern_counts["Estrutura linear (lista/string) - iteração por valor"] += 1

        self.generic_visit(node)
        self.in_for -= 1

    @staticmethod
    def _tem_operacao_acumulo(node_laco):
        """
        Verifica se existe, em qualquer ponto do corpo do laço, uma operação
        aritmética de acúmulo/incremento (AugAssign ou Assign autoreferente
        com Add/Sub/Mult/Div/FloorDiv). Usado para DISTINGUIR M4.1/M4.2 (sem
        acúmulo) de M4.3/M4.4/M4.5 (com acúmulo).
        """
        ops_aritmeticas = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)
        for sub in ast.walk(node_laco):
            if sub is node_laco:
                continue
            if isinstance(sub, ast.AugAssign) and isinstance(sub.op, ops_aritmeticas):
                return True
            if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.BinOp) \
                    and isinstance(sub.value.op, ops_aritmeticas):
                alvos = {t.id for t in sub.targets if isinstance(t, ast.Name)}
                nomes_no_valor = {n.id for n in ast.walk(sub.value) if isinstance(n, ast.Name)}
                if alvos & nomes_no_valor:
                    return True
        return False

    @staticmethod
    def _tem_if_interno(node_laco):
        return any(isinstance(n, ast.If) for n in ast.walk(node_laco) if n is not node_laco)

    def _eh_validacao_entrada(self, node):
        """
        Critério AST para M4.1 (Validação de entrada com repetição até valor
        válido): while SEM if interno, SEM acúmulo aritmético, cuja condição
        de parada referencia uma variável reatribuída dentro do corpo (ex.:
        `while valor != valor_esperado: valor = input()`).
        """
        if self._tem_if_interno(node):
            return False
        if self._tem_operacao_acumulo(node):
            return False

        nomes_na_condicao = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if not nomes_na_condicao:
            return False

        for stmt in ast.walk(node):
            if stmt is node:
                continue
            if isinstance(stmt, ast.Assign):
                alvos = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
                if alvos & nomes_na_condicao:
                    return True
        return False

    def _eh_menu(self, node):
        """
        Critério AST para M4.2 (Exibição de menus): while com condição
        literalmente True, contendo pelo menos um if interno, SEM nenhuma
        operação de acúmulo aritmético (o que a distingue de M4.4/M4.5, que
        também têm if dentro de while, mas COM acúmulo).
        """
        condicao_sempre_verdadeira = isinstance(node.test, ast.Constant) and node.test.value is True
        if not condicao_sempre_verdadeira:
            return False
        if not self._tem_if_interno(node):
            return False
        if self._tem_operacao_acumulo(node):
            return False
        return True

    def visit_While(self, node):
        self.in_while += 1

        # Os dois critérios são mutuamente excludentes por construção: M4.2
        # exige `if` interno e M4.1 exige a ausência dele -- por isso a ordem
        # de checagem aqui não afeta o resultado.
        if self._eh_menu(node):
            self.pattern_counts["Repetição - controle por menu"] += 1
        elif self._eh_validacao_entrada(node):
            self.pattern_counts["Repetição - validação de entrada"] += 1

        self.generic_visit(node)
        self.in_while -= 1

    # ------------------------------------------------------------------ #
    # Comprehensions (antes ignoradas pelo detector de padrões)
    # ------------------------------------------------------------------ #
    def _classifica_comprehension(self, node):
        # FIX: o extrator de métricas (ASTMetricsExtractor) já contava
        # list/dict comprehensions como laço, mas o classificador de padrões
        # (ASTPlanDetector) nunca implementava visit_ListComp/visit_DictComp.
        # Um código cujo único "laço" fosse uma comprehension (muito comum em
        # soluções Python mais idiomáticas) não disparava nenhum padrão e
        # acabava caindo, incorretamente, em "Input/output sequencial" ou em
        # "Sem Padrão Mapeado".
        for generator in node.generators:
            if isinstance(generator.iter, ast.Call) and getattr(generator.iter.func, 'id', None) == 'range':
                self.pattern_counts["Estrutura linear (lista/string) - iteração por índice"] += 1
            else:
                self.pattern_counts["Estrutura linear (lista/string) - iteração por valor"] += 1
        self.generic_visit(node)

    def visit_ListComp(self, node):
        self._classifica_comprehension(node)

    def visit_DictComp(self, node):
        self._classifica_comprehension(node)

    def visit_SetComp(self, node):
        self._classifica_comprehension(node)

    def visit_GeneratorExp(self, node):
        self._classifica_comprehension(node)

    # ------------------------------------------------------------------ #
    # Contadores e acumuladores (Módulos 4 e 6)
    # ------------------------------------------------------------------ #
    def _classifica_incremento_acumulo(self, is_increment):
        """
        FIX (bug crítico): a versão anterior rotulava QUALQUER incremento ou
        acúmulo dentro de um `while` como "Repetição com condição", inclusive
        o padrão M4.3 (Acumuladores), que NÃO possui `if` interno -- apenas a
        própria condição do `while`. Isso misturava, sob o mesmo rótulo, o
        padrão M4.3 (incondicional) com os padrões M4.5/M4.6 (condicionados
        por um `if` interno ao laço). Agora o rótulo "com condição" só é
        usado quando o incremento/acúmulo realmente está dentro de um `if`
        (in_if > 0); caso contrário, usa-se o rótulo genérico M4.3/M6.
        """
        se_condicionado = self.in_if > 0

        if self.in_for > 0:
            if se_condicionado:
                key = "Repetição com condição - incremento de variável" if is_increment \
                    else "Repetição com condição - acúmulo de variável"
            else:
                key = "Repetição - incremento de variável" if is_increment \
                    else "Repetição - acúmulo de variável"
            self.pattern_counts[key] += 1

        if self.in_while > 0:
            if se_condicionado:
                # M4.5 / M4.6
                key = "Repetição com condição - incremento de variável" if is_increment \
                    else "Repetição com condição - acúmulo de variável"
            else:
                # M4.3
                key = "Repetição - incremento de variável" if is_increment \
                    else "Repetição - acúmulo de variável"
            self.pattern_counts[key] += 1

    @staticmethod
    def _eh_passo_unitario(op, valor_constante):
        # FIX: a versão anterior classificava como "incremento" qualquer
        # atribuição cujo operando constante fosse 1, SEM checar o operador.
        # Isso incluía até casos sem sentido, como `x *= 1` ou `x /= 1`.
        # Agora só é "incremento" quando o passo é +1 ou -1 (contador simples),
        # e qualquer outro operador (*, /, //) ou passo diferente de 1 é
        # tratado como "acúmulo".
        return isinstance(op, (ast.Add, ast.Sub)) and valor_constante == 1

    def visit_AugAssign(self, node):
        if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)):
            # FIX (bug crítico): a versão anterior só considerava Add/Sub, o
            # que fazia o padrão M6.2 (Séries numéricas, ex.: fatorial com
            # `fatorial *= i`) nunca ser detectado quando escrito com `*=`.
            is_increment = (
                isinstance(node.value, ast.Constant)
                and self._eh_passo_unitario(node.op, node.value.value)
            )
            self._classifica_incremento_acumulo(is_increment)
        self.generic_visit(node)

    def visit_Assign(self, node):
        if isinstance(node.value, ast.BinOp) and isinstance(
            node.value.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)
        ):
            # FIX: adicionados Mult/Div/FloorDiv para cobrir
            # `fatorial = fatorial * i` (M6.2), que antes era ignorado.
            targets = [getattr(t, 'id', None) for t in node.targets if isinstance(t, ast.Name)]
            left = getattr(node.value.left, 'id', None) if isinstance(node.value.left, ast.Name) else None
            right = getattr(node.value.right, 'id', None) if isinstance(node.value.right, ast.Name) else None

            for t in targets:
                if t is not None and (t == left or t == right):
                    is_increment = False
                    if isinstance(node.value.right, ast.Constant):
                        is_increment = self._eh_passo_unitario(node.value.op, node.value.right.value)
                    elif isinstance(node.value.left, ast.Constant):
                        is_increment = self._eh_passo_unitario(node.value.op, node.value.left.value)

                    self._classifica_incremento_acumulo(is_increment)
                    # FIX: `break` evitava contagem duplicada quando há mais
                    # de um alvo na mesma atribuição (ex.: `x = y = x + 1`).
                    break

        self.generic_visit(node)


def _mapa_posicoes_estruturas(tree):
    """
    Pré-calcula, para CADA nó If/For/While do arquivo, se existe alguma
    instrução antes e/ou depois dele na lista de instruções (body/orelse/
    finalbody) que o contém -- indexado por id(node).

    É o que permite ao ASTPlanDetector cruzar a posição com o tipo
    estrutural do MESMO nó (ex.: "este if específico, já classificado como
    Condicional composto, tem operação antes?"), em vez de um agregado
    global desconectado do tipo (que é o que detectar_subpadroes_posicionais
    continua fazendo, propositalmente, para os sub-padrões de laço).
    """
    posicoes = {}
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            lista_stmts = getattr(node, attr, None)
            if not isinstance(lista_stmts, list):
                continue
            for idx, stmt in enumerate(lista_stmts):
                if isinstance(stmt, (ast.If, ast.For, ast.While)):
                    # cada stmt pertence a exatamente uma lista de
                    # instruções (seu único pai sintático), então id(stmt)
                    # nunca é sobrescrito por engano aqui.
                    posicoes[id(stmt)] = _bloco_tem_vizinhos(lista_stmts, idx)
    return posicoes


def _bloco_tem_vizinhos(lista_stmts, idx):
    """Retorna (tem_antes, tem_apos) para a instrução no índice `idx`
    dentro da lista de instruções `lista_stmts` que a contém."""
    tem_antes = idx > 0
    tem_apos = idx < len(lista_stmts) - 1
    return tem_antes, tem_apos


def _variavel_inicializada_e_atualizada(stmt_antes, no_laco):
    """
    Sub-padrão 5: verifica se `stmt_antes` é uma atribuição simples
    (`var = <algo>`) e se essa mesma variável é reatribuída em algum ponto
    dentro do corpo do laço (`no_laco`), via Assign ou AugAssign.

    Generaliza o conceito de "acumulador" (M4.3-M4.5, M5.2, M6.1, M6.2) para
    qualquer variável de estado/controle inicializada antes do laço e
    modificada dentro dele -- cobre também M5.1 (maior = lista[i], que não é
    autoreferente), M4.2 (opcao = input(), estado do menu) e M4.1 (valor
    relido a cada iteração).
    """
    if not isinstance(stmt_antes, ast.Assign):
        return False

    nomes_alvo = {t.id for t in stmt_antes.targets if isinstance(t, ast.Name)}
    if not nomes_alvo:
        return False

    for sub_node in ast.walk(no_laco):
        if isinstance(sub_node, ast.AugAssign) and isinstance(sub_node.target, ast.Name):
            if sub_node.target.id in nomes_alvo:
                return True
        if isinstance(sub_node, ast.Assign):
            alvos_sub = {t.id for t in sub_node.targets if isinstance(t, ast.Name)}
            if alvos_sub & nomes_alvo:
                return True

    return False


def detectar_subpadroes_posicionais(tree):
    """
    Detecta os sub-padrões estruturais de POSIÇÃO (antes/dentro/após) que o
    documento de padrões já anotava nos comentários do esqueleto de código
    (ex.: "# operações antes do condicional", "# operações antes do laço"),
    mas que nunca eram extraídos como feature pelo pipeline original.

    Diferente de ASTPlanDetector (que escolhe 1 padrão dominante por
    arquivo), aqui os sub-padrões NÃO são mutuamente exclusivos -- um mesmo
    `if` ou laço pode contribuir para múltiplas contagens ao mesmo tempo,
    por isso o resultado fica fora da lógica de hierarquia/dominância.
    """
    contagem = Counter()

    # Percorre toda lista de instruções do código (body/orelse/finalbody de
    # qualquer nó), para também capturar estruturas de controle aninhadas,
    # não só as de "topo" do arquivo/função.
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            lista_stmts = getattr(node, attr, None)
            if not isinstance(lista_stmts, list):
                continue

            for idx, stmt in enumerate(lista_stmts):
                tem_antes, tem_apos = _bloco_tem_vizinhos(lista_stmts, idx)

                if isinstance(stmt, ast.If):
                    if tem_antes:
                        contagem["If - operação antes do condicional"] += 1
                    if tem_apos:
                        contagem["If - operação após o condicional"] += 1

                elif isinstance(stmt, (ast.For, ast.While)):
                    if tem_antes:
                        contagem["Laço - operação antes do laço"] += 1
                        if _variavel_inicializada_e_atualizada(lista_stmts[idx - 1], stmt):
                            contagem["Laço - variável inicializada antes e atualizada dentro"] += 1
                    if tem_apos:
                        contagem["Laço - operação após o laço"] += 1

    return contagem


def analisar_arquivo(caminho_arquivo):
    try:
        with open(caminho_arquivo, "r", encoding="utf-8") as f:
            codigo = f.read()
            linhas_validas = [l for l in codigo.splitlines() if l.strip() and not l.strip().startswith('#')]
            loc = len(linhas_validas) if len(linhas_validas) > 0 else 1

            tree = ast.parse(codigo)

        extractor = ASTMetricsExtractor()
        extractor.visit(tree)
        metrics = extractor.metrics

        mapa_posicoes = _mapa_posicoes_estruturas(tree)

        detector = ASTPlanDetector(metrics, posicoes=mapa_posicoes)
        detector.visit(tree)

        subpadroes = detectar_subpadroes_posicionais(tree)

        # LLOC (linhas lógicas de código) via radon -- mais robusto que a
        # contagem de linhas física (LOC) feita acima, pois normaliza
        # statements que ocupam várias linhas físicas (parênteses, barras de
        # continuação) e statements múltiplos na mesma linha física (`;`).
        try:
            lloc = radon_analyze(codigo).lloc
            if not lloc:
                lloc = loc  # fallback: código sem lloc detectável (raro)
        except Exception:
            lloc = None  # radon falhou (ex.: tokenização); mantém LOC como única métrica confiável

        features = {
            'LOC': loc,
            'LLOC': lloc,
            'AST_Profundidade_Fluxo': metrics['max_depth'],
            'AST_Complexidade_Ciclomatica': metrics['complexidade_ciclomatica'],
            'AST_Qtd_Loops': metrics['num_loops'],
            'AST_Qtd_Ifs': metrics['num_ifs'],
            'AST_Qtd_Variaveis': len(metrics['variaveis_unicas']),
            'AST_Qtd_Funcoes': metrics['num_funcoes'],
            'AST_Tem_Recursao': metrics['tem_recursao'],
        }

        features['Norm_Complexidade_Por_LOC'] = round(features['AST_Complexidade_Ciclomatica'] / loc, 4)
        features['Norm_Ifs_Por_LOC'] = round(features['AST_Qtd_Ifs'] / loc, 4)
        features['Norm_Loops_Por_LOC'] = round(features['AST_Qtd_Loops'] / loc, 4)

        # Normalizações equivalentes usando LLOC (quando disponível), mais
        # fiéis para comparar exercícios com estilos de formatação distintos.
        if lloc:
            features['Norm_Complexidade_Por_LLOC'] = round(features['AST_Complexidade_Ciclomatica'] / lloc, 4)
            features['Norm_Ifs_Por_LLOC'] = round(features['AST_Qtd_Ifs'] / lloc, 4)
            features['Norm_Loops_Por_LLOC'] = round(features['AST_Qtd_Loops'] / lloc, 4)
        else:
            features['Norm_Complexidade_Por_LLOC'] = None
            features['Norm_Ifs_Por_LLOC'] = None
            features['Norm_Loops_Por_LLOC'] = None

        # Sub-padrões posicionais (ver relatório): não entram na hierarquia
        # de dominância, pois não são mutuamente exclusivos entre si nem com
        # o padrão dominante escolhido abaixo.
        subpadroes_mapeados = {
            "If - operação antes do condicional": "Sub_If_Operacao_Antes",
            "If - operação após o condicional": "Sub_If_Operacao_Apos",
            "Laço - operação antes do laço": "Sub_Laco_Operacao_Antes",
            "Laço - operação após o laço": "Sub_Laco_Operacao_Apos",
            "Laço - variável inicializada antes e atualizada dentro": "Sub_Laco_Var_Inicializada_Atualizada",
        }
        for chave, coluna in subpadroes_mapeados.items():
            features[coluna] = subpadroes.get(chave, 0)

        # Sub-padrões CRUZADOS (tipo específico x posição), calculados dentro
        # de ASTPlanDetector.visit_If usando a posição real de CADA nó. Ao
        # contrário dos Sub_If_Operacao_* acima (agregados globais, sem saber
        # qual tipo de if era), estes sabem exatamente a qual tipo pertencem
        # -- e, dentro de cada tipo, usam 4 categorias MUTUAMENTE EXCLUSIVAS
        # (isolado / só antes / só depois / dupla) em vez de 2 contadores
        # independentes, evitando a ambiguidade entre "1 if com antes+depois"
        # e "2 ifs separados, um só-antes + um só-depois" (ver conversa).
        # A soma das 4 colunas de um tipo sempre bate com o total de
        # ocorrências daquele tipo em padroes_str.
        _tipos_condicional = ["Condicional simples", "Condicional composto",
                               "Condicional encadeado", "Condicional aninhado"]
        _nome_coluna_tipo = {
            "Condicional simples": "Simples",
            "Condicional composto": "Composto",
            "Condicional encadeado": "Encadeado",
            "Condicional aninhado": "Aninhado",
        }
        # FIX (nomenclatura): alinhado com os nomes de coluna do documento de
        # padrões (Sub_<Tipo>_Antes / Sub_<Tipo>_Depois), que usa nomes mais
        # curtos que a versão anterior do código (que tinha "So_Antes"/"So_Apos").
        _categorias_posicao = {
            "isolado (sem antes/depois)": "Isolado",
            "só operação antes": "Antes",
            "só operação após": "Depois",
            "dupla operação (antes e após)": "Dupla",
        }
        for _tipo in _tipos_condicional:
            for _cat_chave, _cat_sufixo in _categorias_posicao.items():
                _chave = f"SUBPOS::{_tipo}::{_cat_chave}"
                _coluna = f"Sub_{_nome_coluna_tipo[_tipo]}_{_cat_sufixo}"
                features[_coluna] = detector.pattern_counts.get(_chave, 0)

        # M1 - Input/output sequencial
        if features['AST_Qtd_Loops'] == 0 and features['AST_Qtd_Ifs'] == 0:
            detector.pattern_counts["Input/output sequencial"] += 1

        # LÓGICA DE HIERARQUIA GLOBAL (mantém apenas o padrão mais complexo)
        # Ordem do mais difícil (listas) para o mais fácil (sequencial).
        # NOTA (ver relatório): por design, "Estrutura linear" domina qualquer
        # `for` sobre range()/lista, o que faz os padrões M6.1 (Somatórios) e
        # M6.2 (Séries numéricas) raramente aparecerem como padrão dominante
        # quando implementados com `for` -- eles ficam "escondidos" atrás de
        # "Estrutura linear - iteração por índice", já que M5.2 (Soma de
        # Vetor) e M6.1 (Somatórios) são, no documento de padrões, literalmente
        # o mesmo trecho de código. Isso é uma inconsistência do documento de
        # padrões, e não um bug deste script (ver relatório em anexo).
        ordem_complexidade = [
            "Estrutura linear (lista/string) - iteração por índice",
            "Estrutura linear (lista/string) - iteração por valor",
            "Repetição com condição - acúmulo de variável",
            "Repetição com condição - incremento de variável",
            "Repetição - acúmulo de variável",
            "Repetição - incremento de variável",
            # M4.2 e M4.1: laços sem acúmulo aritmético. Ficam abaixo dos
            # tiers numéricos (M4.3-M4.5), mas acima de qualquer condicional
            # isolado, pois já combinam laço (+ if/elif, no caso do menu).
            "Repetição - controle por menu",
            "Repetição - validação de entrada",
            "Condicional aninhado",
            "Condicional encadeado",
            "Condicional composto",
            "Condicional simples",
            "Input/output sequencial"
        ]

        padrao_dominante = None
        for p in ordem_complexidade:
            if detector.pattern_counts.get(p, 0) > 0:
                padrao_dominante = p
                break

        if padrao_dominante:
            for p in ordem_complexidade:
                if p != padrao_dominante:
                    detector.pattern_counts[p] = 0

        padroes_mapeados = [
            "Input/output sequencial",
            "Condicional simples",
            "Condicional composto",
            "Condicional encadeado",
            "Condicional aninhado",
            "Repetição por contagem - incremento de variável",
            "Repetição por contagem - acúmulo de variável",
            "Repetição com condição - incremento de variável",
            "Repetição com condição - acúmulo de variável",
            "Repetição - controle por menu",
            "Repetição - validação de entrada",
            "Estrutura linear (lista/string) - iteração por índice",
            "Estrutura linear (lista/string) - iteração por valor"
        ]

        for p in padroes_mapeados:
            features[f'Freq_{p.replace(" ", "_").replace("/", "_")}'] = detector.pattern_counts.get(p, 0)

        # FIX: exclui os rótulos cruzados (prefixo "SUBPOS::") do padroes_str
        # -- eles vivem em detector.pattern_counts para alimentar as colunas
        # Sub_*_Isolado/So_Antes/So_Apos/Dupla acima, mas não são padrões
        # dominantes por si só (são anotações sobre um padrão já listado),
        # então não devem aparecer duplicados dentro de padroes_str.
        encontrados = [
            p for p, count in detector.pattern_counts.items()
            if count > 0 and not p.startswith("SUBPOS::")
        ]
        features['padroes_str'] = "; ".join(encontrados) if encontrados else "Sem Padrão Mapeado"

        return features
    except Exception:
        return None


def processar_exercicios_v15(path_exercises):
    base_path = Path(path_exercises)
    resultados = []

    pastas_exercicios = [p for p in base_path.iterdir() if p.is_dir()]
    print(f"Encontradas {len(pastas_exercicios)} pastas em {base_path}")

    for pasta in tqdm(pastas_exercicios, desc="Extraindo Taxonomia Estrutural (V15)"):
        arquivos_py = list(pasta.glob("*.py"))
        arquivo_alvo = None

        if not arquivos_py:
            continue

        for py in arquivos_py:
            if "sample_solution" in py.name:
                arquivo_alvo = py
                break

        if not arquivo_alvo:
            arquivo_alvo = max(arquivos_py, key=lambda p: p.stat().st_size)

        features = analisar_arquivo(arquivo_alvo)

        if features:
            features['id_exercicio'] = pasta.name
            resultados.append(features)

    df = pd.DataFrame(resultados)
    cols = ['id_exercicio', 'padroes_str'] + [c for c in df.columns if c not in ['id_exercicio', 'padroes_str']]
    return df[cols]


# EXECUÇÃO DO PIPELINE
caminho_do_script = Path(__file__).parent
#pasta_testes = caminho_do_script.parent
arquivos_gerais_pibic = caminho_do_script.parent

caminho_exercises = arquivos_gerais_pibic / "DataSet" / "exerciciosSolucao"

df_features_final = processar_exercicios_v15(caminho_exercises)

if not df_features_final.empty:
    output_file = caminho_do_script /"resultado_analise_padroes" / "features_ast_padroes_completos.csv"
    df_features_final.to_csv(output_file, index=False)
    print(f"\nSucesso! Arquivo V15 salvo em: {output_file}")