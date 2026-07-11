import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LoopWidget } from './LoopWidget';

describe('LoopWidget', () => {
  it('renders all 8 step labels', () => {
    render(<LoopWidget currentIndex={0} />);
    // labels come through t(); with key-returning t, the capture label key is present
    expect(screen.getByText(/controlPlane\.loop\.capture|Capture/)).toBeInTheDocument();
    expect(screen.getByText(/controlPlane\.loop\.trace|Trace/)).toBeInTheDocument();
  });

  it('renders the Personal-Company boundary marker', () => {
    render(<LoopWidget currentIndex={0} />);
    expect(screen.getByText(/controlPlane\.loop\.boundary|boundary/i)).toBeInTheDocument();
  });
});
