# Course website

This is a Quarto website. Edit the `.qmd` files as Markdown. `_quarto.yml` defines the required course navigation; `theme.scss` defines the shared appearance.

The project has a local portable Quarto under `../.tools/`. From the repository root, `python src/build_website.py` prepares the reviewed data downloads and figures, renders every page, and copies the static output to `../dist` relative to this folder. GitHub Actions runs this same build and publishes the output to GitHub Pages on every push to `main`.

The first version presents an introduction, ten research questions, the pilot data and ten descriptive figures. Later analysis pages explicitly remain pending. Additional data collection and the final course submission remain next steps.

Live site: https://sgoodell14.github.io/polymarket-market-efficiency/

Hosting is configured in `../.github/workflows/pages.yml`; the Pages source in GitHub repository settings is GitHub Actions. Keep `site-url` in `_quarto.yml` aligned with the live URL, including the repository path.
