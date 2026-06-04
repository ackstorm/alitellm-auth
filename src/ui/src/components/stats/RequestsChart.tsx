// RequestsChart.tsx — STATS-04 Requests by Day, a bar chart (Recharts port of
// the old uPlot RequestsChart in src/ui/charts.js).
//
// Mirrors the old intent: accent (green) bars with a slightly rounded top,
// --border gridlines, muted ticks, a dark themed hover tooltip formatted with
// formatInt, ~240px tall. Themed entirely via var(--*) tokens — NEVER a raw hex.
//
// Render order (shared with SpendChart):
//   1. loading        -> <Skeleton variant="chart" />
//   2. no rows         -> <ChartEmpty /> (the locked empty state, not a grid)
//   3. otherwise       -> the BarChart in a ResponsiveContainer.

import * as React from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { StatsSeriesPoint } from '@/lib/api-types';
import { formatDate, formatInt } from '@/lib/format';
import { seriesToRecharts } from '@/lib/stats-series';
import { Skeleton } from '@/components/ui/skeleton';

import {
  AXIS_LINE_STROKE,
  AXIS_TICK,
  CHART_HEIGHT,
  ChartEmpty,
  SERIES_COLOR,
  TOOLTIP_CONTENT_STYLE,
  TOOLTIP_ITEM_STYLE,
  TOOLTIP_LABEL_STYLE,
  makeTooltipFormatter,
  tooltipLabelFormatter,
} from './chart-common';

export interface RequestsChartProps {
  series: StatsSeriesPoint[] | null | undefined;
  loading?: boolean;
}

export function RequestsChart({ series, loading }: RequestsChartProps): React.ReactElement {
  if (loading) {
    return <Skeleton variant="chart" />;
  }

  const rows = seriesToRecharts(series);
  if (rows.length === 0) {
    return <ChartEmpty />;
  }

  return (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
      <BarChart data={rows}>
        <CartesianGrid stroke={AXIS_LINE_STROKE} strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tickFormatter={formatDate}
          tick={AXIS_TICK}
          axisLine={{ stroke: AXIS_LINE_STROKE }}
          tickLine={{ stroke: AXIS_LINE_STROKE }}
          minTickGap={24}
          interval="preserveStartEnd"
        />
        <YAxis
          width={64}
          tickFormatter={formatInt}
          tick={AXIS_TICK}
          axisLine={{ stroke: AXIS_LINE_STROKE }}
          tickLine={{ stroke: AXIS_LINE_STROKE }}
        />
        <Tooltip
          contentStyle={TOOLTIP_CONTENT_STYLE}
          labelStyle={TOOLTIP_LABEL_STYLE}
          itemStyle={TOOLTIP_ITEM_STYLE}
          labelFormatter={tooltipLabelFormatter}
          formatter={makeTooltipFormatter(formatInt)}
          cursor={{ fill: 'var(--border)', opacity: 0.3 }}
        />
        <Bar dataKey="requests" fill={SERIES_COLOR} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
