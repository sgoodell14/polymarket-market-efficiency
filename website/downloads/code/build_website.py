"""Build the Quarto website and stage portable static output."""
import shutil
import subprocess
from pathlib import Path
from prepare_website import main as prepare

ROOT = Path(__file__).resolve().parents[1]

def main():
    prepare()
    portable = ROOT / ".tools/bin/quarto.exe"
    executable = str(portable) if portable.exists() else shutil.which("quarto")
    if not executable:
        raise SystemExit("Install Quarto 1.9.38 or newer, then run this script again.")
    # Build from a staging copy so Quarto's live preview cannot race the render.
    stage = ROOT / ".artifacts/quarto-build"
    if stage.exists():
        if stage.resolve() != ROOT.resolve() / ".artifacts/quarto-build":
            raise RuntimeError("Staging path safety check failed")
        shutil.rmtree(stage)
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
        shutil.rmtree(target)
    shutil.copytree(source, target)
    print(f"Built static website: {target}")

if __name__ == "__main__":
    main()
