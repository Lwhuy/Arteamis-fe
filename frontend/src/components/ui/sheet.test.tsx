import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Sheet, SheetContent, SheetTitle } from './sheet';

describe('Sheet', () => {
  it('renders content and title when open', () => {
    render(
      <Sheet open>
        <SheetContent side="left">
          <SheetTitle>Artifact</SheetTitle>
        </SheetContent>
      </Sheet>,
    );
    expect(screen.getByText('Artifact')).toBeInTheDocument();
  });
});
