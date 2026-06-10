// ExportCsvButton.tsx — caption-styled button that serializes the given rows to
// CSV (lib/csv) and triggers a client-side download. Renders nothing for an
// empty row set (nothing to export).

import * as React from 'react';

import { downloadCsv, toCsv, type CsvColumn } from '@/lib/csv';

export function ExportCsvButton<T>({
  rows,
  columns,
  filename,
}: {
  rows: T[];
  columns: CsvColumn<T>[];
  filename: string;
}): React.ReactElement | null {
  if (rows.length === 0) return null;
  return (
    <button
      type="button"
      data-slot="export-csv"
      onClick={() => downloadCsv(filename, toCsv(rows, columns))}
      className="cursor-pointer font-mono text-[10px] font-semibold uppercase tracking-wider text-text-secondary transition-colors hover:text-text-primary"
    >
      export csv
    </button>
  );
}
