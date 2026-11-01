-- The Word marker introduces a table, calculation, and explanation paragraph.
-- Fold only those three blocks; subsequent overview writing stays outside.
function Blocks(blocks)
  if not quarto.doc.is_format("html") then return nil end
  local result = pandoc.Blocks({})
  local i = 1
  while i <= #blocks do
    local block = blocks[i]
    local title = block.t == "Para"
      and pandoc.utils.stringify(block):match("^Expandable example:%s*(.+)$")
    if title then
      local data, calculation, explanation = blocks[i + 1], blocks[i + 2], blocks[i + 3]
      local has_math = false
      if calculation then
        calculation:walk({Math = function() has_math = true end})
      end
      if not data or data.t ~= "Table" or not calculation
          or calculation.t ~= "Para" or not has_math
          or not explanation or explanation.t ~= "Para" then
        error("Expandable example requires a table, equation, and explanation: " .. title)
      end
      local id = "worked-example-" .. title:lower():gsub("[^%w]+", "-"):gsub("-$", "")
      result:insert(pandoc.RawBlock("html", '<details class="worked-example" id="' .. id .. '">'))
      result:insert(pandoc.RawBlock("html", '<summary>View a simple worked example</summary>'))
      result:insert(pandoc.Div({
        pandoc.Para({pandoc.Strong({pandoc.Str(title)})}),
        data,
        pandoc.Div({calculation}, pandoc.Attr("", {"worked-example-calculation"})),
        explanation
      }, pandoc.Attr("", {"worked-example-content"})))
      result:insert(pandoc.RawBlock("html", "</details>"))
      i = i + 4
    else
      result:insert(block)
      i = i + 1
    end
  end
  return result
end
