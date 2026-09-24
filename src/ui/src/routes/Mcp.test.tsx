// Mcp.test.tsx — vitest for the #/mcp page (jsdom).
//
// useMcp is fully mocked so NO real fetch happens; each test programs its return
// to drive the loading / error / unavailable / empty / populated branches.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { UseQueryResult } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import type { McpResponse, McpServerRow } from '@/lib/api-types';

vi.mock('@/hooks/use-mcp', () => ({ useMcp: vi.fn() }));

import { useMcp } from '@/hooks/use-mcp';
import { Mcp } from './Mcp';

const useMcpMock = vi.mocked(useMcp);


function makeServer(over: Partial<McpServerRow> = {}): McpServerRow {
  return {
    id: 'github-mcp',
    name: 'GitHub',
    description: 'Repos and issues.',
    url: 'https://mcp.internal/github',
    transport: 'http',
    auth_type: 'oauth2',
    status: 'healthy',
    tools: ['list_repos', 'create_issue'],
    tool_count: 2,
    access_groups: ['platform'],
    ...over,
  };
}

function setPending(): void {
  useMcpMock.mockReturnValue({
    data: undefined,
    isPending: true,
    isError: false,
    refetch: vi.fn(),
  } as unknown as UseQueryResult<McpResponse>);
}

function setError(): ReturnType<typeof vi.fn> {
  const refetch = vi.fn();
  useMcpMock.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: true,
    refetch,
  } as unknown as UseQueryResult<McpResponse>);
  return refetch;
}

function setSuccess(data: McpResponse): void {
  useMcpMock.mockReturnValue({
    data,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as UseQueryResult<McpResponse>);
}

afterEach(() => {
  vi.clearAllMocks();
  cleanup();
});


describe('Mcp — loading', () => {
  beforeEach(() => setPending());
  it('renders skeletons and keeps the title', () => {
    const { container } = render(<Mcp />);
    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0);
    expect(screen.getByText('MCP')).toBeInTheDocument();
  });
});

describe('Mcp — error', () => {
  it('shows the locked error heading and retry re-fires the query', () => {
    const refetch = setError();
    render(<Mcp />);
    expect(screen.getByText("Couldn't load MCP servers")).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});



describe('Mcp — populated', () => {
  it('renders the server name, status, tools, and access group', () => {
    setSuccess({ servers: [makeServer()], available: true });
    render(<Mcp />);
    expect(screen.getByText('GitHub')).toBeInTheDocument();
    expect(screen.getByText('healthy')).toBeInTheDocument();
    expect(screen.getByText('list_repos')).toBeInTheDocument();
    expect(screen.getByText('create_issue')).toBeInTheDocument();
    expect(screen.getByText('platform')).toBeInTheDocument();
  });

  it('splits vmcp-* virtual groups from the servers they aggregate', () => {
    setSuccess({
      servers: [
        makeServer({ id: '1', name: 'mcp-gitlab' }),
        makeServer({ id: '2', name: 'vmcp-dev' }),
        makeServer({ id: '3', name: 'mcp-drive' }),
      ],
      available: true,
    });
    const { container } = render(<Mcp />);
    const sections = [...container.querySelectorAll('[data-slot="mcp-section"]')];
    expect(sections.map((el) => el.querySelector('h2')?.textContent)).toEqual([
      'Virtual groups (1)',
      'Servers (2)',
    ]);
    expect(sections[0]).toHaveTextContent('vmcp-dev');
    expect(sections[1]).not.toHaveTextContent('vmcp-dev');
  });

  it('caps the visible tool chips at six with a "+N more" marker', () => {
    const tools = Array.from({ length: 9 }, (_, i) => `tool_${i}`);
    setSuccess({
      servers: [makeServer({ tools, tool_count: 9 })],
      available: true,
    });
    render(<Mcp />);
    expect(screen.getByText('tool_5')).toBeInTheDocument(); // 6th chip (index 5)
    expect(screen.queryByText('tool_6')).not.toBeInTheDocument(); // hidden
    expect(screen.getByText('+3 more')).toBeInTheDocument();
  });
});
