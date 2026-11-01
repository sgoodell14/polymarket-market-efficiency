-- Keep older notebook URLs pointing to the site's readable HTML notebooks.
local notebooks = {
  ["downloads/current/eda-visualization-notebook.ipynb"] = "downloads/current/02_eda.html",
  ["downloads/current/03_clustering.ipynb"] = "downloads/current/03_clustering.html",
  ["downloads/current/04_pca.ipynb"] = "downloads/current/04_pca.html"
}

function Link(link)
  if not quarto.doc.is_format("html") then return nil end
  local path = notebooks[link.target]
  if not path then return nil end
  link.target = path
  link.title = "View the saved notebook with code and outputs"
  return link
end
