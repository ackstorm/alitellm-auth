import { render, screen } from '@testing-library/react';
import { DataTable, type DataTableColumn } from './data-table';

type Row = { id: string; name: string };

const columns: DataTableColumn<Row>[] = [
  { key: 'id', header: 'ID', cell: (row) => row.id },
  { key: 'name', header: 'Name', cell: (row) => row.name },
];

const rows: Row[] = [
  { id: 'a', name: 'Alice' },
  { id: 'b', name: 'Bob' },
];

test('renders all column headers', () => {
  render(<DataTable columns={columns} rows={rows} getRowId={(r) => r.id} />);
  expect(screen.getByText('ID')).toBeInTheDocument();
  expect(screen.getByText('Name')).toBeInTheDocument();
});

test('renders a cell value for each row via the cell renderer', () => {
  render(<DataTable columns={columns} rows={rows} getRowId={(r) => r.id} />);
  expect(screen.getByText('Alice')).toBeInTheDocument();
  expect(screen.getByText('Bob')).toBeInTheDocument();
});

test('renders the empty node and no data rows when rows is empty', () => {
  render(
    <DataTable
      columns={columns}
      rows={[]}
      getRowId={(r) => r.id}
      empty={<span>Nothing here</span>}
    />
  );
  expect(screen.getByText('Nothing here')).toBeInTheDocument();
  expect(screen.queryByText('Alice')).not.toBeInTheDocument();
});

test('renders a rowActions element per row when provided', () => {
  render(
    <DataTable
      columns={columns}
      rows={rows}
      getRowId={(r) => r.id}
      rowActions={(row) => <button type="button">delete {row.name}</button>}
    />
  );
  expect(screen.getByRole('button', { name: 'delete Alice' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'delete Bob' })).toBeInTheDocument();
});

test('renders caption when provided', () => {
  render(
    <DataTable
      columns={columns}
      rows={rows}
      getRowId={(r) => r.id}
      caption={<span>Showing 2 of 2</span>}
    />
  );
  expect(screen.getByText('Showing 2 of 2')).toBeInTheDocument();
});
