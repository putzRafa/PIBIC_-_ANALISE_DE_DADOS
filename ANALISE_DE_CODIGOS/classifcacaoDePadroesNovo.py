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


# Módulo do documento de padrões (v7) a que cada padrão dominante pertence.
#   M1 sequencial | M2 condicional simples | M3 condicional composto
#   M4 encadeado/aninhado | M5 while | M6 estrutura linear (for sobre coleção)
#   M7 repetição por contagem (for sobre contagem numérica)
MODULO_POR_PADRAO = {
    "Input/output sequencial": "M1",
    "Condicional simples": "M2",
    "Condicional composto": "M3",
    "Condicional encadeado": "M4",
    "Condicional aninhado": "M4",
    "Repetição - validação de entrada": "M5",
    "Repetição - controle por menu": "M5",
    "Repetição - incremento de variável": "M5",
    "Repetição - acúmulo de variável": "M5",
    "Repetição com condição - incremento de variável": "M5",
    "Repetição com condição - acúmulo de variável": "M5",
    "Estrutura linear (lista/string) - iteração por índice": "M6",
    "Estrutura linear (lista/string) - iteração por valor": "M6",
    "Repetição por contagem - incremento de variável": "M7",
    "Repetição por contagem - acúmulo de variável": "M7",
}

OPS_ARITMETICAS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)
OPS_MULTIPLICATIVAS = (ast.Mult, ast.Div, ast.FloorDiv)


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
        self._enter_control_flow(node)

    def visit_DictComp(self, node):
        self.metrics['num_loops'] += 1
        self.metrics['complexidade_ciclomatica'] += 1
        self._enter_control_flow(node)

    def visit_SetComp(self, node):
        self.metrics['num_loops'] += 1
        self.metrics['complexidade_ciclomatica'] += 1
        self._enter_control_flow(node)

    def visit_GeneratorExp(self, node):
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
    "Padrões de Programação" (Módulos 1 a 7):

        M1 sequencial            M5 repetição por condição (while)
        M2 condicional simples   M6 estrutura linear (for sobre coleção)
        M3 condicional composto  M7 repetição por contagem (for sobre range numérico)
        M4 encadeado/aninhado
    """

    def __init__(self, global_metrics, posicoes=None):
        self.global_metrics = global_metrics
        self.pattern_counts = Counter()

        # {id(node): (tem_antes, tem_apos)} pré-calculado por
        # _mapa_posicoes_estruturas -- permite cruzar a posição com o TIPO
        # específico deste mesmo nó.
        self.posicoes = posicoes or {}

        self.in_if = 0

        # Pilha de laços ativos. Cada item guarda o tipo do laço ('for' ou
        # 'while'), a classe do `for` ('indice', 'valor' ou 'contagem') e o
        # valor de in_if no momento em que o laço foi aberto -- este último
        # permite saber se um incremento/acúmulo está condicionado por um `if`
        # DENTRO do laço, e não por um `if` que apenas envolve o laço.
        self.pilha_lacos = []

        # Raiz (`if` mais externo) da estrutura condicional em visita.
        self._raiz_if = None

    # ------------------------------------------------------------------ #
    # Condicionais (Módulos 2, 3 e 4)
    # ------------------------------------------------------------------ #
    def visit_If(self, node):
        is_elif = getattr(node, 'is_elif', False)

        # O `if` mais externo da estrutura é a RAIZ. É ele que define a
        # posição (antes/depois) do padrão "Condicional aninhado" (M4.2).
        eh_raiz = (self.in_if == 0)
        if eh_raiz:
            self._raiz_if = node
            node.tem_aninhado = False

        # Rótulos de formato atribuídos a ESTE nó (simples/composto/encadeado).
        tipos_deste_no = []

        # Um `if` dentro de outro `if` (que não seja elo de uma cadeia elif)
        # marca a raiz como estrutura aninhada. A contagem do aninhado é
        # feita UMA VEZ POR ESTRUTURA, no fim desta função, na raiz.
        if self.in_if > 0 and not is_elif:
            self._raiz_if.tem_aninhado = True

        if is_elif:
            # Já foi classificado pelo `if` raiz da cadeia; apenas segue a árvore.
            pass
        else:
            # M2.1 - Condicional simples (sem else)
            if len(node.orelse) == 0:
                self.pattern_counts["Condicional simples"] += 1
                tipos_deste_no.append("Condicional simples")

            # M4.1 - Condicional encadeado (if/elif/.../else)
            elif len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                self.pattern_counts["Condicional encadeado"] += 1
                tipos_deste_no.append("Condicional encadeado")

                # Marca toda a cadeia de elifs para não contá-la de novo nem
                # como um novo "if" nem como "aninhado".
                curr = node
                while len(curr.orelse) == 1 and isinstance(curr.orelse[0], ast.If):
                    curr = curr.orelse[0]
                    curr.is_elif = True

            # M3.1 - Condicional composto (if/else)
            else:
                self.pattern_counts["Condicional composto"] += 1
                tipos_deste_no.append("Condicional composto")

        # Cruzamento tipo x posição: cada ocorrência cai em exatamente 1 de 4
        # categorias mutuamente exclusivas (isolado / só antes / só depois /
        # dupla), usando a posição REAL deste nó.
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
            # filtrados de `padroes_str` em analisar_arquivo.
            self.pattern_counts[f"SUBPOS::{tipo}::{categoria_posicao}"] += 1

        self.in_if += 1
        self.generic_visit(node)
        self.in_if -= 1

        # M4.2 - Condicional aninhado: medido ao redor do `if` MAIS EXTERNO
        # da estrutura (a raiz), e contado uma vez por estrutura. Antes, a
        # posição era a do `if` interno dentro do ramo do externo, o que não
        # correspondia ao exemplo do documento (operações antes/depois do
        # `if` externo).
        if eh_raiz and getattr(node, 'tem_aninhado', False):
            self.pattern_counts["Condicional aninhado"] += 1
            self.pattern_counts[f"SUBPOS::Condicional aninhado::{categoria_posicao}"] += 1

    # ------------------------------------------------------------------ #
    # Laços for (Módulos 6 e 7)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _range_usa_len(chamada_range):
        """True se algum argumento do range() contém uma chamada a len()."""
        for sub in ast.walk(chamada_range):
            if isinstance(sub, ast.Call) and getattr(sub.func, 'id', None) == 'len':
                return True
        return False

    @staticmethod
    def _nomes_do_alvo(alvo):
        return {n.id for n in ast.walk(alvo) if isinstance(n, ast.Name)}

    @classmethod
    def _variavel_indexa_colecao(cls, no_busca, alvo):
        """
        True se, dentro de `no_busca`, a variável do laço (`alvo`) aparece
        dentro de um índice (`lista[i]`, `lista[i + 1]`, `m[i][j]`...).
        """
        nomes = cls._nomes_do_alvo(alvo)
        if not nomes:
            return False
        for sub in ast.walk(no_busca):
            if isinstance(sub, ast.Subscript):
                for n in ast.walk(sub.slice):
                    if isinstance(n, ast.Name) and n.id in nomes:
                        return True
        return False

    def _classifica_for(self, node):
        """
        Classifica o `for` de acordo com o documento de padrões:

          'indice'    -> M6 (iteração por índice): range() cujo limite vem do
                         tamanho de uma coleção (`range(len(x))`) OU cuja
                         variável é usada para indexar uma coleção (`x[i]`).
          'valor'     -> M6 (iteração por valor): percorre a coleção direto.
          'contagem'  -> M7: range() numérico, sem len() e sem indexar
                         coleção; a variável é um contador usado na conta.
        """
        iterador = node.iter

        if isinstance(iterador, ast.Call) and getattr(iterador.func, 'id', None) == 'range':
            corpo = ast.Module(body=node.body, type_ignores=[])
            if self._range_usa_len(iterador) or self._variavel_indexa_colecao(corpo, node.target):
                return "indice"
            return "contagem"

        if isinstance(iterador, (ast.Name, ast.List, ast.Tuple, ast.Set,
                                 ast.Dict, ast.Call, ast.Constant)):
            return "valor"

        return None

    def visit_For(self, node):
        tipo_for = self._classifica_for(node)

        if tipo_for == "indice":
            self.pattern_counts["Estrutura linear (lista/string) - iteração por índice"] += 1
        elif tipo_for == "valor":
            self.pattern_counts["Estrutura linear (lista/string) - iteração por valor"] += 1
        # 'contagem' (M7) não gera rótulo aqui: o padrão é identificado pelo
        # tipo de atualização do acumulador dentro do laço
        # (ver _classifica_incremento_acumulo).

        self.pilha_lacos.append({'tipo': 'for', 'tipo_for': tipo_for, 'if_base': self.in_if})
        self.generic_visit(node)
        self.pilha_lacos.pop()

    # ------------------------------------------------------------------ #
    # Laços while (Módulo 5)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _tem_operacao_acumulo(node_laco):
        """
        Verifica se existe, em qualquer ponto do corpo do laço, uma operação
        aritmética de acúmulo/incremento (AugAssign ou Assign autoreferente).
        Distingue M5.1/M5.2 (sem acúmulo) de M5.3/M5.4/M5.5 (com acúmulo).
        """
        for sub in ast.walk(node_laco):
            if sub is node_laco:
                continue
            if isinstance(sub, ast.AugAssign) and isinstance(sub.op, OPS_ARITMETICAS):
                return True
            if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.BinOp) \
                    and isinstance(sub.value.op, OPS_ARITMETICAS):
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
        Critério AST para M5.1 (Validação de entrada): while SEM if interno,
        SEM acúmulo aritmético, cuja condição de parada referencia uma
        variável reatribuída dentro do corpo (ex.: `valor = input()`).
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
        Critério AST para M5.2 (Exibição de menus): while com condição
        literalmente True, com pelo menos um if interno e SEM acúmulo
        aritmético (o que o distingue de M5.4/M5.5).
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
        # M5.1 e M5.2 são mutuamente excludentes por construção (M5.2 exige
        # `if` interno e M5.1 exige a ausência dele).
        if self._eh_menu(node):
            self.pattern_counts["Repetição - controle por menu"] += 1
        elif self._eh_validacao_entrada(node):
            self.pattern_counts["Repetição - validação de entrada"] += 1

        self.pilha_lacos.append({'tipo': 'while', 'tipo_for': None, 'if_base': self.in_if})
        self.generic_visit(node)
        self.pilha_lacos.pop()

    # ------------------------------------------------------------------ #
    # Comprehensions
    # ------------------------------------------------------------------ #
    def _classifica_comprehension(self, node):
        # Mesma regra do `for`: percorrer coleção = M6; range numérico sem
        # acúmulo não corresponde a nenhum padrão documentado.
        for generator in node.generators:
            iterador = generator.iter
            if isinstance(iterador, ast.Call) and getattr(iterador.func, 'id', None) == 'range':
                if self._range_usa_len(iterador) or self._variavel_indexa_colecao(node, generator.target):
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
    # Contadores e acumuladores (Módulos 5 e 7)
    # ------------------------------------------------------------------ #
    def _classifica_incremento_acumulo(self, is_increment, op):
        """
        Rotula o incremento/acúmulo de acordo com o laço MAIS INTERNO:

          while, sem `if` interno ao laço  -> M5.3 (Repetição - ...)
          while, dentro de `if` do laço    -> M5.4/M5.5 (Repetição com condição - ...)
          for de contagem numérica         -> M7 (Repetição por contagem - ...)
          for sobre coleção (M6)           -> sem rótulo próprio: a operação já
                                              faz parte do padrão Estrutura linear.

        Para M7 também é registrada a família da operação (aditiva ou
        multiplicativa), que separa M7.1 (Somatórios) de M7.2 (Séries).
        """
        if not self.pilha_lacos:
            return

        laco = self.pilha_lacos[-1]
        # Só conta como "condicionado" um `if` aberto DEPOIS do laço; um `if`
        # que apenas envolve o laço não torna o acúmulo condicional.
        condicionado = self.in_if > laco['if_base']

        if laco['tipo'] == 'while':
            if condicionado:
                chave = "Repetição com condição - incremento de variável" if is_increment \
                    else "Repetição com condição - acúmulo de variável"
            else:
                chave = "Repetição - incremento de variável" if is_increment \
                    else "Repetição - acúmulo de variável"
            self.pattern_counts[chave] += 1

        elif laco['tipo_for'] == 'contagem':
            chave = "Repetição por contagem - incremento de variável" if is_increment \
                else "Repetição por contagem - acúmulo de variável"
            self.pattern_counts[chave] += 1

            familia = "multiplicativo" if isinstance(op, OPS_MULTIPLICATIVAS) else "aditivo"
            self.pattern_counts[f"SUBCONT::{familia}"] += 1

    @staticmethod
    def _eh_passo_unitario(op, valor_constante):
        # Só é "incremento" quando o passo é +1 ou -1 (contador simples);
        # qualquer outro operador ou passo é tratado como "acúmulo".
        return isinstance(op, (ast.Add, ast.Sub)) and valor_constante == 1

    def visit_AugAssign(self, node):
        if isinstance(node.op, OPS_ARITMETICAS):
            is_increment = (
                isinstance(node.value, ast.Constant)
                and self._eh_passo_unitario(node.op, node.value.value)
            )
            self._classifica_incremento_acumulo(is_increment, node.op)
        self.generic_visit(node)

    def visit_Assign(self, node):
        if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, OPS_ARITMETICAS):
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

                    self._classifica_incremento_acumulo(is_increment, node.value.op)
                    # `break` evita contagem duplicada quando há mais de um
                    # alvo na mesma atribuição (ex.: `x = y = x + 1`).
                    break

        self.generic_visit(node)


def _mapa_posicoes_estruturas(tree):
    """
    Pré-calcula, para CADA nó If/For/While do arquivo, se existe alguma
    instrução antes e/ou depois dele na lista de instruções (body/orelse/
    finalbody) que o contém -- indexado por id(node).
    """
    posicoes = {}
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            lista_stmts = getattr(node, attr, None)
            if not isinstance(lista_stmts, list):
                continue
            for idx, stmt in enumerate(lista_stmts):
                if isinstance(stmt, (ast.If, ast.For, ast.While)):
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
    Verifica se `stmt_antes` é uma atribuição simples (`var = <algo>`) e se
    essa mesma variável é reatribuída em algum ponto dentro do corpo do laço
    (via Assign ou AugAssign).

    Generaliza o conceito de "acumulador" (M5.3-M5.5, M6.1, M6.2, M7.1, M7.2)
    para qualquer variável de estado/controle inicializada antes do laço e
    modificada dentro dele -- cobre também M6.1 (maior = lista[i], que não é
    autoreferente), M5.2 (opcao = input(), estado do menu) e M5.1 (valor
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
    Detecta os sub-padrões estruturais de POSIÇÃO (antes/depois) em torno de
    condicionais e laços. Diferente de ASTPlanDetector (que escolhe 1 padrão
    dominante por arquivo), aqui os sub-padrões NÃO são mutuamente exclusivos,
    por isso ficam fora da lógica de hierarquia/dominância.
    """
    contagem = Counter()

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

        # LLOC (linhas lógicas de código) via radon.
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

        if lloc:
            features['Norm_Complexidade_Por_LLOC'] = round(features['AST_Complexidade_Ciclomatica'] / lloc, 4)
            features['Norm_Ifs_Por_LLOC'] = round(features['AST_Qtd_Ifs'] / lloc, 4)
            features['Norm_Loops_Por_LLOC'] = round(features['AST_Qtd_Loops'] / lloc, 4)
        else:
            features['Norm_Complexidade_Por_LLOC'] = None
            features['Norm_Ifs_Por_LLOC'] = None
            features['Norm_Loops_Por_LLOC'] = None

        # Sub-padrões posicionais globais (não exclusivos entre si nem com o
        # padrão dominante).
        subpadroes_mapeados = {
            "If - operação antes do condicional": "Sub_If_Operacao_Antes",
            "If - operação após o condicional": "Sub_If_Operacao_Apos",
            "Laço - operação antes do laço": "Sub_Laco_Operacao_Antes",
            "Laço - operação após o laço": "Sub_Laco_Operacao_Apos",
            "Laço - variável inicializada antes e atualizada dentro": "Sub_Laco_Var_Inicializada_Atualizada",
        }
        for chave, coluna in subpadroes_mapeados.items():
            features[coluna] = subpadroes.get(chave, 0)

        # Sub-padrões CRUZADOS (tipo de condicional x posição): 4 categorias
        # mutuamente exclusivas por tipo. A soma das 4 colunas de um tipo é o
        # total de ocorrências daquele tipo (para Aninhado: uma ocorrência por
        # estrutura aninhada, medida ao redor do `if` mais externo).
        _tipos_condicional = ["Condicional simples", "Condicional composto",
                               "Condicional encadeado", "Condicional aninhado"]
        _nome_coluna_tipo = {
            "Condicional simples": "Simples",
            "Condicional composto": "Composto",
            "Condicional encadeado": "Encadeado",
            "Condicional aninhado": "Aninhado",
        }
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

        # Sub-padrões do Módulo 7: família da operação do acumulador em
        # laços de contagem numérica (M7.1 aditivo x M7.2 multiplicativo).
        features['Sub_Contagem_Aditivo'] = detector.pattern_counts.get("SUBCONT::aditivo", 0)
        features['Sub_Contagem_Multiplicativo'] = detector.pattern_counts.get("SUBCONT::multiplicativo", 0)

        # M1 - Input/output sequencial
        if features['AST_Qtd_Loops'] == 0 and features['AST_Qtd_Ifs'] == 0:
            detector.pattern_counts["Input/output sequencial"] += 1

        # HIERARQUIA GLOBAL (mantém apenas o padrão mais complexo), do mais
        # complexo ao mais simples. Critérios, em ordem de peso: estruturas
        # combinadas (decisão < laço < laço com decisão < coleção); repetições
        # conhecidas (for de contagem) < desconhecidas (while); incremento <
        # acúmulo; iteração por valor < por índice.
        ordem_complexidade = [
            # Nível 5 - Coleção (M6): o laço percorre uma estrutura de dados
            "Estrutura linear (lista/string) - iteração por índice",
            "Estrutura linear (lista/string) - iteração por valor",
            # Nível 4 - Laço com decisão (M5): while + if (+ coleção indexada)
            "Repetição com condição - acúmulo de variável",
            "Repetição com condição - incremento de variável",
            "Repetição - controle por menu",
            # Nível 3 - Repetição básica: repetições desconhecidas (while) e
            # repetições conhecidas (for de contagem, M7)
            "Repetição - acúmulo de variável",
            "Repetição - incremento de variável",
            "Repetição - validação de entrada",
            "Repetição por contagem - acúmulo de variável",
            "Repetição por contagem - incremento de variável",
            # Nível 2 - Decisão (M2 a M4)
            "Condicional aninhado",
            "Condicional encadeado",
            "Condicional composto",
            "Condicional simples",
            # Nível 1 - Sequencial (M1)
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

        features['Modulo_Dominante'] = MODULO_POR_PADRAO.get(padrao_dominante, "Sem módulo")

        # Os rótulos "Repetição - ..." (while, M5.3) e "Repetição por
        # contagem - ..." (for, M7) são categorias distintas e ambos têm
        # coluna própria.
        padroes_mapeados = [
            "Input/output sequencial",
            "Condicional simples",
            "Condicional composto",
            "Condicional encadeado",
            "Condicional aninhado",
            "Repetição - incremento de variável",
            "Repetição - acúmulo de variável",
            "Repetição com condição - incremento de variável",
            "Repetição com condição - acúmulo de variável",
            "Repetição - controle por menu",
            "Repetição - validação de entrada",
            "Estrutura linear (lista/string) - iteração por índice",
            "Estrutura linear (lista/string) - iteração por valor",
            "Repetição por contagem - incremento de variável",
            "Repetição por contagem - acúmulo de variável",
        ]

        for p in padroes_mapeados:
            features[f'Freq_{p.replace(" ", "_").replace("/", "_")}'] = detector.pattern_counts.get(p, 0)

        # Rótulos auxiliares (SUBPOS::, SUBCONT::) alimentam colunas Sub_*,
        # mas não são padrões dominantes e ficam fora de padroes_str.
        encontrados = [
            p for p, count in detector.pattern_counts.items()
            if count > 0 and not p.startswith(("SUBPOS::", "SUBCONT::"))
        ]
        features['padroes_str'] = "; ".join(encontrados) if encontrados else "Sem Padrão Mapeado"

        return features
    except Exception:
        return None


def processar_exercicios_v16(path_exercises):
    base_path = Path(path_exercises)
    resultados = []

    pastas_exercicios = [p for p in base_path.iterdir() if p.is_dir()]
    print(f"Encontradas {len(pastas_exercicios)} pastas em {base_path}")

    for pasta in tqdm(pastas_exercicios, desc="Extraindo Taxonomia Estrutural (V16)"):
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
    cols = ['id_exercicio', 'padroes_str', 'Modulo_Dominante'] + [
        c for c in df.columns if c not in ['id_exercicio', 'padroes_str', 'Modulo_Dominante']
    ]
    return df[cols]


# EXECUÇÃO DO PIPELINE
caminho_do_script = Path(__file__).parent
arquivos_gerais_pibic = caminho_do_script.parent

caminho_exercises = arquivos_gerais_pibic / "DataSet" / "exerciciosSolucao"

df_features_final = processar_exercicios_v16(caminho_exercises)

if not df_features_final.empty:
    output_file = caminho_do_script / "resultado_analise_padroes" / "features_ast_padroes_completos.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df_features_final.to_csv(output_file, index=False)
    print(f"\nSucesso! Arquivo V16 salvo em: {output_file}")