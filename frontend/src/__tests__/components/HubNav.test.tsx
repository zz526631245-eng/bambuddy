import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { HubNav } from '../../components/HubNav';

describe('HubNav', () => {
  it('reveals an inline section without navigating when a selector is provided', () => {
    const onSelect = vi.fn();
    render(
      <MemoryRouter initialEntries={['/production-orders']}>
        <HubNav
          ariaLabel="生产中心导航"
          activeTo="/production-orders"
          onSelect={onSelect}
          items={[
            { to: '/production-orders', label: '生产订单' },
            { to: '/queue', label: '打印队列' },
          ]}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('link', { name: '打印队列' }));

    expect(onSelect).toHaveBeenCalledWith('/queue');
    expect(screen.getByRole('link', { name: '打印队列' })).toHaveAttribute('href', '/queue');
  });
});
