"""Transfer saved Word copy to Quarto without changing the author's document.

Editorial notes, unfinished prompts and publication checklists are excluded.
This transfer deliberately uses the 589-contract figures referenced in Word;
the user deferred reconciliation to the newer 565-family cohort.
"""
import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'website'
SOURCE = ROOT / 'docs/writing/website_writing_template.docx'
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
W = '{' + NS['w'] + '}'
R = '{' + NS['r'] + '}'
ROUTES = {
    'Introduction': 'index.qmd',
    'Data sources and study scope': 'DataPrep_EDA.qmd',
    'Sampling and Market Selection': 'DataPrep_EDA.qmd',
    'Forecast windows and prepared tables': 'DataPrep_EDA.qmd',
    'Cleaning and data quality': 'DataPrep_EDA.qmd',
    'Exploratory findings': 'DataPrep_EDA.qmd',
    'Figure captions one through five': 'captions',
    'Figure captions six through ten': 'captions',
    'Conclusions and publication review': 'Conclusions.qmd',
}
TITLES = {'index.qmd': 'Introduction', 'DataPrep_EDA.qmd': 'Data Preparation & EDA',
          'Conclusions.qmd': 'Conclusions'}


def text(node):
    return ''.join(t.text or '' for t in node.iter(W + 't')).strip()


def main():
    body = SOURCE.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive = ROOT / 'docs/writing/transfers' / (stamp + '_' + digest[:10])
    archive.mkdir(parents=True, exist_ok=False)
    (archive / 'source.docx').write_bytes(body)
    for name in [*TITLES, '_quarto.yml']:
        shutil.copyfile(WEB / name, archive / name)
    with zipfile.ZipFile(SOURCE) as z:
        document = ET.fromstring(z.read('word/document.xml'))
        relationships = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(z.read('word/_rels/document.xml.rels'))}
    if document.findall('.//w:ins', NS) or document.findall('.//w:del', NS):
        raise ValueError('Tracked changes need an explicit accepted/rejected version before transfer.')

    excluded, included, local_links = [], [], []

    def inline(node):
        parts = []
        for child in node:
            if child.tag == W + 'r':
                value = ''.join(t.text or '' for t in child.iter(W + 't'))
                if child.find('w:tab', NS) is not None:
                    value += ' '
                if child.find('w:br', NS) is not None:
                    value += ' '
                props = child.find('w:rPr', NS)
                if props is not None and value.strip():
                    stripped = value.strip()
                    if props.find('w:b', NS) is not None:
                        value = value.replace(stripped, '**' + stripped + '**')
                    elif props.find('w:i', NS) is not None:
                        value = value.replace(stripped, '*' + stripped + '*')
                parts.append(value)
            elif child.tag == W + 'hyperlink':
                label = inline(child)
                target = relationships.get(child.get(R + 'id'), '')
                if target.startswith(('https://', 'http://')):
                    parts.append(f'[{label}]({target})')
                else:
                    parts.append(label)
                    if target:
                        local_links.append(dict(label=label, original_target=target))
        return ''.join(parts).strip()

    pages = {name: [] for name in TITLES}
    route, section, pending_heading, caption = None, None, None, None
    captions = []
    ordered_blocks = []
    for index, block in enumerate(document.find('w:body', NS)):
        if block.tag == W + 'p':
            value = text(block)
            style_node = block.find('w:pPr/w:pStyle', NS)
            style = style_node.get(W + 'val') if style_node is not None else 'Normal'
            ordered_blocks.append(dict(index=index, type='paragraph', style=style, text=value))
            if not value:
                continue
            if style == 'Heading1':
                if value not in ROUTES:
                    raise ValueError('Unmapped main heading: ' + value)
                route, section, caption = ROUTES[value], value, None
                pending_heading = '## ' + value if route == 'DataPrep_EDA.qmd' else None
                continue
            if route is None or style in ('AuthorNote', 'SourceNote') or value.startswith(('Author note:', 'Review evidence:')):
                excluded.append(dict(index=index, text=value, reason='editorial_or_front_matter'))
                continue
            if route == 'Conclusions.qmd' and value in ('Later method pages', 'Before transferring the writing'):
                route = None
                excluded.append(dict(index=index, text=value, reason='publication_checklist'))
                continue
            if value.startswith('[') and re.match(r'^\[(WRITE|ADD|CHOOSE|INSERT)\b', value):
                excluded.append(dict(index=index, text=value, reason='unfinished_prompt'))
                pending_heading = None
                continue
            if route == 'captions':
                if style == 'Heading2':
                    match = re.match(r'Figure\s+(\d+)\s+(.+)', value)
                    if not match:
                        raise ValueError('Unmapped figure heading: ' + value)
                    caption = dict(id=match[1].zfill(2), title=match[2], paragraphs=[])
                    captions.append(caption)
                elif caption is not None:
                    caption['paragraphs'].append(inline(block))
                    included.append(dict(index=index, page='DataPrep_EDA.qmd', role='caption', text=value))
                continue
            if style == 'Heading2':
                if value == 'A suggested set of ten figures':
                    pending_heading = None
                    continue
                # An empty heading above an unfinished prompt is not emitted.
                if pending_heading and pending_heading.startswith('## ') and route == 'DataPrep_EDA.qmd':
                    pages[route].append(pending_heading)
                pending_heading = ('### ' if route == 'DataPrep_EDA.qmd' else '## ') + value
                continue
            if pending_heading:
                pages[route].append(pending_heading)
                pending_heading = None
            formatted = inline(block)
            if style == 'CodeExample':
                formatted = '```text\n' + value + '\n```'
            elif style in ('ListBullet', 'ListParagraph'):
                formatted = '- ' + formatted
            pages[route].append(formatted)
            included.append(dict(index=index, page=route, role='body', text=value))
        elif block.tag == W + 'tbl':
            rows = [[inline(p) for p in cell.findall('w:p', NS)] for row in block.findall('w:tr', NS) for cell in row.findall('w:tc', NS)]
            table = [[' '.join(inline(p) for p in cell.findall('w:p', NS)).replace('|', '\\|')
                      for cell in row.findall('w:tc', NS)] for row in block.findall('w:tr', NS)]
            ordered_blocks.append(dict(index=index, type='table', rows=table))
            if route not in pages or not table or table[0][0] == 'Figure':
                excluded.append(dict(index=index, reason='routing_or_figure_selection_table'))
                continue
            if pending_heading:
                pages[route].append(pending_heading)
                pending_heading = None
            # Preserve table text, adding the requested direct API base links.
            for row in table[1:]:
                urls = {'Gamma API': 'https://gamma-api.polymarket.com', 'Data API': 'https://data-api.polymarket.com', 'CLOB API': 'https://clob.polymarket.com'}
                if row[0] in urls:
                    row[0] = f'[{row[0]}]({urls[row[0]]})'
            pages[route].append('\n'.join(['| ' + ' | '.join(table[0]) + ' |', '| ' + ' | '.join(['---'] * len(table[0])) + ' |'] + ['| ' + ' | '.join(row) + ' |' for row in table[1:]]))
            included.append(dict(index=index, page=route, role='table', rows=table))

    figures = ROOT / 'figures/eda_20260916'
    assets = WEB / 'assets/eda_20260916'
    assets.mkdir(parents=True, exist_ok=True)
    pages['DataPrep_EDA.qmd'].append('## Figures')
    copied = []
    for item in captions:
        matches = list(figures.glob(item['id'] + '_*.png'))
        if len(matches) != 1:
            raise ValueError('Figure match is not unique: ' + item['id'])
        source = matches[0]
        shutil.copyfile(source, assets / source.name)
        copied.append(source.relative_to(ROOT).as_posix())
        pages['DataPrep_EDA.qmd'].extend([
            f"### Figure {item['id']} {item['title']}",
            '![' + ' '.join(item['paragraphs']) + '](assets/eda_20260916/' + source.name + '){fig-alt="' + item['title'].replace('"', '') + ' for the earlier 589-contract cohort."}'
        ])
    note = ('**Draft checkpoint.** The text and figures below retain the earlier 589-contract analysis while revisions are in progress. '
            'The updated cohort contains 565 distinct event families: 200 Sports, 200 Politics and 165 Economics. '
            'The September 2025-August 2026 study period is unchanged.')
    pages['DataPrep_EDA.qmd'].insert(0, note)
    if not pages['Conclusions.qmd']:
        pages['Conclusions.qmd'] = ['Conclusions are still being developed.', '[Read the data preparation and exploratory analysis](DataPrep_EDA.qmd).']
    for name, blocks in pages.items():
        output = f'---\ntitle: "{TITLES[name]}"\n---\n\n' + '\n\n'.join(blocks) + '\n'
        assert 'file:///' not in output
        assert 'Review evidence:' not in output and 'Author note:' not in output
        (WEB / name).write_text(output, encoding='utf-8', newline='\n')
    config = WEB / '_quarto.yml'
    config.write_text(config.read_text(encoding='utf-8').replace('Polymarket pilot - September 2026', 'Polymarket research - September 2026'), encoding='utf-8')
    marker = dict(source=SOURCE.relative_to(ROOT).as_posix(), source_sha256=digest,
                  transferred_at_utc=datetime.now(timezone.utc).isoformat(),
                  narrative_source='saved_word_document', figures_checkpoint='20260916_v1',
                  current_data_checkpoint='20260916_v2', counts_reconciliation_deferred_by_user=True,
                  archive=archive.relative_to(ROOT).as_posix(), pages=list(pages), figure_count=len(captions))
    (WEB / 'writing-transfer.json').write_text(json.dumps(marker, indent=2) + '\n', encoding='utf-8')
    (archive / 'extracted_blocks.json').write_text(json.dumps(ordered_blocks, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (archive / 'transfer_receipt.json').write_text(json.dumps(dict(**marker, included=included, excluded=excluded, local_links_not_published=local_links, copied_figures=copied), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (archive / 'review_notes.md').write_text('''# Word transfer review notes

The saved author text was transferred without factual rewriting. Editorial paragraphs, unfinished prompts, empty associated headings and the publication checklist were omitted. API labels link to the three public base URLs. Ten figures use the same earlier cohort as the supplied captions; a visible draft note distinguishes that checkpoint from the current cohort.

For the next author revision:

- Reconcile the earlier 589/496/199/191/199 figures and all related rows, missingness, history and activity counts against version 2. The current cohort has 565 contracts and families (200/200/165).
- The extraction paragraph currently says the first outcome was selected for Data API transactions. Trades were collected across both tokens using the condition ID; the first token was selected for CLOB price history. Gamma supplies the identifiers, not the trade records.
- Initial event-ID grouping did not ensure unique real-world families. The later family audit and replacement step established one contract per reviewed family.
- Sports winner propositions can include draws. Accepted event boundaries retain documented timing conventions/uncertainty; avoid implying every actual start minute was independently established.
- Introduction prose, an introduction image, public data-download packaging and conclusions remain unfinished in Word. They were not invented during this text transfer.

The user's Word document is preserved unchanged. Existing data, audits and figures were not recalculated. This is a local website preview, not a publication.
''', encoding='utf-8')
    assert SOURCE.read_bytes() == body, 'Source Word document changed during transfer'
    print(json.dumps(marker, indent=2))


if __name__ == '__main__':
    main()
