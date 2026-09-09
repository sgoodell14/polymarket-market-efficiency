# Course website

This is a Quarto website. Edit the `.qmd` files as Markdown. `_quarto.yml` defines the required course navigation; `theme.scss` defines the shared appearance.

The project has a local portable Quarto under `../.tools/`. From the repository root, `python src/build_website.py` prepares the reviewed data downloads and figures, renders every page, and copies the static output to `../dist` relative to this folder. The same static output can be served with Sites or GitHub Pages.

The first version presents an introduction, ten research questions, the pilot data and ten descriptive figures. Later analysis pages explicitly remain pending. Public course submission and additional data collection are separate next steps.
