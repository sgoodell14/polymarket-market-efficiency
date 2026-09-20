"""Build the Quarto website and stage portable static output."""
import shutil
import os
import stat
import subprocess
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def remove_generated(path):
    allowed = {ROOT.resolve() / "dist", ROOT.resolve() / ".artifacts/quarto-build"}
    if path.resolve() not in allowed:
        raise RuntimeError("Generated-output path safety check failed")
    def writable_retry(operation, name, error):
        # OneDrive can mark generated directories read-only on Windows.
        os.chmod(name, stat.S_IWRITE | stat.S_IREAD)
        operation(name)
    shutil.rmtree(path, onerror=writable_retry)


def main():
    # Word-authored pages and their selected figures are already staged. The old
    # pilot generator would overwrite the author's DataPrep_EDA prose.
    if not (ROOT / 'website/writing-transfer.json').exists():
        from prepare_website import main as prepare
        prepare()
    else:
        # Rendering figures is not a Word import. Make saved prose drift visible
        # without overwriting either the author's document or the staged pages.
        from transfer_website_writing import read_saved_document
        receipt = json.loads((ROOT / 'website/writing-transfer.json').read_text(encoding='utf-8'))
        word_path = ROOT / receipt['source']
        if word_path.exists():
            word_hash = hashlib.sha256(read_saved_document(word_path)).hexdigest()
            if word_hash != receipt['source_sha256']:
                print('NOTICE: Saved Word changes have not been imported. This build uses the last transferred text. '
                      'Run src/transfer_website_writing.py to sync the saved writing.', flush=True)
    portable = ROOT / ".tools/bin/quarto.exe"
    executable = str(portable) if portable.exists() else shutil.which("quarto")
    if not executable:
        raise SystemExit("Install Quarto 1.9.38 or newer, then run this script again.")
    # Build from a staging copy so Quarto's live preview cannot race the render.
    stage = ROOT / ".artifacts/quarto-build"
    if stage.exists():
        if stage.resolve() != ROOT.resolve() / ".artifacts/quarto-build":
            raise RuntimeError("Staging path safety check failed")
        remove_generated(stage)
    shutil.copytree(ROOT / "website", stage,
                    ignore=shutil.ignore_patterns("dist", ".quarto", "*_files", "site_libs", "*.html"))
    subprocess.run([executable, "render", str(stage)], cwd=ROOT, check=True)
    source, target = stage / "dist", ROOT / "dist"
    if not (source / "index.html").exists():
        raise RuntimeError("Quarto did not produce index.html")
    # Only replace the generated, ignored output inside this project.
    if target.exists():
        if target.resolve() != (ROOT.resolve() / "dist"):
            raise RuntimeError("Output path safety check failed")
        remove_generated(target)
    shutil.copytree(source, target)
    print(f"Built static website: {target}")

if __name__ == "__main__":
    main()
