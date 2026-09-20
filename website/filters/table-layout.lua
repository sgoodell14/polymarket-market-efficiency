-- Apply presentation at render time so fresh Word transfers keep the layout.
-- Match semantic headers, not table order or Markdown separator lengths.
local layouts = {
  ["source|information collected"] = {
    class = "table-sources", widths = {18, 82}, label = "API sources"
  },
  ["topic|event boundary"] = {
    class = "table-boundaries", widths = {16, 84}, label = "Event boundaries"
  },
  ["topic|market (id)|reason for exclusion"] = {
    class = "table-exclusions", widths = {14, 36, 50}, label = "Exclusion examples"
  },
  ["table|rows|granularity"] = {
    class = "table-datasets", widths = {20, 14, 66}, label = "Prepared datasets"
  }
}

function Table(tbl)
  if not quarto.doc.is_format("html") or #tbl.head.rows ~= 1 then return nil end
  local headers = {}
  for _, cell in ipairs(tbl.head.rows[1].cells) do
    local text = pandoc.utils.stringify(cell.contents):lower()
    headers[#headers + 1] = text:gsub("%s+", " "):match("^%s*(.-)%s*$")
  end
  local layout = layouts[table.concat(headers, "|")]
  if not layout or #tbl.colspecs ~= #layout.widths then return nil end
  local specs = {}
  for i, width in ipairs(layout.widths) do
    specs[i] = {tbl.colspecs[i][1], width / 100}
  end
  tbl.colspecs = specs
  -- Quarto's automatic link-table rule otherwise discards explicit widths.
  tbl.attributes["tbl-colwidths"] = "true"
  tbl.classes:insert("content-table")
  tbl.classes:insert(layout.class)
  -- Keep narrow screens readable without making the whole page scroll sideways.
  return pandoc.Div({tbl}, pandoc.Attr("", {"table-scroll"}, {
    ["tabindex"] = "0", ["role"] = "region", ["aria-label"] = layout.label
  }))
end
