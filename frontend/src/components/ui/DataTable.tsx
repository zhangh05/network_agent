import type { ReactNode } from "react";
import { EmptyState } from "../common";

interface Column<T> {
  key: string;
  header: ReactNode;
  width?: string | number;
  align?: "left" | "center" | "right";
  render?: (row: T, index: number) => ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  keyExtractor: (row: T) => string;
  empty?: { text: string; hint?: string; action?: ReactNode };
  loading?: boolean;
  onRowClick?: (row: T) => void;
  className?: string;
  "data-testid"?: string;
}

export function DataTable<T>({
  columns,
  rows,
  keyExtractor,
  empty,
  loading,
  onRowClick,
  className = "",
  "data-testid": testId,
}: DataTableProps<T>) {
  if (!loading && rows.length === 0) {
    return (
      <EmptyState
        text={empty?.text ?? "暂无数据"}
        hint={empty?.hint}
        action={empty?.action}
      />
    );
  }

  return (
    <div className="data-table-scroll" data-testid={testId}>
      <table className={`tbl data-table ${className}`}>
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                style={{
                  width: col.width,
                  textAlign: col.align ?? "left",
                }}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={keyExtractor(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={onRowClick ? "cursor-pointer" : undefined}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  style={{
                    textAlign: col.align ?? "left",
                    width: col.width,
                  }}
                >
                  {col.render ? col.render(row, i) : null}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
