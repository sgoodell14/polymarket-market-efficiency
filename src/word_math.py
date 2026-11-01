"""Preserve native Word equations when importing the author's website draft."""
import json
import shutil
import subprocess

M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def read_equations(document, saved_docx, root):
    """Use Pandoc's OMML reader, matching every equation in document order."""
    nodes = list(document.iter(M + 'oMath'))
    if not nodes:
        return {}
    portable = root / '.tools/bin/tools/pandoc.exe'
    executable = str(portable) if portable.exists() else shutil.which('pandoc')
    if not executable:
        raise RuntimeError('Pandoc is required to preserve native Word equations')
    result = subprocess.run([executable, str(saved_docx), '-f', 'docx', '-t', 'json'],
                            check=True, capture_output=True, encoding='utf-8')
    equations = []

    def visit(value):
        if isinstance(value, dict):
            if value.get('t') == 'Math':
                equations.append(value['c'])
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(json.loads(result.stdout)['blocks'])
    if len(nodes) != len(equations):
        raise ValueError(f'Word equation coverage mismatch: {len(nodes)} vs {len(equations)}')
    result = {}
    for node, value in zip(nodes, equations):
        # Pandoc preserves the formula but drops Word's explicit font size.
        sizes = [int(size.get(W + 'val')) / 2 for size in node.iter(W + 'sz')
                 if size.get(W + 'val', '').isdigit()]
        result[node] = {'display': value[0]['t'] == 'DisplayMath', 'latex': value[1],
                        'font_size_points': max(sizes) if sizes else None}
    return result


