-- Open the rendered notebook on GitHub instead of raw JSON in the browser.
local notebooks = {
  ["downloads/current/03_clustering.ipynb"] = "notebooks/03_clustering.ipynb",
  ["downloads/current/04_pca.ipynb"] = "notebooks/04_pca.ipynb"
}

function Link(link)
  if not quarto.doc.is_format("html") then return nil end
  local path = notebooks[link.target]
  if not path then return nil end
  link.target = "https://github.com/sgoodell14/polymarket-market-efficiency/blob/main/" .. path
  link.title = "View notebook on GitHub"
  return link
end
