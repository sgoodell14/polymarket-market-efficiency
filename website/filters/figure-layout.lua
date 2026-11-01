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
  if block.classes:includes("method-prose-flow") then
    -- Keep paragraphs in normal flow so later lines can use the full width.
    figure.classes:insert("method-figure-float")
    return block
  end
  local paragraphs = pandoc.Blocks({})
  local following = pandoc.Blocks({})
  for i = 2, #block.content do
    if i > 2 and block.classes:includes("method-prose-first-paragraph") then
      following:insert(block.content[i])
    else
      paragraphs:insert(block.content[i])
    end
  end
  block.classes:insert("method-prose-image-aligned")
  block.content = pandoc.Blocks({figure,
    pandoc.Div(paragraphs, pandoc.Attr("", {"method-prose-copy"}))})
  if #following > 0 then
    following:insert(1, block)
    return following
  end
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

-- Attach a source to the preceding figure, including when prose wraps beside it.
-- Keep this at render time so the author's Word text survives fresh imports.
local function attach_figure_sources(blocks)
  if not quarto.doc.is_format("html") then return nil end
  local result = pandoc.Blocks({})
  local figure
  for _, block in ipairs(blocks) do
    if block.t == "Div" and block.classes:includes("method-figure") then
      figure = block
    elseif block.t == "Header" or (block.t == "Div" and block.classes:includes("method-equation")) then
      figure = nil
    end
    local first = block.t == "Para" and block.content[1] or nil
    local is_source = first and first.t == "Str"
      and (first.text:lower() == "citation:" or first.text:lower() == "source:")
    local caption
    if is_source and figure and figure.t == "Div"
        and figure.classes:includes("method-figure") then
      for _, paragraph in ipairs(figure.content) do
        if paragraph.t == "Para" then
          for _, inline in ipairs(paragraph.content) do
            if inline.t == "Span" and inline.classes:includes("method-caption") then
              caption = inline
            end
          end
        end
      end
    end
    if caption then
      local source = pandoc.Span(block.content):walk({
        Emph = function(el) return el.content end,
        Strong = function(el) return el.content end
      }).content
      source[1] = pandoc.Str("(Source:")
      source:insert(pandoc.Str(")"))
      caption.content:insert(pandoc.Span({pandoc.Emph(source)},
        pandoc.Attr("", {"method-source"})))
    else
      result:insert(block)
    end
  end
  return result
end

-- Word uses "Caption:" as an editing label; the site keeps only its explanation.
local function strip_caption_label(span)
  if not span.classes:includes("method-caption") then return nil end
  local first = span.content[1]
  if first and first.t == "Str" and first.text:sub(1, 8):lower() == "caption:" then
    first.text = first.text:sub(9)
    if first.text == "" then
      span.content:remove(1)
      if span.content[1] and span.content[1].t == "Space" then
        span.content:remove(1)
      end
    end
    return span
  end
end

return {{Blocks = attach_figure_sources}, {Div = align_figure},
        {Blocks = attach_topic_heading}, {Span = strip_caption_label}}
