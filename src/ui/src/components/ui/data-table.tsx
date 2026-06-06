import * as React from 'react';

import { cn } from '@/lib/utils';

export type DataTableColumn<T> = {
  /** Unique column id (React key + data-col). */
  key: string;
  /** Header cell content. */
  header: React.ReactNode;
  /** Data cell renderer. */
  cell: (row: T) => React.ReactNode;
  /** Optional <td> className. */
  className?: string;
  /** Optional <th> className. */
  headerClassName?: string;
};

export type DataTableProps<T> = {
  columns: DataTableColumn<T>[];
  rows: T[];
  /** Stable React key per row. */
  getRowId: (row: T) => string;
  /** Shown (spanning all columns) when rows is empty. */
  empty?: React.ReactNode;
  /** Optional trailing right-aligned actions cell. */
  rowActions?: (row: T) => React.ReactNode;
  /** Optional per-row <tr> className (e.g. dim an inactive row). */
  rowClassName?: (row: T) => string | undefined;
  /**
   * Header label for the trailing actions column. When omitted the header is
   * visually hidden (sr-only "Actions"); pass a node to show a real label (e.g.
   * "Action"). The actions column always hugs its content width.
   */
  actionsHeader?: React.ReactNode;
  /** Optional footer/caption region rendered below the table. */
  caption?: React.ReactNode;
  /** Wrapper className. */
  className?: string;
} & Omit<React.ComponentProps<'div'>, 'children'>;

export function DataTable<T>({
  columns,
  rows,
  getRowId,
  empty,
  rowActions,
  rowClassName,
  actionsHeader,
  caption,
  className,
  ...rest
}: DataTableProps<T>): React.ReactElement {
  const hasActions = rowActions !== undefined;
  const colSpan = columns.length + (hasActions ? 1 : 0);

  return (
    <div
      data-slot="data-table"
      className={cn(
        'bg-card text-card-foreground overflow-x-auto rounded-xl border',
        className
      )}
      {...rest}
    >
      <table data-slot="data-table-table" className="w-full border-collapse">
        <thead data-slot="data-table-header">
          <tr className="border-b">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                data-col={column.key}
                className={cn(
                  'text-muted-foreground px-4 py-3 text-left text-xs font-semibold tracking-wider uppercase',
                  column.headerClassName
                )}
              >
                {column.header}
              </th>
            ))}
            {hasActions ? (
              <th
                scope="col"
                data-col="__actions"
                className="text-muted-foreground w-px px-4 py-3 text-right text-xs font-semibold tracking-wider whitespace-nowrap uppercase"
              >
                {actionsHeader ?? <span className="sr-only">Actions</span>}
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody data-slot="data-table-body">
          {rows.length === 0 ? (
            <tr data-slot="data-table-empty">
              <td colSpan={colSpan} className="text-muted-foreground px-4 py-6 text-center text-sm">
                {empty ?? 'No items'}
              </td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr
                key={getRowId(row)}
                data-slot="data-table-row"
                className={cn(index < rows.length - 1 && 'border-b', rowClassName?.(row))}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    data-col={column.key}
                    className={cn('px-4 py-3 text-sm', column.className)}
                  >
                    {column.cell(row)}
                  </td>
                ))}
                {hasActions ? (
                  <td
                    data-col="__actions"
                    className="w-px px-4 py-3 text-right text-sm whitespace-nowrap"
                  >
                    {rowActions(row)}
                  </td>
                ) : null}
              </tr>
            ))
          )}
        </tbody>
      </table>
      {caption !== undefined ? (
        <div data-slot="data-table-caption" className="text-muted-foreground border-t px-4 py-3 text-sm">
          {caption}
        </div>
      ) : null}
    </div>
  );
}
