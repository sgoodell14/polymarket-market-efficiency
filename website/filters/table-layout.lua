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
  },
  ["feature|transformation|definition"] = {
    class = "table-features", widths = {25, 18, 57}, label = "Modeling feature definitions"
  },
  ["feature|transformation|definition|model inclusion"] = {
    class = "table-features", widths = {21, 16, 45, 18}, label = "Modeling feature definitions"
  },
  ["component|variance explained (%)|cumulative variance (%)"] = {
    class = "table-pca-variance", widths = {26, 37, 37}, label = "PCA explained variance"
  },
  ["row|distinct wallets|trade count|trading activity per day ($)|average trade value ($)|wallet concentration (hhi)|forecast certainty|price movement per hour (pp)"] = {
    class = "table-model-sample", widths = {5, 12, 10, 16, 14, 15, 12, 16}, label = "Market feature sample"
  },
  ["row|distinct wallets|trade count|trading activity per day|average trade value|wallet concentration (hhi)|forecast certainty|price movement per hour"] = {
    class = "table-model-sample", widths = {5, 12, 10, 16, 14, 15, 12, 16}, label = "Prepared market feature sample"
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
  local widths = layout.widths
  if layout.class == "table-model-sample" then
    -- Omit the display-only row index, preserving the seven feature values.
    local function remove_index(rows)
      for _, row in ipairs(rows) do row.cells:remove(1) end
    end
    remove_index(tbl.head.rows)
    for _, body in ipairs(tbl.bodies) do
      remove_index(body.head)
      remove_index(body.body)
    end
    remove_index(tbl.foot.rows)
    tbl.colspecs:remove(1)
    widths = {12, 10, 17, 14, 19, 12, 16}
  end
  local specs = {}
  for i, width in ipairs(widths) do
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
