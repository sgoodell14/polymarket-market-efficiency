"""Render a saved notebook as readable local HTML without executing its cells."""
import argparse
from pathlib import Path
import nbformat
from nbconvert import HTMLExporter


def render(notebook, output):
    html, _ = HTMLExporter(template_name='lab').from_notebook_node(
        nbformat.read(notebook, as_version=4))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('notebook', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    render(args.notebook, args.output)
    print(f'Rendered saved notebook without execution: {args.output}')


if __name__ == '__main__':
    main()
