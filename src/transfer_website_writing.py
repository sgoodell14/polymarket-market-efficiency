"""Transfer saved Word copy to Quarto without changing the author's document.

Editorial notes, unfinished prompts and publication checklists are excluded.
Word supplies editable titles and captions; the figure registry supplies current
image assets and accessible descriptions.
"""
import hashlib
import base64
import os
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET
from word_math import M, read_equations

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
    'Clustering': 'Clustering.qmd',
    'PCA': 'PCA.qmd',
    'Naïve Bayes': 'NaiveBayes.qmd',
    'Naive Bayes': 'NaiveBayes.qmd',
    'Decision Trees': 'DecTrees.qmd',
    'Conclusions and publication review': 'Conclusions.qmd',
}
TITLES = {'index.qmd': 'Introduction', 'DataPrep_EDA.qmd': 'Data Preparation & EDA',
          'Conclusions.qmd': 'Conclusions', 'Clustering.qmd': 'Clustering', 'PCA.qmd': 'PCA',
          'NaiveBayes.qmd': 'Naïve Bayes', 'DecTrees.qmd': 'Decision Trees'}


def text(node):
    return ''.join(t.text or '' for t in node.iter() if t.tag in (W + 't', M + 't')).strip()


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


def prose_in_heading_style(style, value):
    """Treat sentence-length inherited headings as prose, regardless of wording."""
    return style == 'Heading2' and len(value.split()) >= 20


def assert_paragraph_coverage(required, pages):
    """Fail before writing pages if a source prose paragraph was lost in layout."""
    def normalize(value):
        return re.sub(r'[\s*_\\]+', '', value)
    outputs = {name: normalize('\n\n'.join(blocks)) for name, blocks in pages.items()}
    missing = [item for item in required
               if normalize(item['markdown']) not in outputs[item['page']]]
    if missing:
        details = '; '.join(f"{item['page']} Word paragraph {item['index']}: "
                            + item['text'][:100] for item in missing)
        raise ValueError('Word prose missing from website transfer: ' + details)
    return dict(checked=len(required), missing=0)


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
    equations = read_equations(document, archive / 'source.docx', ROOT)
    used_equations = set()
    equation_blocks, equation_sources, equation_captions = {}, {}, {}
    method_equations = []

    excluded, included, local_links, formatting_adjustments = [], [], [], []
    reference_map = json.loads((WEB / 'reference-links.json').read_text(encoding='utf-8'))
    reference_keys = {label.casefold(): label for label in reference_map}
    reference_prefix = re.compile(r'^(?:(?:Linked\s+)?References|Coding Notebook):\s*', re.IGNORECASE)
    linked_references = []
    method_registry_path = WEB / 'method-figures.json'
    method_registry = json.loads(method_registry_path.read_text(encoding='utf-8')) if method_registry_path.exists() else {}
    method_figures = []
    method_captions = {}
    inline_panels = {}
    rules_path = WEB / 'method-import-rules.json'
    method_import_rules = json.loads(rules_path.read_text(encoding='utf-8')) if rules_path.exists() else {}
    skipped_method_captions = {}
    prior_rule = None
    body_blocks = list(document.find('w:body', NS))
    for block_index, node in enumerate(document.find('w:body', NS)):
        value = text(node)
        if not value:
            continue
        figure_title = re.fullmatch(r'INSERT FIGURE (\d+):\s*(.+)', value, re.IGNORECASE)
        if figure_title and figure_title[1] in method_registry:
            method_registry[figure_title[1]]['title'] = figure_title[2]
        equation_title = re.fullmatch(r'INSERT EQUATION:\s*(.+)', value, re.IGNORECASE)
        if equation_title:
            # Accept both equation/title/caption and title/caption/equation.
            # Claimed equations belong to the preceding titled block, so an
            # adjacent new title must not reuse them as its own formula.
            previous_indices = []
            for previous_index in range(block_index - 1, -1, -1):
                previous = body_blocks[previous_index]
                if not text(previous):
                    continue
                previous_math = list(previous.iter(M + 'oMath'))
                if (previous_index in equation_sources
                        or previous.tag != W + 'p' or len(previous_math) != 1
                        or any(t.text for t in previous.iter(W + 't'))):
                    break
                previous_indices.insert(0, previous_index)
            caption_index = next((i for i in range(block_index + 1, len(body_blocks))
                                  if text(body_blocks[i])), None)
            if caption_index is None:
                raise ValueError('Expected an explanation after ' + value)
            explanation = body_blocks[caption_index]
            caption_style = explanation.find('w:pPr/w:pStyle', NS)
            if (explanation.tag != W + 'p' or text(explanation).startswith('INSERT ')
                    or explanation.find('m:oMathPara', {'m': M[1:-1]}) is not None
                    or (caption_style is not None and caption_style.get(W + 'val', '').startswith('Heading'))):
                raise ValueError('Expected a caption paragraph after ' + value)
            source_indices = previous_indices
            if not source_indices:
                for next_index in range(caption_index + 1, len(body_blocks)):
                    following = body_blocks[next_index]
                    if not text(following):
                        continue
                    following_math = list(following.iter(M + 'oMath'))
                    if (following.tag != W + 'p' or len(following_math) != 1
                            or any(t.text for t in following.iter(W + 't'))):
                        break
                    source_indices.append(next_index)
            math_nodes = [math for i in source_indices
                          for math in body_blocks[i].iter(M + 'oMath')]
            if not math_nodes:
                raise ValueError('Expected standalone Word equations adjacent to ' + value)
            # Preserve blank lines between a formula and its following definition.
            blank_lines_before = [0] + [
                sum(body_blocks[j].tag == W + 'p' and not text(body_blocks[j])
                    for j in range(left + 1, right))
                for left, right in zip(source_indices, source_indices[1:])]
            equation_blocks[block_index] = dict(title=equation_title[1], nodes=math_nodes,
                                               caption_index=caption_index,
                                               blank_lines_before=blank_lines_before)
            for source_index in source_indices:
                equation_sources[source_index] = block_index
            equation_captions[caption_index] = block_index
        if prior_rule and value.startswith(prior_rule.get('skip_following_caption_prefix', '\0')):
            skipped_method_captions[block_index] = prior_rule['reason']
        prior_rule = method_import_rules.get(value)

    def method_figure(number, page, index):
        entry = method_registry[number]
        if entry['page'] != page:
            raise ValueError('Method figure on unexpected page: ' + number)
        if entry.get('panels'):
            panels, panel_images = [], []
            for panel in entry['panels']:
                image_bytes = (WEB / panel['asset']).read_bytes()
                panel_images.append(dict(asset=panel['asset'],
                                         image_sha256=hashlib.sha256(image_bytes).hexdigest()))
                panels.append(
                    '::: {.method-figure-panel}\n\n'
                    f"[{panel['title']}]{{.method-panel-title}}\n\n"
                    f"[![]({panel['asset']}){{fig-alt={json.dumps(panel['alt'])}}}](#figure-{number})"
                    '{.figure-preview aria-haspopup="dialog"}\n\n:::')
            method_figures.append(dict(number=number, index=index, **entry,
                                       panel_images=panel_images))
            return (f'::::: {{.method-figure .method-figure-gallery #figure-{number}}}\n\n'
                    f"[{entry['title']}]{{.method-figure-title}}\n\n"
                    ':::: {.method-figure-row}\n\n' + '\n\n'.join(panels)
                    + '\n\n::::\n\n'
                    + f"[{method_captions.get(number, 'Figure ' + number + ':')}]{{.method-caption}}"
                    + '\n\n:::::')
        source_hash = {}
        if entry.get('source_image'):
            image_bytes = (ROOT / entry['source_image']).read_bytes()
            source_hash['source_sha256'] = hashlib.sha256(image_bytes).hexdigest()
        else:
            notebook_path = ROOT / entry['notebook']
            notebook_bytes = notebook_path.read_bytes()
            notebook = json.loads(notebook_bytes)
            if entry.get('cell_id'):
                cells = [cell for cell in notebook['cells'] if cell.get('id') == entry['cell_id']]
            else:
                cells = [cell for cell in notebook['cells'] if entry['tag'] in cell.get('metadata', {}).get('tags', [])]
            if len(cells) != 1:
                raise ValueError('Expected one notebook cell for figure ' + number)
            images = [output['data']['image/png'] for output in cells[0].get('outputs', [])
                      if 'image/png' in output.get('data', {})]
            output_index = entry.get('output_index')
            if output_index is not None:
                if not isinstance(output_index, int) or not 0 <= output_index < len(images):
                    raise ValueError('Invalid PNG output index for figure ' + number)
            elif len(images) != 1:
                raise ValueError('Execute notebook to save one PNG for figure ' + number)
            encoded = images[output_index if output_index is not None else 0]
            image_bytes = base64.b64decode(''.join(encoded) if isinstance(encoded, list) else encoded)
            source_hash['notebook_sha256'] = hashlib.sha256(notebook_bytes).hexdigest()
        target = WEB / entry['asset']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image_bytes)
        method_figures.append(dict(number=number, index=index, **entry, **source_hash,
                                   image_sha256=hashlib.sha256(image_bytes).hexdigest()))
        figure_class = '.method-figure'
        if entry.get('placement') == 'float-left':
            figure_class += ' .method-figure-float'
        if entry.get('presentation') == 'overview':
            figure_class += ' .method-figure-overview'
        if entry.get('size') == 'large':
            figure_class += ' .method-figure-large'
        if entry.get('source_on_preview'):
            figure_class += ' .source-on-preview'
        subtitle = f"\n[{entry['subtitle']}]{{.method-figure-subtitle}}  " if entry.get('subtitle') else ''
        return (f"::: {{{figure_class} #figure-{number}}}\n\n"
                f"[{entry['title']}]{{.method-figure-title}}  {subtitle}\n"
                f"[![]({entry['asset']}){{fig-alt={json.dumps(entry['alt'])}}}](#figure-{number}){{.figure-preview aria-haspopup=\"dialog\"}}\n\n"
                f"[{method_captions.get(number, 'Figure ' + entry.get('display_number', number) + ':')}]{{.method-caption}}\n\n:::")

    def reference_line(value, index):
        prefix = reference_prefix.match(value)
        labels = [label.strip() for label in value[prefix.end():].split(',')]
        links = []
        for label in labels:
            if label.casefold() not in reference_keys:
                raise ValueError('Unmapped reference label: ' + label)
            entry = reference_map[reference_keys[label.casefold()]]
            if entry.get('source'):
                destination = WEB / entry['target']
                destination.parent.mkdir(parents=True, exist_ok=True)
                if entry.get('render_notebook'):
                    from render_saved_notebook import render
                    render(ROOT / entry['source'], destination)
                else:
                    shutil.copyfile(ROOT / entry['source'], destination)
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
                    label = reference_map[reference_key].get('display_label', label)
                    parts.append(f'[{label}]({reference_map[reference_key]["target"]})')
                elif target.startswith(('https://', 'http://')):
                    parts.append(f'[{label}]({portable_reference_url(target, reference_map)})')
                else:
                    parts.append(label)
                    if target:
                        local_links.append(dict(label=label, original_target=target))
            elif child.tag in (M + 'oMath', M + 'oMathPara'):
                nodes = [child] if child.tag == M + 'oMath' else list(child.iter(M + 'oMath'))
                for math in nodes:
                    equation = equations[math]
                    delimiter = '$$' if equation['display'] else '$'
                    parts.append(delimiter + equation['latex'] + delimiter)
                    used_equations.add(math)
        return ''.join(parts).strip()

    # Caption fields in Word are separate from image placement instructions.
    # Read them first so a caption can follow its placeholder in the document.
    caption_blocks = {}
    caption_page = None
    for index, block in enumerate(document.find('w:body', NS)):
        if block.tag != W + 'p' or index in skipped_method_captions:
            continue
        style = block.find('w:pPr/w:pStyle', NS)
        if style is not None and style.get(W + 'val') == 'Heading1':
            caption_page = ROUTES.get(text(block))
        match = re.match(r'^Figure\s+(\d+):\s*(.*)$', text(block))
        if match and match[1] in method_registry:
            number, prose = match.groups()
            candidates = [key for key, entry in method_registry.items()
                          if entry.get('display_number', key) == number and entry['page'] == caption_page]
            if len(candidates) == 1:
                number = candidates[0]
            if number in method_captions:
                raise ValueError('Duplicate method caption: ' + number)
            placeholder = prose == '[Write caption here.]'
            method_captions[number] = 'Figure ' + number + ':' if placeholder else inline(block)
            caption_blocks[index] = dict(number=number, placeholder=placeholder)

    design_file = WEB / 'site-design.json'
    design = json.loads(design_file.read_text(encoding='utf-8')) if design_file.exists() else {}
    word_figure_ids = design.get('word_figure_ids', {})
    pages = {name: [] for name in TITLES}
    route, section, pending_heading, caption = None, None, None, None
    captions = []
    ordered_blocks = []
    required_prose = []
    for index, block in enumerate(document.find('w:body', NS)):
        if block.tag == W + 'p':
            value = text(block)
            style_node = block.find('w:pPr/w:pStyle', NS)
            style = style_node.get(W + 'val') if style_node is not None else 'Normal'
            ordered_blocks.append(dict(index=index, type='paragraph', style=style, text=value))
            if not value:
                continue
            if index in equation_sources:
                included.append(dict(index=index, page=route, role='equation_source', text=value))
                continue
            # Independently require authored prose, including long paragraphs
            # carrying a heading style. Do not infer deletion from styling.
            if (route in pages and style != 'Heading1' and index not in skipped_method_captions
                    and (style != 'Heading2' or prose_in_heading_style(style, value))
                    and not value.startswith(('Author note:', 'Review evidence:', 'ADD SOMETHING ABOUT ', '[WRITE', '[ADD', '[CHOOSE', '[INSERT'))
                    and not re.match(r'^INSERT (?:FIGURES?|EQUATION)\b', value, re.IGNORECASE)
                    and not reference_prefix.match(value)):
                required_prose.append(dict(index=index, page=route, text=value, markdown=inline(block)))
            # These saved author edits contain prose despite inherited Word styles.
            if prose_in_heading_style(style, value):
                formatting_adjustments.append(dict(index=index, original_style=style,
                                                   output_style='body', reason='sentence-length prose has inherited heading style'))
                style = 'Normal'
            if (style in ('SourceNote', 'AuthorNote')
                    and not value.startswith(('Author note:', 'Review evidence:'))):
                formatting_adjustments.append(dict(index=index, original_style=style,
                                                   output_style='body', reason='authored prose, not an explicitly labeled editing note'))
                style = 'Normal'
            if style == 'Heading1':
                if value not in ROUTES:
                    raise ValueError('Unmapped main heading: ' + value)
                route, section, caption = ROUTES[value], value, None
                pending_heading = '## ' + value if route == 'DataPrep_EDA.qmd' else None
                continue
            if route is None or style in ('AuthorNote', 'SourceNote') or value.startswith(('Author note:', 'Review evidence:', 'ADD SOMETHING ABOUT ')):
                excluded.append(dict(index=index, text=value, reason='editorial_or_front_matter'))
                continue
            if index in skipped_method_captions:
                excluded.append(dict(index=index, text=value, reason=skipped_method_captions[index]))
                continue
            if index in equation_blocks:
                entry = equation_blocks[index]
                latex_parts = [equations[math]['latex'] for math in entry['nodes']]
                latex = '\n\n'.join(latex_parts)
                base_size = equations[entry['nodes'][0]]['font_size_points']
                display_parts = []
                for math, part, blank_lines in zip(entry['nodes'], latex_parts, entry['blank_lines_before']):
                    display = '$$\n' + part + '\n$$'
                    size = equations[math]['font_size_points']
                    styles = []
                    if size and base_size and size != base_size:
                        styles.append(f'font-size: {100 * size / base_size:.4f}%;')
                    if blank_lines:
                        styles.append(f'padding-top: {blank_lines}rem;')
                    if styles:
                        display = ('::: {.equation-line style="' + ' '.join(styles) + '"}\n\n'
                                   + display + '\n\n:::')
                    display_parts.append(display)
                displays = '\n\n'.join(display_parts)
                explanation = inline(body_blocks[entry['caption_index']])
                if pending_heading:
                    pages[route].append(pending_heading)
                    pending_heading = None
                pages[route].append(
                    '::::: {.method-equation}\n\n'
                    f"[{entry['title']}]{{.method-figure-title}}\n\n"
                    f'[{explanation}]{{.method-caption}}\n\n'
                    ':::: {.equation-display}\n\n'
                    f'{displays}\n\n::::\n\n:::::')
                used_equations.update(entry['nodes'])
                method_equations.append(dict(index=index, page=route, title=entry['title'],
                                             latex=latex, caption=explanation,
                                             caption_position='above_equation'))
                included.append(dict(index=index, page=route, role='equation_placeholder', text=value))
                continue
            if index in equation_captions:
                included.append(dict(index=index, page=route, role='equation_caption', text=value))
                continue
            if index in caption_blocks:
                entry = caption_blocks[index]
                if method_registry[entry['number']]['page'] != route:
                    raise ValueError('Method caption on unexpected page: ' + value)
                included.append(dict(index=index, page=route, role='method_caption', text=value,
                                     placeholder=entry['placeholder']))
                continue
            if route == 'Conclusions.qmd' and value in ('Later method pages', 'Before transferring the writing'):
                route = None
                excluded.append(dict(index=index, text=value, reason='publication_checklist'))
                continue
            if route in ('Clustering.qmd', 'PCA.qmd', 'NaiveBayes.qmd', 'DecTrees.qmd') and re.match(r'^\[?INSERT FIGURES?\b', value, re.IGNORECASE):
                rule = method_import_rules.get(value, {})
                if rule.get('pending'):
                    excluded.append(dict(index=index, text=value, reason=rule['reason']))
                    continue
                numbers = rule.get('figures') or re.findall(r'\bFig(?:ure)?\s+(\d+)\b', value, re.IGNORECASE)
                if re.search(r'side.by.side with', value, re.IGNORECASE):
                    numbers = numbers[:1]
                if not numbers or any(number not in method_registry for number in numbers):
                    raise ValueError('Unmapped method figure placeholder: ' + value)
                if pending_heading:
                    pages[route].append(pending_heading)
                    pending_heading = None
                figure_blocks = [method_figure(number, route, index) for number in numbers]
                if len(figure_blocks) > 1:
                    panel = (':::: {.method-figure-pair}\n\n'
                             + '\n\n'.join(figure_blocks) + '\n\n::::')
                    if all(method_registry[number].get('placement') == 'after-overview-first-paragraph'
                           for number in numbers):
                        overview = pages[route].index('## Overview')
                        paragraph = overview + 1
                        if (paragraph >= len(pages[route])
                                or pages[route][paragraph].startswith(('#', ':::'))):
                            raise ValueError('Overview needs an opening paragraph before its figures')
                        pages[route].insert(paragraph + 1, panel)
                    else:
                        pages[route].append(panel)
                elif method_registry[numbers[0]].get('pair_with_table'):
                    table_number = method_registry[numbers[0]]['pair_with_table']
                    if (len(pages[route]) < 2
                            or not pages[route][-1].startswith('Table ' + table_number + ':')
                            or not pages[route][-2].startswith('|')):
                        raise ValueError('Expected preceding table ' + table_number)
                    table_caption = pages[route].pop()
                    table_block = pages[route].pop()
                    pages[route].append('::::: {.method-table-figure-pair}\n\n'
                                        + ':::: {.method-table-panel}\n\n' + table_block
                                        + '\n\n' + table_caption + '\n\n::::\n\n'
                                        + figure_blocks[0] + '\n\n:::::')
                elif method_registry[numbers[0]].get('placement') == 'wrap-previous-prose':
                    if not pages[route] or pages[route][-1].startswith(('#', ':::')):
                        raise ValueError('Expected prose before figure ' + numbers[0])
                    paragraphs = []
                    for _ in range(method_registry[numbers[0]].get('prose_paragraphs', 1)):
                        if not pages[route] or pages[route][-1].startswith(('#', ':::', '|')):
                            raise ValueError('Expected adjacent prose before figure ' + numbers[0])
                        paragraphs.insert(0, pages[route].pop())
                    side = method_registry[numbers[0]].get('side', 'left')
                    prose_layout = method_registry[numbers[0]].get('prose_layout')
                    flow = {'flow': ' .method-prose-flow',
                            'columns-first': ' .method-prose-first-paragraph'}.get(prose_layout, '')
                    pages[route].append(':::: {.method-prose .method-prose-' + side + flow + '}\n\n'
                                        + figure_blocks[0] + '\n\n' + '\n\n'.join(paragraphs) + '\n\n::::')
                elif method_registry[numbers[0]].get('pair_with_previous'):
                    previous = method_registry[numbers[0]]['pair_with_previous']
                    if (len(method_figures) < 2 or method_figures[-2]['number'] != previous
                            or not pages[route][-1].startswith('::: {.method-figure')):
                        raise ValueError('Expected preceding figure ' + previous)
                    previous_block = pages[route].pop()
                    overview_pair = all(method_registry[n].get('placement') == 'after-overview-first-paragraph'
                                        for n in [previous, numbers[0]])
                    pair_class = '.method-figure-pair' + ('' if overview_pair else ' .method-results-pair')
                    panel = ':::: {' + pair_class + '}\n\n' + previous_block + '\n\n' + figure_blocks[0] + '\n\n::::'
                    if overview_pair:
                        overview = pages[route].index('## Overview')
                        pages[route].insert(overview + 2, panel)
                    else:
                        pages[route].append(panel)
                elif (method_registry[numbers[0]].get('placement') == 'wrap-previous-paragraph'
                      and pages[route]
                      and re.search(r'\bFigure\s+' + re.escape(numbers[0]) + r'\b', pages[route][-1])
                      and not pages[route][-1].startswith(('#', ':::'))):
                    paragraph = pages[route].pop()
                    # Adjacent illustrated paragraphs share one text column so
                    # a tall thumbnail cannot force a gap between paragraphs.
                    figures, paragraphs = [], []
                    if pages[route] and pages[route][-1] in inline_panels:
                        figures, paragraphs = inline_panels.pop(pages[route].pop())
                    figures = figures + figure_blocks
                    paragraphs = paragraphs + [paragraph]
                    panel = ('::::: {.method-inline}\n\n:::: {.method-inline-figures}\n\n'
                             + '\n\n'.join(figures) + '\n\n::::\n\n'
                             + ':::: {.method-inline-copy}\n\n' + '\n\n'.join(paragraphs)
                             + '\n\n::::\n\n:::::')
                    inline_panels[panel] = (figures, paragraphs)
                    pages[route].append(panel)
                else:
                    pages[route].extend(figure_blocks)
                included.append(dict(index=index, page=route, role='method_figure_placeholder', text=value))
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
            preparation_title = re.sub(r'\s*\(CSV\)\s*$', '', value, flags=re.IGNORECASE)
            if preparation_title in ('Original feature values', 'Prepared model inputs'):
                formatted = '[' + value + ']{.preparation-table-title}'
                if route in ('NaiveBayes.qmd', 'DecTrees.qmd'):
                    is_tree = route == 'DecTrees.qmd'
                    prefix = 'decision_tree' if is_tree else 'naive_bayes'
                    samples = {
                        'Original feature values': ('original_three_markets.csv', prefix + '_original_sample.csv'),
                        'Prepared model inputs': (
                            'prepared_three_markets.csv' if is_tree else 'encoded_three_markets.csv',
                            prefix + '_prepared_sample.csv'),
                    }
                    source_name, download_name = samples[preparation_title]
                    source = ROOT / 'data/analysis' / (prefix + '_sample') / source_name
                    target = 'downloads/current/' + download_name
                    shutil.copyfile(source, WEB / target)
                    formatted = (f'[[{value}]({target}){{download="{download_name}" '
                                 f'title="Download CSV"}}]{{.preparation-table-title}}')
            elif route == 'DecTrees.qmd' and value in ('Training example (CSV)', 'Testing example (CSV)'):
                target = reference_map[value]['target']
                if not (WEB / target).is_file():
                    raise FileNotFoundError('Missing split preview CSV: ' + target)
                download_name = Path(target).name
                formatted = (f'[[{value}]({target}){{download="{download_name}" '
                             f'title="Download CSV"}}]{{.preparation-table-title}}')
            elif route == 'PCA.qmd' and value == 'Biplot Analysis':
                formatted = '[**' + value + '**]{.method-subsection-title}'
            elif reference_prefix.match(value):
                formatted = reference_line(value, index)
            elif style == 'CodeExample':
                formatted = '```text\n' + value + '\n```'
            elif (style in ('ListBullet', 'ListParagraph')
                  or (route in ('NaiveBayes.qmd', 'DecTrees.qmd')
                      and re.fullmatch(r'[01]: the favored outcome at the cutoff (?:won|lost)', value))):
                formatted = '- ' + formatted
            pages[route].append(formatted)
            included.append(dict(index=index, page=route, role='body', text=value))
        elif block.tag == W + 'tbl':
            rows = [[inline(p) for p in cell.findall('w:p', NS)] for row in block.findall('w:tr', NS) for cell in row.findall('w:tc', NS)]
            table = [[' '.join(inline(p) for p in cell.findall('w:p', NS)).replace('|', '\\|').replace('$', '\\$')
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
            '![Figure ' + str(display_number) + ': ' + ' '.join(item['paragraphs']) + ']('
            + override['asset'] + '){fig-alt="' + override['alt'] + '"}'
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
            pages['DataPrep_EDA.qmd'].append(
                '::: {.section-references}\nCoding Notebook: '
                + ' | '.join(links) + '\n:::')
    # Let subsequent body paragraphs continue beside an embedded figure,
    # rather than clearing it early and leaving an empty area beside the image.
    for page_name in ('Clustering.qmd', 'PCA.qmd', 'NaiveBayes.qmd', 'DecTrees.qmd'):
        blocks = pages[page_name]
        for position in range(len(blocks) - 1, -1, -1):
            if not blocks[position].startswith(':::: {.method-prose '):
                continue
            following = []
            while position + 1 < len(blocks) and not blocks[position + 1].startswith(('#', ':::', '|', '**')):
                following.append(blocks.pop(position + 1))
            if following:
                blocks[position] = (blocks[position].rsplit('\n\n::::', 1)[0]
                                    + '\n\n' + '\n\n'.join(following) + '\n\n::::')
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
    for page in ('Conclusions.qmd', 'Clustering.qmd', 'PCA.qmd', 'NaiveBayes.qmd', 'DecTrees.qmd'):
        if not pages[page]:
            pages[page] = [module_placeholder]
    prose_coverage = assert_paragraph_coverage(required_prose, pages)
    if used_equations != set(equations):
        raise ValueError('One or more native Word equations were not transferred')
    for name, blocks in pages.items():
        page_options = '\ntoc: false' if blocks == [module_placeholder] else ''
        if any(figure['page'] == name for figure in method_figures):
            page_options += '\nlightbox:\n  effect: fade'
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
                  narrative_source='saved_word_document', prose_coverage=prose_coverage, figures_checkpoint=figures_checkpoint,
                  equation_coverage=dict(checked=len(equations), missing=0),
                  figure_text_source='saved_word_document', word_figure_ids=word_figure_ids,
                  current_data_checkpoint='20260916_v2', counts_reconciliation_deferred_by_user=True,
                  archive=archive.relative_to(ROOT).as_posix(), pages=list(pages), figure_count=len(captions),
                  figure_overrides_applied=overridden_ids,
                  method_figures=method_figures,
                  method_equations=method_equations,
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
