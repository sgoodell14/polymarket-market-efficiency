-- Keep adjacent paragraphs together while aligning them with the image.
-- Apply at render time so subsequent Word imports preserve the layout.
function Div(block)
  if not quarto.doc.is_format("html")
      or not block.classes:includes("method-prose")
      or block.classes:includes("method-prose-image-aligned") then return nil end
  local figure = block.content[1]
  if not figure or figure.t ~= "Div" or not figure.classes:includes("method-figure") then
    return nil
  end
  local paragraphs = pandoc.Blocks({})
  for i = 2, #block.content do paragraphs:insert(block.content[i]) end
  block.classes:insert("method-prose-image-aligned")
  block.content = pandoc.Blocks({figure,
    pandoc.Div(paragraphs, pandoc.Attr("", {"method-prose-copy"}))})
  return block
end
