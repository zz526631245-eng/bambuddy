import { Link, useLocation } from 'react-router-dom';

export interface HubNavItem {
  to: string;
  label: string;
}

interface HubNavProps {
  items: HubNavItem[];
  ariaLabel: string;
  /** When supplied, keep the user on the current page and reveal the section. */
  onSelect?: (to: string) => void;
  activeTo?: string;
}

/**
 * Small, page-local navigation for related features that intentionally stay
 * out of the primary sidebar. It keeps existing routes discoverable without
 * creating another feature or changing any backend behaviour.
 */
export function HubNav({ items, ariaLabel, onSelect, activeTo }: HubNavProps) {
  const location = useLocation();

  return (
    <nav aria-label={ariaLabel} className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary/60 p-2">
      <div className="mb-2 px-2 text-xs text-bambu-gray">相关功能</div>
      <div className="flex flex-wrap gap-2">
        {items.map(item => {
          const active = (activeTo || location.pathname) === item.to ||
            (item.to !== '/' && location.pathname.startsWith(`${item.to}/`));
          return (
            <Link
              key={item.to}
              to={item.to}
              onClick={event => {
                if (!onSelect) return;
                event.preventDefault();
                onSelect(item.to);
              }}
              className={`rounded-md px-3 py-1.5 text-sm transition-colors ${active
                ? 'bg-bambu-green text-bambu-dark font-medium'
                : 'text-bambu-gray-light hover:bg-bambu-dark-tertiary hover:text-white'}`}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
