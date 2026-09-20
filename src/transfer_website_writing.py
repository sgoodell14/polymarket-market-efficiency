"""Transfer saved Word copy to Quarto without changing the author's document.

Editorial notes, unfinished prompts and publication checklists are excluded.
Word supplies editable titles and captions; the figure registry supplies current
image assets and accessible descriptions.
"""
import hashlib
import os
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
    'Data Sources & Scope': 'DataPrep_EDA.qmd',
    'Sampling and Market Selection': 'DataPrep_EDA.qmd',
    'Forecast windows and prepared tables': 'DataPrep_EDA.qmd',
    'Cleaning and data quality': 'DataPrep_EDA.qmd',
    'Cleaning and Data Quality Checks': 'DataPrep_EDA.qmd',
    'Cleaning & Data Quality Checks': 'DataPrep_EDA.qmd',
    'Exploratory findings': 'DataPrep_EDA.qmd',
    'Exploratory Visualizations': 'DataPrep_EDA.qmd',
    'Figure captions one through five': 'captions',
    'Figure captions six through ten': 'captions',
    'Visualization captions': 'captions',
    'Conclusions and publication review': 'Conclusions.qmd',
}
TITLES = {'index.qmd': 'Introduction', 'DataPrep_EDA.qmd': 'Data Preparation & EDA',
          'Conclusions.qmd': 'Conclusions'}


def text(node):
    return ''.join(t.text or '' for t in node.iter(W + 't')).strip()


def read_saved_document(path):
    """Read saved bytes while Word keeps a shared handle open on Windows."""
    try:
        return path.read_bytes()
    except PermissionError:
        if os.name != 'nt':
            raise
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x7, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        chunks = []
        buffer = ctypes.create_string_buffer(131072)
        count = wintypes.DWORD()
        while True:
            if not kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not count.value:
                return b''.join(chunks)
            chunks.append(buffer.raw[:count.value])
    finally:
        kernel.CloseHandle(handle)


def portable_reference_url(target, reference_map):
    """Route known project links, including older download URLs, to current assets."""
    aliases = {}
    for entry in reference_map.values():
        for previous in [entry['target'], *entry.get('previous_targets', [])]:
            aliases[previous] = entry['target']
    if target in aliases:
        return aliases[target]
    for prefix in ('http://127.0.0.1:8765/', 'http://localhost:8765/',
                   'https://sgoodell14.github.io/polymarket-market-efficiency/'):
        if target.startswith(prefix) and target[len(prefix):] in aliases:
            return aliases[target[len(prefix):]]
    return target


def integrate_introduction_media(blocks, design):
    """Place linked screenshots around intact Word paragraphs, without rewriting."""
    includes = design['introduction_media_parts']
    for name in ('pew', 'nyt', 'cbs'):
        if not (WEB / includes[name]).is_file():
            raise FileNotFoundError('Missing introduction media: ' + includes[name])
    boundary = next((i for i, block in enumerate(blocks) if block.startswith('## ')), len(blocks))
    paragraphs = [i for i, block in enumerate(blocks[:boundary])
                  if block.strip() and not block.startswith(('#', '{{<', ':::'))]
    if len(paragraphs) < 2:
        raise ValueError('Integrated introduction layout needs at least two introductory paragraphs.')

    def include(name):
        return '{{< include ' + includes[name] + ' >}}'

    result = []
    for index, block in enumerate(blocks):
        if index == paragraphs[0]:
            result.append('::: {.intro-opening}\n\n' + include('pew') + '\n\n' + block + '\n\n:::')
            result.append('::: {.intro-headlines}\n\n' + include('nyt') + '\n\n' + include('cbs') + '\n\n:::')
        elif index == paragraphs[-1]:
            result.append('::: {.intro-study}\n\n' + block + '\n\n:::')
        else:
            result.append(block)
    return result


def main():
    body = read_saved_document(SOURCE)
    digest = hashlib.sha256(body).hexdigest()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive = ROOT / 'docs/writing/transfers' / (stamp + '_' + digest[:10])
    archive.mkdir(parents=True, exist_ok=False)
    (archive / 'source.docx').write_bytes(body)
    for name in [*TITLES, '_quarto.yml']:
        shutil.copyfile(WEB / name, archive / name)
    with zipfile.ZipFile(archive / 'source.docx') as z:
        document = ET.fromstring(z.read('word/document.xml'))
        relationships = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(z.read('word/_rels/document.xml.rels'))}
    if document.findall('.//w:ins', NS) or document.findall('.//w:del', NS):
        raise ValueError('Tracked changes need an explicit accepted/rejected version before transfer.')

    excluded, included, local_links, formatting_adjustments = [], [], [], []
    reference_map = json.loads((WEB / 'reference-links.json').read_text(encoding='utf-8'))
    reference_keys = {label.casefold(): label for label in reference_map}
    reference_prefix = re.compile(r'^(?:Linked\s+)?References:\s*', re.IGNORECASE)
    linked_references = []

    def reference_line(value, index):
        prefix = reference_prefix.match(value)
        labels = [label.strip() for label in value[prefix.end():].split(',')]
        links = []
        for label in labels:
            if label.casefold() not in reference_keys:
                raise ValueError('Unmapped reference label: ' + label)
            entry = reference_map[reference_keys[label.casefold()]]
            if not (WEB / entry['target']).is_file():
                raise FileNotFoundError('Package the reference first: ' + entry['target'])
            links.append(f'[{label}]({entry["target"]} "{entry["title"]}")')
            linked_references.append(dict(index=index, label=label, **entry))
        return '::: {.section-references}\n' + value[:prefix.end()] + ', '.join(links) + '\n:::'

    def enabled(node):
        return node is not None and node.get(W + 'val', '1') not in ('0', 'false', 'off')

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
                    if enabled(props.find('w:b', NS)):
                        value = value.replace(stripped, '**' + stripped + '**')
                    elif enabled(props.find('w:i', NS)):
                        value = value.replace(stripped, '*' + stripped + '*')
                parts.append(value)
            elif child.tag == W + 'hyperlink':
                label = inline(child)
                target = relationships.get(child.get(R + 'id'), '')
                reference_key = reference_keys.get(label.strip('*_').casefold())
                if reference_key is not None:
                    # Recognized reference labels always use the current reader download.
                    parts.append(f'[{label}]({reference_map[reference_key]["target"]})')
                elif target.startswith(('https://', 'http://')):
                    parts.append(f'[{label}]({portable_reference_url(target, reference_map)})')
                else:
                    parts.append(label)
                    if target:
                        local_links.append(dict(label=label, original_target=target))
        return ''.join(parts).strip()

    design_file = WEB / 'site-design.json'
    design = json.loads(design_file.read_text(encoding='utf-8')) if design_file.exists() else {}
    word_figure_ids = design.get('word_figure_ids', {})
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
            # These saved author edits contain prose despite inherited Word styles.
            if (style == 'Heading2' and value.startswith('The trading and price history windows cover')):
                formatting_adjustments.append(dict(index=index, original_style=style,
                                                   output_style='body', reason='window explanation is prose'))
                style = 'Normal'
            if style == 'SourceNote' and not value.startswith('Review evidence:'):
                formatting_adjustments.append(dict(index=index, original_style=style,
                                                   output_style='body', reason='authored prose, not an evidence-link note'))
                style = 'Normal'
            if style == 'AuthorNote' and value.startswith('Trading activity was measured'):
                formatting_adjustments.append(dict(index=index, original_style=style,
                                                   output_style='body', reason='authored activity definition, not an editing instruction'))
                style = 'Normal'
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
                if reference_prefix.match(value):
                    if caption is None:
                        raise ValueError('Figure reference has no preceding figure')
                    caption.setdefault('references', []).append(reference_line(value, index))
                    included.append(dict(index=index, page='DataPrep_EDA.qmd', role='figure_reference', text=value))
                elif style == 'Heading2':
                    match = re.match(r'Figure\s+(\d+)\s+(.+)', value)
                    if not match:
                        raise ValueError('Unmapped figure heading: ' + value)
                    word_id = match[1].zfill(2)
                    if word_figure_ids and word_id not in word_figure_ids:
                        raise ValueError('No current image mapped to Word figure ' + word_id)
                    source_id = word_figure_ids.get(word_id, word_id)
                    if any(item['id'] == source_id for item in captions):
                        raise ValueError('Repeated figure number in Word: ' + word_id)
                    caption = dict(id=source_id, word_id=word_id, title=match[2], paragraphs=[])
                    captions.append(caption)
                elif caption is not None:
                    caption['paragraphs'].append(inline(block))
                    included.append(dict(index=index, page='DataPrep_EDA.qmd', role='caption', text=value))
                continue
            if style == 'Heading2':
                if value == 'Code and data access':
                    excluded.append(dict(index=index, text=value, reason='references_distributed_by_section'))
                    continue
                if value == 'A suggested set of ten figures':
                    pending_heading = None
                    continue
                # An empty heading above an unfinished prompt is not emitted.
                if pending_heading and pending_heading.startswith('## ') and route == 'DataPrep_EDA.qmd':
                    pages[route].append(pending_heading)
                pending_heading = ('### ' if route == 'DataPrep_EDA.qmd' else '## ') + value
                if route == 'DataPrep_EDA.qmd' and value in (
                        'Market Exclusions & Reserve Replacements', 'Exclusions and reserve replacements'):
                    pending_heading += ' {#exclusions-and-reserve-replacements}'
                continue
            if pending_heading:
                pages[route].append(pending_heading)
                pending_heading = None
            formatted = inline(block)
            if reference_prefix.match(value):
                formatted = reference_line(value, index)
            elif style == 'CodeExample':
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
            if route not in pages or not table or table[0][0].strip('*_') == 'Figure':
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

    figure_order = {source_id: rank for rank, source_id in enumerate(design.get('figure_order', []))}
    if figure_order:
        captions.sort(key=lambda item: figure_order.get(item['id'], len(figure_order) + int(item['id'])))
    # Keep charts under the author's EDA section, including when its prose is
    # intentionally empty. Do not introduce a second "Figures" section.
    visualizations_heading = '## Exploratory Visualizations'
    if visualizations_heading not in pages['DataPrep_EDA.qmd']:
        pages['DataPrep_EDA.qmd'].append(visualizations_heading)
    copied = []
    override_file = WEB / 'figure-overrides.json'
    figure_overrides = json.loads(override_file.read_text(encoding='utf-8')) if override_file.exists() else {}
    if word_figure_ids and {item['word_id'] for item in captions} != set(word_figure_ids):
        raise ValueError('Word is missing one or more current figure headings.')
    if not captions:
        raise ValueError('No Word figure captions were found.')
    for display_number, item in enumerate(captions, 1):
        # Word owns the text. Missing mappings must never revive an older chart.
        if item['id'] not in figure_overrides:
            raise ValueError('No current image registered for figure ' + item['id'])
        if not item['paragraphs']:
            raise ValueError('Missing Word caption for figure ' + item['word_id'])
        override = figure_overrides[item['id']]
        source = ROOT / override['source']
        target = WEB / override['asset']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append(source.relative_to(ROOT).as_posix())
        pages['DataPrep_EDA.qmd'].extend([
            f"### Figure {display_number:02d} {item['title']}",
            '![' + ' '.join(item['paragraphs']) + '](' + override['asset'] + '){fig-alt="' + override['alt'] + '"}'
        ])
        if design.get('per_figure_references', True):
            pages['DataPrep_EDA.qmd'].extend(item.get('references', []))
    if not design.get('per_figure_references', True):
        # The notebook reference in Word follows the last caption, but belongs
        # to the whole visualization section and must survive this setting.
        notebook_target = reference_map['EDA Visualization Notebook']['target']
        notebook_refs = [entry for entry in linked_references
                         if entry['target'] == notebook_target]
        if notebook_refs:
            entry = notebook_refs[0]
            links = [f'[{entry["label"]}]({entry["target"]} "{entry["title"]}")']
            if bundle := reference_map.get('EDA Notebook and Data'):
                if not (WEB / bundle['target']).is_file():
                    raise FileNotFoundError('Package the notebook inputs first: ' + bundle['target'])
                links.append(f'[Notebook + Data (ZIP)]({bundle["target"]} "{bundle["title"]}")')
            pages['DataPrep_EDA.qmd'].append(
                '::: {.section-references}\nLinked References: '
                + ' | '.join(links) + '\n:::')
    module_placeholder = '::: {.eyebrow}\nLater course module\n:::'
    # Keep the author's linked introduction images across future Word transfers.
    if design.get('introduction_media_layout') == 'within_text':
        pages['index.qmd'] = integrate_introduction_media(pages['index.qmd'], design)
    elif media_include := design.get('introduction_media_include'):
        if not (WEB / media_include).is_file():
            raise FileNotFoundError('Missing introduction media: ' + media_include)
        introduction = pages['index.qmd']
        position = next((i for i, block in enumerate(introduction)
                         if block.lstrip('# ').strip().casefold() == 'research questions'), len(introduction))
        introduction.insert(position, '{{< include ' + media_include + ' >}}')
    if not pages['Conclusions.qmd']:
        pages['Conclusions.qmd'] = [module_placeholder]
    for name, blocks in pages.items():
        page_options = '\ntoc: false' if blocks == [module_placeholder] else ''
        page_title = TITLES[name]
        if name == 'index.qmd' and design.get('project_title'):
            page_title = design['project_title']
            page_options = ('\nsubtitle: ' + json.dumps(design['project_subtitle']) +
                            '\nbody-classes: ' + design['home_body_class'] + '\ntoc: true\ntoc-depth: 2')
            # The introduction's page menu points readers to the research questions.
            blocks = ['## References {.unlisted}' if block == '## References' else block
                      for block in blocks]
        output = '---\ntitle: ' + json.dumps(page_title) + page_options + '\n---\n\n' + '\n\n'.join(blocks) + '\n'
        assert 'file:///' not in output
        assert 'Review evidence:' not in output and 'Author note:' not in output
        (WEB / name).write_text(output, encoding='utf-8', newline='\n')
    config = WEB / '_quarto.yml'
    config.write_text(config.read_text(encoding='utf-8').replace('Polymarket pilot - September 2026', 'Polymarket research - September 2026'), encoding='utf-8')
    overridden_ids = [item['id'] for item in captions if item['id'] in figure_overrides]
    figures_checkpoint = '20260916_v2'
    marker = dict(source=SOURCE.relative_to(ROOT).as_posix(), source_sha256=digest,
                  transferred_at_utc=datetime.now(timezone.utc).isoformat(),
                  narrative_source='saved_word_document', figures_checkpoint=figures_checkpoint,
                  figure_text_source='saved_word_document', word_figure_ids=word_figure_ids,
                  current_data_checkpoint='20260916_v2', counts_reconciliation_deferred_by_user=True,
                  archive=archive.relative_to(ROOT).as_posix(), pages=list(pages), figure_count=len(captions),
                  figure_overrides_applied=overridden_ids,
                  figures_section='Exploratory Visualizations')
    (WEB / 'writing-transfer.json').write_text(json.dumps(marker, indent=2) + '\n', encoding='utf-8')
    (archive / 'extracted_blocks.json').write_text(json.dumps(ordered_blocks, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (archive / 'transfer_receipt.json').write_text(json.dumps(dict(**marker, included=included, excluded=excluded, formatting_adjustments=formatting_adjustments, local_links_not_published=local_links, copied_figures=copied, linked_references=linked_references), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (archive / 'review_notes.md').write_text("""# Word transfer notes

The saved author text was transferred without factual rewriting. Editorial instructions,
unfinished prompts and the publication checklist were omitted. The transfer receipt records
all included/excluded blocks and style adjustments. Section reference labels are resolved
through website/reference-links.json; the Word document itself is unchanged.

Figure titles and captions come from the saved Word document. Its visible figure
numbers map to current image source IDs through website/site-design.json.
website/figure-overrides.json supplies image paths and accessible descriptions
only; missing mappings stop the transfer instead of restoring historical charts.
The receipt identifies the mapped assets and checkpoint. Research data and
figures were not recalculated by this transfer. This is a local preview.

The current substantive review is [September 17 site review](../../reviews/20260917_site_review.md).
It distinguishes factual corrections, interpretation limits and unfinished assignment items.
Earlier dated review notes describe their own saved checkpoints and may be superseded.
""", encoding='utf-8')
    assert read_saved_document(SOURCE) == body, 'Source Word document changed during transfer'
    print(json.dumps(marker, indent=2))


if __name__ == '__main__':
    main()
