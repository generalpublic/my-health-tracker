Run the Design Audit Checklist against the specified tab(s): $ARGUMENTS

If no tab specified, audit all tabs. For each tab, check:

1. **Yellow check**: every manual-entry column has yellow background `{"red": 1.0, "green": 1.0, "blue": 0.8}`
2. **Gradient check**: numeric score/metric columns have appropriate color grading
3. **Banding check**: weekly alternating white/grey on non-graded, non-yellow cells
4. **No yellow on auto columns**: auto-populated columns must NOT have yellow background
5. **Column width check**: all columns have explicit widths set
6. **Wrap check**: text-heavy columns have WRAP enabled
7. **Alignment check**: short labels/categorical=CENTER, long text=LEFT+TOP+WRAP, numeric=CENTER

Use Python + gspread to query actual sheet metadata and compare against the spec. Report PASS/FAIL for each item per tab.
