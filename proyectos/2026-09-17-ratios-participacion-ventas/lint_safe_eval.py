# -*- coding: utf-8 -*-
"""Lint estatico contra las prohibiciones de safe_eval (ver skill
odoo-server-action-safe-eval). Corre con python3, no en Odoo."""
import ast
import io
import sys

FORBIDDEN_NAMES = {
    'getattr', 'setattr', 'hasattr', 'delattr', 'type', 'eval', 'exec',
    'open', 'print', 'vars', 'dir', 'globals', 'locals', 'compile',
    '__import__', 'fields',
}
ALLOWED_CTX = {
    'env', 'model', 'record', 'records', 'log', '_logger', 'UserError',
    'Command', 'uid', 'user', 'time', 'datetime', 'dateutil', 'timezone',
    'float_compare', 'b64encode', 'b64decode',
}
BUILTINS = {
    'True', 'False', 'None', 'bool', 'int', 'float', 'str', 'bytes', 'dict',
    'list', 'tuple', 'set', 'enumerate', 'map', 'filter', 'zip', 'sorted',
    'reduce', 'range', 'abs', 'min', 'max', 'sum', 'round', 'len', 'repr',
    'ord', 'chr', 'divmod', 'isinstance', 'any', 'all', 'Exception',
}


def check(path):
    src = io.open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    errs = []

    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
            for a in node.args.args:
                defined.add(a.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, (ast.comprehension,)):
            pass
        elif isinstance(node, ast.Lambda):
            for a in node.args.args:
                defined.add(a.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            errs.append('linea %s: import prohibido' % node.lineno)
        elif isinstance(node, ast.Global):
            errs.append('linea %s: global prohibido (STORE_GLOBAL)' % node.lineno)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            errs.append('linea %s: asignacion a atributo (STORE_ATTR); usar .write()' % node.lineno)
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                errs.append('linea %s: nombre prohibido "%s"' % (node.lineno, node.id))
            elif isinstance(node.ctx, ast.Load):
                if node.id not in defined and node.id not in ALLOWED_CTX and node.id not in BUILTINS:
                    errs.append('linea %s: nombre no definido ni inyectado: "%s"' % (node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr.startswith('__'):
            errs.append('linea %s: atributo interno "%s"' % (node.lineno, node.attr))

    # closures: def/lambda anidado que captura un local de la funcion externa
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if inner is node:
                    continue
                if isinstance(inner, (ast.FunctionDef, ast.Lambda)):
                    errs.append('linea %s: def/lambda anidado dentro de def (riesgo MAKE_CELL)' % inner.lineno)
    return errs


if __name__ == '__main__':
    bad = 0
    for p in sys.argv[1:]:
        e = check(p)
        if e:
            bad = 1
            print('%s:' % p)
            for x in e:
                print('   ' + x)
        else:
            print('%s: OK safe_eval' % p)
    sys.exit(bad)
