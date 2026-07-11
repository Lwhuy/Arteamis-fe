import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Rail } from './Rail';

vi.mock('next/navigation', () => ({ usePathname: () => '/control-plane' }));

describe('Rail', () => {
  it('renders a Chat home link pointing to /control-plane', () => {
    render(<Rail />);
    const chat = screen.getByRole('link', { name: /chat/i });
    expect(chat).toHaveAttribute('href', '/control-plane');
  });

  it('renders a Sources legacy link', () => {
    render(<Rail />);
    expect(screen.getByRole('link', { name: /sources/i })).toHaveAttribute('href', '/sources');
  });
});
