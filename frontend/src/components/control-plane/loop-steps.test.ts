import { describe, it, expect } from 'vitest';
import { LOOP_STEPS, deriveLoopSteps } from './loop-steps';

describe('deriveLoopSteps', () => {
  it('has 8 steps with propose before review', () => {
    expect(LOOP_STEPS).toHaveLength(8);
    const ids = LOOP_STEPS.map((s) => s.id);
    expect(ids.indexOf('propose')).toBeLessThan(ids.indexOf('review'));
  });

  it('marks done/current/later around currentIndex', () => {
    const steps = deriveLoopSteps(2);
    expect(steps[0].status).toBe('done');
    expect(steps[1].status).toBe('done');
    expect(steps[2].status).toBe('current');
    expect(steps[3].status).toBe('later');
  });

  it('index 0 => first is current, exactly one current', () => {
    const steps = deriveLoopSteps(0);
    expect(steps.filter((s) => s.status === 'current')).toHaveLength(1);
    expect(steps[0].status).toBe('current');
  });

  it('index >= 8 => all done, no current', () => {
    const steps = deriveLoopSteps(8);
    expect(steps.every((s) => s.status === 'done')).toBe(true);
    expect(steps.some((s) => s.status === 'current')).toBe(false);
  });
});
