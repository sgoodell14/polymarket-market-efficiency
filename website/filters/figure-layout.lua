-- Keep adjacent paragraphs together while aligning them with the image.
-- Apply at render time so subsequent Word imports preserve the layout.
local function align_figure(block)
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

-- Keep this subsection heading directly above its prose, beside the figure title.
local function attach_topic_heading(blocks)
  if not quarto.doc.is_format("html") then return nil end
  local result = pandoc.Blocks({})
  for _, block in ipairs(blocks) do
    local previous = result[#result]
    if block.t == "Div" and block.classes:includes("method-prose-image-aligned")
        and block.content[1].identifier == "figure-20"
        and previous and previous.t == "Para"
        and pandoc.utils.stringify(previous) == "Cluster-Topic Comparison" then
      result:remove(#result)
      block.content:insert(1, pandoc.Div({previous},
        pandoc.Attr("", {"method-prose-heading"})))
    end
    result:insert(block)
  end
  return result
end

return {{Div = align_figure}, {Blocks = attach_topic_heading}}
